"""Turn configuration text into logical lines (sections and key/value entries).

* Blank lines end the current value.
* Comment lines start with '#' or ';' after optional indentation; they are
  skipped and do NOT end the current value.
* An indented non-comment line continues the value of the entry above it;
  the pieces are joined with single spaces.
* An inline comment starts at '#' or ';' preceded by whitespace.
"""
import re

from confkit.errors import ConfigError

_SECTION = re.compile(r'^\[([^\[\]]+)\]$')
_INLINE_COMMENT = re.compile(r'\s[#;]')


class Logical:
    __slots__ = ('lineno', 'kind', 'name', 'value')

    def __init__(self, lineno, kind, name, value=None):
        self.lineno = lineno   # line the section header / entry starts on
        self.kind = kind       # 'section' or 'entry'
        self.name = name
        self.value = value

    def __repr__(self):
        return 'Logical(%d, %r, %r, %r)' % (self.lineno, self.kind, self.name, self.value)


def _strip_comment(text):
    m = _INLINE_COMMENT.search(text)
    return (text[:m.start()] if m else text).strip()


def logical_lines(text):
    out = []
    pending = None  # the entry whose value may still continue
    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            pending = None
            continue
        if stripped[0] in '#;':
            continue
        if raw[0] in ' \t':
            if pending is None:
                raise ConfigError('continuation line without a preceding key', lineno)
            piece = _strip_comment(stripped)
            pending.value = (pending.value + ' ' + piece).strip() if piece else pending.value
            pending.lineno = lineno  # keep the position current for error reporting
            continue
        pending = None
        line = _strip_comment(stripped)
        m = _SECTION.match(line)
        if m:
            out.append(Logical(lineno, 'section', m.group(1).strip()))
            continue
        seps = [i for i in (line.find('='), line.find(':')) if i >= 0]
        if not seps:
            raise ConfigError('expected "key = value" or "[section]"', lineno)
        sep = min(seps)
        key = line[:sep].strip().lower()
        if not key:
            raise ConfigError('empty key', lineno)
        pending = Logical(lineno, 'entry', key, line[sep + 1:].strip())
        out.append(pending)
    return out
