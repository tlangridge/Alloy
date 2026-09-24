# cadence

Schedule expressions for the internal job runner (`cadence/jobs.py`).
An expression has five fields — `minute hour day_of_month month day_of_week`
— plus a few `@macros`. The complete, authoritative rules are in the task
specification; they intentionally differ from classic cron in places (for
example how day-of-month and day-of-week combine).

```python
from datetime import datetime
from cadence import parse
parse('30 9 * * MON-FRI').next_after(datetime(2026, 3, 6, 9, 30))  # -> 2026-03-09 09:30
```

## Tests

```
python3 -m unittest discover -s tests -v
```
