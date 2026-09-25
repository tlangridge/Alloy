"""Format integer minor-unit amounts (cents, pence, yen) for invoices."""


class UnknownCurrencyError(ValueError):
    """The currency code is not supported."""


def _group(number, sep):
    digits = str(number)
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return sep.join(groups)


def format_money(amount, currency):
    """Format ``amount`` (an int in the currency's minor unit) for display.

    >>> format_money(123456, 'USD')
    '$1,234.56'
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError('amount must be an int number of minor units')
    code = currency.upper()
    negative = amount < 0
    amount = abs(amount)
    if code == 'USD':
        whole, cents = divmod(amount, 100)
        text = '$%s.%02d' % (_group(whole, ','), cents)
        return '-' + text if negative else text
    if code == 'GBP':
        whole, pence = divmod(amount, 100)
        text = '£%s.%02d' % (_group(whole, ','), pence)
        return '-' + text if negative else text
    if code == 'EUR':
        whole, cents = divmod(amount, 100)
        text = '%s,%02d €' % (_group(whole, '.'), cents)
        return '-' + text if negative else text
    if code == 'CHF':
        whole, rappen = divmod(amount, 100)
        digits = "%s.%02d" % (_group(whole, "'"), rappen)
        return 'CHF ' + ('-' + digits if negative else digits)
    if code == 'JPY':
        text = '¥' + _group(amount, ',')
        return '-' + text if negative else text
    raise UnknownCurrencyError('unsupported currency: %r' % (currency,))
