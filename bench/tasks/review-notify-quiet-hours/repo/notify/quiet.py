"""Daily do-not-disturb windows in local wall-clock time."""
from datetime import time


class QuietHours:
    """The half-open local-time window [start, end) in which nothing is sent.

    start > end wraps past midnight (22:00-07:00 covers 23:30 and 06:59 but not
    07:00). start == end means the user has no quiet hours.
    """

    def __init__(self, start, end):
        for name, value in (('start', start), ('end', end)):
            if not isinstance(value, time):
                raise TypeError('%s must be a datetime.time' % name)
            if value.tzinfo is not None:
                raise ValueError('%s must be a naive local time' % name)
        self.start = start
        self.end = end

    def __repr__(self):
        return 'QuietHours(%s-%s)' % (self.start.strftime('%H:%M'), self.end.strftime('%H:%M'))

    def contains(self, local_time):
        """True if the naive local wall-clock `local_time` is inside the window."""
        t = local_time.replace(tzinfo=None, fold=0)
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end


def is_quiet(now, tz, quiet):
    """True if the aware instant `now` falls in the user's quiet hours."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    return quiet.contains(now.astimezone(tz).time())
