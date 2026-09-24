"""Rate limiters keyed by API key (or any hashable)."""
import threading
from bisect import bisect_right


def _positive_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('%s must be a positive integer, got %r' % (name, value))
    return value


class FixedWindowLimiter:
    """At most `limit` allowed requests per key in each aligned window.

    Windows are [k * window_ms, (k + 1) * window_ms) on the clock's timeline.
    """

    def __init__(self, limit, window_ms, clock):
        self.limit = _positive_int('limit', limit)
        self.window_ms = _positive_int('window_ms', window_ms)
        self._clock = clock
        self._counts = {}          # key -> (window index, allowed count)
        self._lock = threading.Lock()

    def allow(self, key):
        with self._lock:
            index = self._clock() // self.window_ms
            window, count = self._counts.get(key, (index, 0))
            if window != index:
                count = 0
            if count >= self.limit:
                return False
            self._counts[key] = (index, count + 1)
            return True


class SlidingLogLimiter:
    """At most `limit` allowed requests per key in any `window_ms` span.

    A request at time t is allowed iff fewer than `limit` requests were allowed
    in the half-open interval (t - window_ms, t]; a request exactly window_ms
    old has dropped out. Rejected requests are not recorded, so a client that
    keeps hammering does not extend its own lockout.

    Each key keeps a sorted log of allowed timestamps, pruned lazily when the
    key is next used; a key whose log empties is deleted.
    """

    def __init__(self, limit, window_ms, clock):
        self.limit = _positive_int('limit', limit)
        self.window_ms = _positive_int('window_ms', window_ms)
        self._clock = clock
        self._logs = {}            # key -> ascending list of allowed timestamps
        self._lock = threading.Lock()

    def _live(self, key, now):
        """The key's timestamps inside (now - window_ms, now], older ones dropped."""
        log = self._logs.get(key)
        if log is None:
            return []
        # Everything <= now - window_ms has expired; bisect_right puts the cut
        # after entries equal to the boundary so they are dropped too.
        expired = bisect_right(log, now - self.window_ms)
        if expired:
            del log[:expired]
        if not log:
            del self._logs[key]
        return log

    def allow(self, key):
        """Record and allow the request, or reject it without recording."""
        with self._lock:
            now = self._clock()
            log = self._live(key, now)
            if len(log) >= self.limit:
                return False
            if not log:
                self._logs[key] = log
            log.append(now)
            return True

    def retry_after(self, key):
        """Milliseconds until allow(key) would succeed; 0 if it would now."""
        with self._lock:
            now = self._clock()
            log = self._live(key, now)
            if len(log) < self.limit:
                return 0
            # The log never holds more than `limit` live entries; the next slot
            # frees when the oldest of the last `limit` requests leaves the window.
            return log[-self.limit] + self.window_ms - now
