# SPEC: confkit resolves inherited values wrongly and misreports error lines

## Goal
Find and fix the root causes of two regressions in the `confkit` configuration
loader so that it behaves as documented in `README.md` and below.

## Current behavior
Bug report from the deploy team (ticket OPS-2203):

> 1. After the loader "performance work", every section gets the **same**
>    value for keys inherited from `[DEFAULT]`, even when the section overrides
>    what they reference:
>
>    ```python
>    from confkit import load
>    cfg = load("[DEFAULT]\nroot = /srv/app\nlogs = ${root}/logs\n\n"
>               "[web]\nport = 8080\n\n[worker]\nroot = /srv/worker\n")
>    cfg.get('web', 'logs')      # '/srv/app/logs'   (correct)
>    cfg.get('worker', 'logs')   # '/srv/app/logs'   (expected '/srv/worker/logs')
>    ```
>
> 2. Error messages point at the wrong line for multi-line values, which makes
>    big configs painful to fix:
>
>    ```python
>    load("[deploy]\nhosts = web1,\n    web2,\n    # web3 is being rebuilt\n"
>         "    ${spare_host}\nregion = eu-west\n")
>    # ConfigError: line 5: undefined reference ${spare_host}
>    # expected:    line 2: undefined reference ${spare_host}
>    ```
>
> We are not sure whether these are one bug or two.

The existing tests pass.

## Desired behavior
The documented behavior (README.md) must hold. In particular:

1. `confkit.load(text)` returns a `Config`; `Config.sections()` lists the
   sections in file order **excluding** `[DEFAULT]`; `cfg[section]` is a dict
   of that section's own keys followed by the keys it inherits from
   `[DEFAULT]`; `cfg.get(section, key, default=None)` and
   `cfg.getint(section, key)` read resolved values (keys case-insensitive).
2. Syntax: comment lines (`#`/`;` after optional indentation) are skipped and
   do **not** end a multi-line value; a blank line ends it; an indented
   non-comment line continues the previous entry's value, pieces joined with
   single spaces; inline comments need whitespace before `#`/`;`.
3. `${key}` looks in the section being resolved, then `[DEFAULT]`;
   `${section:key}` looks in `section` (which must exist; section names are
   case-sensitive), then `[DEFAULT]`; `$$` is a literal `$`.
4. A value inherited from `[DEFAULT]` is interpolated **in the context of the
   section that inherits it** — for every section independently, including
   when it is reached through `${section:key}`.
5. Values are resolved section by section in file order, own keys first, then
   inherited keys. A reference that would re-enter a value currently being
   resolved raises `ConfigError` (a cycle).
6. Every `ConfigError` has `lineno` = the line on which the offending entry or
   header **starts** (the first line of a multi-line value), and `str(err)` is
   `"line N: <message>"`. This holds for every error: malformed lines, empty
   keys, keys outside a section, duplicate sections/keys (the line where the
   second one starts), continuation lines with no preceding entry (that
   line), bad `$` usage, unterminated or undefined references and cycles (the
   entry containing the offending reference), and `getint` on a non-integer
   (the entry that defines the value, which may be in `[DEFAULT]`).
7. Keep the public API (`load`, `Config`, `ConfigError`) and module layout.

## Allowed paths
`confkit/`, `tests/`.

## Non-goals
New syntax, write support, performance tuning beyond keeping resolution
linear for typical configs, changing error message texts.

## Acceptance criteria
- Both reproductions give the expected results.
- Rules 1–7 hold for any configuration, not only the reported ones.
- Add regression tests in `tests/`; existing tests still pass.

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
For each symptom state the root cause (file and function), the fix, and
before/after output of the reproduction.
