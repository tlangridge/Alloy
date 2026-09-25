"""Invoices: lines, VAT and totals."""
from decimal import Decimal

from billing import split, tax
from billing.money import round_half_up, to_money


class Line:
    """One invoice line. Adjustment/discount lines use a negative unit price."""

    def __init__(self, sku, qty, unit_price, category='standard', discount='0'):
        if not isinstance(qty, int) or isinstance(qty, bool) or qty == 0:
            raise ValueError('qty must be a non-zero integer')
        self.sku = sku
        self.qty = qty
        self.unit_price = to_money(unit_price)
        self.category = category
        self.discount = to_money(discount)
        if not Decimal(0) <= self.discount < 1:
            raise ValueError('discount must be in [0, 1)')
        tax.rate_for(category)

    @property
    def net(self):
        return round_half_up(self.qty * self.unit_price * (1 - self.discount))

    @property
    def tax(self):
        return tax.line_tax(self.net, self.category)

    @property
    def gross(self):
        return self.net + self.tax


class Invoice:
    def __init__(self, number, lines=()):
        self.number = number
        self.lines = list(lines)

    def add(self, *args, **kwargs):
        line = Line(*args, **kwargs)
        self.lines.append(line)
        return line

    @property
    def subtotal(self):
        return sum((line.net for line in self.lines), Decimal('0.00'))

    @property
    def tax_total(self):
        return sum((line.tax for line in self.lines), Decimal('0.00'))

    @property
    def total(self):
        return self.subtotal + self.tax_total

    def breakdown(self):
        """{category: (net, tax)} summed over the lines of each category."""
        out = {}
        for line in self.lines:
            net, vat = out.get(line.category, (Decimal('0.00'), Decimal('0.00')))
            out[line.category] = (net + line.net, vat + line.tax)
        return out

    def split(self, weights):
        """Shares of the invoice total per payer (see billing.split.allocate)."""
        return split.allocate(self.total, weights)
