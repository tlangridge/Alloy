# SPEC: a test suite that pins down the backup retention policy

## Goal
`retention/policy.py` implements the backup retention planner used by the
backup agent. It is believed correct but has almost no tests, and the team is
about to refactor it. Write a unittest suite in `tests/` that specifies the
behavior below precisely enough that any change breaking one of the rules is
caught. Do **not** change `retention/` — only add or edit files in `tests/`.

## Current behavior
`tests/test_policy.py` has two smoke tests. Most rules below are untested, so
a refactor could silently change which backups get deleted.

## Desired behavior
The rules your tests must pin down. Public API: `retention.Backup(id, taken_at,
pinned=False)` (a namedtuple; `taken_at` is a naive `datetime`),
`retention.plan(backups, now, daily=7, weekly=4, monthly=6, max_age_days=None)`
returning `retention.Plan(keep, delete, skipped, reasons)`.

1. **Validation.** `daily`, `weekly`, `monthly` must be integers >= 0 and
   `max_age_days` must be `None` or an integer >= 1, otherwise `ValueError`.
   Duplicate backup ids raise `ValueError`.
2. **Future backups.** A backup with `taken_at > now` is neither kept nor
   deleted; its id is listed in `skipped` (input order) and it takes part in no
   other rule. A backup taken exactly at `now` is not in the future.
3. **Latest.** The newest non-future backup (pinned or not) is always kept,
   with reason `latest`.
4. **Pinned.** Pinned non-future backups are always kept (reason `pinned`) and
   are invisible to rules 5–7: they are never chosen for a slot, and a day,
   week or month that only has pinned backups does not use up a slot.
5. **Daily.** Among non-future, non-pinned backups, take the `daily` most
   recent distinct calendar dates (`taken_at.date()`) *that have backups* —
   not the last `daily` calendar days before `now` — and keep the newest
   backup of each such date (reason `daily`).
6. **Weekly.** The same with ISO weeks, identified by ISO year and ISO week
   number (`taken_at.isocalendar()`), for `weekly` weeks (reason `weekly`).
   For example 2024-12-30 and 2025-01-02 are both in ISO week 2025-W01.
7. **Monthly.** The same with calendar months `(year, month)`, for `monthly`
   months (reason `monthly`). A count of 0 disables that rule.
8. **Newest / ties.** "Newest" means the greatest `taken_at`; when several
   candidates share the greatest `taken_at`, the one with the greatest `id`
   (string comparison) wins. This applies to rules 3 and 5–7.
9. **Maximum age.** If `max_age_days` is set, a backup kept only by rules 5–7
   whose age `now - taken_at` is strictly greater than `max_age_days` days is
   deleted instead. Backups kept by rule 3 (latest) or rule 4 (pinned) are
   never deleted for age. A backup exactly `max_age_days` old is not too old.
10. **Everything else** that is not future and not kept is deleted.
11. **Result shape.** `keep`: kept ids ordered newest first (by `taken_at`,
    then `id`, descending). `delete`: deleted ids ordered oldest first (by
    `taken_at`, then `id`, ascending). `skipped`: future ids in input order.
    `reasons`: a dict mapping every kept id (and only kept ids) to the list of
    its reasons in the fixed order `latest, pinned, daily, weekly, monthly`.

## How your tests are graded
Your suite is run with `python3 -m unittest discover -s tests` from the
repository root:
- against the current, unmodified `retention/policy.py` — every test must
  pass;
- against each of a set of hidden faulty versions of `retention/policy.py`.
  Every faulty version breaks exactly **one** of rules 1–11 (for some inputs)
  and is otherwise identical. A faulty version is *killed* when the suite
  fails (any failing or erroring test).

The task passes only if the suite passes on the original and kills **every**
faulty version (the grader prints `BENCH_SCORE: killed/total`). Tests must be
deterministic, use fixed datetimes (never the real clock), need only the
standard library (Python 3.8+), and the whole suite must run in a few seconds.

## Allowed paths
`tests/`

## Non-goals
Changing or refactoring `retention/`; testing private helpers or error message
wording; timezone-aware datetimes.

## Acceptance criteria
- `python3 -m unittest discover -s tests -v` passes on the unmodified code.
- Each of rules 1–11 is exercised by at least one assertion on observable
  results of `plan()` (including boundaries and tie cases).

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
List which tests cover which rule and paste the test output.
