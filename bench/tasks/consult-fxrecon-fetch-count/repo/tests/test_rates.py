import unittest
from decimal import Decimal
from unittest import mock

from fxrecon import rates
from fxrecon.ledger import Batch, Transaction
from fxrecon.reconcile import flag_large, post


class RateTests(unittest.TestCase):
    def setUp(self):
        rates.rate.cache_clear()

    def test_same_currency_needs_no_request(self):
        with mock.patch('fxrecon.feed.fetch_rate') as fetch:
            self.assertEqual(rates.rate('USD', 'USD', '2026-09-01'), Decimal('1'))
            fetch.assert_not_called()

    def test_rate_is_cached(self):
        with mock.patch('fxrecon.feed.fetch_rate', return_value=Decimal('1.1')) as fetch:
            rates.rate('EUR', 'USD', '2026-09-01')
            rates.rate('EUR', 'USD', '2026-09-01')
            self.assertEqual(fetch.call_count, 1)

    def test_convert(self):
        self.assertEqual(rates.convert(Decimal('10.00'), 'EUR', '2026-09-01'), Decimal('11.04'))


class ReconcileTests(unittest.TestCase):
    def test_flag_and_post(self):
        rates.rate.cache_clear()
        batch = Batch('card', [Transaction('t1', 'EUR', Decimal('600.00'), '2026-09-01'),
                               Transaction('t2', 'USD', Decimal('900.00'), '2026-09-01')])
        self.assertEqual(flag_large(batch), ['t1'])
        self.assertEqual(post(batch), [('t1', Decimal('662.52')), ('t2', Decimal('900.00'))])


if __name__ == '__main__':
    unittest.main()
