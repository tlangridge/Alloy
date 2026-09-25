# docpatch

Patch engine behind the settings service. Clients never upload whole
documents; they send an ordered list of operations addressed with pointers
(`/billing/contacts/0/email`). `DocumentStore` keeps a revision number per
document and applies patches with optimistic concurrency.

## Layout

| Module | Responsibility |
| --- | --- |
| `docpatch/errors.py` | `PatchError(code, index, pointer)` (done) |
| `docpatch/store.py` | Revisioned in-memory `DocumentStore` (done; relies on `apply_patch` being atomic) |
| `docpatch/pointer.py` | Pointer parsing, formatting and resolution |
| `docpatch/equality.py` | JSON value equality used by the `test` operation and by `diff` |
| `docpatch/ops.py` | `apply_patch(doc, patch)` |
| `docpatch/diff.py` | `diff(a, b)` producing a patch |

Documents are plain JSON-compatible Python values: `dict` (string keys),
`list`, `str`, `int`, `float`, `bool` and `None`.

## Tests

```
python3 -m unittest discover -s tests -v
```
