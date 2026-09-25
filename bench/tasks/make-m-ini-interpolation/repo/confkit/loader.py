"""Public entry point: load(text) -> Config."""
from confkit.errors import ConfigError
from confkit.interp import DEFAULT, resolve_all
from confkit.parser import parse


class Config:
    def __init__(self, values, raw):
        self._values = values
        self._raw = raw

    def sections(self):
        return list(self._values)

    def __getitem__(self, section):
        return dict(self._values[section])

    def get(self, section, key, default=None):
        return self._values.get(section, {}).get(key.lower(), default)

    def _entry(self, section, key):
        entries = self._raw.sections.get(section, {})
        return entries.get(key) or self._raw.sections.get(DEFAULT, {}).get(key)

    def getint(self, section, key):
        key = key.lower()
        value = self._values[section][key]
        try:
            return int(value)
        except ValueError:
            raise ConfigError('[%s] %s: %r is not an integer' % (section, key, value),
                              self._entry(section, key).lineno)


def load(text):
    raw = parse(text)
    return Config(resolve_all(raw), raw)
