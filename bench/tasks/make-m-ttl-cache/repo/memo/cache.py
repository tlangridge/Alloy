"""An in-process cache whose entries expire after a time-to-live.

Used by the account service to memoise directory lookups. The clock is
injected so expiry can be tested without sleeping.
"""
from collections import OrderedDict

from memo import clock as _clock


class ExpiringCache:
    def __init__(self, capacity=128, default_ttl=None, clock=_clock.monotonic):
        if capacity < 1:
            raise ValueError('capacity must be >= 1')
        self.capacity = capacity
        self.default_ttl = default_ttl
        self._clock = clock
        self._data = OrderedDict()  # key -> (value, expires_at or None)

    def set(self, key, value, ttl=None):
        ttl = self.default_ttl if ttl is None else ttl
        expires = None if ttl is None else self._clock() + ttl
        self._data[key] = (value, expires)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def get(self, key, default=None):
        item = self._data.get(key)
        if item is None:
            return default
        value, expires = item
        if expires is not None and self._clock() > expires:
            del self._data[key]
            return default
        return value

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)
