# SPEC: filtering, sorting and cursor pagination for the issue list and export

## Goal

Add multi-value filters, multi-key sorting and cursor (keyset) pagination to
`GET /issues`, and the same filters and sorting to `GET /issues/export.csv`,
for **both** storage backends (`MemoryIssueStore` and `SqliteIssueStore`),
while preserving every existing behavior. Restructure as needed: today the two
handlers each re-implement filtering over `store.all()`; the recommended shape
is one query object parsed once, executed by the service through a storage
`query(...)` method that both backends implement. Only the HTTP-level behavior
below is required.

## Current behavior

See `README.md`. `GET /issues` accepts a single optional `status`
(`open`/`in_progress`/`closed`/legacy `all`); a second `status` is rejected
with `duplicate_param`; any other parameter is `unknown_param`. The export
duplicates that code and sorts by `created_at`, then id. There is no sorting
or pagination.

## Desired behavior

Error responses are HTTP 400 with body exactly
`{"error": {"code": <code>, "param": <parameter name>}}`. "Matching items"
means the issues that pass every given filter.

### Parameters and validation order

1. `GET /issues` accepts `status`, `label`, `assignee`, `q`, `sort`, `limit`,
   `cursor`. `GET /issues/export.csv` accepts `status`, `label`, `assignee`,
   `q`, `sort` (so `limit`/`cursor` are unknown there). Any other parameter →
   `unknown_param`, reporting the alphabetically first unknown name. This check
   happens first.
2. `assignee`, `q`, `sort`, `limit` and `cursor` may appear at most once, else
   `duplicate_param` (checked second, in that order). `status` and `label` may
   be repeated.
3. Then the parameters are validated in this order, and the first failure is
   reported: `status`, `label`, `assignee`, `q`, `sort`, `limit`, `cursor`.

### Filters

4. `status`: each value must be `open`, `in_progress`, `closed` or `all`
   (anything else, including an empty value → `invalid_filter`/`status`).
   Several values combine with OR. `all` means "no status filter"; `all`
   together with any other status value → `invalid_filter`/`status`.
5. `label`: each value must be non-empty (else `invalid_filter`/`label`). An
   issue matches when it carries **every** given label (AND).
6. `assignee`: `none` matches issues without an assignee; any other value
   matches that assignee exactly (case-sensitive). Empty → `invalid_filter`/`assignee`.
7. `q`: an issue matches when `q.casefold()` is a substring of
   `title.casefold()` (so `straße` finds `STRASSE`, `ÉMILE` finds `Émile`).
   An empty `q` applies no text filter.

### Sorting

8. `sort` is a comma-separated list of keys, each optionally prefixed with `-`
   for descending: `id`, `priority` (numeric; ascending puts 1 first),
   `created` (`created_at`), `updated` (`updated_at`), `title` (compares
   `title.casefold()` by code point). An unknown key, an empty entry
   (`sort=`, `sort=priority,`) or the same key twice in any direction →
   `invalid_sort`/`sort`. If `id` is not listed, `id` ascending is appended as
   the final key, so the order is always total.
9. Default order when `sort` is absent: `id` for `GET /issues`; `created`,
   then `id` for the export (legacy order).

### Pagination (`GET /issues` only)

10. `limit` must consist of decimal digits only and be between 1 and 100,
    else `invalid_limit`/`limit`.
11. **Legacy mode.** When neither `limit` nor `cursor` is given, the response
    is exactly `{"items": [...]}` with every matching item in order — no
    `next_cursor` key (unchanged shape).
12. **Paged mode.** When `limit` and/or `cursor` is given, the response is
    `{"items": [...], "next_cursor": <string or null>}`. The page size is
    `limit`, or 25 when only `cursor` is given. Without a cursor the page is the
    first page-size matching items in order.
13. `next_cursor` is non-null if and only if at least one more matching item
    existed after the last returned item at the time of the request. It is an
    opaque string (clients pass it back URL-encoded as the `cursor` parameter).
14. **Keyset semantics.** A cursor captures the sort-key values (rule 8,
    including the appended `id`) of the last item of the page that produced it.
    The page for a cursor is the first page-size items, in order, among the
    issues matching **now** whose sort-key tuple comes strictly after the
    captured tuple in the requested order. Consequently: issues created after
    the first page appear later in the walk if they sort after the captured
    position and never cause duplicates; issues are placed by their current
    values; and updating the item that produced the cursor does not move the
    captured position.
15. A cursor is only valid with the same filters and sort as the request that
    produced it: same set of status values (`all`/no status are the same; order
    and repetition do not matter), same set of labels, same assignee, same `q`
    (compared after casefolding) and same `sort` (after rule 8). `limit` may
    differ between pages. A mismatch → `cursor_mismatch`/`cursor`. A value that
    the server did not produce (for example `garbage` or an empty string) →
    `invalid_cursor`/`cursor`.

### Export

16. The export keeps its current CSV format (header
    `id,title,status,priority,labels,assignee`, labels joined with `;`, empty
    field for no assignee, `csv` module quoting) and contains every matching
    item in the order of rules 8/9.

### Backends and compatibility

17. Every rule above holds identically for `MemoryIssueStore` and
    `SqliteIssueStore` (note that SQLite's `NOCASE` and `LIKE` only fold
    ASCII, so they do not implement rules 7 and 8).
18. Everything else in `README.md` is unchanged: issue creation/validation,
    `GET`/`PATCH /issues/<id>`, 404s, the legacy list shape, `status=all`, and
    `unknown_param`.

## Allowed paths

`tracker/`, `tests/`, `README.md`.

## Non-goals

- No deletion endpoint, no total counts, no offset pagination.
- No change to the issue JSON representation or to POST/PATCH validation.
- Cursor format and signing are implementation details (no crypto required).

## Acceptance criteria

- All rules hold through `App.handle` for both backends.
- Existing visible tests still pass; add tests for the new behavior.
- Standard library only; Python 3.8+.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

Describe the new layering (what each layer owns), how the cursor is encoded
and validated, and how the SQLite backend handles casefolding.
