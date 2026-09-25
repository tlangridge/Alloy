# notify

Per-user notification timing.

* `notify.tz` - time zones with US daylight-saving rules (`EASTERN`, `CENTRAL`,
  `MOUNTAIN`, `PACIFIC`); PEP 495 `fold` semantics.
* `notify.quiet.QuietHours` - a user's daily do-not-disturb window in local
  wall-clock time, e.g. 22:00-07:00.

All instants handed to or returned from the public API are timezone-aware.

Run the tests with `python3 -m unittest discover -s tests -v`.
