"""Evaluator: syntax tree + variables -> value."""
import decimal
import math
from decimal import Decimal

from .errors import EvalError
from .functions import FUNCTIONS, FunctionFailure

_CONTEXT = decimal.Context(prec=28, rounding=decimal.ROUND_HALF_EVEN,
                           traps=[decimal.DivisionByZero, decimal.InvalidOperation, decimal.Overflow])


def _fail(message, pos):
    raise EvalError(message, pos[0], pos[1])


def is_number(v):
    return isinstance(v, Decimal)


def _integral(v):
    return is_number(v) and v.is_finite() and v == v.to_integral_value()


def equal(a, b):
    """Language equality: no cross-type equality, deep for lists and maps."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if is_number(a) and is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(equal(a[k], b[k]) for k in a)
    return False


class _Unsupported(Exception):
    pass


def convert(value):
    """Convert a caller-supplied Python value into a language value."""
    if value is None or isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _Unsupported()
        return Decimal(repr(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise _Unsupported()
        return value
    if isinstance(value, (list, tuple)):
        return [convert(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise _Unsupported()
            out[k] = convert(v)
        return out
    raise _Unsupported()


class _Evaluator(object):
    def __init__(self, variables):
        self.variables = variables
        self.cache = {}

    def eval(self, node):
        return getattr(self, 'e_' + node.kind)(node)

    def e_const(self, node):
        return node.args[0]

    def e_name(self, node):
        name = node.args[0]
        if name in self.cache:
            return self.cache[name]
        if name not in self.variables:
            _fail('unknown variable %r' % name, node.pos)
        try:
            value = convert(self.variables[name])
        except _Unsupported:
            _fail('unsupported value for variable %r' % name, node.pos)
        self.cache[name] = value
        return value

    def e_list(self, node):
        return [self.eval(item) for item in node.args[0]]

    def e_member(self, node):
        obj = self.eval(node.args[0])
        key = node.args[1]
        if obj is None:
            return None
        if not isinstance(obj, dict):
            _fail('member access on a non-map value', node.pos)
        if key not in obj:
            _fail('unknown member %r' % key, node.pos)
        return obj[key]

    def e_index(self, node):
        obj = self.eval(node.args[0])
        index = self.eval(node.args[1])
        if obj is None:
            return None
        if isinstance(obj, (list, str)):
            if isinstance(index, bool) or not _integral(index):
                _fail('index must be an integer', node.pos)
            i = int(index)
            if not -len(obj) <= i < len(obj):
                _fail('index out of range', node.pos)
            return obj[i]
        if isinstance(obj, dict):
            if not isinstance(index, str):
                _fail('map index must be a string', node.pos)
            if index not in obj:
                _fail('unknown key %r' % index, node.pos)
            return obj[index]
        _fail('value is not indexable', node.pos)

    def e_call(self, node):
        name, args = node.args
        values = [self.eval(a) for a in args]
        try:
            return FUNCTIONS[name].impl(*values)
        except FunctionFailure as exc:
            _fail(str(exc), node.pos)

    def e_unary(self, node):
        op, operand = node.args
        value = self.eval(operand)
        if not is_number(value):
            _fail('unary %s needs a number' % op, node.pos)
        return -value if op == '-' else +value

    def e_not(self, node):
        value = self.eval(node.args[0])
        if not isinstance(value, bool):
            _fail('not needs a boolean', node.pos)
        return not value

    def _bool(self, node, value):
        if not isinstance(value, bool):
            _fail('%s needs boolean operands' % node.kind, node.pos)
        return value

    def e_and(self, node):
        if not self._bool(node, self.eval(node.args[0])):
            return False
        return self._bool(node, self.eval(node.args[1]))

    def e_or(self, node):
        if self._bool(node, self.eval(node.args[0])):
            return True
        return self._bool(node, self.eval(node.args[1]))

    def e_coalesce(self, node):
        left = self.eval(node.args[0])
        if left is not None:
            return left
        return self.eval(node.args[1])

    def e_cond(self, node):
        cond = self.eval(node.args[0])
        if not isinstance(cond, bool):
            _fail('condition must be a boolean', node.pos)
        return self.eval(node.args[1] if cond else node.args[2])

    def e_compare(self, node):
        operands, ops = node.args
        left = self.eval(operands[0])
        for (op, pos), operand in zip(ops, operands[1:]):
            right = self.eval(operand)
            if not self.compare(op, left, right, pos):
                return False
            left = right
        return True

    def compare(self, op, a, b, pos):
        if op == '==':
            return equal(a, b)
        if op == '!=':
            return not equal(a, b)
        if op in ('in', 'not in'):
            if isinstance(b, list):
                found = any(equal(a, item) for item in b)
            elif isinstance(b, str):
                if not isinstance(a, str):
                    _fail('left side of in must be a string', pos)
                found = a in b
            elif isinstance(b, dict):
                if not isinstance(a, str):
                    _fail('left side of in must be a string', pos)
                found = a in b
            else:
                _fail('right side of in must be a list, string or map', pos)
            return found if op == 'in' else not found
        if not ((is_number(a) and is_number(b)) or (isinstance(a, str) and isinstance(b, str))):
            _fail('cannot order these values', pos)
        return {'<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b}[op]

    def e_binary(self, node):
        op, lnode, rnode = node.args
        a = self.eval(lnode)
        b = self.eval(rnode)
        if op == '+':
            if is_number(a) and is_number(b):
                return self.arith(lambda: a + b, node.pos)
            if isinstance(a, str) and isinstance(b, str):
                return a + b
            if isinstance(a, list) and isinstance(b, list):
                return a + b
            _fail('cannot add these values', node.pos)
        if not (is_number(a) and is_number(b)):
            _fail('%s needs numbers' % op, node.pos)
        if op == '-':
            return self.arith(lambda: a - b, node.pos)
        if op == '*':
            return self.arith(lambda: a * b, node.pos)
        if op in ('/', '//', '%') and b == 0:
            _fail('division by zero', node.pos)
        if op == '/':
            return self.arith(lambda: a / b, node.pos)
        if op == '//':
            return self.arith(lambda: self.floordiv(a, b), node.pos)
        if op == '%':
            return self.arith(lambda: self.floormod(a, b), node.pos)
        # '**'
        if not _integral(b):
            _fail('exponent must be an integer', node.pos)
        if a == 0 and b < 0:
            _fail('division by zero', node.pos)
        return self.arith(lambda: a ** b, node.pos)

    @staticmethod
    def floordiv(a, b):
        q = a // b  # truncates toward zero
        r = a - q * b
        if r != 0 and (r < 0) != (b < 0):
            q -= 1
        return q

    @staticmethod
    def floormod(a, b):
        r = a % b  # sign follows the dividend
        if r != 0 and (r < 0) != (b < 0):
            r += b
        return r

    @staticmethod
    def arith(thunk, pos):
        try:
            with decimal.localcontext(_CONTEXT):
                return thunk()
        except decimal.DecimalException:
            _fail('arithmetic error', pos)


def evaluate_tree(node, variables):
    """Evaluate the syntax tree ``node`` against the ``variables`` mapping."""
    with decimal.localcontext(_CONTEXT):
        return _Evaluator(variables).eval(node)
