"""Monthly subscription periods."""
import calendar
from datetime import date


def add_months(day, months):
    """Return ``day`` shifted by ``months`` calendar months (may be negative).

    The day of month is clamped to the last day of the target month, so
    Jan 31 + 1 month is Feb 28 (Feb 29 in leap years).
    """
    year, month0 = divmod(day.year * 12 + (day.month - 1) + months, 12)
    month = month0 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def next_renewal(anchor, after):
    """Return the first renewal date strictly after ``after``."""
    k = max(1, (after.year - anchor.year) * 12 + (after.month - anchor.month))
    current = add_months(anchor, k)
    while current <= after:
        k += 1
        current = add_months(anchor, k)
    return current


def renewals(anchor, count):
    """Return the first ``count`` renewal dates of a subscription anchored at ``anchor``."""
    return [add_months(anchor, k) for k in range(1, count + 1)]
