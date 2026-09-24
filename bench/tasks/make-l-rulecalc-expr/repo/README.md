# rulecalc

A small, sandboxed expression language used by the pricing service to evaluate
eligibility and discount rules written by the commercial team, e.g.

```
customer.tier in ["gold", "platinum"] and order.total >= 250
    ? round(order.total * 0.05, 2)
    : 0
```

Rules are compiled once (`compile_rule`) and evaluated many times against a
dictionary of variables (`Rule.evaluate`). The language must never execute
arbitrary Python: the old prototype that translated rules to Python and called
`eval()` has been deleted.

## Layout

| Module | Responsibility |
| --- | --- |
| `rulecalc/errors.py` | Error hierarchy with 1-based line/column positions (done) |
| `rulecalc/lexer.py` | Source text -> tokens |
| `rulecalc/parser.py` | Tokens -> syntax tree (precedence climbing / recursive descent) |
| `rulecalc/evaluator.py` | Syntax tree + variables -> value |
| `rulecalc/functions.py` | Built-in function table (names, arity, implementation) |
| `rulecalc/rule.py` | Public `Rule`, `compile_rule`, `evaluate` |

The language reference lives in the task specification handed to the
implementer; this README is only an overview.

## Running tests

```
python3 -m unittest discover -s tests -v
```
