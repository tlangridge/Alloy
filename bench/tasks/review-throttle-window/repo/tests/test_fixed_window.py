import unittest

from throttle.limiter import FixedWindowLimiter


class Clock:
    def __init__(self, now=0):
        self.now = now

    def __call__(self):
        return self.now


class FixedWindowTests(unittest.TestCase):
    def test_limit_per_aligned_window(self):
        clock = Clock(1000)
        lim = FixedWindowLimiter(2, 1000, clock)
        self.assertEqual([lim.allow('k') for _ in range(3)], [True, True, False])
        clock.now = 1999
        self.assertFalse(lim.allow('k'))
        clock.now = 2000
        self.assertTrue(lim.allow('k'))

    def test_keys_are_independent(self):
        lim = FixedWindowLimiter(1, 1000, Clock())
        self.assertTrue(lim.allow('a'))
        self.assertTrue(lim.allow('b'))
        self.assertFalse(lim.allow('a'))

    def test_validation(self):
        for limit, window in ((0, 10), (1, 0), (True, 10), (1, 1.5), ('2', 10)):
            with self.subTest(limit=limit, window=window):
                with self.assertRaises(ValueError):
                    FixedWindowLimiter(limit, window, Clock())


if __name__ == '__main__':
    unittest.main()
