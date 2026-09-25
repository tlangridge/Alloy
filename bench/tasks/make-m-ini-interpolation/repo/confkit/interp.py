"""${...} interpolation.

* ``${key}`` looks up ``key`` in the section being resolved, then in
  [DEFAULT]; ``${section:key}`` looks in ``section`` (which must exist), then
  in [DEFAULT]. Keys are case-insensitive, section names are not.
* A value inherited from [DEFAULT] is interpolated in the context of the
  section that inherits it.
* ``$$`` is a literal ``$``; any other ``$`` not starting ``${`` is an error.
"""
from collections import OrderedDict

from confkit.errors import ConfigError

DEFAULT = 'DEFAULT'


class Resolver:
    def __init__(self, raw):
        self.sections = raw.sections
        self.defaults = raw.sections.get(DEFAULT, OrderedDict())
        # Each entry is interpolated once: big deploy configs reference the
        # same base paths hundreds of times.
        self._done = {}

    def lookup(self, section, key):
        entries = self.sections.get(section, {})
        if key in entries:
            return entries[key]
        return self.defaults.get(key)

    def resolve(self, section, entry, stack=()):
        if id(entry) in self._done:
            return self._done[id(entry)]
        stack = stack + ((section, entry.key),)
        text, pos, out = entry.value, 0, []
        while True:
            i = text.find('$', pos)
            if i < 0:
                out.append(text[pos:])
                break
            out.append(text[pos:i])
            if text.startswith('$$', i):
                out.append('$')
                pos = i + 2
                continue
            if not text.startswith('${', i):
                raise ConfigError("'$' must be followed by '{' or '$'", entry.lineno)
            j = text.find('}', i)
            if j < 0:
                raise ConfigError('unterminated ${ reference', entry.lineno)
            ref = text[i + 2:j]
            if ':' in ref:
                target_section, key = ref.split(':', 1)
                target_section = target_section.strip()
                if target_section not in self.sections:
                    raise ConfigError('undefined section in ${%s}' % ref, entry.lineno)
            else:
                target_section, key = section, ref
            key = key.strip().lower()
            target = self.lookup(target_section, key)
            if target is None:
                raise ConfigError('undefined reference ${%s}' % ref, entry.lineno)
            if (target_section, key) in stack:
                chain = ' -> '.join('%s:%s' % pair for pair in stack + ((target_section, key),))
                raise ConfigError('interpolation cycle: ' + chain, entry.lineno)
            out.append(self.resolve(target_section, target, stack))
            pos = j + 1
        value = ''.join(out)
        self._done[id(entry)] = value
        return value


def resolve_all(raw):
    """{section: {key: value}} for every section except DEFAULT.

    Sections come in file order; each maps its own keys in file order, then the
    keys it inherits from [DEFAULT] (in DEFAULT's order). Values are resolved
    in that same order.
    """
    resolver = Resolver(raw)
    result = OrderedDict()
    for name, entries in raw.sections.items():
        if name == DEFAULT:
            continue
        keys = list(entries) + [k for k in resolver.defaults if k not in entries]
        result[name] = OrderedDict((k, resolver.resolve(name, resolver.lookup(name, k))) for k in keys)
    return result
