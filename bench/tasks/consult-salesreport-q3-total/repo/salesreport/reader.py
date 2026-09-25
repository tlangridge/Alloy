import csv


def read_rows(path):
    """Yield one dict per CSV row with stripped 'region', 'rep' and 'amount' strings.

    Streaming keeps memory flat for the multi-million-row yearly exports.
    """
    with open(path, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            yield {key.strip(): (value or '').strip() for key, value in row.items()}
