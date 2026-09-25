"""Parsing of firmware release tags.

Tag grammar (surrounding whitespace is ignored):

    [v|V][<epoch>!]<major>.<minor>[.<patch>][-<channel>[.<n>]][+<build>]

* numbers are decimal integers without leading zeros ("0" itself is fine);
* ``patch`` defaults to 0; ``epoch`` defaults to 0;
* ``channel`` is one of dev, alpha, beta, rc, hotfix (case-insensitive,
  stored lower-case); ``n`` defaults to 0 when the channel is present;
* ``build`` is free-form metadata of [0-9A-Za-z.-] characters.
"""
import re

CHANNELS = ('dev', 'alpha', 'beta', 'rc', 'hotfix')

_NUM = r'(?:0|[1-9][0-9]*)'
_TAG = re.compile(
    r'^[vV]?(?:(?P<epoch>' + _NUM + r')!)?'
    r'(?P<major>' + _NUM + r')\.(?P<minor>' + _NUM + r')(?:\.(?P<patch>' + _NUM + r'))?'
    r'(?:-(?P<channel>[A-Za-z]+)(?:\.(?P<num>' + _NUM + r'))?)?'
    r'(?:\+(?P<build>[0-9A-Za-z.-]+))?$')


class InvalidVersion(ValueError):
    """Raised for a tag that does not follow the grammar."""


class Version:
    __slots__ = ('epoch', 'major', 'minor', 'patch', 'channel', 'channel_num', 'build', 'text')

    def __init__(self, epoch, major, minor, patch, channel=None, channel_num=None, build=None, text=None):
        self.epoch = epoch
        self.major = major
        self.minor = minor
        self.patch = patch
        self.channel = channel          # None for a final release
        self.channel_num = channel_num  # None for a final release
        self.build = build
        self.text = text

    @property
    def release(self):
        return (self.major, self.minor, self.patch)

    @property
    def is_prerelease(self):
        return self.channel in ('dev', 'alpha', 'beta', 'rc')

    def __repr__(self):
        return 'Version(%r)' % (self.text if self.text is not None else str(self))

    def __str__(self):
        out = '%d.%d.%d' % self.release
        if self.epoch:
            out = '%d!%s' % (self.epoch, out)
        if self.channel is not None:
            out += '-%s.%d' % (self.channel, self.channel_num)
        if self.build:
            out += '+' + self.build
        return out

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))


def parse(tag):
    """Parse a release tag into a Version, raising InvalidVersion."""
    if not isinstance(tag, str):
        raise InvalidVersion('tag must be a string: %r' % (tag,))
    m = _TAG.match(tag.strip())
    if not m:
        raise InvalidVersion('invalid release tag: %r' % (tag,))
    channel = m.group('channel')
    if channel is not None:
        channel = channel.lower()
        if channel not in CHANNELS:
            raise InvalidVersion('unknown channel %r in %r' % (channel, tag))
    return Version(int(m.group('epoch') or 0), int(m.group('major')), int(m.group('minor')),
                   int(m.group('patch') or 0), channel,
                   None if channel is None else int(m.group('num') or 0),
                   m.group('build'), tag)
