# SPEC: per-client rate limits are not enforced and idle clients are never forgotten

## Goal
Find and fix the root causes of two production problems in the `throttle`
package so that `KeyedLimiter` enforces its limits and releases idle clients,
while every other documented behavior stays the same.

## Current behavior
Incident notes (INC-5531):

> 1. Scrapers are getting through our "5/min" limit on the search endpoint.
>    Only the bulk export endpoint (cost=2) ever returns 429.
>
>    ```python
>    from throttle.clock import FakeClock
>    from throttle.limiter import KeyedLimiter
>    clock = FakeClock()
>    lim = KeyedLimiter(capacity=5, rate=5/60, clock=clock)
>    print([lim.allow('10.0.0.7').allowed for _ in range(8)])
>    # [True, True, True, True, True, True, True, True]
>    # expected [True, True, True, True, True, False, False, False]
>    print([lim.allow('10.0.0.8', cost=2).allowed for _ in range(4)])
>    # [True, True, False, False]   (looks right)
>    ```
>
> 2. Memory of the API pods grows all day. `sweep()` runs every minute but
>    almost never removes anything:
>
>    ```python
>    clock.advance(3600)          # nobody has been seen for an hour
>    print(lim.sweep(), len(lim)) # 0 2    expected 2 0
>    ```
>
> Someone suggested the refill arithmetic or the cost handling is broken.

The existing tests pass.

## Desired behavior
1. **TokenBucket** (`throttle/bucket.py`, `TokenBucket(capacity, rate, clock)`):
   starts full; refills continuously at `rate` tokens/second up to
   `capacity`; if the clock goes backwards no time passes and the reference
   time never moves backwards. `try_take(cost=1)` takes `cost` tokens if
   available and returns `True`, else returns `False` and takes nothing;
   `wait_time(cost=1)` is the seconds until `cost` tokens are available (`0.0`
   if now); both raise `ValueError` unless `0 < cost <= capacity`.
   `idle_for()` is the seconds since the last `try_take` (allowed or not) or
   since creation. `len(bucket)` is the number of **whole** tokens available
   now (`floor`), used by the metrics exporter — it must keep working.
   `is_full()` is `True` iff the bucket, refilled up to the current clock
   time, holds `capacity` tokens.
2. **KeyedLimiter** (`throttle/limiter.py`,
   `KeyedLimiter(capacity, rate, clock, idle_ttl=300.0)`): each key has its
   own bucket, created full on the key's first request and then **kept and
   reused** for every later request by that key until `sweep()` removes it —
   regardless of how many tokens it holds.
3. `allow(key, cost=1)` returns `Decision(allowed, retry_after, remaining)`:
   when allowed, `retry_after == 0`; when rejected, `retry_after` is
   `ceil(wait_time(cost))` whole seconds and at least 1. `remaining` is
   `len(bucket)` after the decision. A request made exactly `retry_after`
   seconds after a rejection (with no requests in between) is allowed.
4. `sweep()` removes every bucket whose `idle_for() >= idle_ttl` **and** that
   `is_full()` at the current time, and returns how many it removed. `len(limiter)`
   and `key in limiter` reflect the stored buckets. A removed key that comes
   back starts with a new full bucket.
5. `KeyedLimiter.from_policy(text, clock, idle_ttl=300.0)` and
   `throttle.policy.parse(text)` keep their current behavior
   (`"<count>/<unit>"`, units s/sec/second, m/min/minute, h/hour, d/day;
   returns `(count, count / seconds_per_unit)`; `ValueError` otherwise).
6. Keep all public names and signatures unchanged.

## Allowed paths
`throttle/`, `tests/`.

## Non-goals
Thread safety, distributed limiting, changing the refill model, automatic
sweeping inside `allow`.

## Acceptance criteria
- Both reproductions print the expected output.
- Rules 1–6 hold for any sequence of calls, not just the reported ones.
- Add regression tests in `tests/`; existing tests still pass.

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
For each symptom state the root cause (file and function), why it showed up
only for some requests or clients, the fix, and before/after output.
