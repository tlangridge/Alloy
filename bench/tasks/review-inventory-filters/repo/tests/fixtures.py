from inventory.db import add_product, connect


def catalogue():
    conn = connect()
    add_product(conn, 'DRL-100', 'Cordless drill', 'Makita', 'tools', 4200, stock={'north': 5, 'south': 0})
    add_product(conn, 'DRL-200', 'Hammer drill', 'Bosch', 'tools', 6100, stock={'south': 2})
    add_product(conn, 'SAW-010', 'Hand saw', 'Stanley', 'tools', 900, stock={'north': 12})
    add_product(conn, 'GLV-001', "O'Neil work gloves", "O'Neil", 'safety', 300, stock={'east': 40})
    add_product(conn, 'GLV-002', 'Nitrile gloves 100%', 'Bosch', 'safety', 450, status='discontinued')
    add_product(conn, 'TAP-050', 'Duct_tape', 'Stanley', 'consumables', 150, status='hidden', stock={'north': 3})
    return conn
