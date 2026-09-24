import unittest
from datetime import datetime

from notify.tz import EASTERN, PACIFIC, UTC, us_dst_range


class TimeZoneTests(unittest.TestCase):
    def test_dst_range_2026(self):
        self.assertEqual(us_dst_range(2026), (datetime(2026, 3, 8, 2), datetime(2026, 11, 1, 2)))

    def test_offsets(self):
        self.assertEqual(datetime(2026, 1, 15, 12, tzinfo=EASTERN).utcoffset().total_seconds(), -5 * 3600)
        self.assertEqual(datetime(2026, 7, 15, 12, tzinfo=EASTERN).utcoffset().total_seconds(), -4 * 3600)
        self.assertEqual(datetime(2026, 7, 15, 12, tzinfo=PACIFIC).tzname(), 'PDT')

    def test_repeated_hour_uses_fold(self):
        first = datetime(2026, 11, 1, 5, 30, tzinfo=UTC).astimezone(EASTERN)
        second = datetime(2026, 11, 1, 6, 30, tzinfo=UTC).astimezone(EASTERN)
        self.assertEqual((first.hour, first.minute, first.fold), (1, 30, 0))
        self.assertEqual((second.hour, second.minute, second.fold), (1, 30, 1))


if __name__ == '__main__':
    unittest.main()
