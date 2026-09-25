import unittest

from inventory.db import add_product, connect
from inventory.search import search


def catalogue():
    conn = connect()
    add_product(conn, 'DRL-100', 'Cordless drill', 'Makita', 'tools', 4200, stock={'north': 5})
    add_product(conn, 'DRL-200', 'Hammer drill', 'Bosch', 'tools', 6100, stock={'south': 2})
    add_product(conn, 'TAP-050', 'Duct tape', 'Stanley', 'consumables', 150, status='hidden')
    return conn


class QualifiedFilterKeyTests(unittest.TestCase):
    """The table part of a qualified key must be validated too."""

    def setUp(self):
        self.conn = catalogue()

    def assertRejected(self, key, value='x'):
        with self.assertRaises(ValueError):
            search(self.conn, filters={key: value})

    def test_sql_in_table_part_is_rejected(self):
        self.assertRejected('1=1 OR products.brand', 'nope')

    def test_sql_in_table_part_cannot_probe_internal_cost(self):
        self.assertRejected('products.cost_cents > 5000 OR products.brand', 'nope')

    def test_sql_in_table_part_with_membership_value(self):
        self.assertRejected("products.status != 'hidden' OR products.status", ['x'])

    def test_column_qualified_with_wrong_table_is_rejected(self):
        self.assertRejected('stock.brand', 'Bosch')
        self.assertRejected('products.warehouse', 'north')

    def test_unknown_table_is_rejected(self):
        self.assertRejected('orders.status', 'active')

    def test_valid_qualified_keys_still_work(self):
        rows = search(self.conn, filters={'products.brand': 'Bosch', 'stock.warehouse': ['south']})
        self.assertEqual([r['sku'] for r in rows], ['DRL-200'])


if __name__ == '__main__':
    unittest.main()
