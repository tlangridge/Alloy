# SPEC: long jobs re-run forever, crashed jobs never dead-letter, dedupe drops requests (taskq)

## Goal

Find and fix the defects behind the three production incidents below so the
queue and the worker pool behave as documented in `README.md` (the documented
contract is restated under "Desired behavior"). Keep the deterministic pool
design and every documented behavior that works today.

## Current behavior

Incident notes from the batch team. All reproductions are deterministic and
run on a clean checkout:

```python
from taskq import FakeClock, JobQueue, WorkerPool

# INC-1: long exports never finish although heartbeats are enabled
def export(payload, ctx):
    for _ in range(payload['steps']):
        yield
    return 'exported %s' % payload['name']

clock = FakeClock(); q = JobQueue(clock)
jid = q.enqueue({'name': 'march', 'steps': 8})
pool = WorkerPool(q, clock, export, workers=('w1', 'w2'),
                  lease_seconds=30, heartbeat_margin=10, round_seconds=10)
pool.run_until_idle(max_rounds=100)
# RuntimeError: pool still busy after 100 rounds
# pool.results == []; pool.lost == [(1, 'w1', 1), (1, 'w2', 2), (1, 'w1', 3), ...]
# i.e. the export is taken away from its worker every 30 s and restarted by the
# other worker; q.job(jid).attempts keeps growing.

# INC-2: a reindex requested while a reindex is running is silently dropped
clock = FakeClock(); q = JobQueue(clock)
first = q.enqueue({'index': 42, 'rev': 1}, key='reindex:42')
lease = q.claim('w1', 30)                   # reindex of rev 1 starts
second = q.enqueue({'index': 42, 'rev': 2}, key='reindex:42')
second == first                              # True -> rev 2 is never indexed

# INC-3: a job that kills its worker (OOM) is retried forever
def oom(payload, ctx):
    yield
    ctx.crash()

clock = FakeClock(); q = JobQueue(clock)
jid = q.enqueue({'huge': True})
pool = WorkerPool(q, clock, oom)
pool.run_until_idle(max_rounds=200)
# RuntimeError; q.job(jid).attempts == 67 and the job is never dead-lettered
```

Expected: INC-1 completes once on `w1` with no lost leases; INC-2 creates a
second job; INC-3 dead-letters the job after 3 attempts.

## Desired behavior

Queue (`JobQueue`):

1. `enqueue(payload, key=None, delay=0, priority=0, max_attempts=3)` returns
   ids 1, 2, 3, …; the job is available at `now + delay`.
2. A job enqueued with a key holds the key from enqueue until it is claimed
   for the first time. While a job holds the key, `enqueue` with that key
   returns that job's id and creates nothing (this applies to delayed jobs
   too). Once claimed, a job never holds a key again — not while running, not
   after a retry, not after it is done or dead — so the next `enqueue` with the
   key creates a new job, which then holds the key under the same rule.
   Finishing, retrying or dead-lettering an older job never affects which job
   holds a key.
3. `claim(worker, lease_seconds)` picks, among ready jobs with
   `available_at <= now`, the highest priority, then the earliest
   `available_at`, then the lowest id; it increments `attempts` and returns a
   `Lease` with a new token and `expires_at = now + lease_seconds`.
4. A lease is valid while its job is leased under that lease's token and
   `now < expires_at`. At `now >= expires_at` the attempt counts as used: if
   `attempts >= max_attempts` the job becomes `dead` with `dead_reason`
   `'lease-expired'`, otherwise `ready` with `available_at = expires_at`.
   Expiry is applied at the start of every public method (`claim`, `ack`,
   `nack`, `extend`, `job`, `stats`).
5. `ack` → `done`. `nack(lease, delay)` → `ready` at `now + delay`, or `dead`
   with `'failed'` when `attempts >= max_attempts`. `extend(lease, seconds)`
   sets the expiry to `now + seconds` and returns it. With an invalid lease
   (rule 4) each raises `LeaseLost` and changes nothing.
6. `job(id)` returns `JobInfo(id, state, attempts, available_at, expires_at,
   dead_reason, worker)`; `stats()` returns counts for `ready`, `leased`,
   `done`, `dead`.

Worker pool (`WorkerPool`):

7. `run_round()` gives each worker one turn in `workers` order, then advances
   the clock by `round_seconds`.
8. Idle worker: `claim(name, lease_seconds)`; with a lease it creates the
   handler generator and runs its first step in the same turn.
9. Busy worker: heartbeat first — when `now >= expiry - heartbeat_margin`
   (expiry = the value returned by the claim or by the last `extend`) it calls
   `extend(lease, lease_seconds)`; on `LeaseLost` it abandons the job (closes the
   generator, appends `(job_id, worker, attempt)` to `pool.lost`) and the turn
   ends. Then it runs one step.
10. Handler finished → `ack` and append `(job_id, worker, value)` to
    `pool.results`; handler raised → `nack(lease, retry_delay)`;
    `WorkerCrash` → drop the job without ack/nack. An ack/nack raising
    `LeaseLost` appends to `pool.lost` (no result recorded).
11. `run_until_idle(max_rounds=1000)` runs rounds while a worker is busy or
    the queue has ready or leased jobs, returns the number of rounds, and raises
    `RuntimeError` when `max_rounds` is reached.
12. Consequence that must hold: a job whose handler needs any number of steps
    completes exactly once, on the worker that claimed it, with no lost lease,
    whenever `heartbeat_margin >= round_seconds` and
    `lease_seconds > heartbeat_margin` (for example lease 30 / margin 10 /
    round 10, lease 25 / margin 5 / round 5, lease 30 / margin 10 / round 7).

## Allowed paths

`taskq/`, `tests/`, `README.md`.

## Non-goals

- No real threads, sleeps or wall-clock time.
- No change to the public API or to the result/lost record formats.

## Acceptance criteria

- The three incident reproductions behave as expected (above).
- Rules 1–12 hold; add regression tests under `tests/`.
- `python3 -m unittest discover -s tests -v` passes.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

For each incident, name the root cause(s) (file and function), explain why the
symptom needed that exact timing or sequence, and how your fix keeps rules 2,
4 and 9 intact.
