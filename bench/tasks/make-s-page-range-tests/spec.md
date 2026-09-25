# SPEC: unit tests for `parse_page_ranges`

## Goal
`printq.pages.parse_page_ranges` parses the print queue's `--pages` option.
It is believed to be correct but has only one test, and we are about to
refactor it. Write a unit test suite in `tests/` that pins down every
behavior listed below, so that any future change that breaks one of them
makes the suite fail.

**Do not modify `printq/`.** This task is about tests only.

## Current behavior
`tests/test_pages.py` contains a single happy-path test (`"1-3"`). The
implementation in `printq/pages.py` implements all of the behaviors below.

## Desired behavior
Your tests must cover each of these behaviors of
`parse_page_ranges(spec: str, page_count: int) -> list` (a list of `int`):

- **B1 Items and whitespace.** `spec` is a comma-separated list of items.
  Whitespace around items and around the `-` of a range is ignored:
  `"1 - 3, 5"` with 10 pages gives `[1, 2, 3, 5]`.
- **B2 Pages and inclusive ranges.** `"N"` selects page N; `"A-B"` selects
  pages A through B inclusive (`"2-4"` gives `[2, 3, 4]`; `"4-4"` gives `[4]`).
- **B3 Open-ended ranges.** `"A-"` selects A through `page_count` (`"8-"`
  with 10 pages gives `[8, 9, 10]`); `"-B"` selects 1 through B (`"-3"` gives
  `[1, 2, 3]`).
- **B4 Sorted and de-duplicated.** The result is in ascending order with no
  duplicates: `"5, 1-3, 2"` gives `[1, 2, 3, 5]`.
- **B5 Reversed ranges.** A range whose start is greater than its end raises
  `ValueError` (`"5-3"`).
- **B6 Bounds.** Every selected page must be within `1..page_count`,
  otherwise `ValueError`: page `0` (`"0"`, `"0-2"`), a page above
  `page_count` (`"11"` with 10 pages), and a range whose end exceeds
  `page_count` (`"8-20"` with 10 pages) all raise.
- **B7 Empty input.** An empty or whitespace-only `spec` selects every page
  (`""` with 3 pages gives `[1, 2, 3]`). An empty item inside a non-empty spec
  raises `ValueError` (`"1,,3"`, `"1,2,"`, `",1"`).
- **B8 Malformed items** raise `ValueError`, for example `"a"`, `"1-2-3"`,
  `"-"`, `"1.5"`, `"+2"`.
- **B9 Empty documents.** `page_count < 1` raises `ValueError` whatever the
  spec, including an empty spec (`parse_page_ranges("", 0)`).

## How this task is graded
Your suite is run with `python3 -m unittest discover -s tests -v`:
1. against the current implementation, where every test must pass; and
2. against several deliberately broken copies of `printq/pages.py`, each of
   which violates exactly one of the behaviors B1-B9 above (and is otherwise
   identical to the current implementation).

The task is solved only if your suite passes on the current implementation
**and fails on every broken copy**. Tests must be deterministic, use only the
standard library, and finish in a few seconds.

## Allowed paths
- `tests/`

## Non-goals
- No changes to `printq/` or to the README.
- Error message wording is not part of the contract; do not assert on it.

## Acceptance criteria
- `python3 -m unittest discover -s tests -v` passes on the unmodified
  implementation.
- Each behavior B1-B9, including each example given, is exercised by at
  least one assertion.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the test files you wrote, which behaviors each test class covers, and
the test command output.
