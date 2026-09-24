from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    monthly_price: Decimal
    currency: str


PLANS = {p.code: p for p in (
    Plan('starter', 'Starter', Decimal('9.99'), 'USD'),
    Plan('team', 'Team', Decimal('29.99'), 'USD'),
    Plan('business', 'Business', Decimal('49.99'), 'USD'),
    Plan('classic', 'Classic (legacy)', Decimal('12.45'), 'USD'),
    Plan('team-eu', 'Team EU', Decimal('27.50'), 'EUR'),
)}


def get(code):
    try:
        return PLANS[code]
    except KeyError:
        raise ValueError('unknown plan %r' % code) from None
