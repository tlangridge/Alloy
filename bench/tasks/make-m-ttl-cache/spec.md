# SPEC: LRU + expiry semantics for `memo.ExpiringCache`

## Goal
Turn `memo.cache.ExpiringCache` into a correct, bounded LRU cache with
per-entry time-to-live, optional sliding expiry, a read-through loader and
statistics, following the exact rules below. The clock is injected (a
zero-argument callable returning seconds, e.g. `memo.clock.FakeClock`); never
call `time` directly for expiry decisions.

## Current behavior
`ExpiringCache` only supports `set`, `get`, `in` and `len`. Capacity eviction
drops the oldest *inserted* key (FIFO, reads do not count), an entry is still
returned at the exact instant it expires, invalid TTLs are accepted, `len`
counts expired entries, and there is no `peek`, `delete`, `get_or_load`,
sliding expiry or statistics.

## Desired behavior
Public API (all in `memo/cache.py`, class `ExpiringCache`):

- `ExpiringCache(capacity=128, default_ttl=None, clock=memo.clock.monotonic, sliding=False)`
- `set(key, value, ttl=None) -> None`
- `get(key, default=None)`
- `peek(key, default=None)`
- `delete(key) -> bool`
- `get_or_load(key, loader, ttl=None)`
- `stats() -> dict`
- `key in cache`, `len(cache)`

Rules:

1. **Validation.** `capacity` must be an integer >= 1 and `default_ttl` must be
   `None` or a number > 0; otherwise the constructor raises `ValueError`.
   `set`/`get_or_load` raise `ValueError` for a `ttl` that is not `None` and is
   <= 0, and in that case the cache is left completely unchanged.
2. **TTL.** The effective TTL of a stored entry is the `ttl` argument if it is
   not `None`, else `default_ttl`. An entry stored at clock time `t` with
   effective TTL `d` has `expires_at = t + d`; an effective TTL of `None` means
   the entry never expires.
3. **Expiry boundary.** An entry is *live* while `clock() < expires_at`. At
   `clock() == expires_at` (and after) it is expired and must be treated as
   absent by every operation.
4. **Recency.** `set` (of a new or an existing key), and a `get` or
   `get_or_load` that returns a cached value (a hit), make that key the most
   recently used. `peek`, `in` and `len` never change recency.
5. **Updating a key.** `set` on a key that is already stored replaces its value
   and restarts its expiry using the new effective TTL. Updating a stored key
   never evicts or expires any other entry.
6. **Capacity.** When `set` (or a `get_or_load` miss) adds a key that is not
   currently stored and the cache already stores `capacity` entries (expired
   entries that have not been removed yet count as stored), it first removes
   **every** expired entry; only if it still stores `capacity` entries does it
   evict the single least recently used entry. No purging happens when the
   cache is not full.
7. **Sliding expiry.** With `sliding=True`, every hit from `get` or
   `get_or_load` resets that entry's `expires_at` to `clock() + d`, where `d` is
   the entry's own effective TTL from when it was stored (not `default_ttl`).
   Entries that never expire are unaffected. `peek` and `in` never extend
   expiry. With `sliding=False` (default) reads never change expiry.
8. **get.** Returns the value of a live entry; otherwise returns `default`. An
   expired entry found by `get` is removed.
9. **peek / in / len.** `peek(key, default=None)` returns a live entry's value
   or `default`, and changes nothing: no recency update, no expiry extension,
   no removal of expired entries, no statistics. `key in cache` is `True` iff
   the key is stored and live. `len(cache)` is the number of live entries at
   the current clock time (stored-but-expired entries are not counted).
10. **delete.** `delete(key)` removes the key. It returns `True` if a live
    entry was removed and `False` if the key was absent or expired (an expired
    entry is still removed).
11. **get_or_load.** On a hit it returns the cached value (rules 4 and 7
    apply). On a miss it calls `loader(key)` exactly once, stores the result
    under `key` with effective TTL from `ttl`/`default_ttl` (rules 2 and 6
    apply), and returns it. If `loader` raises, the exception propagates
    unchanged and nothing is stored for `key`. A stored value of `None` is a
    valid cached value.
12. **Statistics.** `stats()` returns a new dict with exactly the integer keys
    `hits`, `misses`, `evictions`, `expirations`:
    - `hits` / `misses`: one per `get` or `get_or_load` call that did / did
      not find a live entry (`peek` and `in` are not counted);
    - `evictions`: entries removed as least recently used by rule 6;
    - `expirations`: expired entries actually removed (by `get`,
      `get_or_load`, `delete`, or the capacity purge of rule 6).

## Allowed paths
`memo/`, `tests/`, `README.md`.

## Non-goals
Thread safety, persistence, size-by-bytes limits, background expiry threads.
Do not change `memo/clock.py` semantics.

## Acceptance criteria
- Every rule above holds for the listed public API.
- Existing visible tests still pass; add tests for the new rules in `tests/`.
- Standard library only, Python 3.8+.

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
Report which rules you implemented, the files changed and the test output.
