# SPEC: pointer-addressed patch engine (docpatch)

## Goal

Implement `docpatch`: pointer parsing/formatting/resolution, JSON equality,
atomic patch application with seven operations and precise error codes, and a
`diff` that produces patches. `docpatch/store.py` (already written) must work
correctly on top of it.

## Current behavior

`docpatch/errors.py` and `docpatch/store.py` are complete. `pointer.py`,
`equality.py`, `ops.py` and `diff.py` raise `NotImplementedError`, so the
visible tests fail and `DocumentStore.patch` cannot be used.

## Desired behavior

Documents are JSON-compatible Python values: `dict` with `str` keys, `list`,
`str`, `int`, `float`, `bool`, `None`. The public API is importable from the
package: `docpatch.parse_pointer`, `docpatch.format_pointer`,
`docpatch.resolve`, `docpatch.json_equal`, `docpatch.apply_patch`,
`docpatch.diff`, `docpatch.PatchError`. Every failure raises
`docpatch.PatchError` (never `KeyError`, `IndexError`, `TypeError`, ...)
with attributes `code`, `index` and `pointer` as described below.

### Pointers

1. `parse_pointer(pointer) -> list[str]`. `""` is the whole document and
   parses to `[]`. Any other pointer must start with `/`; it is split on `/`
   into reference tokens (so `"/"` is `[""]` and `"/a//b"` is `["a", "", "b"]`).
   In each token `~1` decodes to `/` and `~0` decodes to `~`, decoded left to
   right in a single pass (`"/~01"` is `["~1"]`, not `["/"]`). A `~` followed
   by anything other than `0` or `1` (or by nothing) is invalid. Invalid
   pointers (including non-strings and strings not starting with `/`) raise
   `PatchError` with code `invalid-pointer`, `index=None`, `pointer` = the
   argument.
2. `format_pointer(tokens) -> str` is the exact inverse: `[]` → `""`; each
   token is escaped (`~` → `~0`, `/` → `~1`) and prefixed with `/`.
3. Traversal. Tokens are followed one by one from the document root:
   - through a `dict`, the token is a key; a missing key → `path-not-found`;
   - through a `list`, the token must be an *array index*: exactly `0` or a
     digit `1`–`9` followed by digits. Anything else — `-`, `01`, `+1`, `1.0`,
     ` 1` — → `invalid-index`. An index `>= len(list)` → `path-not-found`;
   - through any scalar (string, number, boolean, null) → `path-not-found`.
   A dict key is any string: `"01"` and `"-"` are ordinary keys of a dict.
4. `resolve(document, pointer)` returns the value the pointer refers to,
   raising `invalid-pointer` or the traversal errors of rule 3 with
   `index=None` and `pointer` = the argument.

### JSON equality

5. `json_equal(a, b) -> bool`: `None` equals only `None`; a `bool` equals only
   a `bool` of the same value (**`True` is not equal to `1`, `False` is not
   equal to `0`**); numbers (`int`/`float`, excluding `bool`) are equal when
   numerically equal (`1 == 1.0`); strings by value; lists when they have the
   same length and pairwise-equal elements (order matters); dicts when they
   have the same key set and equal values (key order irrelevant); all
   recursively with these same rules.

### apply_patch(document, patch) -> new document

6. `patch` must be a `list` of `dict` operations; otherwise `invalid-op`
   (`index=None` when `patch` itself is not a list; the element's index when
   an element is not a dict).
7. **The whole patch is validated structurally before any operation is
   applied.** If several operations are structurally invalid, the one with the
   lowest index is reported — even if an earlier, structurally valid operation
   would have failed while being applied. Structural validity of one operation:
   - `op` is one of `add`, `remove`, `replace`, `move`, `copy`, `test`, `inc`
     (else `invalid-op`);
   - `path` is present and a string (else `invalid-op`), and is a
     syntactically valid pointer (else `invalid-pointer`, `pointer` = that
     path);
   - `add`, `replace` and `test` must have a `value` member. Presence is what
     counts: `"value": None` is a valid value (JSON null). Missing → `invalid-op`;
   - `move` and `copy` must have a string `from` member (else `invalid-op`)
     that is a valid pointer (else `invalid-pointer`, `pointer` = that from);
   - `inc` must have a `by` member that is an `int` or `float` but not a
     `bool` (else `invalid-op`).
   Unknown extra members are ignored. For `invalid-op`, `index` is the
   operation's index; its `pointer` attribute is not specified.
8. Operations are applied in order; each one sees the result of the previous
   ones. If any operation fails, `PatchError` is raised with `index` = that
   operation's index, and **nothing is changed**: `apply_patch` never mutates
   `document` (or the patch), whether it succeeds or fails.
9. The returned document shares no mutable containers (lists/dicts) with the
   input document or with the patch: values taken from the patch or copied
   within the document are deep copies.
10. Unless stated otherwise, an error's `pointer` is the operation's `path`
    exactly as given. Failures while locating a `from` location report
    `pointer` = the `from` string.
11. `add`: `path ""` replaces the whole document with `value`. Otherwise the
    parent (all tokens but the last) is located with rule 3, then:
    parent `dict` → set the key (replacing an existing value);
    parent `list` → last token `-` appends; a valid array index `i` with
    `0 <= i <= len` inserts before position `i` (so `i == len` appends); `i > len`
    → `path-not-found`; a token that is not a valid array index →
    `invalid-index`; parent scalar → `path-not-found`.
12. `remove`: `path ""` → `cannot-remove-root`. Otherwise the target must exist
    (rule 3; `-` → `invalid-index`) and is removed; later list elements shift
    left.
13. `replace`: `path ""` replaces the whole document. Otherwise the target must
    exist (rule 3) and its value is replaced.
14. `move`: in this order — (a) the `from` location must exist (rule 3, errors
    report the `from` pointer); (b) if `from` and `path` have identical tokens
    the operation does nothing; (c) if the tokens of `from` are a **proper
    prefix of the tokens** of `path` → `move-into-self` (a token-wise check:
    moving `/a/b` to `/a/bc` is allowed, `/a` to `/a/b` is not, and `""` to any
    non-empty path is not); (d) the value is removed from `from` and then added
    at `path` using the `add` rules evaluated **on the document after the
    removal** (moving `/l/0` to `/l/2` in `["a", "b", "c"]` gives
    `["b", "c", "a"]`).
15. `copy`: the `from` location must exist (errors report the `from`
    pointer); a deep copy of its value is added at `path` with the `add` rules.
16. `test`: the target must exist (rule 3); if its value is not `json_equal`
    to `value` → `test-failed`.
17. `inc`: the target must exist (rule 3) and be an `int` or `float` that is not
    a `bool`, else `type-mismatch`. It is replaced by `target + by`; the result
    is an `int` when both are `int`, otherwise a `float`.

### diff(source, target) -> patch

18. For any two documents, `apply_patch(source, diff(source, target))` is
    `json_equal` to `target`. `diff` never mutates its arguments.
19. The patch uses only `add`, `remove` and `replace` operations. Each emitted
    operation is a dict with exactly the members `op` and `path`, plus `value`
    for `add`/`replace`; values are deep copies. Keys containing `/` or `~` (and
    the empty key) are escaped per rule 2.
20. If `json_equal(source, target)` the patch is `[]` (so `diff(1, 1.0)` is `[]`
    but `diff(True, 1)` is not).
21. When the JSON types differ (null, boolean, number, string, array, object;
    `int` and `float` are both "number") or two scalars are unequal, the patch
    for that location is a single `replace` of it (at the root this is
    `[{"op": "replace", "path": "", "value": target}]`).
22. When both are objects, the patch for that location is, in this order:
    `remove` for each key only in `source` (ascending key order); then the
    recursive diff of each key present in both (ascending key order); then
    `add` for each key only in `target` (ascending key order). The operations
    produced for two arrays are not prescribed beyond rules 18, 19 and 21.

### DocumentStore

23. `DocumentStore.patch` (unchanged) must behave atomically: a patch that
    fails with `PatchError` leaves the stored document and revision exactly as
    they were.

## Allowed paths

`docpatch/`, `tests/`, `README.md`.

## Non-goals

- No JSON text parsing/serialization; inputs are Python values.
- No concurrency beyond the existing revision check in `DocumentStore`.
- Minimal array diffs (e.g. detecting moves) are not required.

## Acceptance criteria

- All rules above hold through the public API.
- `python3 -m unittest discover -s tests -v` passes.
- Standard library only; Python 3.8+.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

List the error codes you raise for each operation, any rule you found
ambiguous and how you resolved it, and test results.
