"""Parser: token list -> syntax tree (recursive descent, one level per precedence)."""
from .errors import ParseError
from .functions import FUNCTIONS


class Node(object):
    """A syntax tree node: ``kind`` plus positional data in ``args``; ``pos`` is (line, column)."""

    __slots__ = ('kind', 'args', 'pos')

    def __init__(self, kind, pos, *args):
        self.kind = kind
        self.pos = pos
        self.args = args

    def __repr__(self):
        return 'Node(%s, %r)' % (self.kind, self.args)


COMPARISONS = ('==', '!=', '<', '<=', '>', '>=')


class _Parser(object):
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    # -- token helpers -------------------------------------------------------
    @property
    def tok(self):
        return self.tokens[self.i]

    def at(self, kind, value=None, offset=0):
        t = self.tokens[min(self.i + offset, len(self.tokens) - 1)]
        return t.kind == kind and (value is None or t.value == value)

    def at_op(self, value, offset=0):
        return self.at('op', value, offset)

    def at_kw(self, value, offset=0):
        return self.at('keyword', value, offset)

    def take(self):
        t = self.tokens[self.i]
        if t.kind != 'eof':
            self.i += 1
        return t

    def fail(self, token=None, message='unexpected token'):
        t = token or self.tok
        if t.kind == 'eof':
            message = 'unexpected end of input'
        raise ParseError(message, t.line, t.column)

    def expect_op(self, value):
        if not self.at_op(value):
            self.fail()
        return self.take()

    # -- grammar -------------------------------------------------------------
    def parse(self):
        node = self.conditional()
        if self.tok.kind != 'eof':
            self.fail()
        return node

    def conditional(self):
        cond = self.coalesce()
        if self.at_op('?'):
            q = self.take()
            then = self.conditional()
            self.expect_op(':')
            other = self.conditional()
            return Node('cond', (q.line, q.column), cond, then, other)
        return cond

    def coalesce(self):
        left = self.or_expr()
        while self.at_op('??'):
            t = self.take()
            left = Node('coalesce', (t.line, t.column), left, self.or_expr())
        return left

    def or_expr(self):
        left = self.and_expr()
        while self.at_kw('or'):
            t = self.take()
            left = Node('or', (t.line, t.column), left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.at_kw('and'):
            t = self.take()
            left = Node('and', (t.line, t.column), left, self.not_expr())
        return left

    def not_expr(self):
        if self.at_kw('not'):
            t = self.take()
            return Node('not', (t.line, t.column), self.not_expr())
        return self.comparison()

    def comparison(self):
        first = self.additive()
        operands, ops = [first], []
        while True:
            if self.tok.kind == 'op' and self.tok.value in COMPARISONS:
                t = self.take()
                ops.append((t.value, (t.line, t.column)))
            elif self.at_kw('in'):
                t = self.take()
                ops.append(('in', (t.line, t.column)))
            elif self.at_kw('not') and self.at_kw('in', 1):
                t = self.take()
                self.take()
                ops.append(('not in', (t.line, t.column)))
            else:
                break
            operands.append(self.additive())
        if not ops:
            return first
        return Node('compare', ops[0][1], operands, ops)

    def additive(self):
        left = self.multiplicative()
        while self.tok.kind == 'op' and self.tok.value in ('+', '-'):
            t = self.take()
            left = Node('binary', (t.line, t.column), t.value, left, self.multiplicative())
        return left

    def multiplicative(self):
        left = self.unary()
        while self.tok.kind == 'op' and self.tok.value in ('*', '/', '//', '%'):
            t = self.take()
            left = Node('binary', (t.line, t.column), t.value, left, self.unary())
        return left

    def unary(self):
        if self.tok.kind == 'op' and self.tok.value in ('-', '+'):
            t = self.take()
            return Node('unary', (t.line, t.column), t.value, self.unary())
        return self.power()

    def power(self):
        base = self.postfix()
        if self.at_op('**'):
            t = self.take()
            return Node('binary', (t.line, t.column), '**', base, self.unary())
        return base

    def postfix(self):
        node = self.primary()
        while True:
            if self.at_op('.'):
                self.take()
                if self.tok.kind != 'name':
                    self.fail()
                name = self.take()
                node = Node('member', (name.line, name.column), node, name.value)
            elif self.at_op('['):
                t = self.take()
                index = self.conditional()
                self.expect_op(']')
                node = Node('index', (t.line, t.column), node, index)
            else:
                return node

    def primary(self):
        t = self.tok
        pos = (t.line, t.column)
        if t.kind == 'number':
            self.take()
            return Node('const', pos, t.value)
        if t.kind == 'string':
            self.take()
            return Node('const', pos, t.value)
        if t.kind == 'keyword' and t.value in ('true', 'false', 'null'):
            self.take()
            return Node('const', pos, {'true': True, 'false': False, 'null': None}[t.value])
        if t.kind == 'name':
            self.take()
            if self.at_op('('):
                return self.call(t)
            return Node('name', pos, t.value)
        if t.kind == 'op' and t.value == '(':
            self.take()
            node = self.conditional()
            self.expect_op(')')
            return node
        if t.kind == 'op' and t.value == '[':
            self.take()
            items = []
            if not self.at_op(']'):
                items.append(self.conditional())
                while self.at_op(','):
                    self.take()
                    items.append(self.conditional())
            self.expect_op(']')
            return Node('list', pos, items)
        self.fail()

    def call(self, name_tok):
        pos = (name_tok.line, name_tok.column)
        fn = FUNCTIONS.get(name_tok.value)
        if fn is None:
            raise ParseError('unknown function %r' % name_tok.value, *pos)
        self.take()  # '('
        args = []
        if not self.at_op(')'):
            args.append(self.conditional())
            while self.at_op(','):
                self.take()
                args.append(self.conditional())
        self.expect_op(')')
        low, high = fn.min_args, fn.max_args
        if len(args) < low or (high is not None and len(args) > high):
            raise ParseError('wrong number of arguments for %s()' % name_tok.value, *pos)
        return Node('call', pos, name_tok.value, args)


def parse(tokens):
    """Parse a complete expression from ``tokens`` and return the root node."""
    return _Parser(tokens).parse()


def root_names(node, out=None):
    """Set of root variable names referenced anywhere in the tree."""
    out = set() if out is None else out
    if node.kind == 'name':
        out.add(node.args[0])
    for arg in node.args:
        if isinstance(arg, Node):
            root_names(arg, out)
        elif isinstance(arg, list):
            for item in arg:
                if isinstance(item, Node):
                    root_names(item, out)
    return out
