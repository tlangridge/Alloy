# SPEC: compound durations for retention policies

## Goal
Retention policies in the `retention` package are configured with duration
strings such as `keep = "30d"`. Operators want to write compound durations
like `"1w 3d"` or `"1h30m"`, and reports need to print durations back in a
canonical form. Implement `parse_duration` and `format_duration` in
`retention/durations.py` exactly as specified below.

## Current behavior
- `parse_duration` accepts only a single lower-case component:
  `parse_duration("30d")` returns `2592000`, but `parse_duration("1h30m")`
  and `parse_duration("30D")` raise `ValueError`.
- `format_duration(5400)` raises `NotImplementedError`.

## Desired behavior

### `retention.durations.parse_duration(text: str) -> int`
Returns the total number of seconds as an `int`.

1. **Components.** A duration is one or more components. A component is a
   non-negative integer written with the digits `0`-`9`, immediately followed
   (no space) by a unit letter: `w` = 604800 s, `d` = 86400 s, `h` = 3600 s,
   `m` = 60 s, `s` = 1 s. Unit letters are case-insensitive (`"2H"` equals
   `"2h"`). The result is the sum of all components, and a component's number
   is not limited by the next larger unit (`"1h30m"` -> 5400, `"90m"` -> 5400,
   `"0h"` -> 0).
2. **Whitespace.** Leading and trailing whitespace is ignored. Components may
   be separated by any amount of whitespace or by nothing (`"1h30m"`,
   `"1h 30m"` and `"1w\t2d"` are all valid). Whitespace between a number and
   its unit is not allowed (`"5 m"` is invalid).
3. **Order.** Units must appear in strictly decreasing size order
   (`w`, `d`, `h`, `m`, `s`) and each unit at most once: `"1d2h"` is valid;
   `"2h1d"` (out of order) and `"1h 1h"` (repeated) are invalid.
4. **Bare seconds.** If the whole string, after stripping surrounding
   whitespace, is just an integer, it is a number of seconds (`"90"` -> 90,
   `" 0 "` -> 0). A number without a unit is not allowed inside a
   multi-component string (`"1h 30"` is invalid).
5. **Errors.** Every other input raises `ValueError`, including: empty or
   whitespace-only strings, signs (`"-5m"`, `"+5m"`), decimals (`"1.5h"`),
   unknown units (`"5y"`, `"5ms"`), and any other characters such as
   separators or punctuation (`"1h, 30m"`, `"1h30m!"`, `"h"`). A `text`
   argument that is not a `str` (for example `90`, `None` or `b"1h"`) raises
   `TypeError`.

### `retention.durations.format_duration(seconds: int) -> str`
6. Returns the canonical form: components from the largest to the smallest
   unit (`w`, `d`, `h`, `m`, `s`), lower-case, no spaces, zero components
   omitted, each component as large as possible. Examples: 5400 -> `"1h30m"`,
   694861 -> `"1w1d1h1m1s"`, 86400 -> `"1d"`, 3601 -> `"1h1s"`, 59 -> `"59s"`.
   Zero is `"0s"`. A negative value raises `ValueError`. For every
   non-negative integer `n`, `parse_duration(format_duration(n)) == n`.

`retention.policy.expired` must keep working unchanged (it calls
`parse_duration`, so it gains compound durations automatically).

## Allowed paths
- `retention/`
- `tests/`

## Non-goals
- No new units (months, years, milliseconds) and no fractional values.
- No changes to `retention.policy` behavior or to the package's public names.
- No third-party dependencies; Python 3.8+ standard library only.

## Acceptance criteria
- Every rule above holds, including every example given.
- The visible test suite passes; add tests of your own for the new rules.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the files you changed, the test command output, and any rule you
found ambiguous and how you resolved it.
