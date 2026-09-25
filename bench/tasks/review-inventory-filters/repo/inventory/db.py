"""Schema and write helpers."""
import sqlite3

SCHEMA = '''
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    brand TEXT,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    cost_cents INTEGER NOT NULL
);
CREATE TABLE stock (
    product_id INTEGER NOT NULL REFERENCES products(id),
    warehouse TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (product_id, warehouse)
);
'''


def connect(path=':memory:'):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_product(conn, sku, name, brand=None, category=None, cost_cents=0, status='active', stock=None):
    """Insert a product plus optional {warehouse: quantity} stock; return its id."""
    cur = conn.execute(
        'INSERT INTO products (sku, name, brand, category, status, cost_cents) VALUES (?, ?, ?, ?, ?, ?)',
        (sku, name, brand, category, status, cost_cents))
    product_id = cur.lastrowid
    for warehouse, quantity in (stock or {}).items():
        conn.execute('INSERT INTO stock (product_id, warehouse, quantity) VALUES (?, ?, ?)',
                     (product_id, warehouse, quantity))
    return product_id
