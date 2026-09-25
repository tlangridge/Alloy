"""Grandfather-father-son retention planning for database backups.

`plan()` is pure: it never looks at the wall clock (the caller passes `now`)
and never deletes anything itself; the backup agent executes the plan.
"""
from collections import namedtuple
import datetime as _dt

REASONS = ('latest', 'pinned', 'daily', 'weekly', 'monthly')


class Backup(namedtuple('Backup', 'id taken_at pinned')):
    """One backup: a unique string id, a naive `datetime`, and a pin flag."""
    __slots__ = ()

    def __new__(cls, id, taken_at, pinned=False):
        return super(Backup, cls).__new__(cls, id, taken_at, pinned)


Plan = namedtuple('Plan', 'keep delete skipped reasons')


def _newest(items):
    """Greatest taken_at; ties go to the greatest id."""
    return max(items, key=lambda b: (b.taken_at, b.id))


def _day(t):
    return t.date()


def _iso_week(t):
    iso = t.isocalendar()
    return (iso[0], iso[1])


def _month(t):
    return (t.year, t.month)


def _bucket_keep(candidates, keyfunc, count):
    """The newest backup of each of the `count` most recent buckets that have backups."""
    if count == 0:
        return []
    buckets = {}
    for b in candidates:
        buckets.setdefault(keyfunc(b.taken_at), []).append(b)
    recent = sorted(buckets, reverse=True)[:count]
    return [_newest(buckets[key]) for key in recent]


def _check_count(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError('%s must be a non-negative integer, got %r' % (name, value))


def plan(backups, now, daily=7, weekly=4, monthly=6, max_age_days=None):
    """Return a Plan(keep, delete, skipped, reasons) for `backups` at time `now`."""
    _check_count('daily', daily)
    _check_count('weekly', weekly)
    _check_count('monthly', monthly)
    if max_age_days is not None and (not isinstance(max_age_days, int) or isinstance(max_age_days, bool)
                                     or max_age_days < 1):
        raise ValueError('max_age_days must be None or an integer >= 1, got %r' % (max_age_days,))
    backups = list(backups)
    ids = [b.id for b in backups]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate backup ids')

    skipped = [b.id for b in backups if b.taken_at > now]
    present = [b for b in backups if b.taken_at <= now]

    reasons = {}

    def add(b, why):
        reasons.setdefault(b.id, set()).add(why)

    if present:
        add(_newest(present), 'latest')
    for b in present:
        if b.pinned:
            add(b, 'pinned')
    rotating = [b for b in present if not b.pinned]
    for b in _bucket_keep(rotating, _day, daily):
        add(b, 'daily')
    for b in _bucket_keep(rotating, _iso_week, weekly):
        add(b, 'weekly')
    for b in _bucket_keep(rotating, _month, monthly):
        add(b, 'monthly')

    if max_age_days is not None:
        limit = _dt.timedelta(days=max_age_days)
        for b in present:
            why = reasons.get(b.id)
            if why and not why & {'latest', 'pinned'} and now - b.taken_at > limit:
                del reasons[b.id]

    order = lambda b: (b.taken_at, b.id)  # noqa: E731
    kept = sorted((b for b in present if b.id in reasons), key=order, reverse=True)
    gone = sorted((b for b in present if b.id not in reasons), key=order)
    keep = [b.id for b in kept]
    return Plan(keep=keep,
                delete=[b.id for b in gone],
                skipped=skipped,
                reasons={i: [r for r in REASONS if r in reasons[i]] for i in keep})
