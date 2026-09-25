import unittest
from decimal import Decimal

from salesreport.checks import has_blank_amounts, missing_columns
from salesreport.summary import render, summarize


ROWS = [
    {'region': 'north', 'rep': 'a', 'amount': '10.00'},
    {'region': 'South', 'rep': 'b', 'amount': '2.50'},
    {'region': 'north', 'rep': 'c', 'amount': ''},
    {'region': 'NORTH', 'rep': 'd', 'amount': '1.25'},
]


class SummaryTests(unittest.TestCase):
    def test_summarize_skips_blank_and_folds_case(self):
        self.assertEqual(summarize(ROWS), {'north': Decimal('11.25'), 'south': Decimal('2.50')})

    def test_render_total_line(self):
        lines = render(summarize(ROWS))
        self.assertEqual(lines[-1].split(), ['TOTAL', '13.75'])

    def test_blank_amount_check(self):
        self.assertTrue(has_blank_amounts(ROWS))
        self.assertFalse(has_blank_amounts(ROWS[:2]))

    def test_missing_columns(self):
        self.assertEqual(missing_columns(['region', ' amount']), ['rep'])


if __name__ == '__main__':
    unittest.main()
