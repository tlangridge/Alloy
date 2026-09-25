# SPEC: fix month arithmetic and renewal drift in `billing.periods`

## Goal
`billing.periods` computes renewal dates for monthly subscriptions. Two
production incidents trace back to it. Find and fix the root causes in
`billing/periods.py` so that `add_months`, `next_renewal` and `renewals` meet
the contract below, and add regression tests.

## Current behavior
Incident reports:

> **INC-2291: renewal job crashed.** A subscription anchored on 2024-11-15
> could not be renewed:
> ```python
> add_months(date(2024, 11, 15), 1)
> # calendar.IllegalMonthError: bad month number 0; must be 1-12
> ```
>
> **INC-2304: customer billed on the wrong day.** A customer who subscribed on
> 2024-01-31 was charged on 2024-03-29 instead of 2024-03-31, and on the 29th
> of every month after that:
> ```python
> next_renewal(date(2024, 1, 31), date(2024, 2, 29))   # date(2024, 3, 29)
> renewals(date(2024, 1, 31), 3)
> # [date(2024, 2, 29), date(2024, 3, 29), date(2024, 4, 29)]
> # expected [date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)]
> ```

## Desired behavior
All arguments and results are `datetime.date` objects (proleptic Gregorian
calendar, so leap years follow the usual 4/100/400 rule).

1. **`add_months(day, months)`** shifts `day` by `months` calendar months;
   `months` may be positive, zero or negative, and the year rolls over
   correctly in both directions. `add_months(day, 0)` returns `day`.
   Examples: 2024-11-15 +1 -> 2024-12-15; 2024-12-15 +1 -> 2025-01-15;
   2024-01-15 -1 -> 2023-12-15; 2024-12-05 +0 -> 2024-12-05;
   2024-06-10 +18 -> 2025-12-10; 2024-05-20 -17 -> 2022-12-20.
2. **Clamping.** If the target month is shorter than `day.day`, the result is
   the last day of the target month (2024-03-31 -1 -> 2024-02-29;
   2023-03-31 -1 -> 2023-02-28; 2024-02-29 +12 -> 2025-02-28).
3. **Renewal dates.** The renewal dates of a subscription anchored at `anchor`
   are `add_months(anchor, k)` for k = 1, 2, 3, ... Each one is computed from
   the anchor, never from the previous (possibly clamped) renewal: an anchor of
   2024-01-31 renews on 2024-02-29, 2024-03-31, 2024-04-30, 2024-05-31, ...
4. **`next_renewal(anchor, after)`** returns the earliest renewal date that is
   strictly later than `after`. If `after` is earlier than the first renewal
   (including when `after` is before the anchor), the result is the first
   renewal, `add_months(anchor, 1)`.
5. **`renewals(anchor, count)`** returns the first `count` renewal dates in
   order (`count >= 0`; `count == 0` gives `[]`).

## Allowed paths
- `billing/`
- `tests/`

## Non-goals
- No time zones, datetimes or business-day adjustments.
- No change to function names or signatures.
- No third-party dependencies; Python 3.8+ standard library only.

## Acceptance criteria
- Both incidents are fixed and every rule above holds, including every
  example given.
- The visible test suite passes, and new regression tests cover both incidents.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the root causes you found, the files you changed, and the test
command output before and after the fix.
