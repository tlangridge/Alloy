import unittest
from datetime import date, timedelta

from billing.periods import add_months, next_renewal, renewals


class AddMonthsTests(unittest.TestCase):
    def test_spec_examples(self):
        cases = [
            (date(2024, 11, 15), 1, date(2024, 12, 15)),
            (date(2024, 12, 15), 1, date(2025, 1, 15)),
            (date(2024, 1, 15), -1, date(2023, 12, 15)),
            (date(2024, 12, 5), 0, date(2024, 12, 5)),
            (date(2024, 6, 10), 18, date(2025, 12, 10)),
            (date(2024, 5, 20), -17, date(2022, 12, 20)),
        ]
        for day, months, expected in cases:
            with self.subTest(day=day, months=months):
                self.assertEqual(add_months(day, months), expected)

    def test_results_landing_in_december(self):
        bad = []
        for start_month in range(1, 13):
            for years in (0, 1, -1, 3):
                months = 12 - start_month + 12 * years
                got = add_months(date(2024, start_month, 7), months)
                if got != date(2024 + years, 12, 7):
                    bad.append((start_month, months, got))
        self.assertEqual(bad, [])

    def test_zero_returns_same_day_every_month(self):
        for month in range(1, 13):
            day = date(2023, month, 28)
            self.assertEqual(add_months(day, 0), day)

    def test_whole_years(self):
        self.assertEqual(add_months(date(2024, 3, 3), 12), date(2025, 3, 3))
        self.assertEqual(add_months(date(2024, 3, 3), -24), date(2022, 3, 3))
        self.assertEqual(add_months(date(2024, 12, 3), 24), date(2026, 12, 3))
        self.assertEqual(add_months(date(2024, 12, 3), -12), date(2023, 12, 3))

    def test_matches_month_counting_model(self):
        bad = []
        for start_month in range(1, 13):
            for months in range(-40, 41):
                got = add_months(date(2021, start_month, 9), months)
                index = 2021 * 12 + (start_month - 1) + months
                if (got.year, got.month, got.day) != (index // 12, index % 12 + 1, 9):
                    bad.append((start_month, months, got))
        self.assertEqual(bad, [])


class ClampingTests(unittest.TestCase):
    def test_spec_examples(self):
        self.assertEqual(add_months(date(2024, 3, 31), -1), date(2024, 2, 29))
        self.assertEqual(add_months(date(2023, 3, 31), -1), date(2023, 2, 28))
        self.assertEqual(add_months(date(2024, 2, 29), 12), date(2025, 2, 28))

    def test_leap_year_rules(self):
        self.assertEqual(add_months(date(2024, 2, 29), 48), date(2028, 2, 29))
        self.assertEqual(add_months(date(2099, 1, 31), 1), date(2099, 2, 28))
        self.assertEqual(add_months(date(2100, 1, 31), 1), date(2100, 2, 28))
        self.assertEqual(add_months(date(2000, 1, 31), 1), date(2000, 2, 29))

    def test_thirty_day_months(self):
        self.assertEqual(add_months(date(2024, 5, 31), -1), date(2024, 4, 30))
        self.assertEqual(add_months(date(2024, 8, 31), 1), date(2024, 9, 30))
        self.assertEqual(add_months(date(2024, 10, 31), 1), date(2024, 11, 30))
        self.assertEqual(add_months(date(2024, 12, 31), -3), date(2024, 9, 30))


class RenewalsTests(unittest.TestCase):
    def test_incident_anchor_jan_31(self):
        self.assertEqual(renewals(date(2024, 1, 31), 6), [
            date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30),
            date(2024, 5, 31), date(2024, 6, 30), date(2024, 7, 31)])

    def test_anchor_aug_31_across_year_end(self):
        self.assertEqual(renewals(date(2024, 8, 31), 7), [
            date(2024, 9, 30), date(2024, 10, 31), date(2024, 11, 30), date(2024, 12, 31),
            date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)])

    def test_anchor_nov_15_crosses_december(self):
        self.assertEqual(renewals(date(2024, 11, 15), 3),
                         [date(2024, 12, 15), date(2025, 1, 15), date(2025, 2, 15)])

    def test_count_zero(self):
        self.assertEqual(renewals(date(2024, 1, 31), 0), [])

    def test_each_renewal_is_computed_from_anchor(self):
        anchor = date(2023, 5, 31)
        self.assertEqual(renewals(anchor, 30), [add_months(anchor, k) for k in range(1, 31)])


class NextRenewalTests(unittest.TestCase):
    def test_incident(self):
        self.assertEqual(next_renewal(date(2024, 1, 31), date(2024, 2, 29)), date(2024, 3, 31))

    def test_strictly_after(self):
        anchor = date(2024, 1, 31)
        self.assertEqual(next_renewal(anchor, date(2024, 3, 30)), date(2024, 3, 31))
        self.assertEqual(next_renewal(anchor, date(2024, 3, 31)), date(2024, 4, 30))
        self.assertEqual(next_renewal(anchor, date(2024, 4, 29)), date(2024, 4, 30))

    def test_crash_case(self):
        self.assertEqual(next_renewal(date(2024, 11, 15), date(2024, 11, 20)), date(2024, 12, 15))
        self.assertEqual(next_renewal(date(2023, 12, 1), date(2024, 11, 1)), date(2024, 12, 1))

    def test_after_before_first_renewal(self):
        anchor = date(2024, 1, 31)
        self.assertEqual(next_renewal(anchor, anchor), date(2024, 2, 29))
        self.assertEqual(next_renewal(anchor, date(2024, 2, 28)), date(2024, 2, 29))
        self.assertEqual(next_renewal(anchor, date(2023, 6, 1)), date(2024, 2, 29))
        self.assertEqual(next_renewal(anchor, date(2020, 12, 31)), date(2024, 2, 29))

    def test_after_late_in_month_past_short_renewal(self):
        self.assertEqual(next_renewal(date(2024, 1, 31), date(2025, 2, 28)), date(2025, 3, 31))
        self.assertEqual(next_renewal(date(2024, 1, 30), date(2024, 2, 29)), date(2024, 3, 30))

    def test_far_future(self):
        self.assertEqual(next_renewal(date(2024, 1, 31), date(2090, 6, 15)), date(2090, 6, 30))

    def test_consistent_with_renewals(self):
        for anchor in (date(2024, 1, 31), date(2023, 8, 30), date(2024, 11, 15), date(2024, 2, 29)):
            dates = renewals(anchor, 26)
            bad = []
            for previous, current in zip([anchor] + dates, dates):
                if next_renewal(anchor, current - timedelta(days=1)) != current:
                    bad.append(('day before', current))
                if next_renewal(anchor, previous) != current:
                    bad.append(('previous', previous, current))
            self.assertEqual(bad, [], anchor)


if __name__ == '__main__':
    unittest.main()
