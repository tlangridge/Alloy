# ledger

A thin transactional layer over SQLite for the bookkeeping service.

* `ledger.pool.ConnectionPool` hands out a bounded number of connections.
* `ledger.tx.run_in_transaction(pool, work)` runs `work(conn)` inside a
  transaction and returns its result.
* `ledger.errors.is_transient(exc)` recognises SQLite failures that are worth
  retrying (lock contention, transient I/O).

Run the tests with `python3 -m unittest discover -s tests -v`.
