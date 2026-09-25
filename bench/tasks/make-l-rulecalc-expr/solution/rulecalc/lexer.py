"""Tokenizer for rulecalc source text."""
from decimal import Decimal

from .errors import LexError

KEYWORDS = frozenset(['true', 'false', 'null', 'and', 'or', 'not', 'in'])
# Longest operators first so that maximal munch falls out of the scan order.
OPERATORS = ('**', '//', '==', '!=', '<=', '>=', '??',
             '*', '/', '%', '+', '-', '<', '>', '?', ':', '(', ')', '[', ']', ',', '.')
WHITESPACE = ' \t\r\n'
ESCAPES = {'\\': '\\', '"': '"', "'": "'", 'n': '\n', 't': '\t'}
HEX = '0123456789abcdefABCDEF'


class Token(object):
    """One token. ``kind`` is 'number', 'string', 'name', 'keyword', 'op' or 'eof'."""

    __slots__ = ('kind', 'value', 'line', 'column')

    def __init__(self, kind, value, line, column):
        self.kind = kind
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return 'Token(%r, %r, %d:%d)' % (self.kind, self.value, self.line, self.column)


class _Scanner(object):
    def __init__(self, source):
        self.src = source
        self.i = 0
        self.line = 1
        self.col = 1

    def peek(self, offset=0):
        j = self.i + offset
        return self.src[j] if j < len(self.src) else ''

    def advance(self):
        ch = self.src[self.i]
        self.i += 1
        if ch == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch


def _is_ident_start(ch):
    return ch == '_' or ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')


def _is_ident_char(ch):
    return _is_ident_start(ch) or ('0' <= ch <= '9')


def _is_digit(ch):
    return '0' <= ch <= '9' and ch != ''


def _string(sc):
    quote_line, quote_col = sc.line, sc.col
    quote = sc.advance()
    out = []
    while True:
        ch = sc.peek()
        if ch == '' or ch == '\n':
            raise LexError('unterminated string', quote_line, quote_col)
        if ch == quote:
            sc.advance()
            return ''.join(out)
        if ch == '\\':
            esc_line, esc_col = sc.line, sc.col
            sc.advance()
            nxt = sc.peek()
            if nxt in ESCAPES and nxt != '':
                sc.advance()
                out.append(ESCAPES[nxt])
                continue
            if nxt == 'u':
                sc.advance()
                if sc.peek() != '{':
                    raise LexError('invalid escape', esc_line, esc_col)
                sc.advance()
                digits = ''
                while sc.peek() != '' and sc.peek() in HEX:
                    digits += sc.advance()
                if sc.peek() != '}' or not 1 <= len(digits) <= 6:
                    raise LexError('invalid escape', esc_line, esc_col)
                sc.advance()
                cp = int(digits, 16)
                if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                    raise LexError('invalid code point', esc_line, esc_col)
                out.append(chr(cp))
                continue
            raise LexError('invalid escape', esc_line, esc_col)
        out.append(sc.advance())


def tokenize(source):
    """Return the list of tokens for ``source``, ending with an 'eof' token."""
    if not isinstance(source, str):
        raise TypeError('rule source must be a str')
    sc = _Scanner(source)
    tokens = []
    while sc.i < len(source):
        ch = sc.peek()
        if ch in WHITESPACE:
            sc.advance()
            continue
        if ch == '#':
            while sc.peek() not in ('', '\n'):
                sc.advance()
            continue
        line, col = sc.line, sc.col
        if _is_digit(ch):
            text = ''
            while _is_digit(sc.peek()):
                text += sc.advance()
            if sc.peek() == '.' and _is_digit(sc.peek(1)):
                text += sc.advance()
                while _is_digit(sc.peek()):
                    text += sc.advance()
            tokens.append(Token('number', Decimal(text), line, col))
            continue
        if _is_ident_start(ch):
            text = ''
            while sc.peek() != '' and _is_ident_char(sc.peek()):
                text += sc.advance()
            tokens.append(Token('keyword' if text in KEYWORDS else 'name', text, line, col))
            continue
        if ch in ('"', "'"):
            tokens.append(Token('string', _string(sc), line, col))
            continue
        for op in OPERATORS:
            if source.startswith(op, sc.i):
                for _ in op:
                    sc.advance()
                tokens.append(Token('op', op, line, col))
                break
        else:
            raise LexError('unexpected character %r' % ch, line, col)
    tokens.append(Token('eof', None, sc.line, sc.col))
    return tokens
