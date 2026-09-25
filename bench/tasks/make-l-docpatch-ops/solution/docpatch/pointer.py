"""Pointer parsing, formatting and resolution."""
import re

from .errors import PatchError

_INDEX = re.compile(r'(0|[1-9][0-9]*)\Z')


def parse_pointer(pointer, index=None):
    """Return the list of reference tokens for ``pointer``."""
    if not isinstance(pointer, str):
        raise PatchError('invalid-pointer', index, pointer)
    if pointer == '':
        return []
    if not pointer.startswith('/'):
        raise PatchError('invalid-pointer', index, pointer)
    tokens = []
    for raw in pointer[1:].split('/'):
        out, i = [], 0
        while i < len(raw):
            ch = raw[i]
            if ch == '~':
                nxt = raw[i + 1] if i + 1 < len(raw) else ''
                if nxt == '0':
                    out.append('~')
                elif nxt == '1':
                    out.append('/')
                else:
                    raise PatchError('invalid-pointer', index, pointer)
                i += 2
            else:
                out.append(ch)
                i += 1
        tokens.append(''.join(out))
    return tokens


def escape_token(token):
    return token.replace('~', '~0').replace('/', '~1')


def format_pointer(tokens):
    """Inverse of :func:`parse_pointer`."""
    return ''.join('/' + escape_token(t) for t in tokens)


def array_index(token, index=None, pointer=None):
    """Return the int for a valid array index token or raise invalid-index."""
    if not _INDEX.match(token):
        raise PatchError('invalid-index', index, pointer)
    return int(token)


def walk(document, tokens, index=None, pointer=None):
    """Follow ``tokens`` from ``document`` and return the value reached."""
    current = document
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                raise PatchError('path-not-found', index, pointer)
            current = current[token]
        elif isinstance(current, list):
            i = array_index(token, index, pointer)
            if i >= len(current):
                raise PatchError('path-not-found', index, pointer)
            current = current[i]
        else:
            raise PatchError('path-not-found', index, pointer)
    return current


def resolve(document, pointer):
    """Return the value ``pointer`` refers to inside ``document``."""
    return walk(document, parse_pointer(pointer), None, pointer)
