"""Schedules.

A schedule is any object with next_after(instant) returning the first fire
time strictly after the aware datetime `instant`, as an aware UTC datetime.
"""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def require_aware(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('%s must be a timezone-aware datetime' % name)
    return value


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
