"""Credit notes (refunds) for issued invoices."""
from billing.invoice import Invoice, Line


def credit_note(invoice, number, quantities=None):
    """Build the credit note refunding `invoice`.

    `quantities` maps sku -> number of units to refund; None refunds every line
    in full. Each refunded line keeps its unit price, discount and tax category
    and gets a negative quantity, so the credit note's amounts are the exact
    negatives of what those units were invoiced at.
    """
    by_sku = {}
    for line in invoice.lines:
        by_sku.setdefault(line.sku, []).append(line)
    if quantities is None:
        quantities = {}
        for line in invoice.lines:
            quantities[line.sku] = quantities.get(line.sku, 0) + line.qty
    note = Invoice(number)
    for sku, qty in quantities.items():
        lines = by_sku.get(sku)
        if not lines:
            raise ValueError('sku %r is not on invoice %s' % (sku, invoice.number))
        available = sum(l.qty for l in lines)
        if qty <= 0 or qty > available:
            raise ValueError('cannot refund %r units of %r (invoiced %d)' % (qty, sku, available))
        for line in lines:
            take = min(qty, line.qty)
            if take <= 0:
                break
            note.lines.append(Line(line.sku, -take, line.unit_price, line.category, line.discount))
            qty -= take
    return note
