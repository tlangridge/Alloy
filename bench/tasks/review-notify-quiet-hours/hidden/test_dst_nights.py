import unittest
from datetime import datetime, time

from notify.quiet import QuietHours
from notify.schedule import next_delivery
from notify.tz import EASTERN, PACIFIC, UTC

NIGHT = QuietHours(time(22), time(7))


class DaylightSavingNightTests(unittest.TestCase):
    """The release time is 07:00 on the user's clock even when DST changes overnight."""

    def test_fall_back_night_eastern(self):
        # 2026-10-31 23:00 EDT; DST ends 2026-11-01 02:00; 07:00 EST = 12:00Z.
        now = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
        got = next_delivery(now, EASTERN, NIGHT)
        self.assertEqual(got, datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
        self.assertEqual(got.astimezone(EASTERN).time(), time(7))

    def test_spring_forward_night_eastern(self):
        # 2026-03-07 23:00 EST; DST starts 2026-03-08 02:00; 07:00 EDT = 11:00Z.
        now = datetime(2026, 3, 8, 4, 0, tzinfo=UTC)
        got = next_delivery(now, EASTERN, NIGHT)
        self.assertEqual(got, datetime(2026, 3, 8, 11, 0, tzinfo=UTC))
        self.assertEqual(got.astimezone(EASTERN).time(), time(7))

    def test_after_the_switch_same_night(self):
        # 2026-11-01 01:30 EST (second pass, fold=1) -> 07:00 EST = 12:00Z.
        now = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
        self.assertEqual(next_delivery(now, EASTERN, NIGHT), datetime(2026, 11, 1, 12, 0, tzinfo=UTC))

    def test_fall_back_night_pacific(self):
        # 2027-11-06 22:30 PDT; DST ends 2027-11-07 02:00; 07:00 PST = 15:00Z.
        now = datetime(2027, 11, 7, 5, 30, tzinfo=UTC)
        self.assertEqual(next_delivery(now, PACIFIC, NIGHT), datetime(2027, 11, 7, 15, 0, tzinfo=UTC))

    def test_ordinary_night_unchanged(self):
        now = datetime(2026, 2, 10, 4, 0, tzinfo=UTC)          # 23:00 EST
        self.assertEqual(next_delivery(now, EASTERN, NIGHT), datetime(2026, 2, 10, 12, 0, tzinfo=UTC))


if __name__ == '__main__':
    unittest.main()
