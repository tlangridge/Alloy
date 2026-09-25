"""Snapshot storage and the (de)serialisation of Account state.

A snapshot is ``(version, state)`` where ``state`` is the JSON-ready dict
produced by :func:`encode_state`. Snapshots are stored as JSON text, exactly
as the production store keeps them.
"""
import json
from decimal import Decimal

from .account import Account, Hold


def encode_state(account):
    return {
        'owner': account.owner,
        'opened': account.opened,
        'balance': str(account.balance),
        'holds': {hold_id: {'amount': str(h.amount), 'expires_at': h.expires_at}
                  for hold_id, h in account.holds.items()},
        'next_hold_id': account.next_hold_id,
    }


def decode_state(account_id, version, state):
    account = Account(account_id)
    account.version = version
    account.owner = state['owner']
    account.opened = state['opened']
    account.balance = Decimal(state['balance'])
    # JSON object keys are always strings: hold ids must be restored as ints.
    account.holds = {int(hold_id): Hold(Decimal(h['amount']), h['expires_at'])
                     for hold_id, h in state['holds'].items()}
    account.next_hold_id = state['next_hold_id']
    return account


class SnapshotStore(object):
    def __init__(self):
        self._rows = {}

    def save(self, account_id, version, state):
        self._rows.setdefault(account_id, []).append((version, json.dumps(state, sort_keys=True)))

    def versions(self, account_id):
        return sorted(v for v, _ in self._rows.get(account_id, ()))

    def latest(self, account_id):
        """``(version, state)`` of the highest-version snapshot, or None."""
        rows = self._rows.get(account_id)
        if not rows:
            return None
        version, text = max(rows, key=lambda row: row[0])
        return version, json.loads(text)
