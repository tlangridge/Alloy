"""Catalogue search."""

# Columns callers may filter on, by table. cost_cents is internal and must not
# be filterable (it would let API users binary-search our purchase prices).
FILTERABLE = {
    'products': ('brand', 'category', 'status'),
    'stock': ('warehouse',),
}

_SELECT = (
    'SELECT DISTINCT products.sku, products.name, products.brand, products.category, products.status '
    'FROM products LEFT JOIN stock ON stock.product_id = products.id'
)


def _escape_like(text):
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def search(conn, text=None, limit=50):
    """Products whose name or SKU contains `text` (case-insensitive), by SKU.

    Returns a list of dicts with keys sku, name, brand, category, status.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError('limit must be an integer from 1 to 500')
    where, params = [], []
    if text:
        pattern = '%' + _escape_like(text) + '%'
        where.append("(products.name LIKE ? ESCAPE '\\' OR products.sku LIKE ? ESCAPE '\\')")
        params += [pattern, pattern]
    sql = _SELECT
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY products.sku LIMIT ?'
    params.append(limit)
    return [dict(row) for row in conn.execute(sql, params)]
