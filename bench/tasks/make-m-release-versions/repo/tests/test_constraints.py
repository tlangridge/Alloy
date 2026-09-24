import unittest

from fwver.constraints import satisfies


class ConstraintSmokeTests(unittest.TestCase):
    def test_range(self):
        self.assertTrue(satisfies('1.4.2', '>=1.4, <2.0'))
        self.assertFalse(satisfies('2.0.0', '>=1.4, <2.0'))
        self.assertFalse(satisfies('1.3.9', '>=1.4, <2.0'))


if __name__ == '__main__':
    unittest.main()
