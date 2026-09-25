"""Parsing schedule expressions."""
import re

from .errors import CronSyntaxError
from .fields import FIELDS, MACROS
from .schedule import DaySpec, Schedule

_NUM = re.compile(r'[0-9]+\Z')
_LAST_OFFSET = re.compile(r'L-([0-9]+)\Z')


def _fail(spec, item, message='invalid item'):
    raise CronSyntaxError(message, spec.name, item)


def _value(token, spec, item):
    if _NUM.match(token):
        value = int(token)
    elif token.upper() in spec.names:
        value = spec.names[token.upper()]
    else:
        _fail(spec, item, 'invalid value %r' % token)
    if not spec.low <= value <= spec.high:
        _fail(spec, item, 'value out of range')
    return value


def _sequence(base, spec, item):
    """Values of '*', 'V', 'V-W' (without step), in order."""
    is_dow = spec.name == 'day_of_week'
    if base == '*':
        return list(range(spec.low, spec.star_high + 1)), True
    if '-' in base:
        left, _, right = base.partition('-')
        start, end = _value(left, spec, item), _value(right, spec, item)
        if is_dow and start == 7:
            start = 0
        if start <= end:
            return list(range(start, end + 1)), True
        if not is_dow:
            _fail(spec, item, 'range start is after its end')
        return list(range(start, 7)) + list(range(0, end + 1)), True
    return [_value(base, spec, item)], False


def _generic(item, spec):
    base, slash, step_text = item.partition('/')
    values, is_range = _sequence(base, spec, item)
    if slash:
        if not _NUM.match(step_text) or int(step_text) < 1:
            _fail(spec, item, 'invalid step')
        step = int(step_text)
        if not is_range:
            start = values[0]
            if spec.name == 'day_of_week' and start == 7:
                start = 0
            values = list(range(start, spec.star_high + 1))
        values = values[::step]
    if spec.name == 'day_of_week':
        values = [0 if v == 7 else v for v in values]
    return values


def _field(text, spec, day):
    """Parse one field. ``day`` is a DaySpec for the two day fields, else None."""
    if text in ('*', '?') and day is not None:
        return None
    values = set()
    for item in text.split(','):
        if item == '':
            _fail(spec, item, 'empty item')
        if item == '?':
            _fail(spec, item, '? must be the whole field')
        if spec.name == 'day_of_month':
            if item == 'L':
                day.last = True
                continue
            m = _LAST_OFFSET.match(item)
            if m:
                n = int(m.group(1))
                if not 1 <= n <= 30:
                    _fail(spec, item, 'L-n needs 1 <= n <= 30')
                day.last_offsets.add(n)
                continue
        if spec.name == 'day_of_week':
            if '#' in item:
                left, _, right = item.partition('#')
                weekday = _value(left, spec, item) % 7
                if not _NUM.match(right) or not 1 <= int(right) <= 5:
                    _fail(spec, item, '# needs 1..5')
                day.nth.add((weekday, int(right)))
                continue
            if len(item) > 1 and item[-1] in 'lL':
                day.last_weekdays.add(_value(item[:-1], spec, item) % 7)
                continue
        values.update(_generic(item, spec))
    if day is not None:
        day.values = values
        return day
    return values


def parse(expression):
    """Parse ``expression`` and return a :class:`cadence.schedule.Schedule`."""
    if not isinstance(expression, str):
        raise TypeError('expression must be a str')
    text = expression.strip(' \t')
    if text.startswith('@'):
        if text.lower() not in MACROS:
            raise CronSyntaxError('unknown macro %r' % text, None, text)
        text = MACROS[text.lower()]
    parts = re.split(r'[ \t]+', text) if text else []
    if len(parts) != 5:
        raise CronSyntaxError('expected 5 fields, got %d' % len(parts))
    minute = _field(parts[0], FIELDS[0], None)
    hour = _field(parts[1], FIELDS[1], None)
    dom = _field(parts[2], FIELDS[2], DaySpec())
    month = _field(parts[3], FIELDS[3], None)
    dow = _field(parts[4], FIELDS[4], DaySpec())
    return Schedule(expression, minute, hour, dom, month, dow)
