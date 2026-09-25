# SPEC: extract one pricing module and add clearance pricing

## Goal
The same unit-price calculation is implemented three times, in three styles,
in `shop/cart.py` (`Cart._unit_price`), `shop/quote.py` (`Quote.add`) and
`shop/pos.py` (`Receipt._price`). Move it into a single new module
`shop/pricing.py`, make all three sales channels use it, and then add
clearance pricing (a feature that would otherwise have to be written three
times). Apart from the clearance extension, observable behavior must not
change.

## Current behavior
Every channel computes a unit price for `qty` units of a product like this:

1. Volume discount by the line's quantity: 12 % from 100 units, 8 % from 50,
   4 % from 10, otherwise none.
2. Member discount by customer tier: silver 2 %, gold 5 %, anything else (and
   a walk-in till customer, `customer=None`) none. Applied after the volume
   discount: `base_price * (1 - volume) * (1 - member)`.
3. Rounded to the cent, halves up.
4. Margin floor: never below `cost * 1.10` rounded **up** to the cent.

Quotes may instead take a negotiated `override` unit price, which replaces
steps 1–2 (it is still rounded and floored). Channel-specific behavior that
must be preserved: carts and till receipts merge repeated adds/scans of a sku
into one line and price lines when `lines()`/`total()` is called; a quote
creates one line per `add()` and locks its unit price at `add()` time (and
`add()` returns that price); stock checks (`Cart.add`, `Quote.accept`,
`Receipt.checkout`) and their all-or-nothing behavior stay as they are.

## Desired behavior

### A. `shop/pricing.py` (new)
- `VOLUME_TIERS`: a list of `(min_qty, fraction)` pairs, currently
  `[(100, Decimal('0.12')), (50, Decimal('0.08')), (10, Decimal('0.04'))]`.
  The volume fraction for a quantity is the fraction of the pair with the
  largest `min_qty <= qty`, or 0 if there is none (the list's order must not
  matter).
- `MEMBER_DISCOUNTS`: dict tier -> fraction, currently
  `{'silver': Decimal('0.02'), 'gold': Decimal('0.05')}`; unknown tiers and
  `customer=None` get 0.
- `MARGIN_FLOOR = Decimal('1.10')`
- `CLEARANCE_MARKDOWN = Decimal('0.30')`
- `unit_price(product, qty, customer=None, clearance=False, override=None) -> Decimal`
  implementing, in order:
  1. if `override` is not `None`, the price is `Decimal(override)`;
     otherwise `v` = the volume fraction, and **if `clearance`**,
     `v = max(v, CLEARANCE_MARKDOWN)` (the bigger discount wins, they never
     stack); `m` = the member fraction; price =
     `base_price * (1 - v) * (1 - m)`;
  2. round to the cent, halves up;
  3. **unless `clearance`**, raise it to the floor `cost * MARGIN_FLOOR`
     rounded up to the cent. Clearance items may sell below the floor.

  With `clearance=False` this is exactly today's calculation.

### B. The three channels
- `Cart`, `Quote` and `Receipt` must obtain every unit price by calling
  `shop.pricing.unit_price`, passing
  `clearance=inventory.is_clearance(sku)` as of the moment they price the line
  (carts and receipts: when `lines()`/`total()` runs; quotes: in `add()`).
  Remove their private copies of the tables, rounding and floor logic.
- The tables are read **at call time**: the acceptance tests replace them with
  `unittest.mock.patch.object(shop.pricing, 'VOLUME_TIERS', [...])` (likewise
  `MEMBER_DISCOUNTS`, `MARGIN_FLOOR`, `CLEARANCE_MARKDOWN`) and expect prices
  from `unit_price` and from all three channels to follow the patched values.
- Everything described under *Current behavior* keeps working unchanged;
  public classes, methods and signatures stay the same.

## Allowed paths
`shop/`, `tests/`, `README.md`.

## Non-goals
Changing stock handling, currency handling, persistence, or tier/discount
values; caching prices.

## Acceptance criteria
- `shop/pricing.py` provides the API above; the three channel modules no
  longer contain their own discount tables, rounding or floor code.
- All existing tests pass; add tests for `shop.pricing` and for clearance in
  each channel.
- Standard library only, Python 3.8+.

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
List what moved where, anything you found that differed between the three
copies, and the test output.
