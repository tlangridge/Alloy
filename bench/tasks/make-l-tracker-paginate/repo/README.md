# tracker

Internal issue tracker API. `App.handle(Request)` routes to handlers, which
call `IssueService` (business rules), which uses a storage backend. Two
backends exist and must behave identically: `MemoryIssueStore` (tests, local
dev) and `SqliteIssueStore` (production).

```python
from tracker import Request, create_app, FakeClock, SqliteIssueStore
app = create_app(SqliteIssueStore(), FakeClock())
app.handle(Request('POST', '/issues', {'title': 'Crash on save', 'priority': 1, 'labels': ['bug']}))
app.handle(Request('GET', '/issues?status=open'))
```

## Endpoints (current)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/issues` | `{"items": [issue, ...]}` sorted by id. Optional `status` (`open`, `in_progress`, `closed`, or legacy `all`). |
| GET | `/issues/export.csv` | CSV (`id,title,status,priority,labels,assignee`, labels joined with `;`, empty assignee as empty field), ordered by `created_at` then id. Optional `status` as above. |
| POST | `/issues` | body: `title` (required), `priority` 1-4 (default 3, 1 = most urgent), `status` (default `open`), `labels` (list of non-empty strings), `assignee` (string, not `none`). 201 + issue. |
| GET | `/issues/<id>` | 200 + issue, 404 `not_found`. |
| PATCH | `/issues/<id>` | any of the POST fields; sets `updated_at`. |

Issue JSON: `id, title, status, priority, labels (sorted), assignee (or null), created_at, updated_at`
(integers, seconds, from the injected clock).

Errors are `{"error": {"code": ..., "param": ...}}` with HTTP 400 (validation)
or 404. Unknown query parameters are rejected with `unknown_param`.

## Tests

```
python3 -m unittest discover -s tests -v
```
