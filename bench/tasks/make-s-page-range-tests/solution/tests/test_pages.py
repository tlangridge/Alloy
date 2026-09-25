import unittest

from printq import parse_page_ranges


class ItemsAndWhitespaceTests(unittest.TestCase):  # B1
    def test_spec_example(self):
        self.assertEqual(parse_page_ranges('1 - 3, 5', 10), [1, 2, 3, 5])

    def test_whitespace_variants(self):
        self.assertEqual(parse_page_ranges('  2 ,4-5 ', 10), [2, 4, 5])
        self.assertEqual(parse_page_ranges('1 -2', 10), [1, 2])
        self.assertEqual(parse_page_ranges('8 -', 10), [8, 9, 10])
        self.assertEqual(parse_page_ranges('- 2', 10), [1, 2])


class PagesAndRangesTests(unittest.TestCase):  # B2
    def test_single_page(self):
        self.assertEqual(parse_page_ranges('7', 10), [7])

    def test_inclusive_range(self):
        self.assertEqual(parse_page_ranges('2-4', 10), [2, 3, 4])
        self.assertEqual(parse_page_ranges('4-4', 10), [4])
        self.assertEqual(parse_page_ranges('1-10', 10), list(range(1, 11)))

    def test_returns_list_of_int(self):
        result = parse_page_ranges('1,3', 5)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [1, 3])


class OpenEndedTests(unittest.TestCase):  # B3
    def test_open_end(self):
        self.assertEqual(parse_page_ranges('8-', 10), [8, 9, 10])
        self.assertEqual(parse_page_ranges('10-', 10), [10])

    def test_open_start(self):
        self.assertEqual(parse_page_ranges('-3', 10), [1, 2, 3])
        self.assertEqual(parse_page_ranges('-1', 10), [1])


class SortedUniqueTests(unittest.TestCase):  # B4
    def test_spec_example(self):
        self.assertEqual(parse_page_ranges('5, 1-3, 2', 10), [1, 2, 3, 5])

    def test_unsorted_input_is_sorted(self):
        self.assertEqual(parse_page_ranges('9,1', 10), [1, 9])

    def test_overlapping_ranges_deduplicated(self):
        self.assertEqual(parse_page_ranges('1-4,3-6,6', 10), [1, 2, 3, 4, 5, 6])


class ReversedTests(unittest.TestCase):  # B5
    def test_reversed_range_rejected(self):
        with self.assertRaises(ValueError):
            parse_page_ranges('5-3', 10)


class BoundsTests(unittest.TestCase):  # B6
    def test_out_of_range(self):
        for spec in ('0', '0-2', '11', '8-20', '11-'):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_page_ranges(spec, 10)

    def test_last_page_allowed(self):
        self.assertEqual(parse_page_ranges('10', 10), [10])


class EmptyInputTests(unittest.TestCase):  # B7
    def test_empty_spec_selects_all(self):
        self.assertEqual(parse_page_ranges('', 3), [1, 2, 3])
        self.assertEqual(parse_page_ranges('   ', 3), [1, 2, 3])

    def test_empty_items_rejected(self):
        for spec in ('1,,3', '1,2,', ',1', '1, ,2'):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_page_ranges(spec, 10)


class MalformedTests(unittest.TestCase):  # B8
    def test_malformed_items(self):
        for spec in ('a', '1-2-3', '-', '1.5', '+2', '2x', '1--3'):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_page_ranges(spec, 10)


class EmptyDocumentTests(unittest.TestCase):  # B9
    def test_page_count_below_one(self):
        for spec, count in (('', 0), ('  ', 0), ('1', 0), ('', -1)):
            with self.subTest(spec=spec, count=count), self.assertRaises(ValueError):
                parse_page_ranges(spec, count)


if __name__ == '__main__':
    unittest.main()
