import random
import unittest
from decimal import Decimal as D, ROUND_HALF_UP

from billing import tax
from billing.credit import credit_note
from billing.invoice import Invoice
from billing.money import round_half_up
from billing.split import allocate

RATES = {'standard': D('0.20'), 'reduced': D('0.05'), 'zero': D('0')}


def ref_round(x, places=2):
    return x.quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


class RoundHalfUpTests(unittest.TestCase):
    def check(self, cases):
        bad = [(x, p, str(round_half_up(D(x), p)), want) for x, p, want in cases
               if round_half_up(D(x), p) != D(want)]
        self.assertEqual(bad, [])

    def test_negative_halves_go_away_from_zero(self):
        self.check([('-0.125', 2, '-0.13'), ('-2.675', 2, '-2.68'), ('-0.005', 2, '-0.01'),
                    ('-1.0005', 3, '-1.001'), ('-2.5', 0, '-3'), ('-0.5', 0, '-1')])

    def test_positive_halves_unchanged(self):
        self.check([('0.125', 2, '0.13'), ('2.675', 2, '2.68'), ('0.005', 2, '0.01'),
                    ('1.0005', 3, '1.001'), ('2.5', 0, '3'), ('0.5', 0, '1')])

    def test_non_half_values_round_to_nearest(self):
        self.check([('-0.124', 2, '-0.12'), ('-0.126', 2, '-0.13'), ('0.1249', 2, '0.12'),
                    ('-0.0049', 2, '0'), ('-13.1251', 2, '-13.13'), ('7', 2, '7')])

    def test_symmetry_grid(self):
        bad = []
        for places in (0, 2, 3):
            step = D(1).scaleb(-places - 1) / 2
            for i in range(-400, 401):
                x = step * i
                if (round_half_up(-x, places) != -round_half_up(x, places)
                        or round_half_up(x, places) != ref_round(x, places)):
                    bad.append((str(x), places))
        self.assertEqual(bad, [])


class LineTaxTests(unittest.TestCase):
    def test_negative_half_cent_vat(self):
        self.assertEqual(tax.line_tax(D('-0.10'), 'reduced'), D('-0.01'))
        self.assertEqual(tax.line_tax(D('-10.30'), 'reduced'), D('-0.52'))
        self.assertEqual(tax.line_tax(D('0.10'), 'reduced'), D('0.01'))
        self.assertEqual(tax.line_tax(D('10.30'), 'reduced'), D('0.52'))

    def test_vat_is_symmetric_and_half_up_for_every_cent(self):
        bad = []
        for cents in range(-3000, 3001, 7):
            net = D(cents) / 100
            for cat, rate in RATES.items():
                if (tax.line_tax(net, cat) != ref_round(net * rate)
                        or tax.line_tax(-net, cat) != -tax.line_tax(net, cat)):
                    bad.append((str(net), cat))
        self.assertEqual(bad, [])

    def test_unknown_category(self):
        with self.assertRaises(tax.UnknownTaxCategory):
            tax.line_tax(D('1.00'), 'luxury')


class InvoiceTests(unittest.TestCase):
    def test_bulk_priced_invoice(self):
        inv = Invoice('INV-2291')
        inv.add('BOLT-M6', 7, '1.875')
        inv.add('GASKET', 12, '0.4375')
        inv.add('WASHER', 40, '0.0815')
        self.assertEqual([l.net for l in inv.lines], [D('13.13'), D('5.25'), D('3.26')])
        self.assertEqual((inv.subtotal, inv.tax_total, inv.total), (D('21.64'), D('4.33'), D('25.97')))

    def test_adjustment_line_with_half_cent(self):
        inv = Invoice('INV-9')
        inv.add('KIT', 1, '20.00')
        adj = inv.add('GOODWILL', 1, '-0.125')
        self.assertEqual(adj.net, D('-0.13'))
        self.assertEqual(adj.tax, D('-0.03'))
        self.assertEqual(inv.total, D('23.84'))

    def test_reduced_rate_adjustment(self):
        inv = Invoice('INV-10')
        inv.add('BOOK', 1, '10.30', category='reduced')
        inv.add('CORR', 1, '-0.10', category='reduced')
        self.assertEqual(inv.breakdown()['reduced'], (D('10.20'), D('0.51')))
        self.assertEqual(inv.total, D('10.71'))

    def test_discounted_line(self):
        inv = Invoice('INV-11')
        line = inv.add('A', 3, '2.35', discount='0.15')
        self.assertEqual(line.net, D('5.99'))
        line = inv.add('B', -3, '2.35', discount='0.15')
        self.assertEqual(line.net, D('-5.99'))


def mirror_errors(inv, note):
    bad = []
    for name in ('subtotal', 'tax_total', 'total'):
        if getattr(note, name) != -getattr(inv, name):
            bad.append((inv.number, name, str(getattr(inv, name)), str(getattr(note, name))))
    if len(note.lines) != len(inv.lines):
        bad.append((inv.number, 'line count'))
    for a, b in zip(inv.lines, note.lines):
        if (b.net, b.tax, b.gross) != (-a.net, -a.tax, -a.gross):
            bad.append((inv.number, a.sku, str(a.net), str(a.tax), str(b.net), str(b.tax)))
    got = note.breakdown()
    for cat, (net, vat) in inv.breakdown().items():
        if got.get(cat) != (-net, -vat):
            bad.append((inv.number, 'breakdown', cat))
    return bad


def assert_mirror(case, inv, note):
    case.assertEqual(mirror_errors(inv, note), [])


class CreditNoteTests(unittest.TestCase):
    def test_reported_example(self):
        inv = Invoice('INV-2291')
        inv.add('BOLT-M6', 7, '1.875')
        inv.add('GASKET', 12, '0.4375')
        inv.add('WASHER', 40, '0.0815')
        note = credit_note(inv, 'CN-0107')
        self.assertEqual(note.total, D('-25.97'))
        assert_mirror(self, inv, note)

    def test_mixed_categories_discounts_and_adjustments(self):
        inv = Invoice('INV-77')
        inv.add('BOLT', 7, '1.875')
        inv.add('BOOK', 1, '10.30', category='reduced')
        inv.add('MAP', 2, '0.05', category='reduced')
        inv.add('SEED', 9, '0.3125', category='zero')
        inv.add('CABLE', 3, '2.35', discount='0.15')
        inv.add('GOODWILL', 1, '-0.125')
        note = credit_note(inv, 'CN-77')
        assert_mirror(self, inv, note)
        self.assertEqual(note.total, D('-36.53'))

    def test_split_of_credit_note_mirrors_invoice_split(self):
        inv = Invoice('INV-78')
        inv.add('BOLT', 7, '1.875')
        inv.add('MAP', 2, '0.05', category='reduced')
        note = credit_note(inv, 'CN-78')
        for weights in ([1, 1, 1], [3, 1], [1, 2, 2, 5]):
            self.assertEqual(note.split(weights), [-s for s in inv.split(weights)], weights)

    def test_partial_credit_equals_negated_invoice_for_those_units(self):
        inv = Invoice('INV-80')
        inv.add('BOLT', 7, '1.875')
        inv.add('BOOK', 3, '3.4333', category='reduced')
        note = credit_note(inv, 'CN-80', {'BOLT': 3, 'BOOK': 1})
        ref = Invoice('REF')
        ref.add('BOLT', 3, '1.875')
        ref.add('BOOK', 1, '3.4333', category='reduced')
        self.assertEqual((note.subtotal, note.tax_total, note.total),
                         (-ref.subtotal, -ref.tax_total, -ref.total))
        self.assertEqual(note.total, D('-10.36'))

    def test_credit_of_adjustment_line_is_positive(self):
        inv = Invoice('INV-81')
        inv.add('KIT', 1, '20.00')
        inv.add('GOODWILL', 1, '-0.125')
        note = credit_note(inv, 'CN-81', {'GOODWILL': 1})
        self.assertEqual(note.lines[0].net, D('0.13'))
        self.assertEqual(note.total, D('0.16'))

    def test_seeded_random_invoices_mirror(self):
        rng = random.Random(4127)
        cats = ['standard', 'reduced', 'zero']
        bad = []
        for n in range(150):
            inv = Invoice('R-%d' % n)
            for i in range(rng.randint(1, 6)):
                price = D(rng.randint(-500, 50000)) / 10000
                if price == 0:
                    price = D('0.0005')
                disc = rng.choice(['0', '0', '0.15', '0.075'])
                inv.add('S%d' % i, rng.randint(1, 60), price, category=rng.choice(cats), discount=disc)
            note = credit_note(inv, 'C-%d' % n)
            bad.extend(mirror_errors(inv, note))
            for line in inv.lines:
                if (line.net != ref_round(line.qty * line.unit_price * (1 - line.discount))
                        or line.tax != ref_round(line.net * RATES[line.category])):
                    bad.append((inv.number, line.sku, 'positive amounts changed'))
        self.assertEqual(bad, [])


class AllocateRegressionTests(unittest.TestCase):
    def test_ties_go_to_earlier_payers(self):
        self.assertEqual(allocate(D('10.00'), [1, 1, 1]), [D('3.34'), D('3.33'), D('3.33')])
        self.assertEqual(allocate(D('0.05'), [1, 1, 1, 1]), [D('0.02'), D('0.01'), D('0.01'), D('0.01')])

    def test_negative_total_mirrors(self):
        self.assertEqual(allocate(D('-0.05'), [1, 1, 1, 1]), [D('-0.02'), D('-0.01'), D('-0.01'), D('-0.01')])


if __name__ == '__main__':
    unittest.main()
