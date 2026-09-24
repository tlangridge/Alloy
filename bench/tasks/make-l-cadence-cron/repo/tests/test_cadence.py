import unittest
from datetime import datetime

from cadence import CronSyntaxError, parse
from cadence.jobs import JobTable


class BasicTests(unittest.TestCase):
    def test_every_minute(self):
        self.assertEqual(parse('* * * * *').next_after(datetime(2026, 1, 1, 10, 0)), datetime(2026, 1, 1, 10, 1))

    def test_weekday_mornings(self):
        s = parse('30 9 * * MON-FRI')
        self.assertEqual(s.next_after(datetime(2026, 3, 6, 9, 30)), datetime(2026, 3, 9, 9, 30))
        self.assertTrue(s.matches(datetime(2026, 3, 9, 9, 30)))
        self.assertFalse(s.matches(datetime(2026, 3, 8, 9, 30)))

    def test_monthly_macro(self):
        self.assertEqual(parse('@monthly').next_after(datetime(2026, 1, 15)), datetime(2026, 2, 1))

    def test_syntax_error(self):
        with self.assertRaises(CronSyntaxError) as ctx:
            parse('61 * * * *')
        self.assertEqual((ctx.exception.field, ctx.exception.item), ('minute', '61'))

    def test_job_table(self):
        table = JobTable()
        table.add('report', '0 6 * * *', datetime(2026, 5, 1, 6, 0))
        table.add('cleanup', '*/15 * * * *', datetime(2026, 5, 1, 5, 50))
        self.assertEqual(table.due(datetime(2026, 5, 1, 6, 0)), ['cleanup'])
        self.assertEqual(table.due(datetime(2026, 5, 2, 6, 0)), ['cleanup', 'report'])


if __name__ == '__main__':
    unittest.main()
