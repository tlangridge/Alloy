import unittest
from datetime import datetime, timedelta

from retention import Backup, plan

NOW = datetime(2025, 3, 12, 12, 0)   # a Wednesday


def B(id, *dt, pinned=False):
    return Backup(id, datetime(*dt), pinned)


class ValidationTests(unittest.TestCase):
    def test_counts_must_be_non_negative_ints(self):
        for kw in (dict(daily=-1), dict(weekly=-2), dict(monthly=-1), dict(daily=1.5),
                   dict(max_age_days=0), dict(max_age_days=-3), dict(max_age_days=2.5)):
            with self.assertRaises(ValueError, msg=kw):
                plan([], NOW, **kw)
        plan([], NOW, daily=0, weekly=0, monthly=0, max_age_days=1)

    def test_duplicate_ids(self):
        with self.assertRaises(ValueError):
            plan([B('a', 2025, 3, 1), B('a', 2025, 3, 2)], NOW)


class FutureAndLatestTests(unittest.TestCase):
    def test_future_backups_are_skipped(self):
        backups = [B('f2', 2025, 3, 13), B('old', 2025, 3, 1), B('f1', 2025, 3, 12, 12, 1)]
        p = plan(backups, NOW, daily=0, weekly=0, monthly=0)
        self.assertEqual(p.skipped, ['f2', 'f1'])
        self.assertEqual(p.keep, ['old'])
        self.assertEqual(p.reasons, {'old': ['latest']})
        self.assertEqual(p.delete, [])

    def test_backup_at_now_is_not_future(self):
        p = plan([B('now', 2025, 3, 12, 12, 0), B('old', 2025, 3, 1)], NOW, daily=0, weekly=0, monthly=0)
        self.assertEqual(p.skipped, [])
        self.assertEqual(p.keep, ['now'])
        self.assertEqual(p.delete, ['old'])

    def test_latest_kept_even_with_all_counts_zero_and_can_be_pinned(self):
        p = plan([B('a', 2025, 3, 10), B('b', 2025, 3, 11, pinned=True)], NOW, daily=0, weekly=0, monthly=0)
        self.assertEqual(p.keep, ['b'])
        self.assertEqual(p.reasons, {'b': ['latest', 'pinned']})
        self.assertEqual(p.delete, ['a'])


class PinnedTests(unittest.TestCase):
    def test_pinned_kept_and_not_chosen_for_daily(self):
        backups = [B('d1-early', 2025, 3, 11, 1), B('d1-pin', 2025, 3, 11, 20, pinned=True),
                   B('d2', 2025, 3, 12, 1), B('d0', 2025, 3, 10, 1)]
        p = plan(backups, NOW, daily=2, weekly=0, monthly=0)
        self.assertEqual(p.reasons['d1-pin'], ['pinned'])
        self.assertEqual(p.reasons['d1-early'], ['daily'])
        self.assertEqual(p.keep, ['d2', 'd1-pin', 'd1-early'])
        self.assertEqual(p.delete, ['d0'])

    def test_pinned_only_day_does_not_use_a_slot(self):
        backups = [B('d12', 2025, 3, 12, 1), B('pin11', 2025, 3, 11, 1, pinned=True), B('d10', 2025, 3, 10, 1)]
        p = plan(backups, NOW, daily=2, weekly=0, monthly=0)
        self.assertEqual(p.reasons['d10'], ['daily'])
        self.assertEqual(p.delete, [])


class BucketTests(unittest.TestCase):
    def test_daily_counts_days_with_backups_not_calendar_days(self):
        backups = [B('mar12', 2025, 3, 12, 1), B('mar5', 2025, 3, 5, 1), B('feb20', 2025, 2, 20, 1),
                   B('feb19', 2025, 2, 19, 1)]
        p = plan(backups, NOW, daily=3, weekly=0, monthly=0)
        self.assertEqual(p.keep, ['mar12', 'mar5', 'feb20'])
        self.assertEqual(p.reasons['mar5'], ['daily'])
        self.assertEqual(p.delete, ['feb19'])

    def test_iso_weeks_across_new_year(self):
        now = datetime(2025, 1, 8, 12, 0)
        backups = [B('dec20', 2024, 12, 20), B('dec30', 2024, 12, 30), B('jan02', 2025, 1, 2),
                   B('jan06', 2025, 1, 6)]
        p = plan(backups, now, daily=0, weekly=2, monthly=0)
        self.assertEqual(p.keep, ['jan06', 'jan02'])
        self.assertEqual(p.delete, ['dec20', 'dec30'])
        p = plan(backups, now, daily=0, weekly=4, monthly=0)
        self.assertEqual(p.keep, ['jan06', 'jan02', 'dec20'])
        self.assertEqual(p.delete, ['dec30'])

    def test_iso_week_of_late_december_belongs_to_next_year(self):
        backups = [B('dec27', 2024, 12, 27), B('dec30', 2024, 12, 30)]
        p = plan(backups, datetime(2024, 12, 31), daily=0, weekly=1, monthly=0)
        self.assertEqual(p.keep, ['dec30'])
        self.assertEqual(p.reasons['dec30'], ['latest', 'weekly'])
        self.assertEqual(p.delete, ['dec27'])

    def test_monthly_keeps_newest_of_month(self):
        backups = [B('mar-a', 2025, 3, 1), B('mar-b', 2025, 3, 3), B('feb-a', 2025, 2, 2),
                   B('feb-b', 2025, 2, 27), B('jan', 2025, 1, 15)]
        p = plan(backups, NOW, daily=0, weekly=0, monthly=2)
        self.assertEqual(p.keep, ['mar-b', 'feb-b'])
        self.assertEqual(p.reasons['feb-b'], ['monthly'])
        self.assertEqual(p.delete, ['jan', 'feb-a', 'mar-a'])

    def test_weekly_keeps_newest_of_week(self):
        backups = [B('mon', 2025, 3, 3), B('fri', 2025, 3, 7), B('prev', 2025, 2, 25)]
        p = plan(backups, datetime(2025, 3, 8), daily=0, weekly=1, monthly=0)
        self.assertEqual(p.keep, ['fri'])
        self.assertEqual(p.reasons['fri'], ['latest', 'weekly'])

    def test_zero_disables_rule(self):
        backups = [B('a', 2025, 3, 12), B('b', 2025, 3, 11), B('c', 2025, 2, 1)]
        p = plan(backups, NOW, daily=0, weekly=0, monthly=0)
        self.assertEqual(p.keep, ['a'])
        self.assertEqual(p.delete, ['c', 'b'])

    def test_reasons_fixed_order_and_combined(self):
        backups = [B('a', 2025, 3, 12, 1), B('p', 2025, 3, 11, pinned=True), B('b', 2025, 2, 10)]
        p = plan(backups, NOW, daily=2, weekly=2, monthly=2)
        self.assertEqual(p.reasons, {'a': ['latest', 'daily', 'weekly', 'monthly'],
                                     'p': ['pinned'],
                                     'b': ['daily', 'weekly', 'monthly']})


class TieTests(unittest.TestCase):
    def test_ties_go_to_greatest_id_in_any_input_order(self):
        for order in (['b-1', 'b-2'], ['b-2', 'b-1']):
            backups = [B(i, 2025, 3, 11, 3) for i in order] + [B('x', 2025, 3, 12, 1)]
            p = plan(backups, NOW, daily=2, weekly=0, monthly=0)
            self.assertEqual(p.keep, ['x', 'b-2'], order)
            self.assertEqual(p.delete, ['b-1'], order)

    def test_latest_tie(self):
        for order in (['k1', 'k2'], ['k2', 'k1']):
            backups = [B(i, 2025, 3, 12, 3) for i in order]
            p = plan(backups, NOW, daily=0, weekly=0, monthly=0)
            self.assertEqual(p.keep, ['k2'])
            self.assertEqual(p.delete, ['k1'])


class MaxAgeTests(unittest.TestCase):
    def test_strictly_older_than_limit_deleted(self):
        backups = [B('new', 2025, 3, 12), B('edge', 2025, 3, 2, 12, 0), B('over', 2025, 3, 2, 11, 59)]
        p = plan(backups, NOW, daily=5, weekly=0, monthly=0, max_age_days=10)
        self.assertEqual(p.keep, ['new', 'edge'])
        self.assertEqual(p.delete, ['over'])

    def test_pinned_and_latest_survive_max_age(self):
        backups = [B('pin', 2024, 1, 1, pinned=True), B('only', 2024, 6, 1), B('older', 2024, 5, 1)]
        p = plan(backups, NOW, daily=3, weekly=3, monthly=3, max_age_days=30)
        self.assertEqual(p.keep, ['only', 'pin'])
        self.assertEqual(p.reasons, {'only': ['latest', 'daily', 'weekly', 'monthly'], 'pin': ['pinned']})
        self.assertEqual(p.delete, ['older'])


class ShapeTests(unittest.TestCase):
    def test_delete_is_oldest_first_and_keep_newest_first(self):
        backups = [B('d3', 2025, 3, 3), B('d1', 2025, 3, 1), B('d4', 2025, 3, 4), B('d2', 2025, 3, 2),
                   B('d2b', 2025, 3, 2), B('top', 2025, 3, 12)]
        p = plan(backups, NOW, daily=2, weekly=0, monthly=0)
        self.assertEqual(p.keep, ['top', 'd4'])
        self.assertEqual(p.delete, ['d1', 'd2', 'd2b', 'd3'])
        self.assertEqual(set(p.reasons), {'top', 'd4'})


if __name__ == '__main__':
    unittest.main()
