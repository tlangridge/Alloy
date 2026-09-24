import unittest
from decimal import Decimal as D, ROUND_CEILING, ROUND_HALF_UP
from unittest import mock

import shop.pricing as pricing
from shop.cart import Cart
from shop.catalog import Catalog, UnknownProduct, product
from shop.customers import Customer
from shop.inventory import Inventory, OutOfStock
from shop.pos import Receipt
from shop.quote import Quote

MUG = product('MUG', 'Mug', '19.99', '6.10')
TEA = product('TEA', 'Tea tin', '1.25', '0.40')
LAMP = product('LAMP', 'Desk lamp', '11.00', '10.00')
PEN = product('PEN', 'Pen', '3.50', '3.33')
BOX = product('BOX', 'Gift box', '7.45', '2.00')
PRODUCTS = [MUG, TEA, LAMP, PEN, BOX]
GOLD, SILVER, STANDARD = Customer('g', 'gold'), Customer('s', 'silver'), Customer('p', 'standard')
PLATINUM = Customer('x', 'platinum')


def world(stock=1000):
    inv = Inventory()
    for p in PRODUCTS:
        inv.receive(p.sku, stock)
    return Catalog(PRODUCTS), inv


def ref(prod, qty, customer=None, clearance=False, override=None,
        tiers=((100, D('0.12')), (50, D('0.08')), (10, D('0.04'))),
        members=None, floor=D('1.10'), markdown=D('0.30')):
    members = {'silver': D('0.02'), 'gold': D('0.05')} if members is None else members
    if override is not None:
        price = D(override)
    else:
        eligible = [t for t in tiers if qty >= t[0]]
        v = max(eligible)[1] if eligible else D(0)
        if clearance:
            v = max(v, markdown)
        m = members.get(customer.tier, D(0)) if customer is not None else D(0)
        price = prod.base_price * (1 - v) * (1 - m)
    price = price.quantize(D('0.01'), rounding=ROUND_HALF_UP)
    if not clearance:
        price = max(price, (prod.cost * floor).quantize(D('0.01'), rounding=ROUND_CEILING))
    return price


def channel_prices(sku, qty, customer, clearance=False):
    """Unit price for (sku, qty) as computed by cart, quote and till."""
    catalog, inv = world()
    inv.set_clearance(sku, clearance)
    cart = Cart(catalog, inv, customer or STANDARD)
    cart.add(sku, qty)
    quote = Quote(catalog, inv, customer or STANDARD, 'Q')
    quote.add(sku, qty)
    till = Receipt(catalog, inv, customer)
    till.scan(sku, qty)
    return cart.lines()[0][2], quote.lines()[0][2], till.lines()[0][2]


class PricingModuleTests(unittest.TestCase):
    def test_tables(self):
        self.assertEqual(list(pricing.VOLUME_TIERS), [(100, D('0.12')), (50, D('0.08')), (10, D('0.04'))])
        self.assertEqual(dict(pricing.MEMBER_DISCOUNTS), {'silver': D('0.02'), 'gold': D('0.05')})
        self.assertEqual(pricing.MARGIN_FLOOR, D('1.10'))
        self.assertEqual(pricing.CLEARANCE_MARKDOWN, D('0.30'))

    def test_volume_boundaries(self):
        got = [pricing.unit_price(MUG, q, STANDARD) for q in (9, 10, 49, 50, 99, 100, 250)]
        self.assertEqual(got, [D('19.99'), D('19.19'), D('19.19'), D('18.39'), D('18.39'), D('17.59'), D('17.59')])

    def test_member_after_volume_rounded_half_up(self):
        self.assertEqual(pricing.unit_price(TEA, 1, SILVER), D('1.23'))
        self.assertEqual(pricing.unit_price(MUG, 50, GOLD), D('17.47'))
        self.assertEqual(pricing.unit_price(MUG, 1), D('19.99'))
        self.assertEqual(pricing.unit_price(MUG, 1, None), D('19.99'))
        self.assertEqual(pricing.unit_price(MUG, 1, PLATINUM), D('19.99'))

    def test_margin_floor_rounds_up(self):
        self.assertEqual(pricing.unit_price(LAMP, 1, STANDARD), D('11.00'))
        self.assertEqual(pricing.unit_price(LAMP, 100, GOLD), D('11.00'))
        self.assertEqual(pricing.unit_price(PEN, 100, GOLD), D('3.67'))

    def test_override(self):
        self.assertEqual(pricing.unit_price(MUG, 500, GOLD, override='9.00'), D('9.00'))
        self.assertEqual(pricing.unit_price(MUG, 1, STANDARD, override='9.005'), D('9.01'))
        self.assertEqual(pricing.unit_price(MUG, 1, STANDARD, override='5'), D('6.71'))
        self.assertEqual(pricing.unit_price(MUG, 1, STANDARD, override=D('25.50')), D('25.50'))

    def test_clearance_bigger_discount_wins_and_member_applies(self):
        self.assertEqual(pricing.unit_price(MUG, 1, STANDARD, clearance=True), D('13.99'))
        self.assertEqual(pricing.unit_price(MUG, 100, STANDARD, clearance=True), D('13.99'))
        self.assertEqual(pricing.unit_price(MUG, 1, GOLD, clearance=True), D('13.29'))
        self.assertEqual(pricing.unit_price(BOX, 3, None, clearance=True), D('5.22'))

    def test_clearance_ignores_margin_floor(self):
        self.assertEqual(pricing.unit_price(LAMP, 1, STANDARD, clearance=True), D('7.70'))
        self.assertEqual(pricing.unit_price(LAMP, 1, STANDARD, clearance=True, override='5.00'), D('5.00'))
        self.assertEqual(pricing.unit_price(PEN, 50, GOLD, clearance=True), D('2.33'))

    def test_reference_grid(self):
        bad = []
        for p in PRODUCTS:
            for q in (1, 9, 10, 11, 49, 50, 99, 100, 101, 400):
                for c in (None, STANDARD, SILVER, GOLD, PLATINUM):
                    for cl in (False, True):
                        if pricing.unit_price(p, q, c, clearance=cl) != ref(p, q, c, cl):
                            bad.append((p.sku, q, c and c.tier, cl))
        self.assertEqual(bad, [])

    def test_patched_tables_read_at_call_time(self):
        with mock.patch.object(pricing, 'VOLUME_TIERS', [(10, D('0.05')), (200, D('0.20'))]):
            self.assertEqual(pricing.unit_price(MUG, 250, STANDARD), D('15.99'))
            self.assertEqual(pricing.unit_price(MUG, 100, STANDARD), D('18.99'))
        with mock.patch.object(pricing, 'VOLUME_TIERS', []):
            self.assertEqual(pricing.unit_price(MUG, 500, STANDARD), D('19.99'))
        with mock.patch.object(pricing, 'MEMBER_DISCOUNTS', {'standard': D('0.10')}):
            self.assertEqual(pricing.unit_price(MUG, 1, STANDARD), D('17.99'))
            self.assertEqual(pricing.unit_price(MUG, 1, GOLD), D('19.99'))
        with mock.patch.object(pricing, 'MARGIN_FLOOR', D('2')):
            self.assertEqual(pricing.unit_price(TEA, 1, STANDARD), D('1.25'))
            self.assertEqual(pricing.unit_price(MUG, 1, STANDARD), D('19.99'))
            self.assertEqual(pricing.unit_price(PEN, 1, STANDARD), D('6.66'))
        with mock.patch.object(pricing, 'CLEARANCE_MARKDOWN', D('0.50')):
            self.assertEqual(pricing.unit_price(MUG, 1, STANDARD, clearance=True), D('10.00'))


class ChannelTests(unittest.TestCase):
    def test_all_channels_match_reference(self):
        bad = []
        for p in PRODUCTS:
            for q in (1, 10, 50, 99, 100, 300):
                for c in (None, SILVER, GOLD):
                    for cl in (False, True):
                        want = ref(p, q, c or STANDARD, cl)
                        want_till = ref(p, q, c, cl)
                        got = channel_prices(p.sku, q, c, cl)
                        if got != (want, want, want_till):
                            bad.append((p.sku, q, c and c.tier, cl, got))
        self.assertEqual(bad, [])

    def test_cart_prices_clearance_when_lines_are_read(self):
        catalog, inv = world()
        cart = Cart(catalog, inv, GOLD)
        cart.add('MUG', 60)
        self.assertEqual(cart.lines()[0][2], D('17.47'))
        inv.set_clearance('MUG')
        self.assertEqual(cart.lines(), [('MUG', 60, D('13.29'), D('797.40'))])
        self.assertEqual(cart.total(), D('797.40'))
        inv.set_clearance('MUG', False)
        self.assertEqual(cart.lines()[0][2], D('17.47'))

    def test_quote_locks_price_at_add(self):
        catalog, inv = world()
        q = Quote(catalog, inv, SILVER, 'Q-9')
        self.assertEqual(q.add('LAMP', 5), D('11.00'))
        inv.set_clearance('LAMP')
        self.assertEqual(q.lines(), [('LAMP', 5, D('11.00'), D('55.00'))])
        self.assertEqual(q.add('LAMP', 5), D('7.55'))
        self.assertEqual(q.add('LAMP', 2, override='4.00'), D('4.00'))
        self.assertEqual(q.total(), D('100.75'))
        inv.set_clearance('LAMP', False)
        self.assertEqual(q.total(), D('100.75'))
        self.assertEqual(q.add('LAMP', 1, override='4.00'), D('11.00'))

    def test_till_merges_scans_and_uses_clearance(self):
        catalog, inv = world()
        till = Receipt(catalog, inv)
        till.scan('TEA', 6)
        till.scan('BOX', 1)
        till.scan('TEA', 4)
        inv.set_clearance('BOX')
        self.assertEqual(till.lines(), [('TEA', 10, D('1.20'), D('12.00')), ('BOX', 1, D('5.22'), D('5.22'))])
        self.assertEqual(till.checkout(), D('17.22'))
        self.assertEqual((inv.on_hand('TEA'), inv.on_hand('BOX')), (990, 999))

    def test_patched_volume_tiers_reach_every_channel(self):
        with mock.patch.object(pricing, 'VOLUME_TIERS', [(5, D('0.50'))]):
            self.assertEqual(channel_prices('MUG', 5, None), (D('10.00'), D('10.00'), D('10.00')))
            self.assertEqual(channel_prices('MUG', 100, None), (D('10.00'), D('10.00'), D('10.00')))

    def test_patched_member_discounts_reach_every_channel(self):
        with mock.patch.object(pricing, 'MEMBER_DISCOUNTS', {'gold': D('0.25')}):
            self.assertEqual(channel_prices('MUG', 1, GOLD), (D('14.99'), D('14.99'), D('14.99')))
            self.assertEqual(channel_prices('MUG', 1, SILVER), (D('19.99'), D('19.99'), D('19.99')))

    def test_patched_margin_floor_reaches_every_channel(self):
        with mock.patch.object(pricing, 'MARGIN_FLOOR', D('3')):
            self.assertEqual(channel_prices('MUG', 1, None), (D('19.99'), D('19.99'), D('19.99')))
            self.assertEqual(channel_prices('LAMP', 1, None), (D('30.00'), D('30.00'), D('30.00')))

    def test_patched_clearance_markdown_reaches_every_channel(self):
        with mock.patch.object(pricing, 'CLEARANCE_MARKDOWN', D('0.60')):
            self.assertEqual(channel_prices('LAMP', 1, None, clearance=True), (D('4.40'), D('4.40'), D('4.40')))


class PreservedBehaviorTests(unittest.TestCase):
    def test_cart_merge_and_stock(self):
        catalog, inv = world(stock=60)
        cart = Cart(catalog, inv, STANDARD)
        cart.add('MUG', 30)
        cart.add('TEA', 2)
        cart.add('MUG', 20)
        self.assertEqual([l[:2] for l in cart.lines()], [('MUG', 50), ('TEA', 2)])
        self.assertEqual(cart.lines()[0][2], D('18.39'))
        with self.assertRaises(OutOfStock):
            cart.add('MUG', 11)
        with self.assertRaises(ValueError):
            cart.add('MUG', 0)
        with self.assertRaises(UnknownProduct):
            cart.add('NOPE', 1)

    def test_quote_accept_is_all_or_nothing(self):
        catalog, inv = world(stock=10)
        q = Quote(catalog, inv, GOLD, 'Q-1')
        q.add('MUG', 6)
        q.add('TEA', 5)
        q.add('MUG', 5)
        with self.assertRaises(OutOfStock):
            q.accept()
        self.assertEqual((inv.reserved('MUG'), inv.reserved('TEA')), (0, 0))
        q2 = Quote(catalog, inv, GOLD, 'Q-2')
        q2.add('MUG', 10)
        q2.accept()
        self.assertEqual(inv.available('MUG'), 0)
        with self.assertRaises(ValueError):
            q2.accept()

    def test_till_checkout_all_or_nothing(self):
        catalog, inv = world(stock=5)
        till = Receipt(catalog, inv, SILVER)
        till.scan('MUG', 2)
        till.scan('PEN', 6)
        with self.assertRaises(OutOfStock):
            till.checkout()
        self.assertEqual((inv.on_hand('MUG'), inv.on_hand('PEN')), (5, 5))
        with self.assertRaises(UnknownProduct):
            till.scan('NOPE')


if __name__ == '__main__':
    unittest.main()
