"""Public entry points: compile a rule once, evaluate it many times."""
from .evaluator import evaluate_tree
from .lexer import tokenize
from .parser import parse, root_names


class Rule(object):
    """A compiled rule. Instances are created by :func:`compile_rule`."""

    def __init__(self, source, tree):
        self.source = source
        self._tree = tree
        self._variables = sorted(root_names(tree))

    @property
    def variables(self):
        return list(self._variables)

    def evaluate(self, variables=None):
        return evaluate_tree(self._tree, dict(variables or {}))


def compile_rule(source):
    """Tokenize and parse ``source``; return a :class:`Rule`."""
    return Rule(source, parse(tokenize(source)))


def evaluate(source, variables=None):
    """Convenience: ``compile_rule(source).evaluate(variables)``."""
    return compile_rule(source).evaluate(variables)
