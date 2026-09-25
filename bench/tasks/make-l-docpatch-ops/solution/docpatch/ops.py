"""Applying patches."""
import copy

from .equality import is_number, json_equal
from .errors import PatchError
from .pointer import array_index, parse_pointer, walk

OPS = ('add', 'remove', 'replace', 'move', 'copy', 'test', 'inc')


def _validate(patch):
    """Structural validation of the whole patch; returns parsed pointers."""
    if not isinstance(patch, list):
        raise PatchError('invalid-op', None, None, 'patch must be a list')
    parsed = []
    for i, op in enumerate(patch):
        if not isinstance(op, dict):
            raise PatchError('invalid-op', i, None, 'operation must be an object')
        name = op.get('op')
        if not isinstance(name, str) or name not in OPS:
            raise PatchError('invalid-op', i, None, 'unknown op')
        if 'path' not in op or not isinstance(op['path'], str):
            raise PatchError('invalid-op', i, None, 'missing path')
        path = parse_pointer(op['path'], i)
        source = None
        if name in ('add', 'replace', 'test') and 'value' not in op:
            raise PatchError('invalid-op', i, op['path'], 'missing value')
        if name in ('move', 'copy'):
            if 'from' not in op or not isinstance(op['from'], str):
                raise PatchError('invalid-op', i, op['path'], 'missing from')
            source = parse_pointer(op['from'], i)
        if name == 'inc' and not is_number(op.get('by')):
            raise PatchError('invalid-op', i, op['path'], 'by must be a number')
        parsed.append((name, path, source))
    return parsed


def _parent(doc, tokens, index, pointer):
    return walk(doc, tokens[:-1], index, pointer)


def _add(doc, tokens, value, index, pointer):
    if not tokens:
        return value
    parent = _parent(doc, tokens, index, pointer)
    last = tokens[-1]
    if isinstance(parent, dict):
        parent[last] = value
    elif isinstance(parent, list):
        if last == '-':
            parent.append(value)
        else:
            i = array_index(last, index, pointer)
            if i > len(parent):
                raise PatchError('path-not-found', index, pointer)
            parent.insert(i, value)
    else:
        raise PatchError('path-not-found', index, pointer)
    return doc


def _remove(doc, tokens, index, pointer):
    """Remove and return the value at tokens (tokens non-empty)."""
    walk(doc, tokens, index, pointer)  # existence + index validation
    parent = _parent(doc, tokens, index, pointer)
    last = tokens[-1]
    if isinstance(parent, dict):
        return parent.pop(last)
    return parent.pop(int(last))


def _set_existing(doc, tokens, value, index, pointer):
    if not tokens:
        return value
    walk(doc, tokens, index, pointer)
    parent = _parent(doc, tokens, index, pointer)
    last = tokens[-1]
    if isinstance(parent, dict):
        parent[last] = value
    else:
        parent[int(last)] = value
    return doc


def apply_patch(document, patch):
    """Apply the list of operations ``patch`` to ``document`` and return the
    resulting document."""
    parsed = _validate(patch)
    doc = copy.deepcopy(document)
    for i, (op, (name, path, source)) in enumerate(zip(patch, parsed)):
        pointer = op['path']
        if name == 'add':
            doc = _add(doc, path, copy.deepcopy(op['value']), i, pointer)
        elif name == 'remove':
            if not path:
                raise PatchError('cannot-remove-root', i, pointer)
            _remove(doc, path, i, pointer)
        elif name == 'replace':
            doc = _set_existing(doc, path, copy.deepcopy(op['value']), i, pointer)
        elif name == 'test':
            current = walk(doc, path, i, pointer)
            if not json_equal(current, op['value']):
                raise PatchError('test-failed', i, pointer)
        elif name == 'inc':
            current = walk(doc, path, i, pointer)
            if not is_number(current):
                raise PatchError('type-mismatch', i, pointer)
            by = op['by']
            result = current + by
            if not (isinstance(current, int) and isinstance(by, int)):
                result = float(result)
            doc = _set_existing(doc, path, result, i, pointer)
        elif name == 'copy':
            value = copy.deepcopy(walk(doc, source, i, op['from']))
            doc = _add(doc, path, value, i, pointer)
        else:  # move
            value = walk(doc, source, i, op['from'])
            if source == path:
                continue
            if len(source) < len(path) and path[:len(source)] == source:
                raise PatchError('move-into-self', i, pointer)
            _remove(doc, source, i, op['from'])
            doc = _add(doc, path, value, i, pointer)
    return doc
