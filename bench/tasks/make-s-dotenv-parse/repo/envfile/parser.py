"""Parse ``.env`` files into a dict of environment variables."""


class DotenvError(ValueError):
    """A malformed ``.env`` line; ``lineno`` is the 1-based line number."""

    def __init__(self, lineno, message):
        super().__init__('line %d: %s' % (lineno, message))
        self.lineno = lineno


def parse_env(text):
    """Return a dict mapping variable names to string values."""
    result = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise DotenvError(lineno, 'expected KEY=VALUE')
        key, value = line.split('=', 1)
        result[key.strip()] = value.strip()
    return result
