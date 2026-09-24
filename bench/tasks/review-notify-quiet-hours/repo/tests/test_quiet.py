import unittest
from datetime import datetime, time

from notify.quiet import QuietHours, is_quiet
from notify.tz import EASTERN, UTC


class QuietHoursTests(unittest.TestCase):
    def test_overnight_window(self):
        q = QuietHours(time(22), time(7))
        self.assertTrue(q.contains(time(23, 30)))
        self.assertTrue(q.contains(time(6, 59)))
        self.assertFalse(q.contains(time(7)))
        self.assertTrue(q.contains(time(22)))
        self.assertFalse(q.contains(time(12)))

    def test_daytime_window(self):
        q = QuietHours(time(12), time(13, 30))
        self.assertTrue(q.contains(time(12, 45)))
        self.assertFalse(q.contains(time(13, 30)))

    def test_equal_bounds_means_never_quiet(self):
        self.assertFalse(QuietHours(time(9), time(9)).contains(time(9)))

    def test_is_quiet_uses_local_time(self):
        q = QuietHours(time(22), time(7))
        self.assertTrue(is_quiet(datetime(2026, 1, 15, 4, tzinfo=UTC), EASTERN, q))    # 23:00 EST
        self.assertFalse(is_quiet(datetime(2026, 1, 15, 13, tzinfo=UTC), EASTERN, q))  # 08:00 EST

    def test_naive_now_rejected(self):
        with self.assertRaises(ValueError):
            is_quiet(datetime(2026, 1, 15, 4), EASTERN, QuietHours(time(22), time(7)))

    def test_bounds_must_be_naive_times(self):
        with self.assertRaises(TypeError):
            QuietHours('22:00', time(7))
        with self.assertRaises(ValueError):
            QuietHours(time(22, tzinfo=UTC), time(7))


if __name__ == '__main__':
    unittest.main()
