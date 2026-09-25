"""The Account aggregate: commands raise events, apply() folds them into state."""
from .errors import HoldNotFound, InsufficientFunds, LedgerError
from .events import (AccountOpened, Deposited, FeeCharged, HoldCaptured, HoldPlaced, HoldReleased,
                     TransferReceived, TransferSent, Withdrawn)
from .money import ZERO, amount


class Hold(object):
    __slots__ = ('amount', 'expires_at')

    def __init__(self, amount, expires_at):
        self.amount = amount
        self.expires_at = expires_at


class Account(object):
    def __init__(self, account_id):
        self.id = account_id
        self.version = 0
        self.opened = False
        self.owner = None
        self.balance = ZERO
        self.holds = {}          # hold id (int) -> Hold
        self.next_hold_id = 1
        self._pending = []

    # ------------------------------------------------------------------ queries
    @property
    def available(self):
        return self.balance - sum((h.amount for h in self.holds.values()), ZERO)

    def describe(self):
        return {
            'id': self.id,
            'owner': self.owner,
            'version': self.version,
            'balance': self.balance,
            'available': self.available,
            'holds': {hold_id: {'amount': h.amount, 'expires_at': h.expires_at}
                      for hold_id, h in self.holds.items()},
            'next_hold_id': self.next_hold_id,
        }

    def pending_events(self):
        return list(self._pending)

    def mark_committed(self):
        self._pending = []

    # ---------------------------------------------------------------- commands
    def open(self, owner):
        if self.opened:
            raise LedgerError('account already opened')
        self._raise(AccountOpened(owner=owner))

    def deposit(self, value):
        self._raise(Deposited(amount=amount(value)))

    def withdraw(self, value):
        value = amount(value)
        if value > self.available:
            raise InsufficientFunds('available %s < %s' % (self.available, value))
        self._raise(Withdrawn(amount=value))

    def place_hold(self, value, expires_at):
        value = amount(value)
        if value > self.available:
            raise InsufficientFunds('available %s < %s' % (self.available, value))
        hold_id = self.next_hold_id
        self._raise(HoldPlaced(hold_id=hold_id, amount=value, expires_at=expires_at))
        return hold_id

    def capture_hold(self, hold_id):
        if hold_id not in self.holds:
            raise HoldNotFound(hold_id)
        self._raise(HoldCaptured(hold_id=hold_id))

    def release_hold(self, hold_id):
        if hold_id not in self.holds:
            raise HoldNotFound(hold_id)
        self._raise(HoldReleased(hold_id=hold_id))

    def release_expired(self, now):
        released = []
        for hold_id in sorted(self.holds):
            if self.holds[hold_id].expires_at <= now:
                released.append(hold_id)
        for hold_id in released:
            self._raise(HoldReleased(hold_id=hold_id))
        return released

    def send_transfer(self, to_account, value, fee):
        value = amount(value)
        fee = amount(fee, allow_zero=True)
        if value + fee > self.available:
            raise InsufficientFunds('available %s < %s' % (self.available, value + fee))
        self._raise(TransferSent(to_account=to_account, amount=value))
        if fee > ZERO:
            self._raise(FeeCharged(amount=fee, reason='transfer'))

    def receive_transfer(self, from_account, value):
        self._raise(TransferReceived(from_account=from_account, amount=amount(value)))

    # ------------------------------------------------------------------- state
    def _raise(self, event):
        self.apply(event)
        self._pending.append(event)

    def apply(self, event):
        kind = type(event)
        if kind is AccountOpened:
            self.opened = True
            self.owner = event.owner
        elif kind in (Deposited, TransferReceived):
            self.balance += event.amount
        elif kind in (Withdrawn, TransferSent, FeeCharged):
            self.balance -= event.amount
        elif kind is HoldPlaced:
            self.holds[event.hold_id] = Hold(event.amount, event.expires_at)
            self.next_hold_id = max(self.next_hold_id, event.hold_id + 1)
        elif kind is HoldReleased:
            self.holds.pop(event.hold_id, None)
        elif kind is HoldCaptured:
            hold = self.holds.pop(event.hold_id, None)
            if hold is not None:
                self.balance -= hold.amount
        else:
            raise LedgerError('unknown event %r' % (event,))
        self.version += 1
