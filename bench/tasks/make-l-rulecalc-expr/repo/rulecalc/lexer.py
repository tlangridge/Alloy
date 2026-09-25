"""Tokenizer for rulecalc source text."""


class Token(object):
    """One token. ``kind`` is a short string such as 'number', 'string',
    'name', 'keyword', 'op' or 'eof'; ``line``/``column`` are 1-based."""

    __slots__ = ('kind', 'value', 'line', 'column')

    def __init__(self, kind, value, line, column):
        self.kind = kind
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return 'Token(%r, %r, %d:%d)' % (self.kind, self.value, self.line, self.column)


def tokenize(source):
    """Return the list of tokens for ``source``, ending with an 'eof' token."""
    raise NotImplementedError('tokenize is not implemented yet')
