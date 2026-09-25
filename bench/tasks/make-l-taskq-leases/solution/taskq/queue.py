"""Lease-based job queue (at-least-once delivery)."""
import itertools
from collections import namedtuple

from .errors import LeaseLost
from .store import JobStore

Lease = namedtuple('Lease', 'job_id token attempt payload expires_at worker')
JobInfo = namedtuple('JobInfo', 'id state attempts available_at expires_at dead_reason worker')


class JobQueue(object):
    def __init__(self, clock, store=None):
        self.clock = clock
        self.store = store if store is not None else JobStore()
        self._tokens = itertools.count(1)

    # -- producers ---------------------------------------------------------------
    def enqueue(self, payload, key=None, delay=0, priority=0, max_attempts=3):
        """Add a job; returns its id. A pending job with the same key is reused."""
        if key is not None:
            owner = self.store.key_owner(key)
            if owner is not None:
                return owner
        job = self.store.create(payload, key, self.clock.now() + delay, priority, max_attempts)
        if key is not None:
            self.store.hold_key(key, job.id)
        return job.id

    # -- workers -----------------------------------------------------------------
    def claim(self, worker, lease_seconds):
        self._expire_leases()
        now = self.clock.now()
        job = self.store.next_ready(now)
        if job is None:
            return None
        job.state = 'leased'
        job.attempts += 1
        job.token = next(self._tokens)
        job.worker = worker
        job.claimed_at = now
        job.expires_at = now + lease_seconds
        # A job holds its dedupe key only until it is first claimed; requests that
        # arrive while it runs must create a new job.
        if job.key is not None and self.store.key_owner(job.key) == job.id:
            self.store.release_key(job.key)
        return Lease(job.id, job.token, job.attempts, job.payload, job.expires_at, worker)

    def ack(self, lease):
        job = self._check(lease)
        job.state = 'done'
        job.token = None

    def nack(self, lease, delay=0):
        job = self._check(lease)
        if job.attempts >= job.max_attempts:
            self._bury(job, 'failed')
        else:
            job.state = 'ready'
            job.available_at = self.clock.now() + delay
            job.token = None

    def extend(self, lease, seconds):
        """Keep the lease alive for ``seconds`` more; returns the new expiry time."""
        job = self._check(lease)
        job.expires_at = self.clock.now() + seconds
        return job.expires_at

    # -- inspection --------------------------------------------------------------
    def job(self, job_id):
        self._expire_leases()
        j = self.store.get(job_id)
        return JobInfo(j.id, j.state, j.attempts, j.available_at, j.expires_at, j.dead_reason, j.worker)

    def stats(self):
        self._expire_leases()
        counts = {'ready': 0, 'leased': 0, 'done': 0, 'dead': 0}
        for j in self.store.all():
            counts[j.state] += 1
        return counts

    # -- internals ---------------------------------------------------------------
    def _check(self, lease):
        self._expire_leases()
        job = self.store.get(lease.job_id)
        if job is None or job.state != 'leased' or job.token != lease.token:
            raise LeaseLost('lease %r is no longer valid' % (lease,))
        return job

    def _bury(self, job, reason):
        job.state = 'dead'
        job.dead_reason = reason
        job.token = None

    def _expire_leases(self):
        now = self.clock.now()
        for job in self.store.leased():
            if now >= job.expires_at:
                # The worker vanished or stalled: the attempt is used up.
                if job.attempts >= job.max_attempts:
                    self._bury(job, 'lease-expired')
                else:
                    job.state = 'ready'
                    job.available_at = job.expires_at
                    job.token = None
