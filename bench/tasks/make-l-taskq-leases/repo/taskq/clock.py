"""Time source. Production uses the monotonic clock; tests drive FakeClock."""


class FakeClock(object):
    def __init__(self, now=0):
        self._now = now

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds
