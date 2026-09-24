# tabs

Shared-expense tracking for groups (trips, flats, teams).

All money is **integer cents**; there are no floats anywhere. A positive
balance means the group owes that member money; a negative balance means the
member owes the group. Balances always sum to zero.

Run the tests with `python3 -m unittest discover -s tests -v`.
