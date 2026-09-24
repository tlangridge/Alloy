from meterbill.money import ZERO, percent_of


def discount_for(code, subtotal, catalog, redeemed=set()):
    """Discount for promo `code` on one invoice's `subtotal`.

    A code is redeemed at most once per invoice; unknown or empty codes give
    no discount.
    """
    if not code or code not in catalog or code in redeemed:
        return ZERO
    redeemed.add(code)
    return percent_of(subtotal, catalog[code]['percent'])
