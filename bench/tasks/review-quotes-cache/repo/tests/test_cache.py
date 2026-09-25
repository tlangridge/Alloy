import unittest

from quotes.cache import TTLCache

from fixtures import FakeClock


class TTLCacheTests(unittest.TestCase):
    def test_expiry(self):
        clock = FakeClock()
        cache = TTLCache(10, clock)
        cache.put('k', 1)
        clock.now += 9.9
        self.assertEqual(cache.get('k'), 1)
        clock.now += 0.1
        self.assertIsNone(cache.get('k'))
        self.assertEqual(len(cache), 0)

    def test_drop_where(self):
        cache = TTLCache(10, FakeClock())
        for k in ('a1', 'a2', 'b1'):
            cache.put(k, k)
        self.assertEqual(cache.drop_where(lambda k: k.startswith('a')), 2)
        self.assertEqual(len(cache), 1)

    def test_none_not_cacheable(self):
        with self.assertRaises(ValueError):
            TTLCache(10, FakeClock()).put('k', None)


if __name__ == '__main__':
    unittest.main()
