"""A group's shared-expense ledger. Amounts are integer cents."""
from dataclasses import dataclass
from typing import Dict

from .split import split_cents


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Expense:
    payer: str
    amount_cents: int
    shares: Dict[str, int]
    description: str = ''


class Ledger:
    def __init__(self, members):
        members = tuple(members)
        if not members or len(set(members)) != len(members):
            raise ValueError('members must be a non-empty list of unique names')
        self.members = members
        self._balances = {m: 0 for m in members}
        self.expenses = []

    def add_expense(self, payer, amount_cents, shares, description=''):
        """Record that `payer` paid `amount_cents` owed as `shares` {member: cents}.

        Shares must be ints summing exactly to amount_cents. Negative amounts
        (refunds) are allowed and simply reverse the direction.
        """
        if payer not in self._balances:
            raise ValueError('unknown payer %r' % payer)
        if not _is_int(amount_cents):
            raise TypeError('amount_cents must be an int')
        unknown = [m for m in shares if m not in self._balances]
        if unknown:
            raise ValueError('not members: %s' % ', '.join(map(str, unknown)))
        if not all(_is_int(c) for c in shares.values()):
            raise TypeError('shares must be int cents')
        if sum(shares.values()) != amount_cents:
            raise ValueError('shares sum to %d, expected %d' % (sum(shares.values()), amount_cents))
        self._balances[payer] += amount_cents
        for member, cents in shares.items():
            self._balances[member] -= cents
        expense = Expense(payer, amount_cents, dict(shares), description)
        self.expenses.append(expense)
        return expense

    def add_split_expense(self, payer, amount_cents, weights, description=''):
        """Record an expense split in proportion to `weights` {member: int weight}.

        weights={'ana': 1, 'ben': 1, 'cy': 2} gives cy half, ana and ben a
        quarter each; see split.split_cents for how odd cents are assigned.
        """
        return self.add_expense(payer, amount_cents, split_cents(amount_cents, weights), description)

    def balances(self):
        return dict(self._balances)
