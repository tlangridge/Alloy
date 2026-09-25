"""A parsed schedule and occurrence computation."""
import calendar
import datetime

HORIZON_YEARS = 8
_MINUTE = datetime.timedelta(minutes=1)


class DaySpec(object):
    """A restricted day-of-month or day-of-week field."""

    def __init__(self):
        self.values = set()          # plain days (1..31) or weekdays (0=Sunday..6)
        self.last = False            # 'L'
        self.last_offsets = set()    # 'L-n'
        self.nth = set()             # (weekday, k) for 'V#k'
        self.last_weekdays = set()   # weekday for 'VL'


def _cron_weekday(d):
    return (d.weekday() + 1) % 7   # Python: Monday=0; cron: Sunday=0


def _check(when):
    if not isinstance(when, datetime.datetime):
        raise TypeError('expected a datetime')
    if when.tzinfo is not None:
        raise ValueError('schedules work on naive datetimes only')


class Schedule(object):
    """Created by :func:`cadence.parse`."""

    def __init__(self, expression, minutes, hours, dom, months, dow):
        self.expression = expression
        self.minutes = sorted(minutes)
        self.hours = sorted(hours)
        self.months = frozenset(months)
        self.dom = dom   # DaySpec or None (unrestricted)
        self.dow = dow   # DaySpec or None (unrestricted)

    # -- day logic -------------------------------------------------------------
    def _dom_match(self, d, last):
        spec = self.dom
        return (d.day in spec.values or (spec.last and d.day == last)
                or any(d.day == last - n for n in spec.last_offsets))

    def _dow_match(self, d, last):
        spec = self.dow
        wd = _cron_weekday(d)
        return (wd in spec.values or (wd, (d.day - 1) // 7 + 1) in spec.nth
                or (wd in spec.last_weekdays and d.day + 7 > last))

    def day_matches(self, d):
        if d.month not in self.months:
            return False
        last = calendar.monthrange(d.year, d.month)[1]
        if self.dom is not None and self.dow is not None:
            return self._dom_match(d, last) or self._dow_match(d, last)
        if self.dom is not None:
            return self._dom_match(d, last)
        if self.dow is not None:
            return self._dow_match(d, last)
        return True

    # -- public API ------------------------------------------------------------
    def matches(self, when):
        _check(when)
        return when.minute in self.minutes and when.hour in self.hours and self.day_matches(when.date())

    def next_after(self, when):
        _check(when)
        start = when.replace(second=0, microsecond=0) + _MINUTE
        day = start.date()
        limit = datetime.date(when.year + HORIZON_YEARS, 12, 31)
        while day <= limit:
            if self.day_matches(day):
                for hour in self.hours:
                    for minute in self.minutes:
                        candidate = datetime.datetime(day.year, day.month, day.day, hour, minute)
                        if candidate >= start:
                            return candidate
            day += datetime.timedelta(days=1)
        return None

    def previous_before(self, when):
        _check(when)
        day = when.date()
        limit = datetime.date(when.year - HORIZON_YEARS, 1, 1)
        while day >= limit:
            if self.day_matches(day):
                for hour in reversed(self.hours):
                    for minute in reversed(self.minutes):
                        candidate = datetime.datetime(day.year, day.month, day.day, hour, minute)
                        if candidate < when:
                            return candidate
            day -= datetime.timedelta(days=1)
        return None

    def occurrences(self, after, count):
        out = []
        current = after
        while len(out) < count:
            current = self.next_after(current)
            if current is None:
                break
            out.append(current)
        return out
