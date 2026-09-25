import unittest

from memo.cache import ExpiringCache
from memo.clock import FakeClock


def make(**kw):
    clock = FakeClock(100.0)
    kw.setdefault('capacity', 3)
    return ExpiringCache(clock=clock, **kw), clock


class ValidationTests(unittest.TestCase):
    def test_constructor_rejects_non_positive_default_ttl(self):
        for bad in (0, -1, -0.5):
            with self.assertRaises(ValueError):
                ExpiringCache(capacity=2, default_ttl=bad, clock=FakeClock())

    def test_set_rejects_non_positive_ttl_and_leaves_cache_unchanged(self):
        cache, clock = make(default_ttl=10)
        cache.set('k', 'old')
        for bad in (0, -3):
            with self.assertRaises(ValueError):
                cache.set('k', 'new', ttl=bad)
            with self.assertRaises(ValueError):
                cache.set('other', 'x', ttl=bad)
        self.assertEqual(cache.peek('k'), 'old')
        self.assertNotIn('other', cache)
        clock.advance(9.5)
        self.assertEqual(cache.get('k'), 'old')  # expiry was not restarted

    def test_get_or_load_rejects_non_positive_ttl(self):
        cache, _ = make()
        with self.assertRaises(ValueError):
            cache.get_or_load('k', lambda key: 'v', ttl=0)
        self.assertNotIn('k', cache)


class ExpiryTests(unittest.TestCase):
    def test_entry_is_expired_exactly_at_expires_at(self):
        cache, clock = make(default_ttl=10)
        cache.set('k', 'v')
        clock.advance(9.999)
        self.assertEqual(cache.get('k'), 'v')
        clock.set(110.0)
        self.assertIsNone(cache.get('k'))
        self.assertEqual(cache.get('k', 'dflt'), 'dflt')

    def test_boundary_applies_to_in_len_and_peek(self):
        cache, clock = make(default_ttl=5)
        cache.set('k', 'v')
        clock.advance(5)
        self.assertNotIn('k', cache)
        self.assertEqual(len(cache), 0)
        self.assertEqual(cache.peek('k', 'gone'), 'gone')

    def test_explicit_ttl_overrides_default(self):
        cache, clock = make(default_ttl=100)
        cache.set('short', 1, ttl=2)
        cache.set('long', 2)
        clock.advance(2)
        self.assertIsNone(cache.get('short'))
        self.assertEqual(cache.get('long'), 2)

    def test_no_ttl_means_never_expires(self):
        cache, clock = make()
        cache.set('k', 'v')
        clock.advance(10 ** 9)
        self.assertEqual(cache.get('k'), 'v')

    def test_update_restarts_expiry_with_new_ttl(self):
        cache, clock = make(default_ttl=10)
        cache.set('k', 1)
        clock.advance(8)
        cache.set('k', 2, ttl=5)
        clock.advance(4)
        self.assertEqual(cache.get('k'), 2)
        clock.advance(1)
        self.assertIsNone(cache.get('k'))


class RecencyAndCapacityTests(unittest.TestCase):
    def test_get_hit_refreshes_recency(self):
        cache, _ = make(capacity=2)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.get('a')
        cache.set('c', 3)
        self.assertEqual(cache.peek('a'), 1)
        self.assertIsNone(cache.peek('b'))
        self.assertEqual(cache.stats()['evictions'], 1)

    def test_set_of_existing_key_refreshes_recency(self):
        cache, _ = make(capacity=2)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('a', 10)
        cache.set('c', 3)
        self.assertEqual(cache.peek('a'), 10)
        self.assertIsNone(cache.peek('b'))

    def test_updating_existing_key_at_capacity_evicts_nothing(self):
        cache, clock = make(capacity=2)
        cache.set('a', 1, ttl=1)
        cache.set('b', 2)
        clock.advance(5)  # 'a' is now expired but still stored
        cache.set('b', 20)
        s = cache.stats()
        self.assertEqual((s['evictions'], s['expirations']), (0, 0))
        self.assertEqual(cache.peek('b'), 20)

    def test_peek_and_contains_do_not_refresh_recency(self):
        cache, _ = make(capacity=2)
        cache.set('a', 1)
        cache.set('b', 2)
        self.assertEqual(cache.peek('a'), 1)
        self.assertIn('a', cache)
        self.assertEqual(len(cache), 2)
        cache.set('c', 3)
        self.assertIsNone(cache.peek('a'))
        self.assertEqual(cache.peek('b'), 2)

    def test_expired_entries_are_purged_before_evicting_live_lru(self):
        cache, clock = make(capacity=3)
        cache.set('lru', 1)          # oldest, never expires
        cache.set('temp', 2, ttl=5)
        cache.set('keep', 3)
        clock.advance(6)
        cache.set('new', 4)
        self.assertEqual(cache.peek('lru'), 1)
        self.assertEqual(cache.peek('new'), 4)
        s = cache.stats()
        self.assertEqual((s['evictions'], s['expirations']), (0, 1))

    def test_purge_removes_every_expired_entry(self):
        cache, clock = make(capacity=3)
        cache.set('x', 1, ttl=1)
        cache.set('y', 2, ttl=2)
        cache.set('z', 3)
        clock.advance(3)
        cache.set('n', 4)
        s = cache.stats()
        self.assertEqual((s['evictions'], s['expirations']), (0, 2))
        cache.set('m', 5)            # room for it without evicting
        self.assertEqual(cache.stats()['evictions'], 0)
        self.assertEqual(len(cache), 3)

    def test_no_purge_when_cache_not_full(self):
        cache, clock = make(capacity=3)
        cache.set('x', 1, ttl=1)
        clock.advance(2)
        cache.set('y', 2)
        self.assertEqual(cache.stats()['expirations'], 0)

    def test_lru_eviction_when_nothing_expired(self):
        cache, clock = make(capacity=2, default_ttl=100)
        cache.set('a', 1)
        cache.set('b', 2)
        clock.advance(1)
        cache.set('c', 3)
        self.assertNotIn('a', cache)
        s = cache.stats()
        self.assertEqual((s['evictions'], s['expirations']), (1, 0))


class SlidingTests(unittest.TestCase):
    def test_sliding_get_extends_by_entry_own_ttl(self):
        cache, clock = make(default_ttl=100, sliding=True)
        cache.set('k', 'v', ttl=10)
        clock.advance(8)
        self.assertEqual(cache.get('k'), 'v')   # expires_at -> 118
        clock.advance(9)                        # 117
        self.assertEqual(cache.get('k'), 'v')   # expires_at -> 127
        clock.advance(10)                       # 127
        self.assertIsNone(cache.get('k'))

    def test_sliding_peek_and_contains_do_not_extend(self):
        cache, clock = make(sliding=True)
        cache.set('k', 'v', ttl=10)
        clock.advance(8)
        self.assertEqual(cache.peek('k'), 'v')
        self.assertIn('k', cache)
        clock.advance(2)
        self.assertIsNone(cache.get('k'))

    def test_sliding_get_or_load_hit_extends(self):
        cache, clock = make(sliding=True)
        cache.set('k', 'v', ttl=10)
        clock.advance(9)
        self.assertEqual(cache.get_or_load('k', lambda key: 'loaded'), 'v')
        clock.advance(9)
        self.assertEqual(cache.peek('k'), 'v')

    def test_without_sliding_reads_do_not_extend(self):
        cache, clock = make(default_ttl=10)
        cache.set('k', 'v')
        clock.advance(9)
        self.assertEqual(cache.get('k'), 'v')
        clock.advance(1)
        self.assertIsNone(cache.get('k'))


class PeekDeleteLenTests(unittest.TestCase):
    def test_peek_does_not_remove_or_count_expired(self):
        cache, clock = make(default_ttl=5)
        cache.set('k', 'v')
        clock.advance(6)
        self.assertEqual(cache.peek('k', 'd'), 'd')
        self.assertEqual(cache.stats(), dict(hits=0, misses=0, evictions=0, expirations=0))
        self.assertIsNone(cache.get('k'))
        self.assertEqual(cache.stats()['expirations'], 1)

    def test_len_counts_only_live_entries(self):
        cache, clock = make(capacity=5)
        cache.set('a', 1, ttl=5)
        cache.set('b', 2, ttl=50)
        cache.set('c', 3)
        self.assertEqual(len(cache), 3)
        clock.advance(5)
        self.assertEqual(len(cache), 2)
        clock.advance(100)
        self.assertEqual(len(cache), 1)

    def test_delete(self):
        cache, clock = make()
        cache.set('live', 1)
        cache.set('old', 2, ttl=1)
        clock.advance(1)
        self.assertTrue(cache.delete('live'))
        self.assertFalse(cache.delete('live'))
        self.assertFalse(cache.delete('old'))
        self.assertFalse(cache.delete('never'))
        self.assertEqual(cache.stats()['expirations'], 1)
        self.assertEqual(len(cache), 0)


class LoaderAndStatsTests(unittest.TestCase):
    def test_get_or_load_miss_loads_once_then_hits(self):
        cache, _ = make()
        calls = []

        def loader(key):
            calls.append(key)
            return key.upper()

        self.assertEqual(cache.get_or_load('ab', loader), 'AB')
        self.assertEqual(cache.get_or_load('ab', loader), 'AB')
        self.assertEqual(calls, ['ab'])
        self.assertEqual(cache.get('ab'), 'AB')

    def test_get_or_load_caches_none(self):
        cache, _ = make()
        calls = []

        def loader(key):
            calls.append(key)
            return None

        self.assertIsNone(cache.get_or_load('k', loader))
        self.assertIsNone(cache.get_or_load('k', loader))
        self.assertEqual(len(calls), 1)
        self.assertIn('k', cache)

    def test_get_or_load_uses_ttl_argument(self):
        cache, clock = make(default_ttl=100)
        cache.get_or_load('k', lambda key: 1, ttl=3)
        clock.advance(3)
        self.assertNotIn('k', cache)

    def test_loader_exception_propagates_and_stores_nothing(self):
        cache, clock = make(capacity=1)
        cache.set('k', 'stale', ttl=1)
        clock.advance(2)

        class Boom(Exception):
            pass

        def loader(key):
            raise Boom(key)

        with self.assertRaises(Boom):
            cache.get_or_load('k', loader)
        self.assertNotIn('k', cache)
        self.assertEqual(cache.get_or_load('k', lambda key: 'fresh'), 'fresh')

    def test_get_or_load_miss_respects_capacity(self):
        cache, _ = make(capacity=2)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.get('a')
        cache.get_or_load('c', lambda key: 3)
        self.assertNotIn('b', cache)
        self.assertIn('a', cache)
        self.assertEqual(cache.stats()['evictions'], 1)

    def test_stats_count_hits_and_misses(self):
        cache, clock = make(default_ttl=10)
        cache.set('a', 1)
        cache.get('a')                           # hit
        cache.get('zz')                          # miss
        cache.get_or_load('a', lambda k: 0)      # hit
        cache.get_or_load('b', lambda k: 2)      # miss
        cache.peek('a')
        'a' in cache
        clock.advance(10)
        cache.get('a')                           # miss + expiration
        stats = cache.stats()
        self.assertEqual(stats, dict(hits=2, misses=3, evictions=0, expirations=1))
        stats['hits'] = 99
        self.assertEqual(cache.stats()['hits'], 2)


if __name__ == '__main__':
    unittest.main()
