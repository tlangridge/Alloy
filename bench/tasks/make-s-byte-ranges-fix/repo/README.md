# fetchkit

Resumable downloads for the asset sync service. Chunks can arrive out of
order (parallel range requests, retries), so `fetchkit.ranges.ByteRanges`
records which byte ranges of a file have been received and tells the
resume planner which ranges are still missing.

```python
from fetchkit.ranges import ByteRanges

received = ByteRanges()
received.add(0, 100)
received.add(200, 300)
received.missing(300)    # [(100, 200)]
received.covered()       # 200
```

Run the tests with `python3 -m unittest discover -s tests -v`.
