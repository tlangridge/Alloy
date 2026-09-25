"""Clocks for the cache. A clock is any zero-argument callable returning seconds."""
import time

monotonic = time.monotonic


class FakeClock:
    """A manually driven clock for tests: call it to read the current time."""

    def __init__(self, start=0.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        if seconds < 0:
            raise ValueError('FakeClock cannot move backwards')
        self.now += seconds
        return self.now

    def set(self, when):
        self.now = float(when)
        return self.now
