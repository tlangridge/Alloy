"""Per-client rate limiting: one token bucket per key."""
from collections import namedtuple
import math

from throttle import policy as _policy
from throttle.bucket import TokenBucket

Decision = namedtuple('Decision', 'allowed retry_after remaining')


class KeyedLimiter:
    def __init__(self, capacity, rate, clock, idle_ttl=300.0):
        if idle_ttl <= 0:
            raise ValueError('idle_ttl must be positive')
        self.capacity = capacity
        self.rate = rate
        self.idle_ttl = idle_ttl
        self._clock = clock
        self._buckets = {}

    @classmethod
    def from_policy(cls, text, clock, idle_ttl=300.0):
        capacity, rate = _policy.parse(text)
        return cls(capacity, rate, clock, idle_ttl)

    def _bucket(self, key):
        bucket = self._buckets.get(key) or TokenBucket(self.capacity, self.rate, self._clock)
        self._buckets[key] = bucket
        return bucket

    def allow(self, key, cost=1):
        """Decision(allowed, retry_after, remaining) for one request by `key`."""
        bucket = self._bucket(key)
        if bucket.try_take(cost):
            return Decision(True, 0, len(bucket))
        return Decision(False, max(1, int(math.ceil(bucket.wait_time(cost)))), len(bucket))

    def sweep(self):
        """Forget buckets idle for at least idle_ttl that are full again (a new
        bucket would behave identically). Returns how many were removed."""
        stale = [key for key, bucket in self._buckets.items()
                 if bucket.idle_for() >= self.idle_ttl and bucket.is_full()]
        for key in stale:
            del self._buckets[key]
        return len(stale)

    def __len__(self):
        return len(self._buckets)

    def __contains__(self, key):
        return key in self._buckets
