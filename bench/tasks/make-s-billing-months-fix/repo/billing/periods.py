"""Monthly subscription periods."""
import calendar
from datetime import date


def add_months(day, months):
    """Return ``day`` shifted by ``months`` calendar months (may be negative).

    The day of month is clamped to the last day of the target month, so
    Jan 31 + 1 month is Feb 28 (Feb 29 in leap years).
    """
    year = day.year + (day.month + months) // 12
    month = (day.month + months) % 12
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def next_renewal(anchor, after):
    """Return the first renewal date strictly after ``after``."""
    current = add_months(anchor, 1)
    while current <= after:
        current = add_months(current, 1)
    return current


def renewals(anchor, count):
    """Return the first ``count`` renewal dates of a subscription anchored at ``anchor``."""
    out = []
    current = anchor
    for _ in range(count):
        current = add_months(current, 1)
        out.append(current)
    return out
