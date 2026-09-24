import unittest

from inventory.search import search

from fixtures import catalogue


def skus(rows):
    return [r['sku'] for r in rows]


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.conn = catalogue()

    def test_all_products_sorted_by_sku(self):
        self.assertEqual(skus(search(self.conn)),
                         ['DRL-100', 'DRL-200', 'GLV-001', 'GLV-002', 'SAW-010', 'TAP-050'])

    def test_text_matches_name_or_sku_case_insensitively(self):
        self.assertEqual(skus(search(self.conn, 'DRILL')), ['DRL-100', 'DRL-200'])
        self.assertEqual(skus(search(self.conn, 'glv')), ['GLV-001', 'GLV-002'])

    def test_like_wildcards_are_literal(self):
        self.assertEqual(skus(search(self.conn, '100%')), ['GLV-002'])
        self.assertEqual(skus(search(self.conn, 't_pe')), [])
        self.assertEqual(skus(search(self.conn, 'duct_')), ['TAP-050'])

    def test_limit(self):
        self.assertEqual(len(search(self.conn, limit=2)), 2)
        for bad in (0, 501, '5', True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    search(self.conn, limit=bad)

    def test_rows_do_not_expose_cost(self):
        self.assertNotIn('cost_cents', search(self.conn)[0])


if __name__ == '__main__':
    unittest.main()
