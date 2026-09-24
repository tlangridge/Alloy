# cronlite

A tiny in-process job scheduler.

* `cronlite.tz` - time zones with US daylight-saving rules; PEP 495 `fold`
  semantics (see the module docstring).
* `cronlite.schedules` - schedule objects. Every schedule implements
  `next_after(instant)`: the first fire time strictly after the aware
  `instant`, returned as an aware UTC datetime.
* `cronlite.runner` - decides which fire times are due when the scheduler
  wakes up. The scheduler wakes at least once a day, so the span between the
  last run and now is short.

Run the tests with `python3 -m unittest discover -s tests -v`.
