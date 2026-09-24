"""Format integer minor-unit amounts (cents, pence, yen) for invoices.

Every currency is described by a ``_Currency`` record in ``_REGISTRY``;
``format_money`` has no per-currency logic.
"""
import re
from collections import namedtuple


class UnknownCurrencyError(ValueError):
    """The currency code is not supported."""


_Currency = namedtuple('_Currency', 'code symbol decimals thousands_sep decimal_sep position space')
_CODE = re.compile(r'[A-Za-z]{3}')
_REGISTRY = {}


def register_currency(code, symbol, *, decimals=2, thousands_sep=',', decimal_sep='.',
                      position='prefix', space=False):
    """Register a currency so ``format_money`` can format it."""
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValueError('currency code must be three ASCII letters: %r' % (code,))
    key = code.upper()
    if key in _REGISTRY:
        raise ValueError('currency already registered: %s' % (key,))
    if not isinstance(symbol, str) or not symbol:
        raise ValueError('symbol must be a non-empty string')
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 4:
        raise ValueError('decimals must be an int from 0 to 4: %r' % (decimals,))
    if not isinstance(thousands_sep, str) or not isinstance(decimal_sep, str):
        raise ValueError('separators must be strings')
    if position not in ('prefix', 'suffix'):
        raise ValueError("position must be 'prefix' or 'suffix': %r" % (position,))
    _REGISTRY[key] = _Currency(key, symbol, decimals, thousands_sep, decimal_sep, position, bool(space))


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
    spec = _REGISTRY.get(currency.upper())
    if spec is None:
        raise UnknownCurrencyError('unsupported currency: %r' % (currency,))
    negative = amount < 0
    whole, fraction = divmod(abs(amount), 10 ** spec.decimals)
    number = _group(whole, spec.thousands_sep)
    if spec.decimals:
        number += spec.decimal_sep + str(fraction).zfill(spec.decimals)
    gap = ' ' if spec.space else ''
    if spec.position == 'prefix':
        if negative and spec.space:
            return spec.symbol + gap + '-' + number
        body = spec.symbol + gap + number
    else:
        body = number + gap + spec.symbol
    return '-' + body if negative else body


register_currency('USD', '$')
register_currency('GBP', '£')
register_currency('EUR', '€', thousands_sep='.', decimal_sep=',', position='suffix', space=True)
register_currency('CHF', 'CHF', thousands_sep="'", space=True)
register_currency('JPY', '¥', decimals=0)
