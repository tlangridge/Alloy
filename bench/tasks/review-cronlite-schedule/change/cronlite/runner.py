"""Which fire times are due when the scheduler wakes up."""
from collections import deque

from .schedules import require_aware

CATCH_UP = ('latest', 'all')


def due_times(schedule, last_run, now, catch_up='latest', limit=100):
    """Fire times in (last_run, now] to run now, in chronological order.

    catch_up='latest' coalesces missed runs into the most recent one;
    catch_up='all' replays every missed fire time, keeping only the latest
    `limit` of them (older ones are dropped, not run late).
    """
    if catch_up not in CATCH_UP:
        raise ValueError('catch_up must be one of %s' % ', '.join(CATCH_UP))
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError('limit must be a positive integer')
    require_aware(last_run, 'last_run')
    require_aware(now, 'now')
    kept = deque(maxlen=1 if catch_up == 'latest' else limit)
    fire = schedule.next_after(last_run)
    while fire <= now:
        kept.append(fire)
        fire = schedule.next_after(fire)
    return list(kept)


def due_time(schedule, last_run, now):
    """The most recent fire time in (last_run, now], or None if none is due.

    Missed runs are coalesced: a job that should have fired three times while
    the process was down runs once.
    """
    times = due_times(schedule, last_run, now, 'latest')
    return times[-1] if times else None
