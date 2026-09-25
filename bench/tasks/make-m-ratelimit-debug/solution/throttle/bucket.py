"""A token bucket with continuous refill and an injected clock."""
import math


class TokenBucket:
    """Holds up to `capacity` tokens, refilled continuously at `rate` tokens/s.

    A new bucket starts full. If the clock goes backwards, no time is
    considered to have passed and the bucket's reference time does not move
    backwards.
    """

    def __init__(self, capacity, rate, clock):
        if capacity <= 0 or rate <= 0:
            raise ValueError('capacity and rate must be positive')
        self.capacity = capacity
        self.rate = rate
        self._clock = clock
        self._tokens = float(capacity)
        self._updated = clock()
        self._last_used = self._updated

    def _refill(self):
        now = self._clock()
        if now > self._updated:
            self._tokens = min(float(self.capacity), self._tokens + (now - self._updated) * self.rate)
            self._updated = now
        return now

    @property
    def tokens(self):
        """Tokens available now (fractional)."""
        self._refill()
        return self._tokens

    def _check_cost(self, cost):
        if not 0 < cost <= self.capacity:
            raise ValueError('cost must be in (0, capacity], got %r' % (cost,))

    def try_take(self, cost=1):
        """Take `cost` tokens if available; any attempt counts as activity."""
        self._check_cost(cost)
        now = self._refill()
        self._last_used = max(self._last_used, now)
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    def wait_time(self, cost=1):
        """Seconds until `cost` tokens will be available (0.0 if they are now)."""
        self._check_cost(cost)
        self._refill()
        missing = cost - self._tokens
        return 0.0 if missing <= 0 else missing / self.rate

    def idle_for(self):
        """Seconds since the last try_take (or creation)."""
        return max(0.0, self._clock() - self._last_used)

    def is_full(self):
        return self.tokens >= self.capacity

    def __len__(self):
        """Whole tokens available now; the metrics exporter reports this."""
        return int(math.floor(self.tokens))
