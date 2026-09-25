"""Parse limits written as "<count>/<period>", e.g. "100/min"."""
import re

_UNITS = {
    's': 1, 'sec': 1, 'second': 1,
    'm': 60, 'min': 60, 'minute': 60,
    'h': 3600, 'hour': 3600,
    'd': 86400, 'day': 86400,
}
_POLICY = re.compile(r'^\s*(\d+)\s*/\s*([a-z]+)\s*$')


def parse(policy):
    """Return (capacity, rate): burst capacity and refill rate in tokens/second."""
    m = _POLICY.match(policy.lower()) if isinstance(policy, str) else None
    if not m or m.group(2) not in _UNITS:
        raise ValueError('invalid rate policy: %r' % (policy,))
    count = int(m.group(1))
    if count <= 0:
        raise ValueError('rate policy count must be positive: %r' % (policy,))
    return count, count / float(_UNITS[m.group(2)])
