"""Error hierarchy for rulecalc.

Every error carries the 1-based ``line`` and ``column`` of the source position
it refers to, plus a free-form human readable ``message``.
"""


class RuleError(Exception):
    """Base class for every error raised for a rule."""

    def __init__(self, message, line, column):
        super().__init__('%s at %d:%d' % (message, line, column))
        self.message = message
        self.line = line
        self.column = column


class LexError(RuleError):
    """The source text contains something that is not a valid token."""


class ParseError(RuleError):
    """The token stream does not form a valid expression (raised at compile time)."""


class EvalError(RuleError):
    """The expression failed while being evaluated against variables."""
