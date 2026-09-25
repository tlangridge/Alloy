# quotes

Price quotes for the B2B shop.

A quote for (customer, sku, quantity) is built from several modules:

* `catalog` - products and their list prices (USD);
* `pricing` - the unit price a customer pays;
* `contracts` - negotiated per-category discounts;
* `shipping`, `tax` - per-region costs;
* `fx` - conversion from USD to the customer's billing currency.

`service.QuoteService` assembles them. `cache.TTLCache` is a small expiring
cache shared by services.

Run the tests with `python3 -m unittest discover -s tests -v`.
