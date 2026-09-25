import unittest

from printq import parse_page_ranges


class ParsePageRangesTests(unittest.TestCase):
    def test_simple_range(self):
        self.assertEqual(parse_page_ranges('1-3', 10), [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
