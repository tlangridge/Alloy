import unittest

from termtext.layout import pad, wrap


class LayoutSmokeTests(unittest.TestCase):
    def test_wrap_ascii(self):
        self.assertEqual(wrap('the quick brown fox', 10), ['the quick', 'brown fox'])

    def test_pad_ascii(self):
        self.assertEqual(pad('ab', 5), 'ab   ')
        self.assertEqual(pad('ab', 5, 'right'), '   ab')


if __name__ == '__main__':
    unittest.main()
