"""A small expiring cache."""
import threading


class TTLCache:
    """Maps hashable keys to values for `ttl` seconds of `clock()` time.

    get() returns None for missing or expired keys, so None cannot be cached.
    """

    def __init__(self, ttl, clock):
        if ttl <= 0:
            raise ValueError('ttl must be positive')
        self.ttl = ttl
        self._clock = clock
        self._entries = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at >= self.ttl:
                del self._entries[key]
                return None
            return value

    def put(self, key, value):
        if value is None:
            raise ValueError('cannot cache None')
        with self._lock:
            self._entries[key] = (self._clock(), value)

    def drop_where(self, predicate):
        """Remove every entry whose key satisfies predicate(key); return how many."""
        with self._lock:
            doomed = [k for k in self._entries if predicate(k)]
            for k in doomed:
                del self._entries[k]
            return len(doomed)

    def __len__(self):
        with self._lock:
            return len(self._entries)
