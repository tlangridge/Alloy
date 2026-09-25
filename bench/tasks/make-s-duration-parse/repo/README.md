# retention

Small helpers used by the backup agent to decide which snapshots to prune.

Policies are written as duration strings, for example:

```ini
[policy:nightly]
keep = 30d
```

```python
from retention import parse_duration, format_duration
from retention.policy import expired

parse_duration("30d")                  # -> 2592000
expired({"a": 0, "b": 9000}, "1h", now=9000)   # -> ["a"]
```

Run the tests with `python3 -m unittest discover -s tests -v`.
