import unittest

from ledger.money import UnknownCurrencyError, format_money


class FormatMoneyTests(unittest.TestCase):
    def test_usd(self):
        self.assertEqual(format_money(123456, 'USD'), '$1,234.56')

    def test_eur(self):
        self.assertEqual(format_money(123456, 'EUR'), '1.234,56 €')

    def test_jpy_has_no_minor_unit(self):
        self.assertEqual(format_money(1234, 'JPY'), '¥1,234')

    def test_unknown_currency(self):
        with self.assertRaises(UnknownCurrencyError):
            format_money(100, 'XYZ')


if __name__ == '__main__':
    unittest.main()
