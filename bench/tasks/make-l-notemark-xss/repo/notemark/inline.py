"""Inline markup -> list of nodes."""
import re

from .escape import escape_text

ESCAPABLE = frozenset('\\`*_[]()<>@&!#')
_NAME = re.compile(r'[A-Za-z0-9_]+')
_AUTOLINK = re.compile(r'(?:https?|mailto):[^\s<>]*\Z', re.I)


class Node(object):
    __slots__ = ('kind', 'value', 'children')

    def __init__(self, kind, value=None, children=None):
        self.kind = kind          # text, literal, code, strong, em, link, autolink, mention, break
        self.value = value
        self.children = children or []

    def __repr__(self):
        return 'Node(%s, %r, %r)' % (self.kind, self.value, self.children)


def parse(s):
    nodes, _, _ = _parse(s, 0, None, False)
    return nodes


def _word_char(ch):
    return ch.isalnum() or ch == '_'


def _parse(s, i, closer, in_link):
    nodes, buf = [], []

    def flush():
        if buf:
            nodes.append(Node('text', ''.join(buf)))
            del buf[:]

    while i < len(s):
        if closer is not None and s.startswith(closer, i):
            flush()
            return nodes, i + len(closer), True
        ch = s[i]
        if ch == '\\' and i + 1 < len(s) and s[i + 1] in ESCAPABLE:
            flush()
            nodes.append(Node('literal', s[i + 1]))
            i += 2
            continue
        if ch == '`':
            j = s.find('`', i + 1)
            if j != -1:
                flush()
                nodes.append(Node('code', s[i + 1:j]))
                i = j + 1
                continue
        if s.startswith('**', i):
            inner, k, ok = _parse(s, i + 2, '**', in_link)
            if ok and inner:
                flush()
                nodes.append(Node('strong', children=inner))
                i = k
                continue
            buf.append('**')
            i += 2
            continue
        if ch == '_':
            inner, k, ok = _parse(s, i + 1, '_', in_link)
            if ok and inner:
                flush()
                nodes.append(Node('em', children=inner))
                i = k
                continue
            buf.append('_')
            i += 1
            continue
        if ch == '[' and not in_link:
            inner, k, ok = _parse(s, i + 1, ']', True)
            if ok and k < len(s) and s[k] == '(':
                end = s.find(')', k + 1)
                dest = s[k + 1:end] if end != -1 else ''
                if dest and ' ' not in dest and '\n' not in dest:
                    flush()
                    nodes.append(Node('link', dest, inner))
                    i = end + 1
                    continue
            buf.append('[')
            i += 1
            continue
        if ch == '<' and not in_link:
            j = s.find('>', i + 1)
            if j != -1 and _AUTOLINK.match(s[i + 1:j]):
                flush()
                # store the URL ready for output
                nodes.append(Node('autolink', escape_text(s[i + 1:j])))
                i = j + 1
                continue
        if ch == '@' and not in_link and (i == 0 or not _word_char(s[i - 1])):
            m = _NAME.match(s, i + 1)
            if m:
                flush()
                nodes.append(Node('mention', m.group()))
                i = m.end()
                continue
        if ch == '\n':
            flush()
            nodes.append(Node('break'))
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    return nodes, i, closer is None
