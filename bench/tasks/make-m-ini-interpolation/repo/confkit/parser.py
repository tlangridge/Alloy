"""Group logical lines into sections of raw (uninterpolated) entries."""
from collections import OrderedDict

from confkit.errors import ConfigError
from confkit.lexer import logical_lines


class Entry:
    __slots__ = ('key', 'value', 'lineno')

    def __init__(self, key, value, lineno):
        self.key = key
        self.value = value
        self.lineno = lineno

    def __repr__(self):
        return 'Entry(%r, %r, line %d)' % (self.key, self.value, self.lineno)


class RawConfig:
    def __init__(self):
        self.sections = OrderedDict()  # section name -> OrderedDict(key -> Entry)


def parse(text):
    raw = RawConfig()
    current = None
    for item in logical_lines(text):
        if item.kind == 'section':
            if item.name in raw.sections:
                raise ConfigError('duplicate section [%s]' % item.name, item.lineno)
            current = raw.sections[item.name] = OrderedDict()
            continue
        if current is None:
            raise ConfigError('key %r outside any section' % item.name, item.lineno)
        if item.name in current:
            raise ConfigError('duplicate key %r' % item.name, item.lineno)
        current[item.name] = Entry(item.name, item.value, item.lineno)
    return raw
