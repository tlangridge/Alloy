"""Rate limiters keyed by API key (or any hashable)."""
import threading


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
