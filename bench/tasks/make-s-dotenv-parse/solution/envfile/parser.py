"""Parse ``.env`` files into a dict of environment variables."""
import re

_KEY = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
_EXPORT = re.compile(r'export[ \t]+')
_COMMENT = re.compile(r'[ \t]#')
_ESCAPES = {'n': '\n', 't': '\t', '"': '"', '\\': '\\'}


class DotenvError(ValueError):
    """A malformed ``.env`` line; ``lineno`` is the 1-based line number."""

    def __init__(self, lineno, message):
        super().__init__('line %d: %s' % (lineno, message))
        self.lineno = lineno


def parse_env(text):
    """Return a dict mapping variable names to string values."""
    result = {}
    for lineno, line in enumerate(text.split('\n'), 1):
        if line.endswith('\r'):
            line = line[:-1]
        body = line.strip()
        if not body or body.startswith('#'):
            continue
        export = _EXPORT.match(body)
        if export:
            body = body[export.end():]
        key, sep, raw = body.partition('=')
        if not sep:
            raise DotenvError(lineno, 'expected KEY=VALUE')
        key = key.strip()
        if not _KEY.match(key):
            raise DotenvError(lineno, 'invalid key %r' % (key,))
        result[key] = _value(raw, lineno)
    return result


def _value(raw, lineno):
    text = raw.lstrip(' \t')
    if text.startswith('"'):
        return _double_quoted(text, lineno)
    if text.startswith("'"):
        end = text.find("'", 1)
        if end < 0:
            raise DotenvError(lineno, 'unterminated single-quoted value')
        _check_tail(text[end + 1:], lineno)
        return text[1:end]
    comment = _COMMENT.search(raw)
    if comment:
        raw = raw[:comment.start()]
    return raw.strip()


def _double_quoted(text, lineno):
    out = []
    i = 1
    while i < len(text):
        char = text[i]
        if char == '\\' and i + 1 < len(text):
            following = text[i + 1]
            out.append(_ESCAPES.get(following, '\\' + following))
            i += 2
            continue
        if char == '"':
            _check_tail(text[i + 1:], lineno)
            return ''.join(out)
        out.append(char)
        i += 1
    raise DotenvError(lineno, 'unterminated double-quoted value')


def _check_tail(tail, lineno):
    rest = tail.strip()
    if rest and not rest.startswith('#'):
        raise DotenvError(lineno, 'unexpected text after closing quote: %r' % (rest,))
