# salesreport

Summarises a quarterly sales export (CSV with `region,rep,amount` columns) into
per-region totals and a grand total.

```
python3 -m salesreport data/q3.csv
```

Rows with a blank amount (deals still being booked) are skipped; the tool
prints a warning on stderr when it sees any.

Run the tests with `python3 -m unittest discover -s tests -v`.
