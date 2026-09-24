# ledger

Invoice rendering helpers. Amounts are always integers in the currency's
minor unit (cents, pence, rappen; yen have no minor unit).

```python
from ledger.money import format_money

format_money(123456, 'USD')   # '$1,234.56'
format_money(123456, 'EUR')   # '1.234,56 €'
format_money(-123456, 'CHF')  # "CHF -1'234.56"
format_money(1234, 'JPY')     # '¥1,234'
```

Run the tests with `python3 -m unittest discover -s tests -v`.
