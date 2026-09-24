# meterbill

Builds monthly usage invoices for the metered API product from a period file
(`fixtures/<month>.json`) holding the rate card, the promo catalog and each
customer's metered usage.

```
python3 -m meterbill fixtures/september.json
```

Per meter, the charge is `quantity x unit rate`, rounded to cents (halves away
from zero). A customer's promo code gives a percentage off their subtotal, at
most once per invoice. The last line is the grand total across all invoices.

Rate-card numbers are parsed as exact decimals (never floats).

Run the tests with `python3 -m unittest discover -s tests -v`.
