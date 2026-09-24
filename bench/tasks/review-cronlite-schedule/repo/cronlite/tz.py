"""Time zones with United States daylight-saving rules (2007 onwards).

DST starts at 02:00 local standard time on the second Sunday of March and ends
at 02:00 local daylight time on the first Sunday of November. The classes
follow PEP 495: in the repeated hour after DST ends, fold=0 is the first
(daylight) occurrence and fold=1 the second (standard) one; for a wall time in
the skipped hour, fold=0 uses the offset from before the transition.
"""
from datetime import datetime, timedelta, timezone, tzinfo

ZERO = timedelta(0)
HOUR = timedelta(hours=1)
UTC = timezone.utc


def _first_sunday_on_or_after(dt):
    return dt + timedelta(days=(6 - dt.weekday()) % 7)


def us_dst_range(year):
    """Naive local (start, end) datetimes of DST for `year`."""
    start = _first_sunday_on_or_after(datetime(year, 3, 8, 2))
    end = _first_sunday_on_or_after(datetime(year, 11, 1, 2))
    return start, end


class USTimeZone(tzinfo):
    def __init__(self, hours, std_name, dst_name):
        self.stdoffset = timedelta(hours=hours)
        self.std_name = std_name
        self.dst_name = dst_name

    def __repr__(self):
        return 'USTimeZone(%s)' % self.std_name

    def tzname(self, dt):
        return self.dst_name if self.dst(dt) else self.std_name

    def utcoffset(self, dt):
        return self.stdoffset + self.dst(dt)

    def dst(self, dt):
        if dt is None or dt.tzinfo is None:
            return ZERO
        start, end = us_dst_range(dt.year)
        naive = dt.replace(tzinfo=None)
        if start + HOUR <= naive < end - HOUR:
            return HOUR                              # plainly in DST
        if end - HOUR <= naive < end:
            return ZERO if dt.fold else HOUR         # repeated hour
        if start <= naive < start + HOUR:
            return HOUR if dt.fold else ZERO         # skipped hour
        return ZERO

    def fromutc(self, dt):
        if dt.tzinfo is not self:
            raise ValueError('fromutc: dt.tzinfo is not self')
        start, end = us_dst_range(dt.year)
        start = start.replace(tzinfo=self)
        end = end.replace(tzinfo=self)
        std_time = dt + self.stdoffset
        dst_time = std_time + HOUR
        if end <= dst_time < end + HOUR:
            return std_time.replace(fold=1)          # second pass of the repeated hour
        if std_time < start or dst_time >= end:
            return std_time
        return dst_time


EASTERN = USTimeZone(-5, 'EST', 'EDT')
CENTRAL = USTimeZone(-6, 'CST', 'CDT')
MOUNTAIN = USTimeZone(-7, 'MST', 'MDT')
PACIFIC = USTimeZone(-8, 'PST', 'PDT')
