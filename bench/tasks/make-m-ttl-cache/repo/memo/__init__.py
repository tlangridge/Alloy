"""memo: a small in-process cache with expiry for service lookups."""
from memo.cache import ExpiringCache
from memo.clock import FakeClock

__all__ = ['ExpiringCache', 'FakeClock']
