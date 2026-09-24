"""Built-in functions available to rules."""
from decimal import ROUND_HALF_UP, Decimal, DecimalException


class FunctionFailure(Exception):
    """Raised by an implementation; the evaluator turns it into an EvalError."""


class Function(object):
    __slots__ = ('name', 'min_args', 'max_args', 'impl')

    def __init__(self, name, min_args, max_args, impl):
        self.name = name
        self.min_args = min_args
        self.max_args = max_args
        self.impl = impl


def _is_number(v):
    return isinstance(v, Decimal)


def _integral(v):
    return _is_number(v) and v.is_finite() and v == v.to_integral_value()


def _len(x):
    if isinstance(x, (str, list, dict)):
        return Decimal(len(x))
    raise FunctionFailure('len() needs a string, list or map')


def _lower(s):
    if not isinstance(s, str):
        raise FunctionFailure('lower() needs a string')
    return s.lower()


def _upper(s):
    if not isinstance(s, str):
        raise FunctionFailure('upper() needs a string')
    return s.upper()


def _abs(x):
    if not _is_number(x):
        raise FunctionFailure('abs() needs a number')
    return abs(x)


def _round(x, places=Decimal(0)):
    if not _is_number(x):
        raise FunctionFailure('round() needs a number')
    if not _integral(places) or not 0 <= places <= 28:
        raise FunctionFailure('round() places must be an integer between 0 and 28')
    try:
        return x.quantize(Decimal(1).scaleb(-int(places)), rounding=ROUND_HALF_UP)
    except DecimalException:
        raise FunctionFailure('round() result out of range')


def _extreme(name, pick):
    def impl(*args):
        if all(_is_number(a) for a in args) or all(isinstance(a, str) for a in args):
            best = args[0]
            for a in args[1:]:
                if pick(a, best):
                    best = a
            return best
        raise FunctionFailure('%s() needs all numbers or all strings' % name)
    return impl


FUNCTIONS = {
    'len': Function('len', 1, 1, _len),
    'lower': Function('lower', 1, 1, _lower),
    'upper': Function('upper', 1, 1, _upper),
    'abs': Function('abs', 1, 1, _abs),
    'round': Function('round', 1, 2, _round),
    'min': Function('min', 1, None, _extreme('min', lambda a, b: a < b)),
    'max': Function('max', 1, None, _extreme('max', lambda a, b: a > b)),
}
