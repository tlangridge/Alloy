import unittest
from datetime import datetime, time, timedelta, timezone

from notify.quiet import QuietHours
from notify.schedule import next_delivery
from notify.tz import EASTERN, PACIFIC, UTC

NIGHT = QuietHours(time(22), time(7))


class NextDeliveryTests(unittest.TestCase):
    def test_outside_quiet_hours_is_immediate(self):
        now = datetime(2026, 1, 15, 15, 0, tzinfo=UTC)          # 10:00 EST
        self.assertEqual(next_delivery(now, EASTERN, NIGHT), now)

    def test_result_is_utc(self):
        now = datetime(2026, 1, 15, 10, 0, tzinfo=EASTERN)
        got = next_delivery(now, EASTERN, NIGHT)
        self.assertIs(got.tzinfo, timezone.utc)
        self.assertEqual(got, datetime(2026, 1, 15, 15, 0, tzinfo=UTC))

    def test_before_midnight_waits_until_next_morning(self):
        now = datetime(2026, 1, 15, 4, 0, tzinfo=UTC)            # 23:00 EST on the 14th
        self.assertEqual(next_delivery(now, EASTERN, NIGHT), datetime(2026, 1, 15, 12, 0, tzinfo=UTC))

    def test_after_midnight_waits_until_same_morning(self):
        now = datetime(2026, 7, 15, 9, 30, tzinfo=UTC)           # 05:30 EDT
        self.assertEqual(next_delivery(now, EASTERN, NIGHT), datetime(2026, 7, 15, 11, 0, tzinfo=UTC))

    def test_start_of_window_is_quiet_and_end_is_not(self):
        at_start = datetime(2026, 1, 15, 22, 0, tzinfo=EASTERN)
        self.assertEqual(next_delivery(at_start, EASTERN, NIGHT), datetime(2026, 1, 16, 12, 0, tzinfo=UTC))
        at_end = datetime(2026, 1, 16, 7, 0, tzinfo=EASTERN)
        self.assertEqual(next_delivery(at_end, EASTERN, NIGHT), at_end.astimezone(UTC))

    def test_daytime_window(self):
        lunch = QuietHours(time(12), time(13, 30))
        now = datetime(2026, 7, 15, 19, 10, tzinfo=UTC)          # 12:10 PDT
        self.assertEqual(next_delivery(now, PACIFIC, lunch), datetime(2026, 7, 15, 20, 30, tzinfo=UTC))

    def test_other_input_offset_is_converted(self):
        plus2 = timezone(timedelta(hours=2))
        now = datetime(2026, 1, 15, 6, 0, tzinfo=plus2)          # 04:00Z = 23:00 EST
        self.assertEqual(next_delivery(now, EASTERN, NIGHT), datetime(2026, 1, 15, 12, 0, tzinfo=UTC))

    def test_no_quiet_hours(self):
        now = datetime(2026, 1, 15, 4, 0, tzinfo=UTC)
        self.assertEqual(next_delivery(now, EASTERN, QuietHours(time(9), time(9))), now)

    def test_naive_now_rejected(self):
        with self.assertRaises(ValueError):
            next_delivery(datetime(2026, 1, 15, 4, 0), EASTERN, NIGHT)


if __name__ == '__main__':
    unittest.main()
