"""Proportional splitting of integer cents (largest-remainder method)."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def split_cents(total, weights):
    """Split `total` cents between participants in proportion to `weights`.

    Every participant first gets floor(|total| * w / W) cents, where W is the
    sum of the weights. The cents left over (always fewer than the number of
    participants with a non-zero remainder) go one each to the participants
    with the largest remainders, ties going to the alphabetically first name.
    Shares therefore sum exactly to `total` and each differs from the exact
    proportion by less than one cent. A negative total is split as its
    magnitude and then negated, so refunds mirror the original charge.

    Returns {name: cents} in the order of `weights`.
    """
    if not _is_int(total):
        raise TypeError('total must be an int number of cents')
    if not weights:
        raise ValueError('at least one participant is required')
    for name, weight in weights.items():
        if not isinstance(name, str):
            raise TypeError('participant names must be strings')
        if not _is_int(weight):
            raise TypeError('weights must be ints')
        if weight < 0:
            raise ValueError('weight for %r is negative' % name)
    weight_sum = sum(weights.values())
    if weight_sum == 0:
        raise ValueError('weights must not all be zero')

    magnitude = abs(total)
    shares = {}
    by_remainder = []
    for name, weight in weights.items():
        share, remainder = divmod(magnitude * weight, weight_sum)
        shares[name] = share
        by_remainder.append((-remainder, name))
    leftover = magnitude - sum(shares.values())
    for _, name in sorted(by_remainder)[:leftover]:
        shares[name] += 1
    sign = -1 if total < 0 else 1
    return {name: sign * cents for name, cents in shares.items()}
