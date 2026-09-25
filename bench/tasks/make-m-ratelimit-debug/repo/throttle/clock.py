"""Clocks: zero-argument callables returning seconds as a float."""
import time

monotonic = time.monotonic


class FakeClock:
    """Manually driven clock for tests. It may be set backwards to simulate
    a clock step; the limiter must cope with that."""

    def __init__(self, start=0.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now

    def set(self, when):
        self.now = float(when)
        return self.now
