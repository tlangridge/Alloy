import threading
import unittest

from throttle.limiter import SlidingLogLimiter


class Clock:
    def __init__(self, now=0):
        self.now = now

    def __call__(self):
        return self.now


class SlidingLogTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(10_000)
        self.lim = SlidingLogLimiter(3, 1000, self.clock)

    def test_allows_up_to_limit(self):
        self.assertEqual([self.lim.allow('k') for _ in range(4)], [True, True, True, False])

    def test_window_slides(self):
        for t in (10_000, 10_400, 10_800):
            self.clock.now = t
            self.assertTrue(self.lim.allow('k'))
        self.clock.now = 10_999
        self.assertFalse(self.lim.allow('k'))
        self.clock.now = 11_000            # the 10_000 request is exactly 1000 ms old
        self.assertTrue(self.lim.allow('k'))
        self.assertFalse(self.lim.allow('k'))

    def test_rejections_are_not_recorded(self):
        for _ in range(3):
            self.lim.allow('k')
        for t in range(10_000, 11_000, 50):
            self.clock.now = t
            self.lim.allow('k')
        self.clock.now = 11_000
        self.assertEqual([self.lim.allow('k') for _ in range(4)], [True, True, True, False])

    def test_retry_after(self):
        self.assertEqual(self.lim.retry_after('k'), 0)
        for t in (10_000, 10_300, 10_600):
            self.clock.now = t
            self.lim.allow('k')
        self.clock.now = 10_700
        self.assertEqual(self.lim.retry_after('k'), 300)
        self.clock.now += 300
        self.assertEqual(self.lim.retry_after('k'), 0)
        self.assertTrue(self.lim.allow('k'))
        self.assertEqual(self.lim.retry_after('k'), 300)

    def test_retry_after_does_not_record(self):
        for _ in range(5):
            self.lim.retry_after('k')
        self.assertEqual([self.lim.allow('k') for _ in range(4)], [True, True, True, False])

    def test_keys_are_independent_and_idle_keys_are_dropped(self):
        self.assertTrue(self.lim.allow('a'))
        self.assertTrue(self.lim.allow('b'))
        self.clock.now += 1000
        self.lim.allow('b')
        self.assertIn('a', self.lim._logs)      # not touched yet: pruning is lazy
        self.lim.retry_after('a')
        self.assertNotIn('a', self.lim._logs)

    def test_same_millisecond_requests(self):
        lim = SlidingLogLimiter(2, 5, self.clock)
        self.assertEqual([lim.allow('k') for _ in range(3)], [True, True, False])
        self.clock.now += 5
        self.assertEqual([lim.allow('k') for _ in range(3)], [True, True, False])

    def test_validation(self):
        for limit, window in ((0, 10), (1, 0), (False, 10), (1, 2.5)):
            with self.subTest(limit=limit, window=window):
                with self.assertRaises(ValueError):
                    SlidingLogLimiter(limit, window, Clock())

    def test_concurrent_callers_never_exceed_limit(self):
        lim = SlidingLogLimiter(50, 1000, Clock(0))
        results = []
        lock = threading.Lock()

        def worker():
            got = [lim.allow('shared') for _ in range(40)]
            with lock:
                results.extend(got)
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 50)


if __name__ == '__main__':
    unittest.main()
