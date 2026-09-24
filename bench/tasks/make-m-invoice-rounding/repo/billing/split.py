"""Split an amount between payers."""
from decimal import Decimal, ROUND_FLOOR


def allocate(total, weights, places=2):
    """Split `total` into shares proportional to `weights`.

    Largest-remainder method: every share is first rounded down to the unit
    (0.01 for places=2); the units left over go one each to the shares with the
    largest discarded remainders, earlier payers first on ties. Shares always
    sum exactly to `total`. A negative total is split like its absolute value
    and every share negated, so a refund mirrors the original split.
    """
    if not weights or any(w < 0 for w in weights) or sum(weights) == 0:
        raise ValueError('weights must be non-negative and not all zero')
    if total < 0:
        return [-share for share in allocate(-total, weights, places)]
    unit = Decimal(1).scaleb(-places)
    units = total / unit
    if units != units.to_integral_value():
        raise ValueError('total %s is not a whole number of %s' % (total, unit))
    units = int(units)
    weight_sum = sum(Decimal(w) for w in weights)
    exact = [Decimal(units) * Decimal(w) / weight_sum for w in weights]
    floors = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exact]
    left = units - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:left]:
        floors[i] += 1
    return [Decimal(f) * unit for f in floors]
