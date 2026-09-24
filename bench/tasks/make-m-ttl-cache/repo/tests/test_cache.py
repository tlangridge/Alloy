import unittest

from memo import ExpiringCache, FakeClock


class BasicCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)

    def test_set_and_get(self):
        cache = ExpiringCache(capacity=4, clock=self.clock)
        cache.set('a', 1)
        self.assertEqual(cache.get('a'), 1)
        self.assertIsNone(cache.get('missing'))
        self.assertEqual(cache.get('missing', 'dflt'), 'dflt')

    def test_entry_expires_after_ttl(self):
        cache = ExpiringCache(capacity=4, default_ttl=10, clock=self.clock)
        cache.set('a', 1)
        self.clock.advance(5)
        self.assertEqual(cache.get('a'), 1)
        self.clock.advance(20)
        self.assertIsNone(cache.get('a'))

    def test_oldest_untouched_entry_is_evicted(self):
        cache = ExpiringCache(capacity=2, clock=self.clock)
        cache.set('a', 1)
        cache.set('b', 2)
        cache.set('c', 3)
        self.assertIsNone(cache.get('a'))
        self.assertEqual(cache.get('b'), 2)
        self.assertEqual(cache.get('c'), 3)

    def test_capacity_must_be_positive(self):
        with self.assertRaises(ValueError):
            ExpiringCache(capacity=0)


if __name__ == '__main__':
    unittest.main()
