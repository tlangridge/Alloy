"""Which fire times are due when the scheduler wakes up."""
from .schedules import require_aware


def due_time(schedule, last_run, now):
    """The most recent fire time in (last_run, now], or None if none is due.

    Missed runs are coalesced: a job that should have fired three times while
    the process was down runs once.
    """
    require_aware(last_run, 'last_run')
    require_aware(now, 'now')
    latest = None
    fire = schedule.next_after(last_run)
    while fire <= now:
        latest = fire
        fire = schedule.next_after(fire)
    return latest
