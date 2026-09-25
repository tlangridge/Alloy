import unittest
from datetime import datetime

from cronlite.tz import EASTERN, UTC, us_dst_range


class TimeZoneTests(unittest.TestCase):
    def test_dst_range(self):
        self.assertEqual(us_dst_range(2027), (datetime(2027, 3, 14, 2), datetime(2027, 11, 7, 2)))

    def test_skipped_hour_fold0_uses_standard_offset(self):
        wall = datetime(2027, 3, 14, 2, 30, tzinfo=EASTERN)
        self.assertEqual(wall.astimezone(UTC), datetime(2027, 3, 14, 7, 30, tzinfo=UTC))

    def test_repeated_hour(self):
        self.assertEqual(datetime(2027, 11, 7, 1, 30, tzinfo=EASTERN).astimezone(UTC),
                         datetime(2027, 11, 7, 5, 30, tzinfo=UTC))
        self.assertEqual(datetime(2027, 11, 7, 1, 30, fold=1, tzinfo=EASTERN).astimezone(UTC),
                         datetime(2027, 11, 7, 6, 30, tzinfo=UTC))


if __name__ == '__main__':
    unittest.main()
