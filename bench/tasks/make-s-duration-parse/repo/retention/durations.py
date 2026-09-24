"""Duration strings used in retention policies (e.g. ``keep = "30d"``)."""
import re

UNIT_SECONDS = {'w': 604800, 'd': 86400, 'h': 3600, 'm': 60, 's': 1}

_SINGLE = re.compile(r'^(\d+)([wdhms])$')


def parse_duration(text):
    """Return the number of seconds in a duration string such as ``"30d"``."""
    match = _SINGLE.match(text.strip())
    if not match:
        raise ValueError('invalid duration: %r' % (text,))
    return int(match.group(1)) * UNIT_SECONDS[match.group(2)]


def format_duration(seconds):
    """Return the canonical duration string for ``seconds``."""
    raise NotImplementedError('format_duration is not implemented yet')
