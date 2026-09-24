# billing

Invoices, VAT and credit notes for the wholesale shop. Amounts are
`decimal.Decimal` throughout (floats are refused by `billing.money.to_money`).

* A line's **net** is `qty * unit_price * (1 - discount)` rounded to the cent.
  Unit prices may have up to four decimals (bulk pricing); adjustment lines
  (goodwill credits, corrections) use a negative unit price.
* A line's **VAT** is `net * rate` rounded to the cent. Rates: `standard` 20 %,
  `reduced` 5 %, `zero` 0 %.
* Invoice `subtotal` = sum of line nets, `tax_total` = sum of line VAT,
  `total` = `subtotal + tax_total`; `breakdown()` sums net and VAT per category.
* All rounding is to the nearest cent with halves away from zero (0.125 ->
  0.13, -0.125 -> -0.13), matching the ledger system.
* `billing.credit.credit_note` refunds an invoice (fully or per sku) by
  re-issuing the refunded units with negative quantities.
* `billing.split.allocate` splits a total between payers (largest remainder).

Run the tests with `python3 -m unittest discover -s tests -v`.
