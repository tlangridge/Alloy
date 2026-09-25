"""Short-lived cache for rendered reports, shared by every tenant."""
from collections import OrderedDict


class TTLCache:
    """A small LRU cache whose entries expire `ttl` seconds after being stored."""

    def __init__(self, ttl, maxsize, clock):
        self.ttl = ttl
        self.maxsize = maxsize
        self.clock = clock
        self._data = OrderedDict()   # key -> (stored_at, value)

    def get(self, key):
        entry = self._data.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self.clock() - stored_at >= self.ttl:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key, value):
        self._data[key] = (self.clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def __len__(self):
        return len(self._data)


class TenantCache:
    """Per-tenant namespaces over TTLCache, so one tenant never sees another's entries."""

    def __init__(self, ttl=60.0, maxsize=256, clock=None):
        import time
        self.ttl = ttl
        self.maxsize = maxsize
        self.clock = clock or time.monotonic
        self._spaces = {}

    def _space(self, tenant_id):
        # Tenant ids are ints today but the accounts team wants to move to UUID
        # strings; hash() gives a uniform namespace key for either type.
        return self._spaces.setdefault(hash(tenant_id), TTLCache(self.ttl, self.maxsize, self.clock))

    def get(self, tenant_id, key):
        return self._space(tenant_id).get(key)

    def set(self, tenant_id, key, value):
        self._space(tenant_id).set(key, value)

    def clear(self):
        self._spaces.clear()
