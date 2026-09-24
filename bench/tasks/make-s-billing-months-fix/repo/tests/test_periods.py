import unittest
from datetime import date

from billing.periods import add_months, next_renewal, renewals


class AddMonthsTests(unittest.TestCase):
    def test_simple_shift(self):
        self.assertEqual(add_months(date(2024, 3, 10), 2), date(2024, 5, 10))

    def test_clamps_to_month_end(self):
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_months(date(2023, 1, 31), 1), date(2023, 2, 28))

    def test_into_next_year(self):
        self.assertEqual(add_months(date(2024, 12, 15), 1), date(2025, 1, 15))


class RenewalTests(unittest.TestCase):
    def test_next_renewal(self):
        self.assertEqual(next_renewal(date(2024, 3, 10), date(2024, 5, 1)), date(2024, 5, 10))
        self.assertEqual(next_renewal(date(2024, 3, 10), date(2024, 5, 10)), date(2024, 6, 10))

    def test_renewals(self):
        self.assertEqual(renewals(date(2024, 3, 10), 3),
                         [date(2024, 4, 10), date(2024, 5, 10), date(2024, 6, 10)])


if __name__ == '__main__':
    unittest.main()
