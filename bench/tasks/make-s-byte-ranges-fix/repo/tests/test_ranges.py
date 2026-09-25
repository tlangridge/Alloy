import unittest

from fetchkit.ranges import ByteRanges


class ByteRangesTests(unittest.TestCase):
    def test_disjoint_ranges(self):
        received = ByteRanges()
        received.add(0, 100)
        received.add(200, 300)
        self.assertEqual(received.ranges(), [(0, 100), (200, 300)])
        self.assertEqual(received.covered(), 200)
        self.assertEqual(received.missing(300), [(100, 200)])

    def test_overlap_with_previous_range_merges(self):
        received = ByteRanges()
        received.add(0, 100)
        received.add(50, 150)
        self.assertEqual(received.ranges(), [(0, 150)])

    def test_complete(self):
        received = ByteRanges()
        received.add(0, 60)
        received.add(60, 100)
        self.assertTrue(received.is_complete(100))
        self.assertFalse(received.is_complete(101))

    def test_invalid_range(self):
        with self.assertRaises(ValueError):
            ByteRanges().add(10, 5)


if __name__ == '__main__':
    unittest.main()
