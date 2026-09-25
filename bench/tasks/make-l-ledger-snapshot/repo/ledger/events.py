"""Domain events and their JSON-ready record form.

Records are plain dicts: ``{"type": <class name>, <field>: <value>, ...}``.
Money fields are stored as strings ("12.30") so they survive JSON exactly.
"""
from decimal import Decimal


class Event(object):
    fields = ()
    money = ()

    def __init__(self, **values):
        for name in self.fields:
            setattr(self, name, values[name])

    def __eq__(self, other):
        return type(self) is type(other) and all(getattr(self, f) == getattr(other, f) for f in self.fields)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, ', '.join('%s=%r' % (f, getattr(self, f)) for f in self.fields))


class AccountOpened(Event):
    fields = ('owner',)


class Deposited(Event):
    fields = ('amount',)
    money = ('amount',)


class Withdrawn(Event):
    fields = ('amount',)
    money = ('amount',)


class HoldPlaced(Event):
    fields = ('hold_id', 'amount', 'expires_at')
    money = ('amount',)


class HoldReleased(Event):
    fields = ('hold_id',)


class HoldCaptured(Event):
    fields = ('hold_id',)


class TransferSent(Event):
    fields = ('to_account', 'amount')
    money = ('amount',)


class TransferReceived(Event):
    fields = ('from_account', 'amount')
    money = ('amount',)


class FeeCharged(Event):
    fields = ('amount', 'reason')
    money = ('amount',)


TYPES = {cls.__name__: cls for cls in (AccountOpened, Deposited, Withdrawn, HoldPlaced, HoldReleased,
                                         HoldCaptured, TransferSent, TransferReceived, FeeCharged)}


def to_record(event):
    record = {'type': type(event).__name__}
    for name in event.fields:
        value = getattr(event, name)
        record[name] = str(value) if name in event.money else value
    return record


def from_record(record):
    cls = TYPES[record['type']]
    values = {}
    for name in cls.fields:
        value = record[name]
        values[name] = Decimal(value) if name in cls.money else value
    return cls(**values)
