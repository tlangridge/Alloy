import unittest

from retention import format_duration, parse_duration
from retention.policy import expired


class ParseDurationTests(unittest.TestCase):
    def test_single_component(self):
        self.assertEqual(parse_duration('30d'), 30 * 86400)
        self.assertEqual(parse_duration('45s'), 45)

    def test_compound_duration(self):
        self.assertEqual(parse_duration('1h30m'), 5400)

    def test_garbage_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_duration('soon')


class FormatDurationTests(unittest.TestCase):
    def test_canonical_form(self):
        self.assertEqual(format_duration(5400), '1h30m')


class PolicyTests(unittest.TestCase):
    def test_expired_snapshots(self):
        snapshots = {'a': 0, 'b': 5000, 'c': 9000}
        self.assertEqual(expired(snapshots, '1h', now=9000), ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
