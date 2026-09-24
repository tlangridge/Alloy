"""Stock levels, reservations (accepted quotes) and the clearance list."""


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self):
        self._on_hand = {}
        self._reserved = {}
        self._clearance = set()

    def receive(self, sku, qty):
        self._on_hand[sku] = self._on_hand.get(sku, 0) + qty

    def on_hand(self, sku):
        return self._on_hand.get(sku, 0)

    def reserved(self, sku):
        return self._reserved.get(sku, 0)

    def available(self, sku):
        return self.on_hand(sku) - self.reserved(sku)

    def reserve(self, sku, qty):
        if qty > self.available(sku):
            raise OutOfStock(sku)
        self._reserved[sku] = self.reserved(sku) + qty

    def sell(self, sku, qty):
        if qty > self.available(sku):
            raise OutOfStock(sku)
        self._on_hand[sku] = self.on_hand(sku) - qty

    def set_clearance(self, sku, flag=True):
        if flag:
            self._clearance.add(sku)
        else:
            self._clearance.discard(sku)

    def is_clearance(self, sku):
        return sku in self._clearance
