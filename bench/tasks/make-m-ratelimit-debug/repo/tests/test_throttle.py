import unittest

from throttle.bucket import TokenBucket
from throttle.clock import FakeClock
from throttle.limiter import KeyedLimiter
from throttle import policy


class BucketTests(unittest.TestCase):
    def test_take_and_refill(self):
        clock = FakeClock()
        b = TokenBucket(3, 1.0, clock)
        self.assertTrue(b.try_take())
        self.assertTrue(b.try_take(2))
        self.assertFalse(b.try_take())
        self.assertEqual(b.wait_time(), 1.0)
        clock.advance(1.0)
        self.assertTrue(b.try_take())

    def test_len_is_whole_tokens(self):
        clock = FakeClock()
        b = TokenBucket(4, 0.5, clock)
        b.try_take(4)
        clock.advance(3.0)
        self.assertEqual(len(b), 1)


class LimiterTests(unittest.TestCase):
    def test_bulk_requests_are_limited(self):
        clock = FakeClock()
        lim = KeyedLimiter(10, 1.0, clock)
        self.assertTrue(lim.allow('k', cost=6).allowed)
        d = lim.allow('k', cost=6)
        self.assertFalse(d.allowed)
        self.assertEqual(d.retry_after, 2)
        self.assertEqual(d.remaining, 4)

    def test_keys_are_independent(self):
        clock = FakeClock()
        lim = KeyedLimiter(2, 1.0, clock)
        self.assertTrue(lim.allow('a', 2).allowed)
        self.assertTrue(lim.allow('b', 2).allowed)


class PolicyTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(policy.parse('120/min'), (120, 2.0))
        with self.assertRaises(ValueError):
            policy.parse('5/fortnight')


if __name__ == '__main__':
    unittest.main()
