import unittest

from ledger.money import UnknownCurrencyError, format_money, register_currency


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

    def test_negative_sign_placement(self):
        self.assertEqual(format_money(-123456, 'USD'), '-$1,234.56')
        self.assertEqual(format_money(-123456, 'EUR'), '-1.234,56 €')
        self.assertEqual(format_money(-123456, 'CHF'), "CHF -1'234.56")

    def test_register_currency(self):
        register_currency('sek', 'kr', thousands_sep=' ', decimal_sep=',', position='suffix', space=True)
        self.assertEqual(format_money(-123456, 'SEK'), '-1 234,56 kr')
        with self.assertRaises(ValueError):
            register_currency('USD', '$')


if __name__ == '__main__':
    unittest.main()
