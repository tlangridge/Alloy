"""Append-only event store (in memory, JSON-serialised like the real one)."""
import json

from .errors import ConcurrencyError
from .events import from_record, to_record


class EventStore(object):
    """Streams of events keyed by account id.

    Versions are 1-based: the first event of a stream has version 1 and the
    stream's version is the number of events in it.
    """

    def __init__(self):
        self._streams = {}
        self.events_read = 0  # total events returned by read(); used by ops dashboards

    def version(self, stream):
        return len(self._streams.get(stream, ()))

    def append(self, stream, events, expected_version):
        """Append ``events`` atomically if the stream is at ``expected_version``.

        Returns the new stream version. Raises ConcurrencyError otherwise.
        """
        current = self.version(stream)
        if current != expected_version:
            raise ConcurrencyError('stream %r is at version %d, not %d' % (stream, current, expected_version))
        encoded = [json.dumps(to_record(e), sort_keys=True) for e in events]
        self._streams.setdefault(stream, []).extend(encoded)
        return current + len(encoded)

    def read(self, stream, after_version=0):
        """Return ``[(version, event), ...]`` for every event with version > after_version."""
        rows = self._streams.get(stream, [])
        out = [(i + 1, from_record(json.loads(text))) for i, text in enumerate(rows) if i + 1 > after_version]
        self.events_read += len(out)
        return out
