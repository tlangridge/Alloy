"""Version constraints such as ``^1.2``, ``>=1.4, <2 || 3.*``."""
import re

from .errors import InvalidConstraint
from .version import Version

_PARTIAL = re.compile(r'(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?)?\Z')
_WILDCARD = re.compile(r'(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?\.\*\Z')
_OPERATORS = ('>=', '<=', '!=', '>', '<', '=')


def _partial(text, whole):
    m = _PARTIAL.match(text)
    if not m:
        raise InvalidConstraint('invalid version %r in %r' % (text, whole))
    major, minor, patch = m.groups()
    return int(major), None if minor is None else int(minor), None if patch is None else int(patch)


def _floor(p):
    return Version(p[0], p[1] or 0, p[2] or 0)


def _next_up(p):
    """Smallest version above every version matching the partial (None for a full version)."""
    major, minor, patch = p
    if patch is not None:
        return None
    if minor is not None:
        return Version(major, minor + 1, 0)
    return Version(major + 1, 0, 0)


def _range(low, high):
    return lambda v: (low is None or v >= low) and (high is None or v < high)


def _equal(p):
    if p[2] is not None:
        target = _floor(p)
        return lambda v: v == target
    return _range(_floor(p), _next_up(p))


def _term(text, whole):
    text = text.strip()
    if not text:
        raise InvalidConstraint('empty term in %r' % whole)
    if text == '*':
        return lambda v: True
    m = _WILDCARD.match(text)
    if m:
        major, minor = m.groups()
        p = (int(major), None if minor is None else int(minor), None)
        return _range(_floor(p), _next_up(p))
    if text[0] == '^':
        p = _partial(text[1:].strip(), whole)
        major, minor, patch = p
        if major > 0:
            high = Version(major + 1, 0, 0)
        elif minor is None:
            high = Version(1, 0, 0)
        elif minor > 0:
            high = Version(0, minor + 1, 0)
        elif patch is None:
            high = Version(0, 1, 0)
        else:
            high = Version(0, 0, patch + 1)
        return _range(_floor(p), high)
    if text[0] == '~':
        p = _partial(text[1:].strip(), whole)
        high = Version(p[0] + 1, 0, 0) if p[1] is None else Version(p[0], p[1] + 1, 0)
        return _range(_floor(p), high)
    op = '='
    for candidate in _OPERATORS:
        if text.startswith(candidate):
            op, text = candidate, text[len(candidate):].strip()
            break
    p = _partial(text, whole)
    if op == '=':
        return _equal(p)
    if op == '!=':
        eq = _equal(p)
        return lambda v: not eq(v)
    if op == '>=':
        low = _floor(p)
        return lambda v: v >= low
    if op == '<':
        high = _floor(p)
        return lambda v: v < high
    up = _next_up(p)
    if op == '>':
        if up is None:
            low = _floor(p)
            return lambda v: v > low
        return lambda v: v >= up
    # '<='
    if up is None:
        high = _floor(p)
        return lambda v: v <= high
    return lambda v: v < up


class Constraint(object):
    def __init__(self, text, groups):
        self.text = text
        self._groups = groups

    @classmethod
    def parse(cls, text):
        """Parse constraint text; raises InvalidConstraint."""
        if not isinstance(text, str) or not text.strip():
            raise InvalidConstraint('empty constraint')
        groups = [[_term(term, text) for term in group.split(',')] for group in text.split('||')]
        return cls(text, groups)

    def allows(self, version):
        """True if ``version`` (a Version or version string) satisfies the constraint."""
        version = Version.parse(version)
        return any(all(term(version) for term in group) for group in self._groups)

    def __repr__(self):
        return 'Constraint(%r)' % self.text
