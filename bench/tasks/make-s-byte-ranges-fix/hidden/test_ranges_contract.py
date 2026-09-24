import random
import unittest

from fetchkit.ranges import ByteRanges


def build(*pairs):
    received = ByteRanges()
    for start, end in pairs:
        received.add(start, end)
    return received


def minimal(covered_bytes):
    out = []
    for b in sorted(covered_bytes):
        if out and out[-1][1] == b:
            out[-1][1] = b + 1
        else:
            out.append([b, b + 1])
    return [tuple(r) for r in out]


class AddValidationTests(unittest.TestCase):
    def test_invalid_ranges_rejected(self):
        for start, end in ((-1, 5), (10, 5), (-3, -1)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                ByteRanges().add(start, end)

    def test_empty_range_is_noop(self):
        received = build((5, 5), (0, 0))
        self.assertEqual(received.ranges(), [])
        received.add(10, 20)
        received.add(20, 20)
        self.assertEqual(received.ranges(), [(10, 20)])


class MergeTests(unittest.TestCase):
    def test_reported_case(self):
        received = build((0, 10), (20, 30), (40, 42), (5, 45))
        self.assertEqual(received.ranges(), [(0, 45)])
        self.assertEqual(received.covered(), 45)
        self.assertEqual(received.missing(50), [(45, 50)])

    def test_span_many_ranges_from_before_first(self):
        received = build((10, 20), (30, 40), (50, 60), (70, 80), (90, 100), (0, 95))
        self.assertEqual(received.ranges(), [(0, 100)])
        self.assertEqual(received.covered(), 100)

    def test_span_many_ranges_stopping_in_gap(self):
        received = build((10, 20), (30, 40), (50, 60), (70, 80), (15, 65))
        self.assertEqual(received.ranges(), [(10, 65), (70, 80)])
        self.assertEqual(received.covered(), 65)

    def test_touching_following_range(self):
        self.assertEqual(build((10, 20), (0, 10)).ranges(), [(0, 20)])

    def test_touching_previous_range(self):
        self.assertEqual(build((0, 10), (10, 20)).ranges(), [(0, 20)])

    def test_bridging_range_touching_both_sides(self):
        received = build((0, 10), (20, 30), (10, 20))
        self.assertEqual(received.ranges(), [(0, 30)])
        self.assertEqual(received.covered(), 30)

    def test_touching_chain_added_backwards(self):
        received = build((40, 50), (30, 40), (20, 30), (10, 20), (0, 10))
        self.assertEqual(received.ranges(), [(0, 50)])

    def test_new_range_ends_where_several_touch(self):
        received = build((20, 30), (30, 40), (0, 20))
        self.assertEqual(received.ranges(), [(0, 40)])

    def test_contained_range_is_absorbed(self):
        received = build((0, 100), (10, 20), (0, 100), (99, 100))
        self.assertEqual(received.ranges(), [(0, 100)])
        self.assertEqual(received.covered(), 100)

    def test_same_start(self):
        self.assertEqual(build((10, 20), (10, 30)).ranges(), [(10, 30)])
        self.assertEqual(build((10, 30), (10, 20)).ranges(), [(10, 30)])

    def test_gap_of_one_byte_is_kept(self):
        self.assertEqual(build((0, 10), (11, 20)).ranges(), [(0, 10), (11, 20)])

    def test_ranges_returns_tuples_sorted(self):
        received = build((50, 60), (0, 5), (20, 25))
        self.assertEqual(received.ranges(), [(0, 5), (20, 25), (50, 60)])

    def test_randomized_against_model(self):
        rng = random.Random(20260101)
        for _ in range(60):
            received = ByteRanges()
            model = set()
            for _ in range(rng.randint(1, 25)):
                start = rng.randint(0, 120)
                end = start + rng.choice([0, 1, 1, 2, 3, 5, 8, 13, 30, 70])
                received.add(start, end)
                model.update(range(start, end))
                self.assertEqual(received.ranges(), minimal(model))
                self.assertEqual(received.covered(), len(model))
            for offset in range(-2, 200):
                self.assertEqual(offset in received, offset in model, offset)


class ContainsTests(unittest.TestCase):
    def test_half_open_membership(self):
        received = build((0, 10), (20, 30))
        for offset in (0, 5, 9, 20, 29):
            self.assertIn(offset, received)
        for offset in (-1, 10, 15, 19, 30, 31):
            self.assertNotIn(offset, received)

    def test_empty(self):
        self.assertNotIn(0, ByteRanges())


class MissingTests(unittest.TestCase):
    def test_gaps(self):
        received = build((10, 20), (30, 40))
        self.assertEqual(received.missing(50), [(0, 10), (20, 30), (40, 50)])

    def test_nothing_received(self):
        self.assertEqual(ByteRanges().missing(7), [(0, 7)])

    def test_bytes_beyond_size_ignored(self):
        received = build((0, 10), (20, 200))
        self.assertEqual(received.missing(100), [(10, 20)])
        received = build((0, 10), (150, 200))
        self.assertEqual(received.missing(100), [(10, 100)])

    def test_after_out_of_order_touching_adds(self):
        received = build((30, 40), (10, 20), (20, 30), (0, 10))
        self.assertEqual(received.missing(50), [(40, 50)])
        self.assertFalse(received.is_complete(50))
        received.add(40, 50)
        self.assertTrue(received.is_complete(50))
        self.assertEqual(received.missing(50), [])

    def test_is_complete_ignores_extra_bytes(self):
        self.assertTrue(build((0, 120)).is_complete(100))
        self.assertFalse(build((1, 120)).is_complete(100))


if __name__ == '__main__':
    unittest.main()
