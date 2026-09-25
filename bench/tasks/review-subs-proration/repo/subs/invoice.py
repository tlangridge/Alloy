"""Invoices and line items."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LineItem:
    description: str
    amount: Decimal          # negative for credits
    kind: str = 'charge'     # 'charge', 'credit', 'proration', 'tax'


class Invoice:
    def __init__(self, customer_id, currency):
        self.customer_id = customer_id
        self.currency = currency
        self.lines = []

    def add(self, line):
        """Append a line. Amounts must be Decimals already rounded to cents."""
        amount = line.amount
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount.as_tuple().exponent != -2:
            raise ValueError('line amounts must be Decimals with exactly two decimal places')
        self.lines.append(line)
        return line

    @property
    def total(self):
        return sum((line.amount for line in self.lines), Decimal('0.00'))
