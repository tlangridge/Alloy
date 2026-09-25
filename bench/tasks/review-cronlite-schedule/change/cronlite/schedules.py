"""Schedules.

A schedule is any object with next_after(instant) returning the first fire
time strictly after the aware datetime `instant`, as an aware UTC datetime.
"""
import calendar
from datetime import datetime, time, timedelta, timezone, tzinfo

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Every wall-clock schedule fires at least once a month, so a match is always
# found long before this many days.
_SEARCH_DAYS = 400


def require_aware(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('%s must be a timezone-aware datetime' % name)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class EveryMinutes:
    """Fire every n minutes on UTC boundaries aligned to the Unix epoch."""

    def __init__(self, n):
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError('n must be a positive integer')
        self.n = n

    def __repr__(self):
        return 'EveryMinutes(%d)' % self.n

    def next_after(self, instant):
        require_aware(instant, 'instant')
        step = timedelta(minutes=self.n)
        return EPOCH + ((instant - EPOCH) // step + 1) * step


class _WallClock:
    """Fires at local wall-clock time `at` in `tz` on the days _fires_on() accepts.

    The fire time for a local date is datetime.combine(day, at, tzinfo=tz)
    with fold=0, converted to UTC. cronlite.tz follows PEP 495, where fold=0
    resolves a wall time repeated after DST ends to its first occurrence, and
    a wall time skipped when DST starts with the pre-transition offset (02:30
    becomes 03:30 daylight time). Both DST edge cases therefore fall out of the
    conversion itself and need no special handling here.
    """

    def __init__(self, at, tz):
        if not isinstance(at, time) or at.tzinfo is not None:
            raise ValueError('at must be a naive datetime.time')
        if not isinstance(tz, tzinfo):
            raise ValueError('tz must be a tzinfo instance')
        self.at = at.replace(fold=0)     # a caller's fold=1 would select the second occurrence
        self.tz = tz

    def _fires_on(self, day):
        raise NotImplementedError

    def fire_time(self, day):
        """The UTC instant at which this schedule fires on local date `day`."""
        return datetime.combine(day, self.at, tzinfo=self.tz).astimezone(UTC)

    def next_after(self, instant):
        require_aware(instant, 'instant')
        # Fire times strictly increase from one local date to the next (days are
        # 23-25 hours long), so scanning dates in order and returning the first
        # fire time after `instant` is correct. Starting one day before the
        # local date of `instant` keeps that true for any tz, even one that
        # changes offset around midnight.
        day = instant.astimezone(self.tz).date() - timedelta(days=1)
        for _ in range(_SEARCH_DAYS):
            if self._fires_on(day):
                fire = self.fire_time(day)
                if fire > instant:
                    return fire
            day += timedelta(days=1)
        raise RuntimeError('no fire time within %d days of %s' % (_SEARCH_DAYS, instant))


class DailyAt(_WallClock):
    """Every day at local time `at`."""

    def __repr__(self):
        return 'DailyAt(%s, %r)' % (self.at.isoformat(), self.tz)

    def _fires_on(self, day):
        return True


class WeeklyAt(_WallClock):
    """At local time `at` on the given weekdays (0 = Monday ... 6 = Sunday)."""

    def __init__(self, at, weekdays, tz):
        super().__init__(at, tz)
        try:
            days = frozenset(weekdays)
        except TypeError:
            raise ValueError('weekdays must be a collection of ints 0-6') from None
        if not days or not all(_is_int(d) and 0 <= d <= 6 for d in days):
            raise ValueError('weekdays must be a non-empty collection of ints 0-6')
        self.weekdays = days

    def __repr__(self):
        return 'WeeklyAt(%s, %s, %r)' % (self.at.isoformat(), sorted(self.weekdays), self.tz)

    def _fires_on(self, day):
        return day.weekday() in self.weekdays


class MonthlyAt(_WallClock):
    """At local time `at` on day `day` of each month; shorter months use their last day."""

    def __init__(self, day, at, tz):
        super().__init__(at, tz)
        if not _is_int(day) or not 1 <= day <= 31:
            raise ValueError('day must be an int from 1 to 31')
        self.day = day

    def __repr__(self):
        return 'MonthlyAt(%d, %s, %r)' % (self.day, self.at.isoformat(), self.tz)

    def _fires_on(self, day):
        return day.day == min(self.day, calendar.monthrange(day.year, day.month)[1])
