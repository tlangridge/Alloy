"""Decide which snapshots a retention policy prunes."""
from .durations import parse_duration


def expired(snapshots, keep_for, now):
    """Return the sorted names of snapshots older than ``keep_for``.

    ``snapshots`` maps snapshot name -> creation time in POSIX seconds and
    ``now`` is the current time in POSIX seconds (injected by the caller).
    """
    limit = parse_duration(keep_for)
    return sorted(name for name, created in snapshots.items() if now - created > limit)
