from meterbill import promos, ratecard
from meterbill.money import ZERO, to_money


class Invoice:
    def __init__(self, customer, lines, subtotal, discount):
        self.customer = customer
        self.lines = lines          # [(meter, quantity, amount)]
        self.subtotal = subtotal
        self.discount = discount
        self.total = to_money(subtotal - discount)


def rate_line(quantity, rate):
    """Charge for `quantity` units at `rate`, in cents."""
    return to_money(quantity * rate)


def build(doc, customer):
    lines = []
    for meter, quantity in customer['usage'].items():
        lines.append((meter, quantity, rate_line(quantity, ratecard.unit_rate(doc, meter))))
    subtotal = sum((amount for _, _, amount in lines), ZERO)
    discount = promos.discount_for(customer.get('promo'), subtotal, doc.get('promos', {}))
    return Invoice(customer['id'], lines, subtotal, discount)


def build_all(doc):
    return [build(doc, customer) for customer in doc['customers']]
