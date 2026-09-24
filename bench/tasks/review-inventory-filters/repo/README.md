# inventory

Product catalogue search for the warehouse back office, backed by SQLite.

* `inventory.db` - schema and helpers to create products and stock rows.
* `inventory.search.search(conn, ...)` - catalogue search used by the admin UI
  and the public `/api/products` endpoint (query parameters are passed through
  from the HTTP request, so every argument must be treated as untrusted).

Run the tests with `python3 -m unittest discover -s tests -v`.
