"""Decide when a notification may be delivered."""
from datetime import datetime, timedelta, timezone


def next_delivery(now, tz, quiet):
    """Return the aware UTC instant at which a notification created at `now` may go out.

    Outside the user's quiet hours that is `now` itself. Inside them it is the
    next moment the user's local wall clock reads `quiet.end`, so a 07:00 end
    means 07:00 on the user's own clock.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    now = now.astimezone(timezone.utc)
    local = now.astimezone(tz)
    if not quiet.contains(local.time()):
        return now
    release = datetime.combine(local.date(), quiet.end, tzinfo=tz)
    if release <= local:
        release += timedelta(days=1)
    return release.astimezone(timezone.utc)
