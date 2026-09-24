"""Catalogue search."""

# Columns callers may filter on, by table. cost_cents is internal and must not
# be filterable (it would let API users binary-search our purchase prices).
FILTERABLE = {
    'products': ('brand', 'category', 'status'),
    'stock': ('warehouse',),
}

_FILTERABLE_COLUMNS = {column for columns in FILTERABLE.values() for column in columns}

_SELECT = (
    'SELECT DISTINCT products.sku, products.name, products.brand, products.category, products.status '
    'FROM products LEFT JOIN stock ON stock.product_id = products.id'
)


def _escape_like(text):
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _resolve_column(key):
    """Map a filter key to a table-qualified column: 'brand' -> 'products.brand'.

    Keys may already be qualified ('stock.warehouse'); the admin UI sends
    qualified names, the public API bare ones.
    """
    if not isinstance(key, str):
        raise ValueError('filter keys must be strings')
    table, _, column = key.rpartition('.')
    if column not in _FILTERABLE_COLUMNS:
        raise ValueError('cannot filter on %r' % key)
    if table:
        return key
    for owner, columns in FILTERABLE.items():
        if column in columns:
            return '%s.%s' % (owner, column)


def _filter_clauses(filters):
    """SQL conditions and bound parameters for a {key: value} filter dict."""
    clauses, params = [], []
    for key, value in filters.items():
        column = _resolve_column(key)
        if isinstance(value, (list, tuple, set, frozenset)):
            values = list(value)
            if not values:
                clauses.append('0')           # empty membership matches nothing
                continue
            clauses.append('%s IN (%s)' % (column, ', '.join('?' * len(values))))
            params.extend(values)
        else:
            clauses.append('%s = ?' % column)
            params.append(value)
    return clauses, params


def search(conn, text=None, filters=None, limit=50):
    """Products whose name or SKU contains `text` (case-insensitive), by SKU.

    `filters` maps a filterable column (bare 'brand' or qualified
    'products.brand') to a value (equality) or a list/tuple/set of values
    (membership). All conditions are ANDed. Returns a list of dicts with keys
    sku, name, brand, category, status.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError('limit must be an integer from 1 to 500')
    where, params = [], []
    if text:
        pattern = '%' + _escape_like(text) + '%'
        where.append("(products.name LIKE ? ESCAPE '\\' OR products.sku LIKE ? ESCAPE '\\')")
        params += [pattern, pattern]
    if filters:
        clauses, values = _filter_clauses(filters)
        where += clauses
        params += values
    sql = _SELECT
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY products.sku LIMIT ?'
    params.append(limit)
    return [dict(row) for row in conn.execute(sql, params)]
