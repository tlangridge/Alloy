# fxrecon

Converts a month of foreign-currency card and bank transactions to USD and
flags large foreign items for review.

```
python3 -m fxrecon fixtures/september.json
```

Exchange rates come from our FX provider through `fxrecon.feed.fetch_rate`.
**The provider bills every request**, so `fxrecon.rates.rate` caches rates for
the life of the process. The offline build reads provider responses from
`fixtures/rates.json` instead of calling the network.

Run the tests with `python3 -m unittest discover -s tests -v`.
