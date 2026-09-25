import unittest

from ledger.money import UnknownCurrencyError, format_money, register_currency


# ---- frozen copy of the pre-refactor implementation (the behavior oracle) ----
def _legacy_group(number, sep):
    digits = str(number)
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return sep.join(groups)


def _legacy_format_money(amount, currency):
    """Format ``amount`` (an int in the currency's minor unit) for display.

    >>> format_money(123456, 'USD')
    '$1,234.56'
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError('amount must be an int number of minor units')
    code = currency.upper()
    negative = amount < 0
    amount = abs(amount)
    if code == 'USD':
        whole, cents = divmod(amount, 100)
        text = '$%s.%02d' % (_legacy_group(whole, ','), cents)
        return '-' + text if negative else text
    if code == 'GBP':
        whole, pence = divmod(amount, 100)
        text = '£%s.%02d' % (_legacy_group(whole, ','), pence)
        return '-' + text if negative else text
    if code == 'EUR':
        whole, cents = divmod(amount, 100)
        text = '%s,%02d €' % (_legacy_group(whole, '.'), cents)
        return '-' + text if negative else text
    if code == 'CHF':
        whole, rappen = divmod(amount, 100)
        digits = "%s.%02d" % (_legacy_group(whole, "'"), rappen)
        return 'CHF ' + ('-' + digits if negative else digits)
    if code == 'JPY':
        text = '¥' + _legacy_group(amount, ',')
        return '-' + text if negative else text
    raise LookupError('unsupported currency: %r' % (currency,))


BUILTINS = ('USD', 'GBP', 'EUR', 'CHF', 'JPY')
AMOUNTS = sorted(set(
    [0, 1, 5, 9, 10, 99, 100, 101, 999, 1000, 1001, 99999, 100000, 123456, 1000000, 99999999,
     100000000, 123456789012, 10 ** 15 + 7] + list(range(0, 2500, 37))))


class PreservationTests(unittest.TestCase):
    def test_builtins_match_previous_implementation(self):
        bad = []
        for code in BUILTINS:
            for amount in AMOUNTS + [-a for a in AMOUNTS]:
                want = _legacy_format_money(amount, code)
                got = format_money(amount, code)
                if got != want:
                    bad.append((code, amount, got, want))
        self.assertEqual(bad[:10], [])

    def test_documented_examples(self):
        self.assertEqual(format_money(123456, 'USD'), '$1,234.56')
        self.assertEqual(format_money(-5, 'GBP'), '-£0.05')
        self.assertEqual(format_money(-123456, 'EUR'), '-1.234,56 €')
        self.assertEqual(format_money(-123456, 'CHF'), "CHF -1'234.56")
        self.assertEqual(format_money(1234567, 'jpy'), '¥1,234,567')

    def test_codes_case_insensitive(self):
        for code in ('usd', 'Usd', 'eUr', 'chf', 'Jpy', 'gbp'):
            with self.subTest(code=code):
                self.assertEqual(format_money(-98765, code), _legacy_format_money(-98765, code))

    def test_type_errors_unchanged(self):
        for amount in (1.5, True, False, '100', None, 100.0):
            with self.subTest(amount=amount), self.assertRaises(TypeError):
                format_money(amount, 'USD')

    def test_unknown_currency_unchanged(self):
        for code in ('XYZ', 'EURO', 'US'):
            with self.subTest(code=code), self.assertRaises(UnknownCurrencyError):
                format_money(100, code)
        self.assertTrue(issubclass(UnknownCurrencyError, ValueError))


class RegistryTests(unittest.TestCase):
    def test_builtins_cannot_be_registered_again(self):
        for code in ('USD', 'gbp', 'Eur', 'CHF', 'jpy'):
            with self.subTest(code=code), self.assertRaises(ValueError):
                register_currency(code, 'X')
        self.assertEqual(format_money(100, 'USD'), '$1.00')

    def test_duplicate_registration_rejected_case_insensitively(self):
        register_currency('AUD', 'A$')
        with self.assertRaises(ValueError):
            register_currency('aud', 'AU$')
        self.assertEqual(format_money(150, 'AUD'), 'A$1.50')


class RegisterValidationTests(unittest.TestCase):
    def assert_rejected(self, code, *args, **kwargs):
        with self.assertRaises(ValueError):
            register_currency(code, *args, **kwargs)
        with self.assertRaises(UnknownCurrencyError):
            format_money(100, code if isinstance(code, str) and len(code) == 3 else 'ZZZ')

    def test_bad_codes(self):
        for code in ('US', 'EURO', 'U$D', '12A', 'ÄBC', '', 'A C'):
            with self.subTest(code=code), self.assertRaises(ValueError):
                register_currency(code, 'x')

    def test_empty_symbol(self):
        self.assert_rejected('QAA', '')

    def test_decimals_out_of_range(self):
        self.assert_rejected('QAB', 'q', decimals=5)
        self.assert_rejected('QAC', 'q', decimals=-1)

    def test_bad_position(self):
        self.assert_rejected('QAD', 'q', position='middle')
        self.assert_rejected('QAE', 'q', position='before')

    def test_failed_registration_can_be_retried(self):
        with self.assertRaises(ValueError):
            register_currency('QAF', 'q', decimals=9)
        register_currency('QAF', 'q')
        self.assertEqual(format_money(100, 'QAF'), 'q1.00')


class RegisteredFormattingTests(unittest.TestCase):
    def test_suffix_with_space(self):
        register_currency('sek', 'kr', thousands_sep=' ', decimal_sep=',', position='suffix', space=True)
        self.assertEqual(format_money(123456, 'SEK'), '1 234,56 kr')
        self.assertEqual(format_money(-123456, 'sek'), '-1 234,56 kr')
        self.assertEqual(format_money(0, 'Sek'), '0,00 kr')

    def test_suffix_without_space(self):
        register_currency('PLN', 'zł', thousands_sep='.', decimal_sep=',', position='suffix')
        self.assertEqual(format_money(123456789, 'PLN'), '1.234.567,89zł')
        self.assertEqual(format_money(-7, 'PLN'), '-0,07zł')

    def test_prefix_without_space(self):
        register_currency('BRL', 'R$', thousands_sep='.', decimal_sep=',')
        self.assertEqual(format_money(123456, 'BRL'), 'R$1.234,56')
        self.assertEqual(format_money(-123456, 'brl'), '-R$1.234,56')

    def test_prefix_with_space_puts_sign_before_number(self):
        register_currency('NOK', 'kr', space=True)
        self.assertEqual(format_money(123456, 'NOK'), 'kr 1,234.56')
        self.assertEqual(format_money(-123456, 'NOK'), 'kr -1,234.56')

    def test_three_decimals(self):
        register_currency('KWD', 'KD', decimals=3)
        self.assertEqual(format_money(1234567, 'KWD'), 'KD1,234.567')
        self.assertEqual(format_money(5, 'KWD'), 'KD0.005')
        self.assertEqual(format_money(-1000, 'KWD'), '-KD1.000')

    def test_four_decimals(self):
        register_currency('CLF', 'UF', decimals=4, space=True)
        self.assertEqual(format_money(12345678, 'CLF'), 'UF 1,234.5678')
        self.assertEqual(format_money(-3, 'CLF'), 'UF -0.0003')

    def test_zero_decimals_has_no_separator(self):
        register_currency('KRW', '₩', decimals=0, decimal_sep='!')
        self.assertEqual(format_money(1234567, 'KRW'), '₩1,234,567')
        self.assertEqual(format_money(-5, 'KRW'), '-₩5')
        self.assertEqual(format_money(0, 'KRW'), '₩0')

    def test_empty_thousands_separator_means_no_grouping(self):
        register_currency('INR', 'Rs', thousands_sep='', space=True)
        self.assertEqual(format_money(123456789, 'INR'), 'Rs 1234567.89')

    def test_multi_character_separators(self):
        register_currency('XTS', 'T', thousands_sep='_', decimal_sep='::', position='suffix')
        self.assertEqual(format_money(123456789, 'XTS'), '1_234_567::89T')

    def test_type_error_applies_to_registered(self):
        register_currency('HKD', 'HK$')
        with self.assertRaises(TypeError):
            format_money(1.0, 'HKD')

    def test_returns_none(self):
        self.assertIsNone(register_currency('SGD', 'S$'))


if __name__ == '__main__':
    unittest.main()
