"""Release versions: MAJOR.MINOR.PATCH, nothing else."""
import re
from functools import total_ordering

from .errors import InvalidVersion

_VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')


@total_ordering
class Version(object):
    __slots__ = ('major', 'minor', 'patch')

    def __init__(self, major, minor, patch):
        self.major, self.minor, self.patch = major, minor, patch

    @classmethod
    def parse(cls, text):
        if isinstance(text, Version):
            return text
        m = _VERSION.match(text) if isinstance(text, str) else None
        if not m:
            raise InvalidVersion('invalid version %r' % (text,))
        return cls(*(int(g) for g in m.groups()))

    @property
    def key(self):
        return (self.major, self.minor, self.patch)

    def __eq__(self, other):
        return isinstance(other, Version) and self.key == other.key

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self.key < other.key

    def __hash__(self):
        return hash(self.key)

    def __str__(self):
        return '%d.%d.%d' % self.key

    def __repr__(self):
        return 'Version(%r)' % str(self)
