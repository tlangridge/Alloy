"""A parsed schedule and occurrence computation."""


class Schedule(object):
    """Created by :func:`cadence.parse`."""

    def matches(self, when):
        raise NotImplementedError

    def next_after(self, when):
        raise NotImplementedError

    def previous_before(self, when):
        raise NotImplementedError

    def occurrences(self, after, count):
        raise NotImplementedError
