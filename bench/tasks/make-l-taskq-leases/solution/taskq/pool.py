"""A deterministic, cooperatively scheduled worker pool.

Handlers are generator functions ``handler(payload, ctx)``; every ``yield``
is one unit of work (one turn). The pool gives each worker one turn per round,
in list order, then advances the clock by ``round_seconds``. This makes every
interleaving reproducible in tests while exercising the same lease protocol as
the threaded production pool.
"""
from .errors import LeaseLost, WorkerCrash


class Context(object):
    def __init__(self, pool, worker, lease):
        self.pool = pool
        self.worker = worker
        self.job_id = lease.job_id
        self.attempt = lease.attempt

    def now(self):
        return self.pool.clock.now()

    def crash(self):
        raise WorkerCrash()


class _Worker(object):
    def __init__(self, name):
        self.name = name
        self.lease = None
        self.gen = None
        self.expires_at = None


class WorkerPool(object):
    def __init__(self, queue, clock, handler, workers=('w1', 'w2'), lease_seconds=30, heartbeat_margin=10,
                 retry_delay=5, round_seconds=10):
        self.queue = queue
        self.clock = clock
        self.handler = handler
        self.lease_seconds = lease_seconds
        self.heartbeat_margin = heartbeat_margin
        self.retry_delay = retry_delay
        self.round_seconds = round_seconds
        self._workers = [_Worker(name) for name in workers]
        self.results = []   # (job_id, worker, return value) for every acknowledged run
        self.lost = []      # (job_id, worker, attempt) for every run whose lease was lost

    def busy(self):
        return any(w.lease is not None for w in self._workers)

    def run_round(self):
        for worker in self._workers:
            self._turn(worker)
        self.clock.advance(self.round_seconds)

    def run_until_idle(self, max_rounds=1000):
        """Run rounds until no worker is busy and no job is ready or leased; returns the round count."""
        rounds = 0
        while self.busy() or self._pending():
            if rounds >= max_rounds:
                raise RuntimeError('pool still busy after %d rounds' % rounds)
            self.run_round()
            rounds += 1
        return rounds

    # -- internals ---------------------------------------------------------------
    def _pending(self):
        stats = self.queue.stats()
        return stats['ready'] + stats['leased'] > 0

    def _turn(self, worker):
        if worker.lease is None:
            lease = self.queue.claim(worker.name, self.lease_seconds)
            if lease is None:
                return
            worker.lease = lease
            worker.expires_at = lease.expires_at
            worker.gen = self.handler(lease.payload, Context(self, worker.name, lease))
            self._step(worker)
            return
        if self.clock.now() >= worker.expires_at - self.heartbeat_margin:
            try:
                worker.expires_at = self.queue.extend(worker.lease, self.lease_seconds)
            except LeaseLost:
                self._abandon(worker, lost=True)
                return
        self._step(worker)

    def _step(self, worker):
        try:
            next(worker.gen)
        except StopIteration as stop:
            self._finish(worker, True, stop.value)
        except WorkerCrash:
            self._abandon(worker, lost=False)
        except Exception:
            self._finish(worker, False, None)

    def _finish(self, worker, success, value):
        lease = worker.lease
        self._reset(worker)
        try:
            if success:
                self.queue.ack(lease)
                self.results.append((lease.job_id, worker.name, value))
            else:
                self.queue.nack(lease, self.retry_delay)
        except LeaseLost:
            self.lost.append((lease.job_id, worker.name, lease.attempt))

    def _abandon(self, worker, lost):
        lease, gen = worker.lease, worker.gen
        self._reset(worker)
        gen.close()
        if lost:
            self.lost.append((lease.job_id, worker.name, lease.attempt))

    @staticmethod
    def _reset(worker):
        worker.lease = None
        worker.gen = None
        worker.expires_at = None
