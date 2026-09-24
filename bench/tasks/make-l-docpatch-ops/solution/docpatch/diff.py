"""Computing a patch that turns one document into another."""
import copy

from .equality import json_equal, json_type
from .pointer import escape_token


def _diff(a, b, path, out):
    if json_equal(a, b):
        return
    ta, tb = json_type(a), json_type(b)
    if ta == tb == 'object':
        for key in sorted(set(a) - set(b)):
            out.append({'op': 'remove', 'path': path + '/' + escape_token(key)})
        for key in sorted(set(a) & set(b)):
            _diff(a[key], b[key], path + '/' + escape_token(key), out)
        for key in sorted(set(b) - set(a)):
            out.append({'op': 'add', 'path': path + '/' + escape_token(key), 'value': copy.deepcopy(b[key])})
        return
    if ta == tb == 'array':
        common = min(len(a), len(b))
        for i in range(common):
            _diff(a[i], b[i], '%s/%d' % (path, i), out)
        for i in range(len(a) - 1, common - 1, -1):
            out.append({'op': 'remove', 'path': '%s/%d' % (path, i)})
        for i in range(common, len(b)):
            out.append({'op': 'add', 'path': '%s/%d' % (path, i), 'value': copy.deepcopy(b[i])})
        return
    out.append({'op': 'replace', 'path': path, 'value': copy.deepcopy(b)})


def diff(source, target):
    """Return a patch (list of operations) transforming ``source`` into ``target``."""
    out = []
    _diff(source, target, '', out)
    return out
