"""Monthly billing periods anchored on a day of the month."""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BillingPeriod:
    start: date     # first day of the period (inclusive)
    end: date       # first day of the next period (exclusive)

    @property
    def days(self):
        return (self.end - self.start).days

    def __contains__(self, day):
        return self.start <= day < self.end


def _anchored(year, month, anchor_day):
    """The anchor day in that month, clamped to the month's length."""
    return date(year, month, min(anchor_day, monthrange(year, month)[1]))


def _shift(year, month, months):
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def monthly_period(anchor_day, on):
    """The billing period containing `on` for a subscription billed on `anchor_day`.

    anchor_day is 1-31; in shorter months the period starts on the last day.
    """
    if isinstance(anchor_day, bool) or not isinstance(anchor_day, int) or not 1 <= anchor_day <= 31:
        raise ValueError('anchor_day must be an integer from 1 to 31')
    start = _anchored(on.year, on.month, anchor_day)
    if start > on:
        start = _anchored(*_shift(on.year, on.month, -1), anchor_day)
    end = _anchored(*_shift(start.year, start.month, 1), anchor_day)
    return BillingPeriod(start, end)
