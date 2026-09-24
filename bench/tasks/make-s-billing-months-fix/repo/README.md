# billing

Date arithmetic for monthly subscriptions. A subscription's *anchor* is the
date it started; it renews every month on the anchor's day of month, clamped
to the end of shorter months.

```python
from datetime import date
from billing.periods import add_months, next_renewal, renewals

add_months(date(2024, 1, 31), 1)                     # date(2024, 2, 29)
next_renewal(date(2024, 3, 10), date(2024, 5, 1))    # date(2024, 5, 10)
renewals(date(2024, 3, 10), 3)                       # Apr 10, May 10, Jun 10
```

Run the tests with `python3 -m unittest discover -s tests -v`.
