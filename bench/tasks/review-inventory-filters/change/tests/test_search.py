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



class FilterTests(unittest.TestCase):
    def setUp(self):
        self.conn = catalogue()

    def test_bare_column_equality(self):
        self.assertEqual(skus(search(self.conn, filters={'brand': 'Bosch'})), ['DRL-200', 'GLV-002'])

    def test_qualified_column_equality(self):
        self.assertEqual(skus(search(self.conn, filters={'products.status': 'hidden'})), ['TAP-050'])

    def test_membership_on_joined_table(self):
        self.assertEqual(skus(search(self.conn, filters={'stock.warehouse': ['east', 'south']})),
                         ['DRL-100', 'DRL-200', 'GLV-001'])
        self.assertEqual(skus(search(self.conn, filters={'warehouse': ('north',)})),
                         ['DRL-100', 'SAW-010', 'TAP-050'])

    def test_empty_membership_matches_nothing(self):
        self.assertEqual(search(self.conn, filters={'brand': []}), [])

    def test_filters_combine_with_text_and_each_other(self):
        rows = search(self.conn, 'drill', filters={'category': 'tools', 'stock.warehouse': {'north'}})
        self.assertEqual(skus(rows), ['DRL-100'])

    def test_values_are_bound_not_interpolated(self):
        self.assertEqual(skus(search(self.conn, filters={'brand': "O'Neil"})), ['GLV-001'])
        self.assertEqual(search(self.conn, filters={'brand': "x' OR '1'='1"}), [])

    def test_unknown_or_internal_column_rejected(self):
        for key in ('cost_cents', 'products.cost_cents', 'price', 'brand; DROP TABLE products'):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    search(self.conn, filters={key: 1})


if __name__ == '__main__':
    unittest.main()
