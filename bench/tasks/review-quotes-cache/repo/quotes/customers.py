from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Customer:
    id: str
    region: str                      # shipping/tax region, e.g. 'US-CA'
    currency: str = 'USD'            # billing currency
    segment: str = 'retail'          # 'retail' or 'wholesale'
    contract: Optional[str] = None   # negotiated contract id, see contracts.py
