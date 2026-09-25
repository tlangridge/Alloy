import unittest

from tabs.ledger import Ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(['ana', 'ben', 'cy'])

    def test_expense_updates_balances(self):
        self.ledger.add_expense('ana', 900, {'ana': 300, 'ben': 300, 'cy': 300}, 'dinner')
        self.assertEqual(self.ledger.balances(), {'ana': 600, 'ben': -300, 'cy': -300})

    def test_refund_reverses(self):
        self.ledger.add_expense('ben', 500, {'ana': 250, 'ben': 250})
        self.ledger.add_expense('ben', -500, {'ana': -250, 'ben': -250})
        self.assertEqual(self.ledger.balances(), {'ana': 0, 'ben': 0, 'cy': 0})

    def test_shares_must_add_up(self):
        with self.assertRaises(ValueError):
            self.ledger.add_expense('ana', 100, {'ana': 50, 'ben': 49})

    def test_members_only(self):
        with self.assertRaises(ValueError):
            self.ledger.add_expense('zed', 100, {'ana': 100})
        with self.assertRaises(ValueError):
            self.ledger.add_expense('ana', 100, {'zed': 100})

    def test_int_cents_only(self):
        with self.assertRaises(TypeError):
            self.ledger.add_expense('ana', 1.5, {'ana': 1.5})

    def test_members_unique(self):
        with self.assertRaises(ValueError):
            Ledger(['ana', 'ana'])


if __name__ == '__main__':
    unittest.main()
