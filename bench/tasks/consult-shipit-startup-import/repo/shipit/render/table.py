def table(rows):
    """Plain-text table with left-aligned columns."""
    if not rows:
        return ''
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    return '\n'.join('  '.join(str(cell).ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows)
