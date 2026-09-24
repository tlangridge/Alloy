import unittest
from decimal import Decimal as D

from billing.credit import credit_note
from billing.invoice import Invoice
from billing.money import round_half_up, to_money
from billing.split import allocate


class MoneyTests(unittest.TestCase):
    def test_round_half_up_positive(self):
        self.assertEqual(round_half_up(D('0.125')), D('0.13'))
        self.assertEqual(round_half_up(D('0.124')), D('0.12'))
        self.assertEqual(round_half_up(D('2.5'), 0), D('3'))

    def test_floats_rejected(self):
        with self.assertRaises(TypeError):
            to_money(0.1)


class InvoiceTests(unittest.TestCase):
    def test_totals(self):
        inv = Invoice('INV-1')
        inv.add('A', 3, '19.99')
        inv.add('BOOK', 2, '12.50', category='reduced')
        self.assertEqual(inv.subtotal, D('84.97'))
        self.assertEqual(inv.tax_total, D('13.24'))
        self.assertEqual(inv.total, D('98.21'))

    def test_split(self):
        inv = Invoice('INV-2')
        inv.add('A', 1, '10.00', category='zero')
        self.assertEqual(inv.split([1, 1, 1]), [D('3.34'), D('3.33'), D('3.33')])


class CreditTests(unittest.TestCase):
    def test_full_credit_note_mirrors_simple_invoice(self):
        inv = Invoice('INV-3')
        inv.add('A', 2, '10.00')
        note = credit_note(inv, 'CN-3')
        self.assertEqual(note.total, -inv.total)
        self.assertEqual([l.qty for l in note.lines], [-2])

    def test_refund_more_than_invoiced(self):
        inv = Invoice('INV-4')
        inv.add('A', 2, '10.00')
        with self.assertRaises(ValueError):
            credit_note(inv, 'CN-4', {'A': 3})


class AllocateTests(unittest.TestCase):
    def test_negative_total_mirrors(self):
        self.assertEqual(allocate(D('-10.00'), [1, 2]), [D('-3.33'), D('-6.67')])


if __name__ == '__main__':
    unittest.main()
