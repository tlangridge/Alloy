# SPEC: implement the rulecalc expression language

## Goal

Implement the `rulecalc` package: a tokenizer, a precedence parser and an
evaluator for the small rule language described below, with exact decimal
arithmetic and precise error positions. The public API is fixed (see
"Public API"); internal structure is up to you.

## Current behavior

The package skeleton exists (`rulecalc/errors.py` is complete), but
`compile_rule`, `evaluate`, `Rule.evaluate`, `Rule.variables` and the
lexer/parser/evaluator modules raise `NotImplementedError`. The visible tests
in `tests/` fail.

## Desired behavior

### Public API

- `rulecalc.compile_rule(source: str) -> rulecalc.Rule` tokenizes and parses.
  It raises `rulecalc.LexError` or `rulecalc.ParseError`; it never evaluates
  anything and never raises `EvalError`.
- `rulecalc.Rule.evaluate(variables: dict | None = None)` evaluates the
  compiled rule against `variables` (a mapping of variable name to Python
  value; `None` means no variables) and returns the result as a Python value
  (see rule 5). It raises `rulecalc.EvalError` for every runtime failure.
- `rulecalc.evaluate(source, variables=None)` is
  `compile_rule(source).evaluate(variables)`.
- `rulecalc.Rule.variables` (a property) is the **sorted list of distinct root
  variable names** referenced anywhere in the rule, including inside branches
  that would not be taken. Only root names count: in `a.b[c]` the names are
  `a` and `c`; member names (`b`) and function names are never included.
- Errors: `RuleError` (base), `LexError`, `ParseError`, `EvalError` from
  `rulecalc/errors.py` (already written; do not change their constructor).
  Each has `.line` and `.column`; messages are free-form and not tested.

### 1. Positions

1.1 `line` starts at 1 and increases by one after every `\n`. `column` starts
at 1 and counts **characters (Unicode code points)** since the start of the
line; every character, including tab and `\r`, occupies exactly one column.

1.2 The *end-of-input position* is the line/column immediately after the last
character of the source (trailing whitespace and comments included). For
`"1 + "` it is 1:5; for `""` it is 1:1.

### 2. Lexical rules

2.1 Whitespace is space, tab, `\r` and `\n`; it separates tokens and is
otherwise ignored. `#` starts a comment that runs to the end of the line.

2.2 A number literal is one or more ASCII digits, optionally followed by `.`
and one or more ASCII digits (`12`, `0.5`, `007`). There are no signed, exponent
or leading-dot literals (`-3` is unary minus applied to `3`).

2.3 A string literal is delimited by `"` or `'` (the same character at both
ends). Escapes: `\\`, `\"`, `\'`, `\n`, `\t`, and `\u{H}` where `H` is 1 to 6
hex digits naming a Unicode code point that is at most `10FFFF` and is not a
surrogate (`D800`–`DFFF`). Any other escape, or a malformed/invalid `\u{...}`,
is a `LexError` at the position of the backslash. A string that reaches the end
of input or a raw `\n` before its closing quote is a `LexError` at the position
of its opening quote.

2.4 Names are `[A-Za-z_][A-Za-z0-9_]*`. The keywords `true false null and or
not in` are reserved and case-sensitive (`True` is an ordinary name).

2.5 Operators and punctuation, matched longest-first (`**` before `*`, `//`
before `/`, `??` before `?`, `<=` before `<`, ...):
`**  //  ==  !=  <=  >=  ??  *  /  %  +  -  <  >  ?  :  (  )  [  ]  ,  .`

2.6 Any other character outside a string or comment (for example `=`, a lone
`!`, `@`, `&`, `é`) is a `LexError` at that character's position.

### 3. Grammar and precedence (lowest binds loosest)

| Level | Syntax | Associativity |
| --- | --- | --- |
| 1 | `c ? a : b` (conditional) | right (`a ? b : c ? d : e` = `a ? b : (c ? d : e)`) |
| 2 | `a ?? b` | left |
| 3 | `a or b` | left |
| 4 | `a and b` | left |
| 5 | `not a` (prefix) | — |
| 6 | `==  !=  <  <=  >  >=  in  not in` | chained (rule 4.6) |
| 7 | binary `+  -` | left |
| 8 | `*  /  //  %` | left |
| 9 | unary prefix `-  +` | — |
| 10 | `a ** b` | right; the right operand may itself start with unary `-`/`+` |
| 11 | postfix: member `a.name`, index `a[expr]` | left |
| 12 | literals, names, calls `f(args)`, `( expr )`, list literals `[a, b]` | — |

Consequences that must hold: `-2 ** 2` is `-(2 ** 2)`; `2 ** -1` is valid;
`2 ** 3 ** 2` is `2 ** 9`; `not a == b` is `not (a == b)`; `x ?? y ? p : q` is
`(x ?? y) ? p : q`; `not x in y` is `not (x in y)` while `x not in y` is the
two-word comparison operator.

3.1 A function call is a name immediately followed by `(`; arguments are
comma separated. List literals may be empty (`[]`); a trailing comma in a
list literal or call is a `ParseError` at the closing bracket/parenthesis.
Member names after `.` must be names (not keywords).

3.2 A `ParseError` is reported at the position of the first token that cannot
continue a valid expression; if that "token" is the end of input, at the
end-of-input position (rule 1.2). Extra tokens after a complete expression are
a `ParseError` at the first extra token.

3.3 Calling a function that is not in the built-in table (rule 6), or calling
a built-in with a number of arguments outside its allowed range, is a
`ParseError` at the position of the function name — detected by
`compile_rule`, not at evaluation time.

### 4. Evaluation semantics

4.1 Values are: numbers (`decimal.Decimal`), booleans, `null` (`None`),
strings, lists and maps (dicts with string keys). Number literals are exact
decimals (`0.1` is `Decimal("0.1")`), so `0.1 + 0.2 == 0.3` is `true`.
Arithmetic uses 28 significant digits.

4.2 Variables: an unknown root name raises `EvalError` at the name's position
**when evaluated** (compiling never fails because of unknown names). The value
of a variable is converted recursively when it is read: `bool` stays a
boolean (it is never treated as a number); `int` becomes `Decimal(int)`;
`float` becomes `Decimal(repr(value))` (so `0.1` becomes `Decimal("0.1")`);
`Decimal`, `str` and `None` are kept; `list`/`tuple` become lists; `dict` with
string keys becomes a map. Any other value anywhere inside the variable
(including non-finite floats and dicts with non-string keys) is an `EvalError`
at the position of the root name.

4.3 Arithmetic operators accept numbers only, except `+`, which also
concatenates two strings or two lists. Any other operand combination is an
`EvalError` at the operator.
- `/` is exact decimal division (`7 / 2` is `3.5`).
- `//` is **floored** division: the result is rounded toward negative infinity
  (`-7 // 2` is `-4`, `7 // -2` is `-4`).
- `%` is the **floored** modulo: `a - b * (a // b)`, so the result has the
  sign of the divisor (`-7 % 3` is `2`, `7 % -3` is `-2`, `5.5 % 2` is `1.5`).
- `/`, `//` and `%` with a zero divisor raise `EvalError` at the operator.
- `**`: the exponent must be an integer-valued number (`2 ** 0.5` is an
  `EvalError` at `**`); `0 ** n` with negative `n` is an `EvalError` at `**`;
  `2 ** -2` is `0.25`.
- Unary `-`/`+` require a number (`EvalError` at the operator otherwise).

4.4 Equality `==` / `!=` never raises. Values of different types are never
equal: in particular a boolean is never equal to a number (`true == 1` is
`false`). Numbers compare by value (`1 == 1.00`). Lists are equal when they
have the same length and pairwise-equal elements; maps when they have the same
keys and equal values — both recursively using these same rules
(`[true] == [1]` is `false`).

4.5 Ordering `<  <=  >  >=` requires two numbers or two strings (strings
compare by code point); anything else is an `EvalError` at the operator.

4.6 Comparison chains: `a op1 b op2 c ...` means `(a op1 b) and (b op2 c) ...`
where each operand is evaluated at most once, left to right, and evaluation
**stops at the first comparison that is false** (later operands are not
evaluated). `1 < 2 < 3` is `true`; `1 < 3 < 2` is `false`; `2 < 1 < x` is
`false` even if `x` is undefined. An error in a chain is reported at the
operator of the failing comparison.

4.7 `in` / `not in`: if the right operand is a list, membership uses the
equality of rule 4.4 (`true in [1]` is `false`); if it is a string, the left
operand must be a string (substring test); if it is a map, the left operand
must be a string (key test). Any other combination is an `EvalError` at the
operator (for `not in`, at the `not`).

4.8 `and`, `or`, `not` and the condition of `? :` require booleans; there is
no truthiness. A non-boolean operand is an `EvalError` at the `and`/`or`/`not`
keyword, or at the `?` for a conditional. `and`/`or` short-circuit: the right
operand is evaluated only when needed (`false and x` and `true or x` never
evaluate `x`). Only the selected branch of `? :` is evaluated.

4.9 `a ?? b` evaluates to `a` unless `a` is `null`, in which case `b` is
evaluated and returned (`false ?? 1` is `false`, `0 ?? 1` is `0`). `b` is not
evaluated when `a` is not null. `??` only replaces null values — it never
suppresses errors raised while evaluating `a`.

4.10 Member access `a.name`: if `a` is `null` the result is `null`; if `a` is
a map the result is its value for `name`, and a missing key is an `EvalError`
at the position of `name` (the name token, not the dot); any other `a` is an
`EvalError` at the position of `name`.

4.11 Indexing `a[i]`: if `a` is `null` the result is `null`. For a list or a
string, `i` must be an integer-valued number (booleans are not numbers);
negative indexes count from the end (`-1` is the last element); an index
outside the list/string is an `EvalError`. String indexing yields a one
character string (code points). For a map, `i` must be a string key that
exists. Every indexing failure is an `EvalError` at the position of the `[`.

### 5. Results

`Rule.evaluate` returns: `decimal.Decimal` for numbers, `bool`, `None`, `str`,
`list` for lists and `dict` for maps.

### 6. Built-in functions

Arity is checked at compile time (rule 3.3). Runtime argument errors are an
`EvalError` at the position of the function name.

| Function | Arguments | Result |
| --- | --- | --- |
| `len(x)` | exactly 1: string, list or map | number of code points / elements / keys |
| `lower(s)`, `upper(s)` | exactly 1 string | case-converted string |
| `abs(x)` | exactly 1 number | absolute value |
| `round(x)`, `round(x, places)` | 1 or 2; `x` a number; `places` an integer-valued number from 0 to 28 (default 0) | `x` rounded to `places` decimal places, **ties away from zero** (`round(2.5)` is `3`, `round(-2.5)` is `-3`, `round(1.005, 2)` is `1.01`) |
| `min(a, ...)`, `max(a, ...)` | 1 or more; all numbers or all strings | smallest / largest argument |

## Allowed paths

`rulecalc/`, `tests/`, `README.md`.

## Non-goals

- No assignment, user-defined functions, loops, dates or regular expressions.
- No performance work beyond "a rule of a few hundred characters evaluates
  instantly".
- The exact wording of error messages and the shape of the internal syntax
  tree are not specified.

## Acceptance criteria

- Every rule above holds through the public API.
- Visible tests pass: `python3 -m unittest discover -s tests -v`.
- Standard library only; Python 3.8+ compatible.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

Summarize the module layout you chose, any rule you found ambiguous and how
you resolved it, and the test results.
