import unittest
from datetime import datetime, time, timedelta, timezone

from cronlite.runner import due_time, due_times
from cronlite.schedules import UTC, DailyAt, EveryMinutes, MonthlyAt, WeeklyAt
from cronlite.tz import EASTERN, PACIFIC


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class DailyAtTests(unittest.TestCase):
    def test_next_fire_is_strictly_after(self):
        s = DailyAt(time(9, 0), EASTERN)
        self.assertEqual(s.next_after(utc(2026, 1, 15, 13, 0)), utc(2026, 1, 15, 14, 0))
        self.assertEqual(s.next_after(utc(2026, 1, 15, 14, 0)), utc(2026, 1, 16, 14, 0))

    def test_result_is_utc_for_any_input_zone(self):
        s = DailyAt(time(9, 0), EASTERN)
        got = s.next_after(datetime(2026, 7, 1, 8, 59, tzinfo=EASTERN))
        self.assertIs(got.tzinfo, UTC)
        self.assertEqual(got, utc(2026, 7, 1, 13, 0))

    def test_local_time_kept_across_dst(self):
        s = DailyAt(time(9, 0), EASTERN)
        before = s.next_after(utc(2026, 3, 7, 15, 0))       # Sun 2026-03-08 09:00 EDT
        self.assertEqual(before, utc(2026, 3, 8, 13, 0))
        after = s.next_after(utc(2026, 10, 31, 14, 0))      # Sun 2026-11-01 09:00 EST
        self.assertEqual(after, utc(2026, 11, 1, 14, 0))

    def test_skipped_wall_time_uses_pre_transition_offset(self):
        s = DailyAt(time(2, 30), EASTERN)
        fire = s.next_after(utc(2026, 3, 7, 12, 0))
        self.assertEqual(fire, utc(2026, 3, 8, 7, 30))      # 03:30 EDT
        self.assertEqual(s.next_after(fire), utc(2026, 3, 9, 6, 30))

    def test_repeated_wall_time_fires_once(self):
        s = DailyAt(time(1, 30), EASTERN)
        first = s.next_after(utc(2026, 10, 31, 12, 0))
        self.assertEqual(first, utc(2026, 11, 1, 5, 30))    # 01:30 EDT
        self.assertEqual(s.next_after(first), utc(2026, 11, 2, 6, 30))

    def test_validation(self):
        with self.assertRaises(ValueError):
            DailyAt('09:00', EASTERN)
        with self.assertRaises(ValueError):
            DailyAt(time(9, tzinfo=UTC), EASTERN)
        with self.assertRaises(ValueError):
            DailyAt(time(9), 'America/New_York')
        with self.assertRaises(ValueError):
            DailyAt(time(9), EASTERN).next_after(datetime(2026, 1, 1))


class WeeklyAndMonthlyTests(unittest.TestCase):
    def test_weekly(self):
        s = WeeklyAt(time(18, 30), {0, 4}, PACIFIC)           # Mondays and Fridays
        # Wed 2026-06-03 -> Fri 2026-06-05 18:30 PDT
        self.assertEqual(s.next_after(utc(2026, 6, 3, 12, 0)), utc(2026, 6, 6, 1, 30))

    def test_weekly_validation(self):
        for bad in (set(), {7}, {-1}, {True}, 3, '135'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    WeeklyAt(time(9), bad, EASTERN)

    def test_monthly_clamps_to_short_months(self):
        s = MonthlyAt(31, time(12, 0), EASTERN)
        self.assertEqual(s.next_after(utc(2026, 2, 1, 0, 0)), utc(2026, 2, 28, 17, 0))
        self.assertEqual(s.next_after(utc(2028, 2, 1, 0, 0)), utc(2028, 2, 29, 17, 0))
        self.assertEqual(s.next_after(utc(2026, 3, 1, 0, 0)), utc(2026, 3, 31, 16, 0))

    def test_monthly_validation(self):
        for bad in (0, 32, True, 1.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    MonthlyAt(bad, time(9), EASTERN)


class DueTimesTests(unittest.TestCase):
    def setUp(self):
        self.s = DailyAt(time(6, 0), EASTERN)
        self.last = utc(2026, 1, 10, 12, 0)
        self.now = utc(2026, 1, 14, 12, 0)          # missed 11th..14th 06:00 EST

    def test_latest_coalesces(self):
        self.assertEqual(due_times(self.s, self.last, self.now), [utc(2026, 1, 14, 11, 0)])
        self.assertEqual(due_time(self.s, self.last, self.now), utc(2026, 1, 14, 11, 0))

    def test_all_in_order(self):
        self.assertEqual(due_times(self.s, self.last, self.now, 'all'),
                         [utc(2026, 1, d, 11, 0) for d in (11, 12, 13, 14)])

    def test_all_keeps_only_latest_limit(self):
        self.assertEqual(due_times(self.s, self.last, self.now, 'all', limit=2),
                         [utc(2026, 1, 13, 11, 0), utc(2026, 1, 14, 11, 0)])

    def test_nothing_due(self):
        self.assertEqual(due_times(self.s, self.last, utc(2026, 1, 11, 10, 59), 'all'), [])
        self.assertIsNone(due_time(self.s, self.last, self.last))

    def test_fire_time_equal_to_now_is_due(self):
        self.assertEqual(due_times(EveryMinutes(30), utc(2026, 1, 1, 0, 0), utc(2026, 1, 1, 1, 0), 'all'),
                         [utc(2026, 1, 1, 0, 30), utc(2026, 1, 1, 1, 0)])

    def test_validation(self):
        with self.assertRaises(ValueError):
            due_times(self.s, self.last, self.now, 'some')
        for bad in (0, True, 2.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    due_times(self.s, self.last, self.now, 'all', limit=bad)
        with self.assertRaises(ValueError):
            due_times(self.s, datetime(2026, 1, 1), self.now)


if __name__ == '__main__':
    unittest.main()
