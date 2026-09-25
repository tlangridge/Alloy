import unittest
from datetime import datetime, timedelta, timezone

from cronlite.runner import due_time
from cronlite.schedules import UTC, EveryMinutes


class EveryMinutesTests(unittest.TestCase):
    def test_next_boundary_strictly_after(self):
        s = EveryMinutes(15)
        self.assertEqual(s.next_after(datetime(2026, 5, 1, 10, 7, tzinfo=UTC)), datetime(2026, 5, 1, 10, 15, tzinfo=UTC))
        self.assertEqual(s.next_after(datetime(2026, 5, 1, 10, 15, tzinfo=UTC)), datetime(2026, 5, 1, 10, 30, tzinfo=UTC))
        self.assertEqual(s.next_after(datetime(2026, 5, 1, 10, 14, 59, 999999, tzinfo=UTC)),
                         datetime(2026, 5, 1, 10, 15, tzinfo=UTC))

    def test_other_offsets_are_converted(self):
        plus_5_30 = timezone(timedelta(hours=5, minutes=30))
        got = EveryMinutes(60).next_after(datetime(2026, 5, 1, 10, 0, tzinfo=plus_5_30))   # 04:30Z
        self.assertEqual(got, datetime(2026, 5, 1, 5, 0, tzinfo=UTC))

    def test_validation(self):
        for bad in (0, -5, True, 2.5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    EveryMinutes(bad)
        with self.assertRaises(ValueError):
            EveryMinutes(5).next_after(datetime(2026, 5, 1))


class DueTimeTests(unittest.TestCase):
    def test_latest_missed_fire_time(self):
        s = EveryMinutes(10)
        last = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
        self.assertEqual(due_time(s, last, datetime(2026, 5, 1, 9, 35, tzinfo=UTC)), datetime(2026, 5, 1, 9, 30, tzinfo=UTC))
        self.assertEqual(due_time(s, last, datetime(2026, 5, 1, 9, 10, tzinfo=UTC)), datetime(2026, 5, 1, 9, 10, tzinfo=UTC))
        self.assertIsNone(due_time(s, last, datetime(2026, 5, 1, 9, 9, tzinfo=UTC)))


if __name__ == '__main__':
    unittest.main()
