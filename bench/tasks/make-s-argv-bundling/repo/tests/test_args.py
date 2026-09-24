import unittest

from bakctl.args import ArgParser, UsageError


def make_parser():
    parser = ArgParser()
    parser.add_flag('verbose', short='v')
    parser.add_flag('dry-run', short='n')
    parser.add_option('output', short='o')
    parser.add_option('exclude', short='x', repeat=True)
    parser.add_option('level', default='3')
    return parser


class ParseTests(unittest.TestCase):
    def test_defaults(self):
        values, positionals = make_parser().parse([])
        self.assertEqual(values, {'verbose': False, 'dry_run': False, 'output': None,
                                  'exclude': [], 'level': '3'})
        self.assertEqual(positionals, [])

    def test_long_and_short_options(self):
        values, positionals = make_parser().parse(['src', '-v', '--output', 'out.tar', '-x', '*.tmp', 'more'])
        self.assertTrue(values['verbose'])
        self.assertEqual(values['output'], 'out.tar')
        self.assertEqual(values['exclude'], ['*.tmp'])
        self.assertEqual(positionals, ['src', 'more'])

    def test_long_option_with_equals(self):
        values, _ = make_parser().parse(['--output=out.tar'])
        self.assertEqual(values['output'], 'out.tar')

    def test_bundled_short_flags(self):
        values, _ = make_parser().parse(['-vn'])
        self.assertTrue(values['verbose'])
        self.assertTrue(values['dry_run'])

    def test_double_dash_ends_options(self):
        values, positionals = make_parser().parse(['--', '-v'])
        self.assertFalse(values['verbose'])
        self.assertEqual(positionals, ['-v'])

    def test_unknown_option(self):
        with self.assertRaises(UsageError):
            make_parser().parse(['--bogus'])


if __name__ == '__main__':
    unittest.main()
