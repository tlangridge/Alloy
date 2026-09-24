import unittest
from datetime import datetime as D, timedelta, timezone

from cadence import CronSyntaxError, parse

# 2026-03-02 is a Monday; 2026-03-01 is a Sunday.
WEEK = {name: D(2026, 3, 1 + i) for i, name in enumerate(['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'])}


def days_matching(expr):
    s = parse(expr)
    return {name for name, day in WEEK.items() if s.matches(day)}


class Base(unittest.TestCase):
    def bad(self, expr, field, item):
        with self.assertRaises(CronSyntaxError) as ctx:
            parse(expr)
        self.assertIsInstance(ctx.exception, ValueError)
        self.assertEqual((ctx.exception.field, ctx.exception.item), (field, item), expr)


class SyntaxTests(Base):
    def test_field_count(self):
        for expr in ['* * * *', '* * * * * *', '', '   ']:
            with self.assertRaises(CronSyntaxError) as ctx:
                parse(expr)
            self.assertIsNone(ctx.exception.field, expr)

    def test_macros(self):
        self.bad('@every5m', None, '@every5m')
        self.bad('  @reboot ', None, '@reboot')
        self.assertEqual(parse('  @Daily ').next_after(D(2026, 3, 4, 12, 0)), D(2026, 3, 5, 0, 0))
        self.assertEqual(parse('@WEEKLY').next_after(D(2026, 3, 4, 12, 0)), D(2026, 3, 8, 0, 0))
        self.assertEqual(parse('@annually').next_after(D(2026, 3, 4)), D(2027, 1, 1))
        self.assertEqual(parse('@hourly').next_after(D(2026, 3, 4, 12, 0)), D(2026, 3, 4, 13, 0))
        self.assertEqual(parse('@midnight').previous_before(D(2026, 3, 4, 0, 0)), D(2026, 3, 3, 0, 0))

    def test_out_of_range_values(self):
        self.bad('60 * * * *', 'minute', '60')
        self.bad('0 24 * * *', 'hour', '24')
        self.bad('0 0 0 * *', 'day_of_month', '0')
        self.bad('0 0 1,32 * *', 'day_of_month', '32')
        self.bad('0 0 * 0 *', 'month', '0')
        self.bad('0 0 * 1-13 *', 'month', '1-13')
        self.bad('0 0 * * 8', 'day_of_week', '8')

    def test_names_only_in_their_field(self):
        self.bad('0 0 * * JAN', 'day_of_week', 'JAN')
        self.bad('0 0 * MON *', 'month', 'MON')
        self.bad('MON 0 * * *', 'minute', 'MON')
        self.assertTrue(parse('0 0 * Jan mon').matches(D(2026, 1, 5)))
        self.assertTrue(parse('0 0 * dec-DEC sun').matches(D(2026, 12, 6)))

    def test_reversed_ranges(self):
        self.bad('10-5 * * * *', 'minute', '10-5')
        self.bad('0 0 20-10 * *', 'day_of_month', '20-10')
        self.bad('0 0 * DEC-JAN *', 'month', 'DEC-JAN')
        parse('0 0 * * FRI-MON')

    def test_steps(self):
        self.bad('*/0 * * * *', 'minute', '*/0')
        self.bad('*/x * * * *', 'minute', '*/x')
        self.bad('0 0 1/ * *', 'day_of_month', '1/')
        s = parse('*/90 * * * *')
        self.assertEqual(s.occurrences(D(2026, 1, 1, 0, 0), 2), [D(2026, 1, 1, 1, 0), D(2026, 1, 1, 2, 0)])
        s = parse('5/20,10-30/7 0 * * *')
        self.assertEqual([d.minute for d in s.occurrences(D(2025, 12, 31, 23, 59), 6)], [5, 10, 17, 24, 25, 45])

    def test_empty_items(self):
        self.bad('1,,2 * * * *', 'minute', '')
        self.bad('0 5, * * *', 'hour', '')
        self.bad('0 0 * * ,MON', 'day_of_week', '')

    def test_last_day_items(self):
        self.bad('0 L * * *', 'hour', 'L')
        self.bad('0 0 L-0 * *', 'day_of_month', 'L-0')
        self.bad('0 0 L-31 * *', 'day_of_month', 'L-31')
        self.bad('0 0 L/2 * *', 'day_of_month', 'L/2')
        self.bad('0 0 * * L', 'day_of_week', 'L')
        parse('0 0 L-2,15,L * *')

    def test_nth_weekday_items(self):
        self.bad('0 0 * * MON#6', 'day_of_week', 'MON#6')
        self.bad('0 0 * * 1#0', 'day_of_week', '1#0')
        self.bad('0 0 1#2 * *', 'day_of_month', '1#2')
        self.bad('0 0 * * 1-5#2', 'day_of_week', '1-5#2')
        self.bad('0 0 * * 5L/2', 'day_of_week', '5L/2')
        parse('0 0 * * MON#1,FRIL,3')

    def test_question_mark(self):
        self.bad('? * * * *', 'minute', '?')
        self.bad('0 0 * ? *', 'month', '?')
        self.bad('0 0 ?,5 * *', 'day_of_month', '?')
        self.bad('0 0 * * MON,?', 'day_of_week', '?')
        parse('0 0 ? * ?')

    def test_whitespace(self):
        s = parse('\t0  12 *\t*   *  ')
        self.assertEqual(s.next_after(D(2026, 1, 1, 12, 0)), D(2026, 1, 2, 12, 0))


class ExpansionTests(Base):
    def test_zero_and_seven_are_sunday(self):
        self.assertEqual(days_matching('0 0 * * 7'), {'sun'})
        self.assertEqual(days_matching('0 0 * * 0'), {'sun'})
        self.assertEqual(days_matching('0 0 * * SUN,7'), {'sun'})

    def test_day_of_week_ranges_wrap(self):
        self.assertEqual(days_matching('0 0 * * FRI-MON'), {'fri', 'sat', 'sun', 'mon'})
        self.assertEqual(days_matching('0 0 * * 5-7'), {'fri', 'sat', 'sun'})
        self.assertEqual(days_matching('0 0 * * 7-2'), {'sun', 'mon', 'tue'})
        self.assertEqual(days_matching('0 0 * * sat-sun'), {'sat', 'sun'})

    def test_day_of_week_steps(self):
        self.assertEqual(days_matching('0 0 * * */2'), {'sun', 'tue', 'thu', 'sat'})
        self.assertEqual(days_matching('0 0 * * 1/2'), {'mon', 'wed', 'fri'})
        self.assertEqual(days_matching('0 0 * * MON-SUN/2'), {'mon', 'wed', 'fri', 'sun'})
        self.assertEqual(days_matching('0 0 * * FRI-MON/2'), {'fri', 'sun'})
        self.assertEqual(days_matching('0 0 * * 0-7/7'), {'sun'})

    def test_month_steps(self):
        s = parse('0 0 1 */3 *')
        self.assertEqual([d.month for d in s.occurrences(D(2026, 1, 1), 5)], [4, 7, 10, 1, 4])


class DaySemanticsTests(Base):
    def test_both_restricted_is_or(self):
        s = parse('0 0 13 * FRI')
        self.assertEqual(s.occurrences(D(2026, 1, 1), 5),
                         [D(2026, 1, 2), D(2026, 1, 9), D(2026, 1, 13), D(2026, 1, 16), D(2026, 1, 23)])

    def test_star_step_counts_as_restricted(self):
        s = parse('0 0 */2 * MON')
        self.assertEqual(s.occurrences(D(2026, 3, 1), 6),
                         [D(2026, 3, 2), D(2026, 3, 3), D(2026, 3, 5), D(2026, 3, 7), D(2026, 3, 9), D(2026, 3, 11)])
        self.assertEqual(days_matching('0 0 13 * 0-7'), set(WEEK))
        self.assertTrue(parse('0 0 1-31 * MON').matches(D(2026, 3, 4)))

    def test_question_and_star_are_unrestricted(self):
        self.assertEqual(parse('0 0 ? * MON').occurrences(D(2026, 3, 1), 2), [D(2026, 3, 2), D(2026, 3, 9)])
        self.assertEqual(parse('0 0 13 * ?').occurrences(D(2026, 3, 1), 2), [D(2026, 3, 13), D(2026, 4, 13)])
        self.assertEqual(parse('0 0 13 * *').next_after(D(2026, 3, 1)), D(2026, 3, 13))

    def test_or_rescues_impossible_day_of_month(self):
        self.assertEqual(parse('0 0 30 2 MON').next_after(D(2026, 3, 1)), D(2027, 2, 1))

    def test_last_day_or_weekday(self):
        s = parse('0 0 L * MON')
        self.assertEqual(s.occurrences(D(2026, 1, 25), 4),
                         [D(2026, 1, 26), D(2026, 1, 31), D(2026, 2, 2), D(2026, 2, 9)])

    def test_month_always_applies(self):
        s = parse('0 0 13 6 FRI')
        self.assertEqual(s.next_after(D(2026, 1, 1)), D(2026, 6, 5))


class OccurrenceTests(Base):
    def test_next_after_is_strict_and_truncates_seconds(self):
        s = parse('* * * * *')
        self.assertEqual(s.next_after(D(2026, 1, 1, 10, 0, 0)), D(2026, 1, 1, 10, 1))
        self.assertEqual(s.next_after(D(2026, 1, 1, 10, 0, 30, 5)), D(2026, 1, 1, 10, 1))
        self.assertEqual(parse('0 * * * *').next_after(D(2026, 1, 1, 10, 0)), D(2026, 1, 1, 11, 0))
        self.assertEqual(parse('59 23 31 12 *').next_after(D(2026, 6, 1)), D(2026, 12, 31, 23, 59))

    def test_previous_before_is_strict(self):
        s = parse('* * * * *')
        self.assertEqual(s.previous_before(D(2026, 1, 1, 10, 0, 30)), D(2026, 1, 1, 10, 0))
        self.assertEqual(s.previous_before(D(2026, 1, 1, 10, 0, 0)), D(2026, 1, 1, 9, 59))
        self.assertEqual(parse('0 12 * * *').previous_before(D(2026, 1, 1, 12, 0)), D(2025, 12, 31, 12, 0))
        self.assertEqual(parse('0 12 * * *').previous_before(D(2026, 1, 1, 12, 0, 1)), D(2026, 1, 1, 12, 0))

    def test_matches_ignores_seconds(self):
        s = parse('15 10 * * *')
        self.assertTrue(s.matches(D(2026, 1, 1, 10, 15, 59, 999)))
        self.assertFalse(s.matches(D(2026, 1, 1, 10, 16)))

    def test_short_months_are_skipped(self):
        self.assertEqual(parse('0 0 31 * *').next_after(D(2026, 1, 31)), D(2026, 3, 31))
        self.assertEqual(parse('0 0 31 * *').previous_before(D(2026, 7, 1)), D(2026, 5, 31))

    def test_last_day_of_month(self):
        s = parse('0 12 L * *')
        self.assertEqual(s.next_after(D(2024, 2, 10)), D(2024, 2, 29, 12, 0))
        self.assertEqual(s.next_after(D(2023, 2, 10)), D(2023, 2, 28, 12, 0))
        self.assertEqual(parse('0 0 L 12 *').previous_before(D(2026, 6, 1)), D(2025, 12, 31))

    def test_last_day_offsets(self):
        s = parse('0 0 L-2 * *')
        self.assertEqual(s.next_after(D(2023, 2, 1)), D(2023, 2, 26))
        self.assertEqual(s.next_after(D(2024, 4, 1)), D(2024, 4, 28))
        s = parse('0 0 L-30 * *')
        self.assertEqual(s.next_after(D(2024, 4, 15)), D(2024, 5, 1))
        self.assertIsNone(parse('0 0 L-30 2 *').next_after(D(2024, 1, 1)))

    def test_nth_weekday(self):
        self.assertEqual(parse('0 9 * * MON#2').occurrences(D(2026, 1, 1), 3),
                         [D(2026, 1, 12, 9), D(2026, 2, 9, 9), D(2026, 3, 9, 9)])
        self.assertEqual(parse('0 9 * * 5#5').occurrences(D(2026, 1, 1), 3),
                         [D(2026, 1, 30, 9), D(2026, 5, 29, 9), D(2026, 7, 31, 9)])
        self.assertEqual(parse('0 9 * * 7#1').next_after(D(2026, 3, 2)), D(2026, 4, 5, 9))

    def test_last_weekday(self):
        self.assertEqual(parse('0 0 * * 5L').occurrences(D(2026, 1, 1), 3),
                         [D(2026, 1, 30), D(2026, 2, 27), D(2026, 3, 27)])
        self.assertEqual(parse('0 0 * * friL').next_after(D(2026, 1, 1)), D(2026, 1, 30))
        self.assertEqual(parse('0 0 * * 7L').occurrences(D(2026, 1, 1), 2), [D(2026, 1, 25), D(2026, 2, 22)])

    def test_leap_day_across_2100(self):
        self.assertEqual(parse('0 0 29 2 *').next_after(D(2096, 3, 1)), D(2104, 2, 29))
        self.assertEqual(parse('0 0 29 2 *').previous_before(D(2104, 2, 28)), D(2096, 2, 29))

    def test_search_horizon_is_eight_years(self):
        s = parse('0 0 * 2 FRI#5')   # only when Feb 29 is a Friday: 2008, 2036, 2064, ...
        self.assertEqual(s.next_after(D(2028, 1, 1)), D(2036, 2, 29))
        self.assertIsNone(s.next_after(D(2027, 12, 31, 23, 59)))
        self.assertEqual(s.previous_before(D(2044, 12, 31)), D(2036, 2, 29))
        self.assertIsNone(s.previous_before(D(2045, 1, 1)))

    def test_impossible_schedules_return_none(self):
        for expr in ['0 0 30 2 *', '0 0 31 4,6,9,11 *']:
            self.assertIsNone(parse(expr).next_after(D(2026, 1, 1)), expr)
            self.assertIsNone(parse(expr).previous_before(D(2026, 1, 1)), expr)

    def test_business_hours_step(self):
        s = parse('30 9-17/4 * * MON-FRI')
        self.assertEqual(s.next_after(D(2026, 3, 6, 17, 30)), D(2026, 3, 9, 9, 30))
        self.assertEqual([d.hour for d in s.occurrences(D(2026, 3, 9, 0, 0), 3)], [9, 13, 17])
        self.assertEqual(s.previous_before(D(2026, 3, 9, 9, 30)), D(2026, 3, 6, 17, 30))

    def test_occurrences(self):
        s = parse('*/20 9-10 * * *')
        self.assertEqual(s.occurrences(D(2026, 1, 1, 9, 30), 4),
                         [D(2026, 1, 1, 9, 40), D(2026, 1, 1, 10, 0), D(2026, 1, 1, 10, 20), D(2026, 1, 1, 10, 40)])
        self.assertEqual(parse('0 0 29 2 *').occurrences(D(2088, 1, 1), 5),
                         [D(2088, 2, 29), D(2092, 2, 29), D(2096, 2, 29), D(2104, 2, 29), D(2108, 2, 29)])

    def test_aware_datetimes_are_rejected(self):
        s = parse('* * * * *')
        aware = D(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))
        for method in (s.matches, s.next_after, s.previous_before):
            with self.assertRaises(ValueError):
                method(aware)


if __name__ == '__main__':
    unittest.main()
