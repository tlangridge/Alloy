# taskq

Lease-based job queue with at-least-once delivery, plus a deterministic,
cooperatively scheduled worker pool used by the batch service and its tests.

## Queue (`taskq/queue.py`, records in `taskq/store.py`)

- `enqueue(payload, key=None, delay=0, priority=0, max_attempts=3) -> job id`
  (ids are 1, 2, 3, ...). The job becomes available at `now + delay`.
- **Dedupe keys.** A job enqueued with a `key` *holds* that key from the moment
  it is enqueued until it is claimed for the first time. While a job holds the
  key, `enqueue` with the same key returns that job's id and changes nothing.
  Once the job has been claimed, it never holds the key again (retries do not
  re-acquire it), so a later `enqueue` with that key creates a new job — the
  new request may carry newer data and must run after the one in progress.
- `claim(worker, lease_seconds) -> Lease | None` hands out the ready job with
  the highest priority, then the earliest `available_at`, then the lowest id,
  among jobs with `available_at <= now`. The claim increments `attempts` and
  issues a new lease that expires at `now + lease_seconds`.
- A lease is **valid while** the job is still leased under that lease's token
  **and `now < expires_at`**. At `now >= expires_at` the lease has expired: the
  attempt counts as used; if `attempts >= max_attempts` the job becomes `dead`
  with reason `'lease-expired'`, otherwise it becomes `ready` again with
  `available_at = expires_at`. Expiry is applied at the start of every public
  queue method, so every observation reflects it.
- `ack(lease)` marks the job `done`. `nack(lease, delay)` makes it `ready` at
  `now + delay`, or `dead` with reason `'failed'` when `attempts >= max_attempts`.
  `extend(lease, seconds)` moves the lease expiry to **`now + seconds`** and
  returns it. With an invalid lease all three raise `LeaseLost` and change
  nothing.
- `job(id)` returns a `JobInfo` snapshot; `stats()` counts jobs per state
  (`ready` includes delayed jobs).

## Worker pool (`taskq/pool.py`)

- Handlers are generator functions `handler(payload, ctx)`; each `yield` is one
  unit of work. `ctx.crash()` simulates the worker process dying.
- `run_round()` gives each worker one turn, in the order of `workers`, then
  advances the clock by `round_seconds`.
- An idle worker's turn: `claim`; if it got a lease it starts the handler and
  runs its first step in the same turn.
- A busy worker's turn: **heartbeat first** — if `now >= lease expiry -
  heartbeat_margin` it calls `extend(lease, lease_seconds)` (on `LeaseLost` it
  abandons the job, records it in `pool.lost` and the turn ends) — then one
  step.
- When the handler returns, the worker acks and records
  `(job_id, worker, value)` in `pool.results`; when it raises, the worker nacks
  with `retry_delay`; on `WorkerCrash` it drops the job without ack/nack. An
  ack/nack that raises `LeaseLost` is recorded in `pool.lost` (and the result is
  not recorded).
- `run_until_idle(max_rounds)` runs rounds until no worker is busy and the
  queue has no ready or leased jobs; it raises `RuntimeError` after
  `max_rounds`.

## Tests

```
python3 -m unittest discover -s tests -v
```
