# SPEC: credit notes do not mirror their invoices

## Goal
Find and fix the root cause of credit notes whose amounts are not the exact
negatives of the invoice they refund, so that the billing package agrees with
the ledger system to the cent for invoices, adjustment lines, credit notes and
payer splits.

## Current behavior
Bug report from accounting (ticket FIN-412):

> Since bulk pricing (unit prices with 3–4 decimals) went live, about one
> refund in forty is flagged by the ledger reconciliation: the credit note is
> a cent or two smaller than the invoice it cancels. Support suspects
> `credit_note` because it rebuilds the lines, or the payer split. Example:
>
> ```python
> from billing.invoice import Invoice
> from billing.credit import credit_note
> inv = Invoice('INV-2291')
> inv.add('BOLT-M6', 7, '1.875')
> inv.add('GASKET', 12, '0.4375')
> inv.add('WASHER', 40, '0.0815')
> print(inv.total)                          # 25.97  (correct)
> print(credit_note(inv, 'CN-0107').total)  # -25.95 (expected -25.97)
> ```
>
> Goodwill adjustment lines (negative unit prices) also sometimes disagree
> with the ledger by a cent.

All existing tests pass.

## Desired behavior
The documented rules (README.md) are correct and must hold everywhere:

1. `billing.money.round_half_up(amount, places=2)` rounds to `places`
   decimals with halves going **away from zero**: `0.125 -> 0.13`,
   `-0.125 -> -0.13`, `2.5 -> 3` and `-2.5 -> -3` for `places=0`. For every
   Decimal `x`, `round_half_up(-x, p) == -round_half_up(x, p)`, and non-half
   values round to the nearest step.
2. A line's net is `qty * unit_price * (1 - discount)` rounded to the cent by
   rule 1. Quantities may be negative (credit notes) and unit prices may be
   negative (adjustment lines).
3. A line's VAT, `billing.tax.line_tax(net, category)`, is `net * rate` rounded
   to the cent by rule 1 (rates: standard 0.20, reduced 0.05, zero 0), for
   positive and negative nets alike; an unknown category still raises
   `billing.tax.UnknownTaxCategory`.
4. Invoice `subtotal`, `tax_total`, `total`, `breakdown()` and `split(weights)`
   are computed from the lines exactly as today.
5. A full credit note (`billing.credit.credit_note(invoice, number)`) has every
   line's `net`/`tax`/`gross`, its `subtotal`, `tax_total`, `total`, every
   `breakdown()` value and every `split(weights)` share equal to the exact
   negative of the invoice's.
6. A partial credit note (`quantities={sku: n}`) has amounts equal to the exact
   negatives of an invoice for those `n` units at the same unit price,
   discount and category.
7. Positive amounts must not change: every result that is correct today must
   stay identical (no banker's rounding, no change to how ties are allocated
   in `billing.split.allocate`).
8. Keep all public names and signatures unchanged.

## Allowed paths
`billing/`, `tests/`.

## Non-goals
Currency conversion, new tax categories, performance work, changing how
`credit_note` chooses which lines to refund.

## Acceptance criteria
- The reproduction prints `25.97` and `-25.97`.
- Rules 1–8 hold for any inputs, not just the example; every place the
  package rounds money follows rule 1.
- Add a regression test in `tests/`; the existing tests still pass.

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
State the root cause (file and function), why the symptom appeared only on
some refunds, the fix, and before/after output of the reproduction.
