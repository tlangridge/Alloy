# printq

Print-queue client. `printq --pages "1-3, 5, 8-" report.pdf` prints a subset
of a document; the `--pages` value is parsed by
`printq.pages.parse_page_ranges`.

```python
from printq import parse_page_ranges

parse_page_ranges("1-3, 5, 8-", page_count=10)   # [1, 2, 3, 5, 8, 9, 10]
```

Run the tests with `python3 -m unittest discover -s tests -v`.
