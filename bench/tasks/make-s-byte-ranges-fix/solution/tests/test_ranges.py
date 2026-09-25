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

    def test_regression_chunk_spanning_several_ranges(self):
        received = ByteRanges()
        for start, end in [(0, 10), (20, 30), (40, 42), (5, 45)]:
            received.add(start, end)
        self.assertEqual(received.ranges(), [(0, 45)])
        self.assertEqual(received.covered(), 45)
        self.assertEqual(received.missing(50), [(45, 50)])

    def test_regression_end_offset_not_contained(self):
        received = ByteRanges()
        received.add(0, 10)
        self.assertIn(9, received)
        self.assertNotIn(10, received)

    def test_touching_following_range_merges(self):
        received = ByteRanges()
        received.add(10, 20)
        received.add(0, 10)
        self.assertEqual(received.ranges(), [(0, 20)])


if __name__ == '__main__':
    unittest.main()
