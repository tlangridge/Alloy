"""Duration strings used in retention policies (e.g. ``keep = "30d"``)."""
import re

UNIT_SECONDS = {'w': 604800, 'd': 86400, 'h': 3600, 'm': 60, 's': 1}
_ORDER = 'wdhms'

_BARE = re.compile(r'[0-9]+')
_COMPONENT = re.compile(r'([0-9]+)([wdhmsWDHMS])')
_SPACE = re.compile(r'\s*')


def parse_duration(text):
    """Return the number of seconds in a duration string such as ``"1h30m"``."""
    if not isinstance(text, str):
        raise TypeError('duration must be a str, not %s' % type(text).__name__)
    body = text.strip()
    if not body:
        raise ValueError('empty duration')
    if _BARE.fullmatch(body):
        return int(body)
    total = 0
    last_rank = -1
    pos = 0
    while pos < len(body):
        pos = _SPACE.match(body, pos).end()
        match = _COMPONENT.match(body, pos)
        if match is None:
            raise ValueError('invalid duration: %r' % (text,))
        unit = match.group(2).lower()
        rank = _ORDER.index(unit)
        if rank <= last_rank:
            raise ValueError('units out of order or repeated in %r' % (text,))
        last_rank = rank
        total += int(match.group(1)) * UNIT_SECONDS[unit]
        pos = match.end()
    return total


def format_duration(seconds):
    """Return the canonical duration string for ``seconds`` (e.g. ``"1h30m"``)."""
    if seconds < 0:
        raise ValueError('negative duration: %r' % (seconds,))
    if seconds == 0:
        return '0s'
    parts = []
    for unit in _ORDER:
        count, seconds = divmod(seconds, UNIT_SECONDS[unit])
        if count:
            parts.append('%d%s' % (count, unit))
    return ''.join(parts)
