"""Load a ``.env`` file into an environment mapping."""
import os

from .parser import parse_env


def load_env(path, environ=None, override=False):
    """Parse ``path`` and copy its variables into ``environ`` (default ``os.environ``).

    Variables already present in ``environ`` are kept unless ``override`` is
    true. Returns the parsed dict.
    """
    if environ is None:
        environ = os.environ
    with open(path, encoding='utf-8') as handle:
        values = parse_env(handle.read())
    for key, value in values.items():
        if override or key not in environ:
            environ[key] = value
    return values
