# SPEC: schedule expressions with next/previous occurrence (cadence)

## Goal

Implement `cadence.parse` and `cadence.Schedule` so the job runner can
compute when jobs fire. The expression language is cron-like, but its rules
are the ones below — some deliberately differ from classic cron
implementations, so follow this document, not memory.

## Current behavior

`cadence/errors.py`, `cadence/fields.py` (field ranges, names, macros) and
`cadence/jobs.py` (the job table that calls `Schedule.next_after`) exist.
`cadence.parse` and every `Schedule` method raise `NotImplementedError`.

## Desired behavior

### Public API

- `cadence.parse(expression: str) -> cadence.Schedule`; invalid expressions
  raise `cadence.CronSyntaxError` (a `ValueError`) with attributes `field` and
  `item` (see rule 12).
- `Schedule.matches(when) -> bool`
- `Schedule.next_after(when) -> datetime | None`
- `Schedule.previous_before(when) -> datetime | None`
- `Schedule.occurrences(after, count) -> list[datetime]`

All datetimes are **naive** `datetime.datetime` values; passing one with a
`tzinfo` raises `ValueError`. There are no time zones and no DST.

### Expression syntax

1. After stripping leading/trailing spaces and tabs, an expression is either a
   macro (rule 2) or exactly five fields separated by one or more spaces/tabs:
   `minute hour day_of_month month day_of_week`. Any other number of fields →
   `CronSyntaxError` with `field=None`.
2. Macros (matched case-insensitively): `@yearly` and `@annually` = `0 0 1 1 *`;
   `@monthly` = `0 0 1 * *`; `@weekly` = `0 0 * * 0`; `@daily` and `@midnight`
   = `0 0 * * *`; `@hourly` = `0 * * * *`. Any other text starting with `@` →
   `CronSyntaxError` with `field=None` and `item` = the stripped expression.
3. Field ranges: minute 0–59, hour 0–23, day_of_month 1–31, month 1–12,
   day_of_week 0–7 where **both 0 and 7 mean Sunday** (1 = Monday … 6 =
   Saturday). Values are ASCII decimal integers (leading zeros allowed) or, in
   the month field only, `JAN`…`DEC`, and in the day_of_week field only,
   `SUN`…`SAT` (names are case-insensitive). A value outside its field's range
   or a name in the wrong field is an error.
4. A field is a comma-separated list of one or more items; an empty item
   (`1,,2`, `5,`) is an error. Generic items:
   - `*` — every value; for `*` (and for `V/S`, below) the upper bound of
     day_of_week is 6, so `*` there means 0–6;
   - `V` — one value;
   - `V-W` — the values from `V` to `W` inclusive. `V > W` is an error, except in
     day_of_week where it wraps: the sequence is `V, …, 6, 0, …, W`
     (`FRI-MON` = Fri, Sat, Sun, Mon). In day_of_week a range *start* of 7 is
     treated as 0, while an *end* of 7 stays 7 (`5-7` = Fri, Sat, Sun);
   - `*/S`, `V-W/S`, `V/S` — take every `S`-th value of the sequence, starting
     with its first element. `V/S` means `V-max/S` (max per the `*` bound
     above). `S` is a decimal integer ≥ 1 (`0` is an error; a step larger than
     the sequence just yields its first element). Example: `MON-SUN/2` in
     day_of_week wraps (`SUN` is 0), so the sequence 1, 2, 3, 4, 5, 6, 0 stepped
     by 2 gives Mon, Wed, Fri, Sun.
5. Special day_of_month items (only in that field, never with a step, allowed
   inside lists): `L` = the last day of the month; `L-n` with `1 <= n <= 30` =
   `n` days before the last day (`L-1` is the second-to-last day). If `L-n`
   falls before the 1st, it matches nothing that month.
6. Special day_of_week items (only in that field, never with a step or range,
   allowed inside lists): `V#K` with `1 <= K <= 5` = the K-th such weekday of the
   month (`MON#2` second Monday; `#5` matches only in months that have a 5th);
   `VL` = the last such weekday of the month (`5L`, `FRIL`, `friL`, `7L` =
   last Sunday). `V` may be a number or a name.
7. `?` is allowed only as the **entire** day_of_month or day_of_week field and
   means the same as `*`. Anywhere else (other fields, or inside a list) it is
   an error.

### Day matching

8. The day_of_month field is **unrestricted** if and only if it is exactly
   `*` or `?`; likewise day_of_week. Anything else — including `*/1`, `1-31`,
   `*,5`, `0-7` — is restricted.
9. If both day fields are restricted, a day matches when **either** field
   matches it (OR). If exactly one is restricted, only that field decides. If
   neither is, every day matches. The month field must always match.

### Occurrences

10. `matches(when)` ignores seconds and microseconds.
11. `next_after(when)` returns the earliest datetime with `second == 0` and
    `microsecond == 0` that is **strictly later** than `when` and matches.
    `previous_before(when)` returns the latest such datetime that is **strictly
    earlier** than `when` (so from `10:00:30` it can return `10:00:00`). The
    search covers every date from `when` forward through December 31 of year
    `when.year + 8` (backward: through January 1 of `when.year - 8`); if there is
    no match in that window the result is `None`.
    `occurrences(after, count)` returns up to `count` consecutive results of
    `next_after`, starting from `after`, stopping early at `None`.

### Errors

12. `CronSyntaxError.field` is the field name (`'minute'`, `'hour'`,
    `'day_of_month'`, `'month'`, `'day_of_week'`) and `.item` is the offending
    comma-separated item exactly as written (`''` for an empty item), for every
    error inside a field. Whole-expression errors use `field=None` (rules 1, 2).

## Allowed paths

`cadence/`, `tests/`, `README.md`.

## Non-goals

- No seconds or years fields, no time zones, no `W` (nearest weekday) items.
- No performance requirement beyond each call finishing well under a second.

## Acceptance criteria

- Every rule above holds; `cadence/jobs.py` works unchanged on top of it.
- `python3 -m unittest discover -s tests -v` passes.
- Standard library only; Python 3.8+.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

Summarize your data model for a parsed schedule, how you search for the next
and previous occurrence, and any rule you found ambiguous.
