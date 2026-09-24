import unittest

from throttle import policy
from throttle.bucket import TokenBucket
from throttle.clock import FakeClock
from throttle.limiter import Decision, KeyedLimiter


def limiter(capacity=3, rate=1.0, idle_ttl=300.0, start=1000.0):
    clock = FakeClock(start)
    return KeyedLimiter(capacity, rate, clock, idle_ttl=idle_ttl), clock


class EnforcementTests(unittest.TestCase):
    def test_reported_sequence(self):
        clock = FakeClock()
        lim = KeyedLimiter(capacity=5, rate=5 / 60, clock=clock)
        self.assertEqual([lim.allow('10.0.0.7').allowed for _ in range(8)], [True] * 5 + [False] * 3)

    def test_rejected_until_refilled(self):
        lim, clock = limiter(capacity=3, rate=1.0)
        self.assertEqual([lim.allow('k').allowed for _ in range(3)], [True, True, True])
        d = lim.allow('k')
        self.assertEqual(d, Decision(False, 1, 0))
        clock.advance(0.5)
        d = lim.allow('k')
        self.assertEqual((d.allowed, d.retry_after, d.remaining), (False, 1, 0))
        clock.advance(0.5)
        self.assertEqual(lim.allow('k'), Decision(True, 0, 0))
        self.assertFalse(lim.allow('k').allowed)

    def test_bucket_is_reused_while_empty_or_fractional(self):
        lim, clock = limiter(capacity=2, rate=0.25)
        lim.allow('k', 2)
        results = []
        for _ in range(12):
            clock.advance(0.5)          # +0.125 tokens each time
            results.append(lim.allow('k').allowed)
        # tokens reach 1.0 after 4 s (8 steps), then drop back to 0
        self.assertEqual(results, [False] * 7 + [True] + [False] * 4)

    def test_long_burst_never_exceeds_capacity(self):
        lim, _ = limiter(capacity=4, rate=1.0)
        allowed = sum(lim.allow('k').allowed for _ in range(50))
        self.assertEqual(allowed, 4)

    def test_mixed_costs(self):
        lim, clock = limiter(capacity=5, rate=0.5)
        self.assertTrue(lim.allow('k', 4).allowed)
        self.assertFalse(lim.allow('k', 2).allowed)
        self.assertTrue(lim.allow('k', 1).allowed)
        d = lim.allow('k', 1)
        self.assertEqual((d.allowed, d.retry_after, d.remaining), (False, 2, 0))
        d = lim.allow('k', 5)
        self.assertEqual(d.retry_after, 10)

    def test_keys_are_isolated(self):
        lim, _ = limiter(capacity=2)
        self.assertEqual([lim.allow('a').allowed for _ in range(3)], [True, True, False])
        self.assertEqual([lim.allow('b').allowed for _ in range(3)], [True, True, False])
        self.assertEqual(len(lim), 2)


class RetryAfterTests(unittest.TestCase):
    def test_retry_after_is_ceil_and_at_least_one(self):
        lim, clock = limiter(capacity=4, rate=0.5)
        lim.allow('k', 4)
        clock.advance(1.5)                       # 0.75 tokens
        d = lim.allow('k', 3)
        self.assertEqual((d.allowed, d.retry_after), (False, 5))   # 2.25 / 0.5 = 4.5 -> 5
        d = lim.allow('k')
        self.assertEqual(d.retry_after, 1)                          # 0.25 / 0.5 = 0.5 -> 1

    def test_waiting_retry_after_succeeds(self):
        for capacity, rate, cost in ((3, 1.0, 1), (5, 0.25, 2), (4, 2.0, 4), (6, 0.5, 3)):
            lim, clock = limiter(capacity=capacity, rate=rate)
            for _ in range(capacity // cost):
                self.assertTrue(lim.allow('k', cost).allowed)
            d = lim.allow('k', cost)
            self.assertFalse(d.allowed)
            clock.advance(d.retry_after)
            self.assertTrue(lim.allow('k', cost).allowed, (capacity, rate, cost))

    def test_invalid_costs(self):
        lim, _ = limiter(capacity=3)
        for cost in (0, -1, 4):
            with self.assertRaises(ValueError):
                lim.allow('k', cost)


class BucketTests(unittest.TestCase):
    def test_len_is_floor_of_available_tokens(self):
        clock = FakeClock()
        b = TokenBucket(4, 0.5, clock)
        self.assertEqual(len(b), 4)
        b.try_take(4)
        self.assertEqual(len(b), 0)
        clock.advance(1.0)
        self.assertEqual(len(b), 0)
        clock.advance(4.5)
        self.assertEqual(len(b), 2)
        clock.advance(100)
        self.assertEqual(len(b), 4)

    def test_is_full_accounts_for_refill(self):
        clock = FakeClock()
        b = TokenBucket(3, 1.0, clock)
        self.assertTrue(b.is_full())
        b.try_take(2)
        self.assertFalse(b.is_full())
        clock.advance(1.0)
        self.assertFalse(b.is_full())
        clock.advance(1.0)
        self.assertTrue(b.is_full())

    def test_clock_going_backwards(self):
        clock = FakeClock(100.0)
        b = TokenBucket(4, 1.0, clock)
        b.try_take(4)
        clock.set(50.0)
        self.assertEqual(b.tokens, 0.0)
        self.assertFalse(b.try_take())
        clock.set(101.0)
        self.assertEqual(b.tokens, 1.0)

    def test_failed_take_takes_nothing(self):
        clock = FakeClock()
        b = TokenBucket(5, 1.0, clock)
        b.try_take(3)
        self.assertFalse(b.try_take(3))
        self.assertEqual(b.tokens, 2.0)
        self.assertEqual(b.wait_time(3), 1.0)
        self.assertEqual(b.wait_time(2), 0.0)


class SweepTests(unittest.TestCase):
    def test_reported_sweep(self):
        clock = FakeClock()
        lim = KeyedLimiter(capacity=5, rate=5 / 60, clock=clock)
        for _ in range(8):
            lim.allow('10.0.0.7')
        for _ in range(4):
            lim.allow('10.0.0.8', cost=2)
        clock.advance(3600)
        self.assertEqual((lim.sweep(), len(lim)), (2, 0))

    def test_idle_and_refilled_bucket_is_removed(self):
        lim, clock = limiter(capacity=3, rate=1.0, idle_ttl=60)
        lim.allow('k', 3)
        clock.advance(60)
        self.assertEqual(lim.sweep(), 1)
        self.assertNotIn('k', lim)
        self.assertEqual(lim.allow('k', 3), Decision(True, 0, 0))

    def test_not_idle_long_enough(self):
        lim, clock = limiter(capacity=3, rate=1.0, idle_ttl=60)
        lim.allow('k')
        clock.advance(59.5)
        self.assertEqual(lim.sweep(), 0)
        self.assertIn('k', lim)

    def test_idle_but_not_yet_full_is_kept(self):
        lim, clock = limiter(capacity=10, rate=0.01, idle_ttl=300)
        lim.allow('k', 10)
        clock.advance(400)           # only 4 tokens back
        self.assertEqual(lim.sweep(), 0)
        self.assertIn('k', lim)
        self.assertEqual(lim.allow('k', 5).allowed, False)

    def test_rejected_request_counts_as_activity(self):
        lim, clock = limiter(capacity=2, rate=1.0, idle_ttl=60)
        self.assertTrue(lim.allow('k', 2).allowed)     # t=1000
        clock.advance(1)
        self.assertFalse(lim.allow('k', 2).allowed)    # t=1001, rejected but still activity
        clock.advance(59.5)                            # bucket full again, idle 59.5 s
        self.assertEqual(lim.sweep(), 0)
        clock.advance(0.5)                             # idle exactly 60 s
        self.assertEqual(lim.sweep(), 1)

    def test_unused_full_bucket_removed_after_ttl(self):
        lim, clock = limiter(capacity=2, rate=1.0, idle_ttl=10)
        lim.allow('a')
        lim.allow('b', 2)
        clock.advance(5)
        lim.allow('c')
        clock.advance(5)
        self.assertEqual(lim.sweep(), 2)
        self.assertEqual((('a' in lim), ('b' in lim), ('c' in lim)), (False, False, True))


class PolicyTests(unittest.TestCase):
    def test_parse_units(self):
        self.assertEqual(policy.parse('10/s'), (10, 10.0))
        self.assertEqual(policy.parse('120/minute'), (120, 2.0))
        self.assertEqual(policy.parse('3600/h'), (3600, 1.0))
        self.assertEqual(policy.parse(' 86400 / Day '), (86400, 1.0))
        for bad in ('0/s', '10/week', 'ten/s', '10', ''):
            with self.assertRaises(ValueError):
                policy.parse(bad)

    def test_from_policy_enforces(self):
        clock = FakeClock()
        lim = KeyedLimiter.from_policy('2/s', clock)
        self.assertEqual([lim.allow('k').allowed for _ in range(3)], [True, True, False])
        clock.advance(0.5)
        self.assertTrue(lim.allow('k').allowed)


if __name__ == '__main__':
    unittest.main()
