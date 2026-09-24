import unittest

from pinwheel import (Constraint, CycleError, InvalidConstraint, Registry, ResolutionError, UnknownPackage, Version,
                      install_order, resolve)
from pinwheel.install import plan


def registry(releases):
    """releases: list of (name, version, deps dict, yanked=False)."""
    reg = Registry()
    for entry in releases:
        name, version, deps = entry[:3]
        yanked = entry[3] if len(entry) > 3 else False
        reg.add(name, version, deps, yanked=yanked)
    return reg


class ConstraintTests(unittest.TestCase):
    def check(self, text, allowed, denied):
        c = Constraint.parse(text)
        for v in allowed:
            self.assertTrue(c.allows(v), '%s should allow %s' % (text, v))
        for v in denied:
            self.assertFalse(c.allows(v), '%s should deny %s' % (text, v))

    def test_caret(self):
        self.check('^1.2.3', ['1.2.3', '1.9.0'], ['1.2.2', '2.0.0'])
        self.check('^0.2.3', ['0.2.3', '0.2.9'], ['0.3.0', '0.2.2'])
        self.check('^0.0.3', ['0.0.3'], ['0.0.4', '0.0.2', '0.1.0'])
        self.check('^1.2', ['1.2.0', '1.99.99'], ['1.1.9', '2.0.0'])
        self.check('^0.2', ['0.2.0', '0.2.7'], ['0.3.0'])
        self.check('^0.0', ['0.0.0', '0.0.9'], ['0.1.0'])
        self.check('^0', ['0.0.0', '0.9.9'], ['1.0.0'])
        self.check('^ 1', ['1.0.0', '1.5.0'], ['2.0.0', '0.9.9'])

    def test_tilde(self):
        self.check('~1.2.3', ['1.2.3', '1.2.9'], ['1.3.0', '1.2.2'])
        self.check('~1.2', ['1.2.0', '1.2.9'], ['1.3.0'])
        self.check('~1', ['1.0.0', '1.9.0'], ['2.0.0'])
        self.check('~0.2.3', ['0.2.3'], ['0.3.0'])

    def test_wildcards_and_partial_equality(self):
        self.check('*', ['0.0.0', '9.9.9'], [])
        self.check('1.*', ['1.0.0', '1.9.9'], ['0.9.9', '2.0.0'])
        self.check('1.2.*', ['1.2.0', '1.2.9'], ['1.3.0', '1.1.9'])
        self.check('1.2', ['1.2.0', '1.2.7'], ['1.3.0'])
        self.check('=1', ['1.0.0', '1.4.0'], ['2.0.0'])
        self.check('1.2.3', ['1.2.3'], ['1.2.4'])
        self.check('= 1.2.3', ['1.2.3'], ['1.2.2'])

    def test_comparisons_with_partials(self):
        self.check('>1.2', ['1.3.0'], ['1.2.9', '1.2.0'])
        self.check('>1', ['2.0.0'], ['1.9.9'])
        self.check('>1.2.3', ['1.2.4'], ['1.2.3'])
        self.check('<=1.2', ['1.2.9', '1.0.0'], ['1.3.0'])
        self.check('<=1.2.3', ['1.2.3'], ['1.2.4'])
        self.check('<2', ['1.9.9'], ['2.0.0'])
        self.check('<1.2', ['1.1.9'], ['1.2.0'])
        self.check('>=1.2', ['1.2.0'], ['1.1.9'])

    def test_not_equal(self):
        self.check('!=1.2', ['1.1.9', '1.3.0'], ['1.2.0', '1.2.5'])
        self.check('!=1.2.3', ['1.2.4'], ['1.2.3'])
        self.check('>=1, !=1.4, !=1.6.1', ['1.5.0', '1.6.0', '1.7.0'], ['1.4.2', '1.6.1', '0.9.0'])

    def test_groups_and_whitespace(self):
        self.check(' >= 1.2 , < 2 || ^3.1 ', ['1.2.0', '1.9.9', '3.1.0', '3.9.0'], ['2.0.0', '3.0.9', '4.0.0'])
        self.check('<1 || >=2, <3 || 5.*', ['0.5.0', '2.5.0', '5.1.0'], ['1.0.0', '3.0.0', '6.0.0'])

    def test_invalid_constraints(self):
        for text in ['', '  ', '>>1', '=>1', '==1', '>=1.*', '^*', '~*', '1.*.3', '1.2.3.4', '01.2', 'v1.2.3',
                     '1.2 ||', ',1.0', '>=1,,<2', '^1.02', '1.x', '<', '>= ', '*.*', '!=1.4.*']:
            with self.assertRaises(InvalidConstraint, msg=text):
                Constraint.parse(text)

    def test_allows_version_objects(self):
        self.assertTrue(Constraint.parse('^2').allows(Version(2, 3, 4)))
        self.assertFalse(Constraint.parse('^2').allows(Version.parse('3.0.0')))


class ResolveTests(unittest.TestCase):
    def test_highest_version_satisfying_all_constraints(self):
        reg = registry([('a', '1.0.0', {'c': '>=1.2'}), ('b', '1.0.0', {'c': '<1.5'})] +
                       [('c', v, {}) for v in ('1.0.0', '1.2.0', '1.4.0', '1.5.0', '2.0.0')])
        self.assertEqual(resolve(reg, {'a': '*', 'b': '*'}), {'a': '1.0.0', 'b': '1.0.0', 'c': '1.4.0'})

    def test_backtracks_to_older_version(self):
        reg = registry([('a', '1.0.0', {'c': '^1.0'}), ('a', '2.0.0', {'c': '^2.0'}), ('b', '1.0.0', {'c': '^1.0'}),
                        ('c', '1.0.0', {}), ('c', '1.5.0', {}), ('c', '2.0.0', {})])
        self.assertEqual(resolve(reg, {'a': '*', 'b': '*'}), {'a': '1.0.0', 'b': '1.0.0', 'c': '1.5.0'})

    def test_fewest_candidates_first(self):
        reg = registry([('x', '1.0.0', {}), ('x', '2.0.0', {}), ('x', '3.0.0', {}),
                        ('y', '1.0.0', {}), ('y', '2.0.0', {'x': '<=2.0.0'})])
        self.assertEqual(resolve(reg, {'x': '*', 'y': '*'}), {'x': '2.0.0', 'y': '2.0.0'})

    def test_choice_recomputed_after_each_decision(self):
        reg = registry([('p', '1.0.0', {}), ('p', '2.0.0', {'r': '<2.0.0'}),
                        ('q', '1.0.0', {}), ('q', '2.0.0', {}), ('q', '3.0.0', {}),
                        ('r', '1.0.0', {}), ('r', '1.5.0', {'q': '<3'}), ('r', '3.0.0', {})])
        self.assertEqual(resolve(reg, {'p': '*', 'q': '*', 'r': '*'}), {'p': '2.0.0', 'q': '2.0.0', 'r': '1.5.0'})

    def test_ties_break_alphabetically(self):
        reg = registry([('m', '1.0.0', {}), ('m', '2.0.0', {'n': '<2'}),
                        ('n', '1.0.0', {}), ('n', '2.0.0', {'m': '<2'})])
        self.assertEqual(resolve(reg, {'n': '*', 'm': '*'}), {'m': '2.0.0', 'n': '1.0.0'})

    def test_deep_backtracking_leaves_no_undone_packages(self):
        # lib 2.0.0 is decided first, then core 2.0.0 and extra; util then fails, so all three are undone.
        reg = registry([('lib', '1.0.0', {'core': '^1'}), ('lib', '2.0.0', {'core': '^2', 'extra': '*'}),
                        ('util', '1.0.0', {'core': '~1.1'}), ('util', '1.1.0', {'core': '~1.1'}),
                        ('util', '1.2.0', {'core': '~1.1'}), ('extra', '1.0.0', {}),
                        ('core', '1.1.5', {}), ('core', '2.0.0', {})])
        self.assertEqual(resolve(reg, {'lib': '*', 'util': '*'}),
                         {'lib': '1.0.0', 'util': '1.2.0', 'core': '1.1.5'})

    def test_unsatisfiable(self):
        reg = registry([('a', '1.0.0', {'c': '^1'}), ('a', '1.1.0', {'c': '^1'}), ('b', '1.0.0', {'c': '^2'}),
                        ('c', '1.0.0', {}), ('c', '2.0.0', {})])
        with self.assertRaises(ResolutionError):
            resolve(reg, {'a': '*', 'b': '*'})
        with self.assertRaises(ResolutionError):
            resolve(reg, {'a': '>=5'})

    def test_unknown_root_package(self):
        reg = registry([('a', '1.0.0', {})])
        with self.assertRaises(UnknownPackage) as ctx:
            resolve(reg, {'zeta': '*', 'a': '*', 'beta': '^1'})
        self.assertEqual(ctx.exception.name, 'beta')
        self.assertIsInstance(ctx.exception, ResolutionError)

    def test_unknown_dependency_forces_backtrack(self):
        reg = registry([('a', '1.0.0', {'b': '*'}), ('a', '2.0.0', {'ghost': '^1'}), ('b', '1.0.0', {})])
        self.assertEqual(resolve(reg, {'a': '*'}), {'a': '1.0.0', 'b': '1.0.0'})

    def test_invalid_root_constraint(self):
        reg = registry([('a', '1.0.0', {})])
        with self.assertRaises(InvalidConstraint):
            resolve(reg, {'a': '>>1'})

    def test_yanked_versions_skipped_unless_locked(self):
        reg = registry([('c', '1.4.0', {}), ('c', '1.5.0', {}, True), ('c', '2.0.0', {})])
        self.assertEqual(resolve(reg, {'c': '^1'}), {'c': '1.4.0'})
        self.assertEqual(resolve(reg, {'c': '^1'}, locked={'c': '1.5.0'}), {'c': '1.5.0'})
        with self.assertRaises(ResolutionError):
            resolve(reg, {'c': '1.5.0'})

    def test_locked_version_preferred_when_allowed(self):
        reg = registry([('b', v, {}) for v in ('1.0.0', '1.2.0', '1.3.0', '2.0.0')])
        self.assertEqual(resolve(reg, {'b': '^1'}, locked={'b': '1.2.0'}), {'b': '1.2.0'})
        self.assertEqual(resolve(reg, {'b': '^1'}, locked={'b': '2.0.0'}), {'b': '1.3.0'})
        self.assertEqual(resolve(reg, {'b': '^1'}, locked={'b': '1.9.0'}), {'b': '1.3.0'})

    def test_locked_version_falls_back_when_it_conflicts(self):
        reg = registry([('a', '1.0.0', {'b': '>=1.3'}), ('b', '1.0.0', {}), ('b', '1.2.0', {}), ('b', '1.3.0', {}),
                        ('b', '1.4.0', {})])
        self.assertEqual(resolve(reg, {'a': '*', 'b': '*'}, locked={'b': '1.2.0', 'zzz': '1.0.0'}),
                         {'a': '1.0.0', 'b': '1.4.0'})
        self.assertEqual(resolve(reg, {'b': '*'}, locked={'b': '1.2.0', 'a': '1.0.0'}), {'b': '1.2.0'})

    def test_locked_counts_as_candidate_for_choice(self):
        # 'k' has one non-yanked candidate plus its locked yanked release -> two candidates;
        # 'j' has two as well, so the alphabetical tie-break decides j first.
        reg = registry([('j', '1.0.0', {}), ('j', '2.0.0', {'k': '<1.5'}),
                        ('k', '1.0.0', {}), ('k', '1.9.0', {'j': '<2'}, True)])
        self.assertEqual(resolve(reg, {'j': '*', 'k': '*'}, locked={'k': '1.9.0'}), {'j': '2.0.0', 'k': '1.0.0'})

    def test_candidate_inconsistent_with_decided_package_is_skipped(self):
        reg = registry([('a', '1.0.0', {'c': '^1'}), ('a', '2.0.0', {'d': '*', 'c': '^2'}),
                        ('b', '1.0.0', {'c': '^1'}), ('c', '1.0.0', {}), ('c', '2.0.0', {}), ('d', '1.0.0', {})])
        self.assertEqual(resolve(reg, {'a': '*', 'b': '*'}), {'a': '1.0.0', 'b': '1.0.0', 'c': '1.0.0'})

    def test_self_dependency(self):
        reg = registry([('x', '1.0.0', {'x': '*'}), ('x', '2.0.0', {'x': '<2'})])
        self.assertEqual(resolve(reg, {'x': '*'}), {'x': '1.0.0'})

    def test_independent_of_insertion_and_requirement_order(self):
        releases = [('m', '1.0.0', {}), ('m', '2.0.0', {'n': '<2'}), ('n', '1.0.0', {}),
                    ('n', '2.0.0', {'m': '<2'}), ('o', '1.0.0', {'m': '*'})]
        forward = resolve(registry(releases), {'m': '*', 'n': '*', 'o': '*'})
        backward = resolve(registry(list(reversed(releases))), {'o': '*', 'n': '*', 'm': '*'})
        self.assertEqual(forward, backward)
        self.assertEqual(forward, {'m': '2.0.0', 'n': '1.0.0', 'o': '1.0.0'})

    def test_plan_integration(self):
        reg = registry([('web', '2.1.0', {'http': '^1.4', 'log': '~0.3'}), ('web', '2.2.0', {'http': '^2'}),
                        ('http', '1.4.2', {'log': '>=0.3'}), ('http', '2.0.0', {'log': '^1'}),
                        ('log', '0.3.9', {}), ('log', '0.4.0', {})])
        self.assertEqual(plan(reg, {'web': '^2'}), ['log==0.3.9', 'http==1.4.2', 'web==2.1.0'])


class InstallOrderTests(unittest.TestCase):
    def test_dependencies_first_alphabetical_ties(self):
        reg = registry([('a', '1.0.0', {'b': '*', 'c': '*'}), ('b', '1.0.0', {'d': '*'}), ('c', '1.0.0', {}),
                        ('d', '1.0.0', {}), ('e', '1.0.0', {'a': '*'})])
        resolution = {n: '1.0.0' for n in 'abcde'}
        self.assertEqual(install_order(reg, resolution), ['c', 'd', 'b', 'a', 'e'])

    def test_uses_dependencies_of_the_resolved_version(self):
        reg = registry([('a', '1.0.0', {'b': '*'}), ('a', '2.0.0', {}), ('b', '1.0.0', {'z': '*'}),
                        ('z', '1.0.0', {})])
        self.assertEqual(install_order(reg, {'a': '2.0.0', 'b': '1.0.0', 'z': '1.0.0'}), ['a', 'z', 'b'])
        self.assertEqual(install_order(reg, {'a': '1.0.0', 'b': '1.0.0'}), ['b', 'a'])

    def test_cycle_members(self):
        reg = registry([('a', '1.0.0', {'b': '*'}), ('b', '1.0.0', {'a': '*'}), ('c', '1.0.0', {'a': '*'}),
                        ('d', '1.0.0', {'d': '*'}), ('e', '1.0.0', {})])
        with self.assertRaises(CycleError) as ctx:
            install_order(reg, {n: '1.0.0' for n in 'abcde'})
        self.assertEqual(ctx.exception.members, ['a', 'b', 'd'])

    def test_long_cycle_and_dependents(self):
        reg = registry([('x', '1.0.0', {'y': '*'}), ('y', '1.0.0', {'z': '*'}), ('z', '1.0.0', {'x': '*'}),
                        ('w', '1.0.0', {'x': '*'}), ('v', '1.0.0', {}), ('z', '2.0.0', {})])
        with self.assertRaises(CycleError) as ctx:
            install_order(reg, {'x': '1.0.0', 'y': '1.0.0', 'z': '1.0.0', 'w': '1.0.0', 'v': '1.0.0'})
        self.assertEqual(ctx.exception.members, ['x', 'y', 'z'])
        self.assertEqual(install_order(reg, {'x': '1.0.0', 'y': '1.0.0', 'z': '2.0.0', 'w': '1.0.0', 'v': '1.0.0'}),
                         ['v', 'z', 'y', 'x', 'w'])

    def test_resolve_accepts_cycles(self):
        reg = registry([('a', '1.0.0', {'b': '*'}), ('b', '1.0.0', {'a': '^1'})])
        resolution = resolve(reg, {'a': '*'})
        self.assertEqual(resolution, {'a': '1.0.0', 'b': '1.0.0'})
        with self.assertRaises(CycleError) as ctx:
            install_order(reg, resolution)
        self.assertEqual(ctx.exception.members, ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
