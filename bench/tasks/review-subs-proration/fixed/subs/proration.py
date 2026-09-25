"""Mid-period plan changes (upgrades and downgrades)."""
from decimal import ROUND_HALF_UP, localcontext

from .invoice import LineItem
from .money import CENT


def remaining_days(period, change_date):
    """Days from change_date (inclusive) to the end of the period (exclusive)."""
    if change_date not in period:
        raise ValueError('%s is outside the billing period %s..%s' % (change_date, period.start, period.end))
    return (period.end - change_date).days


def _prorated(price, days, total_days):
    """price * days / total_days with exact Decimal arithmetic, rounded once."""
    with localcontext() as ctx:
        ctx.rounding = ROUND_HALF_UP
        exact = price * days / total_days
    return exact.quantize(CENT, rounding=ROUND_HALF_UP)


def plan_change_lines(old_plan, new_plan, period, change_date):
    """Proration lines for switching plans on change_date within period.

    Returns [credit for the unused part of old_plan (negative),
             charge for the remaining part of new_plan], or [] if the plan
    does not actually change.
    """
    if old_plan.currency != new_plan.currency:
        raise ValueError('cannot prorate between %s and %s' % (old_plan.currency, new_plan.currency))
    days = remaining_days(period, change_date)
    if old_plan.code == new_plan.code:
        return []
    total = period.days
    credit = _prorated(old_plan.monthly_price, days, total)
    charge = _prorated(new_plan.monthly_price, days, total)
    return [
        LineItem('Unused time on %s (%d of %d days)' % (old_plan.name, days, total), -credit, 'proration'),
        LineItem('Remaining time on %s (%d of %d days)' % (new_plan.name, days, total), charge, 'proration'),
    ]


def apply_plan_change(invoice, old_plan, new_plan, period, change_date):
    """Add the proration lines to `invoice` and return their net amount."""
    if invoice.currency != new_plan.currency:
        raise ValueError('invoice is in %s, plan in %s' % (invoice.currency, new_plan.currency))
    lines = plan_change_lines(old_plan, new_plan, period, change_date)
    for line in lines:
        invoice.add(line)
    return sum((line.amount for line in lines), CENT * 0)
