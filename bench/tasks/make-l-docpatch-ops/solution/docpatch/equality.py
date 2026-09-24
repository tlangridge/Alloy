"""JSON value equality."""


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def json_type(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if is_number(value):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    return 'unknown'


def json_equal(a, b):
    """True when ``a`` and ``b`` are equal JSON values."""
    ta, tb = json_type(a), json_type(b)
    if ta != tb:
        return False
    if ta == 'array':
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if ta == 'object':
        return set(a) == set(b) and all(json_equal(a[k], b[k]) for k in a)
    return a == b
