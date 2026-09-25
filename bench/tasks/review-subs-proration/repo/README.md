# subs

Subscription billing primitives.

* `money` - Decimal helpers. House rule: amounts are Decimals; every amount
  that lands on an invoice is rounded **once**, half-up, to cents
  (`money.round_money`).
* `plans` - the plan catalogue (monthly prices).
* `periods` - monthly billing periods anchored on a day of the month
  (half-open `[start, end)` date ranges).
* `invoice` - invoices and line items; line amounts must already be in cents.

Run the tests with `python3 -m unittest discover -s tests -v`.
