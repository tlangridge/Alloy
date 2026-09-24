"""Version constraints for rollout rules, e.g. ``">=1.4, <2.0"``.

Work in progress: only the plain comparison operators are wired up so far.
"""
import operator

from fwver.version import parse

_OPS = {
    '>=': operator.ge,
    '<=': operator.le,
    '>': operator.gt,
    '<': operator.lt,
    '==': operator.eq,
    '!=': operator.ne,
}


def satisfies(version, spec):
    if isinstance(version, str):
        version = parse(version)
    for clause in spec.split(','):
        clause = clause.strip()
        for op in sorted(_OPS, key=len, reverse=True):
            if clause.startswith(op):
                if not _OPS[op](version, parse(clause[len(op):].strip())):
                    return False
                break
    return True
