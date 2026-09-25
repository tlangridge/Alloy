"""A tiny, dependency-free command-line parser for bakctl."""
import re

_LONG_NAME = re.compile(r'[a-z][a-z0-9-]*\Z')


class UsageError(Exception):
    """An invalid command line; the message is shown to the user."""


class _Spec(object):
    __slots__ = ('name', 'short', 'dest', 'takes_value', 'repeat', 'default')

    def __init__(self, name, short, takes_value, repeat, default):
        self.name = name
        self.short = short
        self.dest = name.replace('-', '_')
        self.takes_value = takes_value
        self.repeat = repeat
        self.default = default


class ArgParser(object):
    """Declare options with ``add_flag``/``add_option``, then call ``parse``."""

    def __init__(self):
        self._by_long = {}
        self._by_short = {}

    def add_flag(self, name, short=None):
        """A boolean switch ``--name`` (or ``-s``); defaults to False."""
        self._add(_Spec(name, short, False, False, False))

    def add_option(self, name, short=None, repeat=False, default=None):
        """An option taking one value.

        With ``repeat=True`` every occurrence is collected into a list (default
        ``[]``); otherwise the last occurrence wins.
        """
        self._add(_Spec(name, short, True, repeat, [] if repeat else default))

    def _add(self, spec):
        if not _LONG_NAME.match(spec.name):
            raise ValueError('invalid option name: %r' % (spec.name,))
        if spec.short is not None and not (len(spec.short) == 1 and spec.short.isalpha()):
            raise ValueError('short option must be a single letter: %r' % (spec.short,))
        if spec.name in self._by_long or (spec.short and spec.short in self._by_short):
            raise ValueError('duplicate option: %r' % (spec.name,))
        self._by_long[spec.name] = spec
        if spec.short:
            self._by_short[spec.short] = spec

    def parse(self, argv):
        """Return ``(values, positionals)``.

        ``values`` maps each option's dest (its long name with ``-`` replaced
        by ``_``) to its value; ``positionals`` lists the other arguments in order.
        """
        values = {}
        for spec in self._by_long.values():
            values[spec.dest] = list(spec.default) if spec.repeat else spec.default
        positionals = []
        args = list(argv)
        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith('--'):
                spec = self._by_long.get(arg[2:])
                if spec is None:
                    raise UsageError('unknown option: ' + arg)
                i = self._take(spec, arg, args, i, values)
            elif arg.startswith('-') and arg != '-':
                spec = self._by_short.get(arg[1:]) if len(arg) == 2 else None
                if spec is None:
                    raise UsageError('unknown option: ' + arg)
                i = self._take(spec, arg, args, i, values)
            else:
                positionals.append(arg)
            i += 1
        return values, positionals

    def _take(self, spec, arg, args, i, values):
        """Apply ``spec`` found at ``args[i]``; return the index of the last argument used."""
        if not spec.takes_value:
            values[spec.dest] = True
            return i
        if i + 1 >= len(args):
            raise UsageError('option %s requires a value' % (arg,))
        self._store(spec, args[i + 1], values)
        return i + 1

    @staticmethod
    def _store(spec, value, values):
        if spec.repeat:
            values[spec.dest].append(value)
        else:
            values[spec.dest] = value
