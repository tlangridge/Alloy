import unittest

from retention import format_duration, parse_duration
from retention.policy import expired


class ComponentTests(unittest.TestCase):
    def test_each_unit(self):
        self.assertEqual(parse_duration('2w'), 2 * 604800)
        self.assertEqual(parse_duration('3d'), 3 * 86400)
        self.assertEqual(parse_duration('4h'), 4 * 3600)
        self.assertEqual(parse_duration('5m'), 300)
        self.assertEqual(parse_duration('6s'), 6)

    def test_all_units_summed(self):
        self.assertEqual(parse_duration('1w1d1h1m1s'), 694861)

    def test_units_are_case_insensitive(self):
        self.assertEqual(parse_duration('1H30M'), 5400)
        self.assertEqual(parse_duration('2W 1d'), 2 * 604800 + 86400)

    def test_numbers_not_limited_by_next_unit(self):
        self.assertEqual(parse_duration('90m'), 5400)
        self.assertEqual(parse_duration('36h'), 36 * 3600)

    def test_zero_components(self):
        self.assertEqual(parse_duration('0h'), 0)
        self.assertEqual(parse_duration('1h0m'), 3600)

    def test_result_is_int(self):
        self.assertIs(type(parse_duration('1h30m')), int)


class WhitespaceTests(unittest.TestCase):
    def test_separators_optional_and_repeatable(self):
        self.assertEqual(parse_duration('1h 30m'), 5400)
        self.assertEqual(parse_duration('1h   30m'), 5400)
        self.assertEqual(parse_duration('1w\t2d'), 604800 + 2 * 86400)

    def test_surrounding_whitespace_ignored(self):
        self.assertEqual(parse_duration('  2d 4h  '), 2 * 86400 + 4 * 3600)
        self.assertEqual(parse_duration('\n15m\n'), 900)

    def test_space_between_number_and_unit_rejected(self):
        for text in ('5 m', '1h 30 m'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)


class OrderTests(unittest.TestCase):
    def test_decreasing_order_accepted(self):
        self.assertEqual(parse_duration('1d2h'), 86400 + 7200)
        self.assertEqual(parse_duration('1w30s'), 604830)

    def test_out_of_order_rejected(self):
        for text in ('2h1d', '30m1h', '1s1m', '1d 1w'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)

    def test_repeated_unit_rejected(self):
        for text in ('1h 1h', '5m5m', '1H1h'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)


class BareSecondsTests(unittest.TestCase):
    def test_bare_integer_is_seconds(self):
        self.assertEqual(parse_duration('90'), 90)
        self.assertEqual(parse_duration(' 0 '), 0)
        self.assertEqual(parse_duration('3600'), 3600)

    def test_unitless_number_inside_compound_rejected(self):
        for text in ('1h 30', '30 1h', '1h30'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)


class ErrorTests(unittest.TestCase):
    def test_empty_rejected(self):
        for text in ('', '   ', '\t'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)

    def test_signs_rejected(self):
        for text in ('-5m', '+5m', '-90', '1h -5m'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)

    def test_decimals_rejected(self):
        for text in ('1.5h', '0.5', '1h 2.5m'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)

    def test_unknown_units_rejected(self):
        for text in ('5y', '5ms', '3x', '1h2q'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)

    def test_stray_characters_rejected(self):
        for text in ('1h, 30m', '1h30m!', 'h', 'abc', '1h and 30m', '1h-30m'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_duration(text)

    def test_non_str_raises_type_error(self):
        for value in (90, None, b'1h', 1.5):
            with self.subTest(value=value), self.assertRaises(TypeError):
                parse_duration(value)


class FormatTests(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(format_duration(5400), '1h30m')
        self.assertEqual(format_duration(694861), '1w1d1h1m1s')
        self.assertEqual(format_duration(86400), '1d')
        self.assertEqual(format_duration(3601), '1h1s')
        self.assertEqual(format_duration(59), '59s')

    def test_zero(self):
        self.assertEqual(format_duration(0), '0s')

    def test_weeks_are_largest_unit(self):
        self.assertEqual(format_duration(15 * 86400), '2w1d')
        self.assertEqual(format_duration(604800 * 10 + 60), '10w1m')

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            format_duration(-1)

    def test_round_trip(self):
        values = list(range(0, 4000, 7)) + [59, 60, 61, 3599, 3600, 86399, 86400, 604799,
                                            604800, 694861, 10 ** 9]
        bad = [n for n in values if parse_duration(format_duration(n)) != n]
        self.assertEqual(bad, [])


class PolicyTests(unittest.TestCase):
    def test_policy_accepts_compound_duration(self):
        snapshots = {'old': 0, 'mid': 4000, 'new': 5000}
        self.assertEqual(expired(snapshots, '1h 10m', now=8300), ['mid', 'old'])


if __name__ == '__main__':
    unittest.main()
