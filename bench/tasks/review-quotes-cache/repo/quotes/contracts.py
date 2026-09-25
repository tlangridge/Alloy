"""Negotiated discounts: contract id -> {product category: discount fraction}."""
from decimal import Decimal

CONTRACTS = {
    'ACME-2026': {'tools': Decimal('0.10'), 'safety': Decimal('0.05')},
    'BUILDCO-7': {'tools': Decimal('0.18')},
}


def discount_for(contract, category):
    """Discount fraction (0 <= d < 1) a contract grants on a category."""
    if contract is None:
        return Decimal('0')
    return CONTRACTS.get(contract, {}).get(category, Decimal('0'))
