"""Job records, ready-job selection and the dedupe-key index."""


class Job(object):
    def __init__(self, job_id, payload, key, available_at, priority, max_attempts):
        self.id = job_id
        self.payload = payload
        self.key = key
        self.available_at = available_at
        self.priority = priority
        self.max_attempts = max_attempts
        self.state = 'ready'        # ready | leased | done | dead
        self.attempts = 0
        self.token = None
        self.worker = None
        self.claimed_at = None
        self.expires_at = None
        self.dead_reason = None     # 'failed' | 'lease-expired'


class JobStore(object):
    def __init__(self):
        self._jobs = {}
        self._next_id = 1
        self._keys = {}             # dedupe key -> id of the job holding it

    def create(self, payload, key, available_at, priority, max_attempts):
        job = Job(self._next_id, payload, key, available_at, priority, max_attempts)
        self._jobs[job.id] = job
        self._next_id += 1
        return job

    def get(self, job_id):
        return self._jobs.get(job_id)

    def all(self):
        return [self._jobs[k] for k in sorted(self._jobs)]

    def leased(self):
        return [j for j in self.all() if j.state == 'leased']

    def next_ready(self, now):
        """The ready job to hand out next: highest priority, then earliest available_at, then lowest id."""
        ready = [j for j in self._jobs.values() if j.state == 'ready' and j.available_at <= now]
        if not ready:
            return None
        return min(ready, key=lambda j: (-j.priority, j.available_at, j.id))

    # -- dedupe keys -------------------------------------------------------------
    def hold_key(self, key, job_id):
        self._keys[key] = job_id

    def key_owner(self, key):
        return self._keys.get(key)

    def release_key(self, key):
        self._keys.pop(key, None)
