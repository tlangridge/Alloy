"""Track which byte ranges of a download have been received."""
import bisect


class ByteRanges(object):
    """A set of half-open byte ranges ``[start, end)``.

    The stored ranges are kept sorted by start, non-overlapping and
    non-touching, so ``ranges()`` is always the minimal description of what
    has been received.
    """

    def __init__(self):
        self._ranges = []

    def add(self, start, end):
        """Record that bytes ``[start, end)`` were received."""
        if start < 0 or end < start:
            raise ValueError('invalid range [%r, %r)' % (start, end))
        if start == end:
            return
        starts = [s for s, _ in self._ranges]
        i = bisect.bisect_left(starts, start)
        if i > 0 and self._ranges[i - 1][1] >= start:
            i -= 1
            start = self._ranges[i][0]
            end = max(end, self._ranges[i][1])
            del self._ranges[i]
        # Absorb every following range that overlaps or touches [start, end).
        while i < len(self._ranges) and self._ranges[i][0] <= end:
            end = max(end, self._ranges[i][1])
            del self._ranges[i]
        self._ranges.insert(i, (start, end))

    def ranges(self):
        """Return the received ranges as a sorted list of ``(start, end)`` tuples."""
        return list(self._ranges)

    def covered(self):
        """Return the number of distinct bytes received."""
        return sum(end - start for start, end in self._ranges)

    def __contains__(self, offset):
        starts = [s for s, _ in self._ranges]
        i = bisect.bisect_right(starts, offset) - 1
        return i >= 0 and offset < self._ranges[i][1]

    def missing(self, size):
        """Return the sorted gaps of ``[0, size)`` that have not been received."""
        gaps = []
        pos = 0
        for start, end in self._ranges:
            if start >= size:
                break
            if start > pos:
                gaps.append((pos, start))
            pos = end
        if pos < size:
            gaps.append((pos, size))
        return gaps

    def is_complete(self, size):
        """Return True when every byte of ``[0, size)`` has been received."""
        return not self.missing(size)
