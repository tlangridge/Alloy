from urllib.parse import urlencode


def canonical_query(params):
    """Stable, unambiguous text form of report parameters.

    Keys are sorted, values are stringified and URL-encoded, and parameters
    whose value is None are dropped ({'region': None} means the same as {}).
    """
    items = sorted((str(key), str(value)) for key, value in params.items() if value is not None)
    return urlencode(items)
