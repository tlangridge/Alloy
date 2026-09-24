# shop

Catalog, stock and the three places we sell from:

* `shop.cart.Cart` - web shop cart (prices when you look at it);
* `shop.quote.Quote` - B2B quotes (price locked per line when added,
  negotiated overrides, stock reserved on acceptance);
* `shop.pos.Receipt` - the in-store till (walk-in customers allowed).

All three apply the same pricing: volume tiers, member discounts, rounding to
the cent and a margin floor.

Run the tests with `python3 -m unittest discover -s tests -v`.
