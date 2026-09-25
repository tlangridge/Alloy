import unittest

from pinwheel import Constraint, InvalidConstraint, Registry, ResolutionError, install_order, resolve
from pinwheel.install import plan


class ConstraintTests(unittest.TestCase):
    def test_caret_and_ranges(self):
        c = Constraint.parse('^1.4')
        self.assertTrue(c.allows('1.4.0'))
        self.assertTrue(c.allows('1.9.9'))
        self.assertFalse(c.allows('2.0.0'))
        self.assertFalse(c.allows('1.3.9'))
        self.assertTrue(Constraint.parse('>=1.2, <2 || 3.*').allows('3.5.0'))

    def test_invalid(self):
        with self.assertRaises(InvalidConstraint):
            Constraint.parse('>>1')


class ResolveTests(unittest.TestCase):
    def test_readme_example(self):
        reg = Registry()
        reg.add('web', '2.1.0', {'http': '^1.4', 'log': '~0.3'})
        reg.add('http', '1.4.2', {'log': '>=0.3'})
        reg.add('log', '0.3.9')
        self.assertEqual(plan(reg, {'web': '^2'}), ['log==0.3.9', 'http==1.4.2', 'web==2.1.0'])

    def test_highest_compatible(self):
        reg = Registry()
        for v in ('1.0.0', '1.2.0', '2.0.0'):
            reg.add('lib', v)
        self.assertEqual(resolve(reg, {'lib': '^1'}), {'lib': '1.2.0'})

    def test_conflict(self):
        reg = Registry()
        reg.add('a', '1.0.0', {'c': '^1'})
        reg.add('b', '1.0.0', {'c': '^2'})
        reg.add('c', '1.0.0')
        reg.add('c', '2.0.0')
        with self.assertRaises(ResolutionError):
            resolve(reg, {'a': '*', 'b': '*'})

    def test_install_order(self):
        reg = Registry()
        reg.add('app', '1.0.0', {'db': '*', 'cache': '*'})
        reg.add('db', '1.0.0')
        reg.add('cache', '1.0.0')
        self.assertEqual(install_order(reg, {'app': '1.0.0', 'db': '1.0.0', 'cache': '1.0.0'}),
                         ['cache', 'db', 'app'])


if __name__ == '__main__':
    unittest.main()
