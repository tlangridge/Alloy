"""An in-process cache whose entries expire after a time-to-live.

Used by the account service to memoise directory lookups. The clock is
injected so expiry can be tested without sleeping.
"""
from collections import OrderedDict

from memo import clock as _clock

_MISSING = object()


def _check_ttl(ttl):
    if ttl is not None and not ttl > 0:
        raise ValueError('ttl must be None or > 0')


class _Entry:
    __slots__ = ('value', 'ttl', 'expires_at')

    def __init__(self, value, ttl, expires_at):
        self.value = value
        self.ttl = ttl
        self.expires_at = expires_at


class ExpiringCache:
    def __init__(self, capacity=128, default_ttl=None, clock=_clock.monotonic, sliding=False):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError('capacity must be an integer >= 1')
        _check_ttl(default_ttl)
        self.capacity = capacity
        self.default_ttl = default_ttl
        self.sliding = sliding
        self._clock = clock
        self._data = OrderedDict()  # key -> _Entry, least recently used first
        self._stats = dict(hits=0, misses=0, evictions=0, expirations=0)

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _live(entry, now):
        return entry.expires_at is None or now < entry.expires_at

    def _lookup(self, key):
        """Live entry for key (removing it if expired), or None."""
        entry = self._data.get(key)
        if entry is None:
            return None
        if self._live(entry, self._clock()):
            return entry
        del self._data[key]
        self._stats['expirations'] += 1
        return None

    def _hit(self, key, entry):
        self._data.move_to_end(key)
        if self.sliding and entry.ttl is not None:
            entry.expires_at = self._clock() + entry.ttl
        self._stats['hits'] += 1
        return entry.value

    def _store(self, key, value, ttl):
        ttl = self.default_ttl if ttl is None else ttl
        now = self._clock()
        entry = _Entry(value, ttl, None if ttl is None else now + ttl)
        if key in self._data:
            self._data[key] = entry
            self._data.move_to_end(key)
            return
        if len(self._data) >= self.capacity:
            expired = [k for k, e in self._data.items() if not self._live(e, now)]
            for k in expired:
                del self._data[k]
            self._stats['expirations'] += len(expired)
            if len(self._data) >= self.capacity:
                self._data.popitem(last=False)
                self._stats['evictions'] += 1
        self._data[key] = entry

    # -- public API ----------------------------------------------------------
    def set(self, key, value, ttl=None):
        _check_ttl(ttl)
        self._store(key, value, ttl)

    def get(self, key, default=None):
        entry = self._lookup(key)
        if entry is None:
            self._stats['misses'] += 1
            return default
        return self._hit(key, entry)

    def peek(self, key, default=None):
        entry = self._data.get(key)
        if entry is None or not self._live(entry, self._clock()):
            return default
        return entry.value

    def delete(self, key):
        entry = self._data.pop(key, None)
        if entry is None:
            return False
        if self._live(entry, self._clock()):
            return True
        self._stats['expirations'] += 1
        return False

    def get_or_load(self, key, loader, ttl=None):
        _check_ttl(ttl)
        entry = self._lookup(key)
        if entry is not None:
            return self._hit(key, entry)
        self._stats['misses'] += 1
        value = loader(key)
        self._store(key, value, ttl)
        return value

    def stats(self):
        return dict(self._stats)

    def __contains__(self, key):
        entry = self._data.get(key)
        return entry is not None and self._live(entry, self._clock())

    def __len__(self):
        now = self._clock()
        return sum(1 for e in self._data.values() if self._live(e, now))
