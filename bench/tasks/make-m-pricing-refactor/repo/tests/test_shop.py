import unittest
from decimal import Decimal as D

from shop.cart import Cart
from shop.inventory import OutOfStock
from shop.pos import Receipt
from shop.quote import Quote
from tests.fixtures import GOLD, SILVER, STANDARD, setup


class CartTests(unittest.TestCase):
    def test_prices(self):
        catalog, inv = setup()
        cart = Cart(catalog, inv, GOLD)
        cart.add('MUG', 50)
        cart.add('TEA', 3)
        self.assertEqual(cart.lines(), [('MUG', 50, D('17.47'), D('873.50')), ('TEA', 3, D('1.19'), D('3.57'))])

    def test_stock_check(self):
        catalog, inv = setup()
        cart = Cart(catalog, inv, STANDARD)
        cart.add('MUG', 400)
        with self.assertRaises(OutOfStock):
            cart.add('MUG', 101)


class QuoteTests(unittest.TestCase):
    def test_override_and_floor(self):
        catalog, inv = setup()
        q = Quote(catalog, inv, SILVER, 'Q-1')
        self.assertEqual(q.add('LAMP', 5), D('11.00'))
        self.assertEqual(q.add('MUG', 10, override='9.00'), D('9.00'))
        self.assertEqual(q.add('MUG', 10, override='5.00'), D('6.71'))


class ReceiptTests(unittest.TestCase):
    def test_walk_in(self):
        catalog, inv = setup()
        r = Receipt(catalog, inv)
        r.scan('TEA', 6)
        r.scan('TEA', 4)
        self.assertEqual(r.lines(), [('TEA', 10, D('1.20'), D('12.00'))])
        self.assertEqual(r.checkout(), D('12.00'))
        self.assertEqual(inv.on_hand('TEA'), 490)


if __name__ == '__main__':
    unittest.main()
