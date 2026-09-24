import unittest

from bakctl.args import ArgParser, UsageError


def make_parser():
    parser = ArgParser()
    parser.add_flag('verbose', short='v')
    parser.add_flag('quiet', short='q')
    parser.add_flag('dry-run', short='n')
    parser.add_option('output', short='o')
    parser.add_option('exclude', short='x', repeat=True)
    parser.add_option('define', short='D', repeat=True)
    parser.add_option('level', default='3')
    return parser


def parse(argv):
    return make_parser().parse(argv)


class LongEqualsTests(unittest.TestCase):
    def test_value_after_equals(self):
        values, positionals = parse(['--output=out.tar', 'src'])
        self.assertEqual(values['output'], 'out.tar')
        self.assertEqual(positionals, ['src'])

    def test_empty_value(self):
        values, _ = parse(['--output='])
        self.assertEqual(values['output'], '')

    def test_value_split_on_first_equals_only(self):
        values, _ = parse(['--define=a=b', '--define==x', '--output=k=v=w'])
        self.assertEqual(values['define'], ['a=b', '=x'])
        self.assertEqual(values['output'], 'k=v=w')

    def test_value_may_start_with_dash(self):
        values, _ = parse(['--output=-v'])
        self.assertEqual(values['output'], '-v')
        self.assertFalse(values['verbose'])

    def test_option_without_short_name(self):
        values, _ = parse(['--level=9'])
        self.assertEqual(values['level'], '9')

    def test_flag_with_value_rejected(self):
        for arg in ('--verbose=yes', '--verbose=', '--dry-run=1'):
            with self.subTest(arg=arg), self.assertRaises(UsageError):
                parse([arg])

    def test_unknown_name_with_value_rejected(self):
        for arg in ('--bogus=1', '--outputs=x', '--=x'):
            with self.subTest(arg=arg), self.assertRaises(UsageError):
                parse([arg])


class BundleTests(unittest.TestCase):
    def test_flags_bundle(self):
        values, _ = parse(['-vqn'])
        self.assertTrue(values['verbose'])
        self.assertTrue(values['quiet'])
        self.assertTrue(values['dry_run'])

    def test_attached_value(self):
        values, _ = parse(['-oout.tar'])
        self.assertEqual(values['output'], 'out.tar')
        self.assertFalse(values['verbose'])

    def test_flags_then_attached_value(self):
        values, positionals = parse(['-voout.tar', 'src'])
        self.assertTrue(values['verbose'])
        self.assertEqual(values['output'], 'out.tar')
        self.assertEqual(positionals, ['src'])

    def test_rest_of_bundle_is_value_not_flags(self):
        values, _ = parse(['-ov'])
        self.assertEqual(values['output'], 'v')
        self.assertFalse(values['verbose'])
        values, _ = parse(['-xvq'])
        self.assertEqual(values['exclude'], ['vq'])
        self.assertFalse(values['verbose'])
        self.assertFalse(values['quiet'])

    def test_value_option_last_takes_next_argument(self):
        values, positionals = parse(['-vo', 'out.tar', 'src'])
        self.assertTrue(values['verbose'])
        self.assertEqual(values['output'], 'out.tar')
        self.assertEqual(positionals, ['src'])

    def test_next_argument_taken_even_if_dashed(self):
        values, _ = parse(['-vo', '-q'])
        self.assertEqual(values['output'], '-q')
        self.assertFalse(values['quiet'])

    def test_missing_value_at_end_rejected(self):
        for argv in (['-vo'], ['src', '-nx']):
            with self.subTest(argv=argv), self.assertRaises(UsageError):
                parse(argv)

    def test_unknown_letter_rejected(self):
        for arg in ('-vz', '-zv', '-v-', '-qvn9'):
            with self.subTest(arg=arg), self.assertRaises(UsageError):
                parse([arg])

    def test_unknown_letter_after_value_option_is_value(self):
        values, _ = parse(['-oz'])
        self.assertEqual(values['output'], 'z')


class DoubleDashTests(unittest.TestCase):
    def test_everything_after_is_positional(self):
        values, positionals = parse(['a', '--', '-v', '--output', 'x', '-'])
        self.assertFalse(values['verbose'])
        self.assertIsNone(values['output'])
        self.assertEqual(positionals, ['a', '-v', '--output', 'x', '-'])

    def test_second_double_dash_is_positional(self):
        _, positionals = parse(['--', '--', 'b'])
        self.assertEqual(positionals, ['--', 'b'])

    def test_double_dash_alone(self):
        values, positionals = parse(['-v', '--'])
        self.assertTrue(values['verbose'])
        self.assertEqual(positionals, [])

    def test_double_dash_as_option_value(self):
        values, positionals = parse(['--output', '--', '-v'])
        self.assertEqual(values['output'], '--')
        self.assertTrue(values['verbose'])
        self.assertEqual(positionals, [])


class ConsistencyTests(unittest.TestCase):
    def test_repeat_across_spellings(self):
        values, _ = parse(['--exclude=a', '-xb', '-x', 'c', '--exclude', 'd', '-vxe'])
        self.assertEqual(values['exclude'], ['a', 'b', 'c', 'd', 'e'])

    def test_last_wins_across_spellings(self):
        values, _ = parse(['--output=a', '-ob'])
        self.assertEqual(values['output'], 'b')
        values, _ = parse(['-ob', '--output', 'c'])
        self.assertEqual(values['output'], 'c')
        values, _ = parse(['--output', 'c', '--output=d'])
        self.assertEqual(values['output'], 'd')

    def test_fresh_defaults_each_parse(self):
        parser = make_parser()
        parser.parse(['-xa', '--exclude=b'])
        values, _ = parser.parse([])
        self.assertEqual(values['exclude'], [])
        self.assertIsNone(values['output'])


class PreservedBehaviorTests(unittest.TestCase):
    def test_existing_spellings(self):
        values, positionals = parse(['src', '--verbose', '-o', 'out', '--exclude', '*.o', 'dst'])
        self.assertTrue(values['verbose'])
        self.assertEqual(values['output'], 'out')
        self.assertEqual(values['exclude'], ['*.o'])
        self.assertEqual(positionals, ['src', 'dst'])

    def test_next_argument_value_may_start_with_dash(self):
        values, _ = parse(['--output', '-v'])
        self.assertEqual(values['output'], '-v')
        self.assertFalse(values['verbose'])

    def test_lone_dash_is_positional(self):
        _, positionals = parse(['-', '-v', '-'])
        self.assertEqual(positionals, ['-', '-'])

    def test_missing_value_rejected(self):
        for argv in (['--output'], ['-o']):
            with self.subTest(argv=argv), self.assertRaises(UsageError):
                parse(argv)

    def test_unknown_options_rejected(self):
        for argv in (['--bogus'], ['-z']):
            with self.subTest(argv=argv), self.assertRaises(UsageError):
                parse(argv)

    def test_defaults(self):
        values, positionals = parse([])
        self.assertEqual(values, {'verbose': False, 'quiet': False, 'dry_run': False, 'output': None,
                                  'exclude': [], 'define': [], 'level': '3'})
        self.assertEqual(positionals, [])


if __name__ == '__main__':
    unittest.main()
