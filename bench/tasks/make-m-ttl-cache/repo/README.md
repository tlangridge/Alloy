# memo

`memo` is the tiny in-process cache the account service uses to memoise
directory lookups (user -> groups, group -> policy). Entries expire after a
time-to-live measured by an injected clock, so tests never sleep.

```python
from memo import ExpiringCache, FakeClock

clock = FakeClock()
cache = ExpiringCache(capacity=256, default_ttl=30, clock=clock)
cache.set('alice', ['admins'])
cache.get('alice')          # ['admins']
clock.advance(31)
cache.get('alice')          # None
```

Run the tests with `python3 -m unittest discover -s tests -v`.
