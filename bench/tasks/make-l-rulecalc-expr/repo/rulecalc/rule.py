"""Public entry points: compile a rule once, evaluate it many times."""


class Rule(object):
    """A compiled rule. Instances are created by :func:`compile_rule`."""

    @property
    def variables(self):
        raise NotImplementedError('Rule.variables is not implemented yet')

    def evaluate(self, variables=None):
        raise NotImplementedError('Rule.evaluate is not implemented yet')


def compile_rule(source):
    """Tokenize and parse ``source``; return a :class:`Rule`."""
    raise NotImplementedError('compile_rule is not implemented yet')


def evaluate(source, variables=None):
    """Convenience: ``compile_rule(source).evaluate(variables)``."""
    return compile_rule(source).evaluate(variables)
