REQUIRED_COLUMNS = ('region', 'rep', 'amount')


def missing_columns(header):
    """Required columns absent from a CSV header row."""
    present = {name.strip() for name in header}
    return [name for name in REQUIRED_COLUMNS if name not in present]


def has_blank_amounts(rows):
    """True if any row has an empty amount."""
    return any(not row['amount'] for row in rows)
