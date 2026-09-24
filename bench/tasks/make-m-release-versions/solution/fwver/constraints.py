"""Version constraints for rollout rules, e.g. ``">=1.4, <2.0"``."""
import operator

from fwver.version import InvalidVersion, Version, parse


class InvalidConstraint(ValueError):
    """Raised for a constraint spec that does not follow the syntax."""


_OPS = {
    '>=': operator.ge,
    '<=': operator.le,
    '>': operator.gt,
    '<': operator.lt,
    '==': operator.eq,
    '!=': operator.ne,
}
_ORDER = ('>=', '<=', '==', '!=', '>', '<', '~', '^')


def _final(epoch, major, minor, patch):
    return Version(epoch, major, minor, patch)


def _clause(text):
    text = text.strip()
    if not text:
        raise InvalidConstraint('empty clause')
    op = ''
    for candidate in _ORDER:
        if text.startswith(candidate):
            op = candidate
            break
    try:
        bound = parse(text[len(op):].strip())
    except InvalidVersion as exc:
        raise InvalidConstraint(str(exc))
    if op == '~':
        upper = _final(bound.epoch, bound.major, bound.minor + 1, 0)
        tests = [(operator.ge, bound), (operator.lt, upper)]
    elif op == '^':
        if bound.major > 0:
            upper = _final(bound.epoch, bound.major + 1, 0, 0)
        else:
            upper = _final(bound.epoch, 0, bound.minor + 1, 0)
        tests = [(operator.ge, bound), (operator.lt, upper)]
    else:
        tests = [(_OPS[op or '=='], bound)]
    return bound, tests


def _compile(spec):
    if not isinstance(spec, str) or not spec.strip():
        raise InvalidConstraint('empty constraint')
    return [_clause(part) for part in spec.split(',')]


def _matches(version, clauses):
    for _bound, tests in clauses:
        for op, ref in tests:
            if not op(version, ref):
                return False
    if version.is_prerelease:
        key = (version.epoch,) + version.release
        return any(b.is_prerelease and (b.epoch,) + b.release == key for b, _ in clauses)
    return True


def satisfies(version, spec):
    clauses = _compile(spec)
    if isinstance(version, str):
        version = parse(version)
    return _matches(version, clauses)


def max_satisfying(tags, spec):
    clauses = _compile(spec)
    best, best_tag = None, None
    for tag in tags:
        try:
            v = parse(tag)
        except InvalidVersion:
            continue
        if _matches(v, clauses) and (best is None or v > best):
            best, best_tag = v, tag
    return best_tag


def sort_versions(tags):
    parsed = [(parse(tag), tag) for tag in tags]
    return [tag for _v, tag in sorted(parsed, key=lambda pair: pair[0].sort_key())]
