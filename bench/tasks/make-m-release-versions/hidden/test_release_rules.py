import unittest

from fwver import InvalidVersion, parse
from fwver.constraints import InvalidConstraint, max_satisfying, satisfies, sort_versions


def V(tag):
    return parse(tag)


class OrderingTests(unittest.TestCase):
    def test_phase_order_including_hotfix_after_final(self):
        chain = ['1.2.0-dev.4', '1.2.0-alpha', '1.2.0-alpha.3', '1.2.0-beta.1',
                 '1.2.0-rc.1', '1.2.0', '1.2.0-hotfix', '1.2.0-hotfix.2']
        bad = [(lo, hi) for lo, hi in zip(chain, chain[1:])
               if not (V(lo) < V(hi) and V(hi) > V(lo) and V(lo) <= V(hi) and not V(lo) >= V(hi)
                       and V(lo) != V(hi))]
        self.assertEqual(bad, [])

    def test_channel_numbers_compare_numerically(self):
        self.assertLess(V('3.1-rc.2'), V('3.1-rc.10'))
        self.assertLess(V('3.1-hotfix.9'), V('3.1-hotfix.10'))

    def test_missing_channel_number_is_zero(self):
        self.assertEqual(V('1.0-rc'), V('1.0.0-RC.0'))
        self.assertLess(V('1.0-rc'), V('1.0-rc.1'))

    def test_hotfix_sorts_below_next_patch_prerelease(self):
        self.assertLess(V('1.2.0-hotfix.9'), V('1.2.1-dev'))

    def test_epoch_dominates(self):
        self.assertGreater(V('1!0.1'), V('99.99.99-hotfix.5'))
        self.assertLess(V('1!5.0'), V('2!0.0-dev'))
        self.assertEqual(V('0!1.0'), V('1.0'))

    def test_build_prefix_and_patch_do_not_affect_equality(self):
        a, b, c = V('1.2'), V('1.2.0'), V('v1.2.0+b7')
        self.assertTrue(a == b == c)
        self.assertFalse(a != c)
        self.assertEqual(len({a, b, c}), 1)
        self.assertFalse(V('1.2.0+b2') < V('1.2.0+b1'))
        self.assertFalse(V('1.2.0+b1') < V('1.2.0+b2'))
        self.assertEqual(hash(V('2.0-rc+x')), hash(V('v2.0.0-rc.0')))

    def test_comparison_with_non_version(self):
        self.assertFalse(V('1.0') == '1.0')
        self.assertTrue(V('1.0') != '1.0')
        with self.assertRaises(TypeError):
            V('1.0') < '2.0'


class SortTests(unittest.TestCase):
    def test_sort_versions_returns_original_strings_stably(self):
        tags = ['2.0', 'v1.10.0', '1.2.0-hotfix.1', '1.2+b9', '1.2.0-rc.3', '1.2.0', '1!0.1', '1.9.0']
        self.assertEqual(sort_versions(tags),
                         ['1.2.0-rc.3', '1.2+b9', '1.2.0', '1.2.0-hotfix.1', '1.9.0', 'v1.10.0', '2.0', '1!0.1'])
        self.assertEqual(tags[0], '2.0')  # input untouched

    def test_sort_versions_rejects_invalid(self):
        with self.assertRaises(InvalidVersion):
            sort_versions(['1.0', 'banana'])


class ClauseTests(unittest.TestCase):
    def test_bare_version_means_equality(self):
        self.assertTrue(satisfies('1.2.0+b3', '1.2'))
        self.assertFalse(satisfies('1.2.1', '1.2'))

    def test_equality_ignores_build_and_prefix(self):
        self.assertTrue(satisfies('v1.2.0+b3', '==1.2'))
        self.assertTrue(satisfies(V('1.2.0'), '== v1.2.0+other'))

    def test_not_equal_and_conjunction(self):
        self.assertFalse(satisfies('1.3.0', '>=1.0, !=1.3.0, <2.0'))
        self.assertTrue(satisfies('1.3.1', '>=1.0, !=1.3.0, <2.0'))
        self.assertFalse(satisfies('2.0.0', '>=1.0, !=1.3.0, <2.0'))

    def test_whitespace_is_ignored(self):
        self.assertTrue(satisfies('1.5.0', '  >= 1.0 ,<  2.0 '))
        self.assertTrue(satisfies('1.0.0', '<=  1.0'))

    def test_hotfix_against_comparison_clauses(self):
        self.assertFalse(satisfies('1.2.0-hotfix.1', '<=1.2.0'))
        self.assertFalse(satisfies('1.2.0-hotfix.1', '==1.2.0'))
        self.assertTrue(satisfies('1.2.0-hotfix.1', '>1.2.0'))
        self.assertTrue(satisfies('1.2.0-hotfix.1', '>=1.2, <1.3'))

    def test_invalid_specs(self):
        accepted = []
        for bad in ('', '   ', '>=', '1.0,,2.0', '>=1.0,', '=>1.0', '=1.0', '>=1.x', '~1', '^'):
            try:
                satisfies('1.0.0', bad)
            except InvalidConstraint:
                continue
            except Exception as exc:  # wrong exception type
                accepted.append((bad, type(exc).__name__))
            else:
                accepted.append((bad, 'no error'))
        self.assertEqual(accepted, [])
        self.assertTrue(issubclass(InvalidConstraint, ValueError))

    def test_invalid_version_argument(self):
        with self.assertRaises(InvalidVersion):
            satisfies('one.two', '>=1.0')


class TildeCaretTests(unittest.TestCase):
    def test_tilde_two_and_three_components(self):
        for spec in ('~1.4', '~1.4.0'):
            got = [satisfies(v, spec) for v in ('1.4.0', '1.4.9-hotfix.2', '1.5.0', '1.3.9')]
            self.assertEqual(got, [True, True, False, False], spec)
        self.assertFalse(satisfies('1.4.1', '~1.4.2'))
        self.assertTrue(satisfies('1.4.7', '~1.4.2'))
        self.assertFalse(satisfies('1.5.0', '~1.4.2'))

    def test_caret_major_nonzero(self):
        self.assertTrue(satisfies('1.9.12', '^1.4.2'))
        self.assertTrue(satisfies('1.4.2', '^1.4.2'))
        self.assertFalse(satisfies('1.4.1', '^1.4.2'))
        self.assertFalse(satisfies('2.0.0', '^1.4.2'))

    def test_caret_major_zero(self):
        self.assertTrue(satisfies('0.4.9', '^0.4.2'))
        self.assertFalse(satisfies('0.5.0', '^0.4.2'))
        self.assertTrue(satisfies('0.0.9', '^0.0.3'))
        self.assertFalse(satisfies('0.1.0', '^0.0.3'))
        self.assertFalse(satisfies('0.0.2', '^0.0.3'))

    def test_bounds_keep_the_epoch(self):
        self.assertTrue(satisfies('1!2.5.0', '^1!2.0'))
        self.assertFalse(satisfies('1!2.1.0', '^2.0.0'))
        self.assertFalse(satisfies('1!1.4.3', '~1.4'))
        self.assertTrue(satisfies('1!1.0', '>=2.0'))


class PrereleaseTests(unittest.TestCase):
    def test_prereleases_excluded_by_default(self):
        self.assertFalse(satisfies('1.5.0-rc.1', '>=1.0'))
        self.assertFalse(satisfies('2.0.0-rc.1', '^1.4.0'))
        self.assertFalse(satisfies('1.5.0-dev', '~1.4'))
        self.assertFalse(satisfies('1.4.5-beta.1', '~1.4'))

    def test_prerelease_allowed_when_clause_names_same_release(self):
        self.assertTrue(satisfies('1.5.0-rc.1', '>=1.5.0-beta'))
        self.assertFalse(satisfies('1.6.0-alpha', '>=1.5.0-beta'))
        self.assertTrue(satisfies('1.6.0', '>=1.5.0-beta'))
        self.assertTrue(satisfies('1.4.0-rc.2', '^1.4.0-rc.1'))
        self.assertFalse(satisfies('1.4.0-beta.9', '^1.4.0-rc.1'))

    def test_prerelease_match_requires_same_epoch(self):
        self.assertFalse(satisfies('1!1.5.0-rc.1', '>=1.5.0-beta'))

    def test_prerelease_on_upper_clause_counts(self):
        self.assertTrue(satisfies('2.0.0-beta.1', '>=1.0, <2.0.0-rc'))
        self.assertFalse(satisfies('2.0.0-rc.0', '>=1.0, <2.0.0-rc'))

    def test_hotfix_is_not_a_prerelease(self):
        self.assertTrue(satisfies('1.4.3-hotfix.1', '^1.4.0'))
        self.assertTrue(satisfies('1.9.9-hotfix.1', '<2.0'))


class MaxSatisfyingTests(unittest.TestCase):
    def test_returns_highest_original_string(self):
        tags = ['v1.4.0', '1.4.3', '1.5.0-rc.2', '1.9.1+build.5', '2.0.0-rc.1', '2.0.0', 'junk', '1.9.1-hotfix']
        self.assertEqual(max_satisfying(tags, '^1.4.0'), '1.9.1-hotfix')
        self.assertEqual(max_satisfying(tags, '~1.4'), '1.4.3')
        self.assertEqual(max_satisfying(tags, '>=1.5.0-rc'), '2.0.0')
        self.assertEqual(max_satisfying(tags, '>=1.5.0-rc, <1.6'), '1.5.0-rc.2')

    def test_tie_goes_to_first_in_input(self):
        tags = ['1.2.0+b1', 'v1.2', '1.2.0+b9', '1.1.0']
        self.assertEqual(max_satisfying(tags, '>=1.0'), '1.2.0+b1')
        self.assertEqual(max_satisfying(list(reversed(tags)), '>=1.0'), '1.2.0+b9')

    def test_none_when_nothing_matches_and_invalid_tags_ignored(self):
        self.assertIsNone(max_satisfying(['0.9.0', 'nope', '3.0-alpha'], '>=1.0'))
        self.assertIsNone(max_satisfying([], '>=1.0'))

    def test_invalid_spec_raises_even_for_empty_list(self):
        with self.assertRaises(InvalidConstraint):
            max_satisfying([], '>=1.0,,')


if __name__ == '__main__':
    unittest.main()
