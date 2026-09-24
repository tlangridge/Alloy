import unittest
from datetime import datetime

from retention import Backup, plan


class SmokeTests(unittest.TestCase):
    def test_single_backup_is_kept_as_latest(self):
        now = datetime(2025, 3, 10, 12, 0)
        p = plan([Backup('b1', datetime(2025, 3, 10, 2, 0))], now)
        self.assertEqual(p.keep, ['b1'])
        self.assertEqual(p.delete, [])
        self.assertIn('latest', p.reasons['b1'])

    def test_daily_keeps_newest_of_each_day(self):
        now = datetime(2025, 3, 10, 12, 0)
        backups = [Backup('mon-a', datetime(2025, 3, 10, 1, 0)),
                   Backup('mon-b', datetime(2025, 3, 10, 9, 0)),
                   Backup('sun-a', datetime(2025, 3, 9, 1, 0))]
        p = plan(backups, now, daily=2, weekly=0, monthly=0)
        self.assertEqual(p.keep, ['mon-b', 'sun-a'])
        self.assertEqual(p.delete, ['mon-a'])


if __name__ == '__main__':
    unittest.main()
