import unittest

import tagstats


class TagStatsTests(unittest.TestCase):
    def test_extract_is_case_insensitive(self):
        self.assertEqual(tagstats.extract_tags('Hello #World and #world_2'), ['world', 'world_2'])

    def test_count(self):
        counts = tagstats.count_tags(['#a #b', '#A', 'no tags here'])
        self.assertEqual(counts['a'], 2)
        self.assertEqual(counts['b'], 1)

    def test_format_row(self):
        self.assertEqual(tagstats.format_row(1, 'perf', 4), '1. #perf (4)')


if __name__ == '__main__':
    unittest.main()
