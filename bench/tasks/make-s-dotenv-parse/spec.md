# SPEC: quoting, comments and `export` in `.env` parsing

## Goal
`envfile.parse_env` is too naive for the `.env` files our services actually
ship: quotes end up inside values, inline comments leak into values, and
`export` lines produce broken keys. Rewrite `parse_env` in
`envfile/parser.py` so it implements the rules below. `load_env` must keep
working (it calls `parse_env`).

## Current behavior
- `parse_env('GREETING="hello world"')` returns `{'GREETING': '"hello world"'}`
  (quotes kept).
- `parse_env('PORT=8080 # default')` returns `{'PORT': '8080 # default'}`.
- `parse_env('export TOKEN=abc')` returns `{'export TOKEN': 'abc'}`.
- Invalid keys such as `MY-KEY=1` are accepted, and escape sequences inside
  double quotes are not processed.

## Desired behavior
`envfile.parser.parse_env(text: str) -> dict` returns a dict mapping each key
(`str`) to its value (`str`). `DotenvError` is the existing exception class (a
subclass of `ValueError` with a `lineno` attribute).

1. **Lines.** `text` is split into lines on `\n`; a `\r` at the end of a line
   is removed. Lines are numbered from 1. A line that is empty or contains
   only whitespace is ignored, and so is a line whose first non-whitespace
   character is `#`.
2. **Assignments.** Every other line must have the form `KEY=VALUE`,
   optionally preceded by the word `export` followed by at least one space or
   tab; the `export` prefix is discarded (`export TOKEN=abc` sets `TOKEN`).
   Whitespace is allowed before the key, between the key and `=`, and after
   `=`. The key must match `[A-Za-z_][A-Za-z0-9_]*`. A line with no `=` or with
   an invalid key raises `DotenvError`. A key may itself start with the letters
   `export` (`exporter=1` sets `exporter`).
3. **Unquoted values.** Let the *raw value* be the text after the first `=`.
   If the raw value, ignoring leading spaces and tabs, does not begin with `"`
   or `'`, the value is unquoted: an inline comment starts at the first `#`
   that immediately follows a space or tab in the raw value, and that `#` and
   everything after it are removed; then surrounding whitespace is stripped.
   A `#` that does not immediately follow a space or tab is part of the value.
   Examples: `A=b # note` -> `b`; `A=b#c` -> `b#c`; `COLOR=#fff` -> `#fff`;
   `EMPTY= # nothing` -> `""`; `A=` -> `""`; `MSG=hello world` -> `hello world`.
4. **Double-quoted values.** If the raw value (ignoring leading spaces and
   tabs) begins with `"`, the value extends to the next `"` that is not
   escaped by a backslash. Inside the quotes, `\n` becomes a newline, `\t` a
   tab, `\"` a double quote and `\\` a single backslash; a backslash followed
   by any other character is kept unchanged (both characters, so `"\d"` ->
   `\d`). Whitespace and `#` inside the quotes are kept verbatim. Values never
   span lines: a missing closing quote raises `DotenvError`.
5. **Single-quoted values.** If the raw value begins with `'`, the value
   extends to the next `'` and is taken literally, with no escape processing
   (`'a\nb'` is the four characters `a`, `\`, `n`, `b`). A missing closing
   quote raises `DotenvError`.
6. **After a closing quote** only whitespace, optionally followed by a `#`
   comment, may appear on the line; anything else (`A="x" y`, `A='x'y`) raises
   `DotenvError`.
7. **Duplicates and errors.** When a key appears more than once, the last
   value wins. Every `DotenvError` has `lineno` set to the 1-based number of
   the offending line (counting blank and comment lines).

## Allowed paths
- `envfile/`
- `tests/`

## Non-goals
- No variable interpolation (`${OTHER}` stays literal), no multi-line values.
- No change to `load_env`'s signature or override semantics.
- No third-party dependencies; Python 3.8+ standard library only.

## Acceptance criteria
- Every rule above holds, including every example given.
- The visible test suite passes; add tests of your own for the new rules.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the files you changed, the test command output, and any rule you
found ambiguous and how you resolved it.
