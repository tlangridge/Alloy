# SPEC: fix ByteRanges bookkeeping for out-of-order chunks

## Goal
`fetchkit.ranges.ByteRanges` records which byte ranges of a download have
been received. Since we enabled parallel range requests, chunks arrive out of
order and the resume planner re-downloads data it already has. Find and fix
the root cause(s) in `fetchkit/ranges.py` so the class meets its full contract
below, and add regression tests.

## Current behavior
Bug report from the asset sync team:

> A file of 50 bytes was fetched as chunks `[0,10)`, `[20,30)`, `[40,42)` and
> then a large retry chunk `[5,45)`:
>
> ```python
> received = ByteRanges()
> for start, end in [(0, 10), (20, 30), (40, 42), (5, 45)]:
>     received.add(start, end)
> received.ranges()    # [(0, 45), (40, 42)]   expected [(0, 45)]
> received.covered()   # 47                    expected 45
> received.missing(50) # [(42, 50)]            expected [(45, 50)]
> ```
>
> So the planner asks for bytes 42-44 again, and progress bars sometimes
> report more bytes received than the file has.
>
> Separately, the verifier uses `offset in received` and it claims the first
> byte *after* a range is present: after `received.add(0, 10)`,
> `10 in received` is `True`, although only bytes 0-9 were received.

## Desired behavior
All ranges are half-open: `[start, end)` contains the integer offsets
`start <= offset < end`.

1. `add(start, end)` records `[start, end)`. It raises `ValueError` if
   `start < 0` or `end < start`; `add(x, x)` is a no-op.
2. After any sequence of `add` calls, in any order, `ranges()` returns the
   minimal description of the received bytes: a list of `(start, end)` tuples
   sorted by start, with no two ranges overlapping **or touching** (ranges
   such as `[0,10)` and `[10,20)` are merged into `[0,20)`, whichever of them
   was added first). A new range may overlap, bridge or contain any number of
   existing ranges.
3. `covered()` returns the number of distinct bytes received.
4. `offset in received` is `True` exactly when some received range satisfies
   `start <= offset < end`.
5. `missing(size)` returns, sorted, the maximal gaps of `[0, size)` that have
   not been received, as `(start, end)` tuples; received bytes at or beyond
   `size` are ignored. `is_complete(size)` is `True` exactly when
   `missing(size)` is empty.

## Allowed paths
- `fetchkit/`
- `tests/`

## Non-goals
- No new public methods and no change to method signatures.
- No performance work beyond keeping `add` reasonable for a few thousand ranges.
- No third-party dependencies; Python 3.8+ standard library only.

## Acceptance criteria
- Both reported symptoms are fixed and every rule above holds.
- The visible test suite passes, and new regression tests cover the reported
  cases.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the root cause(s) you found, the files you changed, and the test
command output before and after the fix.
