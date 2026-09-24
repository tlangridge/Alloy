import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List


@dataclass(frozen=True)
class Transaction:
    id: str
    ccy: str          # ISO currency code as sent by the source system
    amount: Decimal
    day: str          # ISO date, YYYY-MM-DD


@dataclass
class Batch:
    source: str
    transactions: List[Transaction] = field(default_factory=list)


def load(path):
    """Batches from a month file, in file order."""
    with open(path, encoding='utf-8') as fh:
        doc = json.load(fh)
    batches = []
    for raw in doc['batches']:
        txs = [Transaction(t['id'], t['ccy'], Decimal(t['amount']), t['day']) for t in raw['transactions']]
        batches.append(Batch(raw['source'], txs))
    return batches
