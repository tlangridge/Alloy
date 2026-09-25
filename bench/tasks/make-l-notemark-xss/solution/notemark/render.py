"""Nodes -> HTML."""
import re

from .entities import decode
from .escape import escape_attr, escape_text
from .inline import parse
from .urls import sanitize

_BLANK = re.compile(r'\n[ \t]*\n')


def render_inline(nodes):
    out = []
    for node in nodes:
        kind = node.kind
        if kind == 'text':
            out.append(escape_text(decode(node.value)))
        elif kind == 'literal':
            out.append(escape_text(node.value))
        elif kind == 'code':
            out.append('<code>%s</code>' % escape_text(node.value))
        elif kind == 'strong':
            out.append('<strong>%s</strong>' % render_inline(node.children))
        elif kind == 'em':
            out.append('<em>%s</em>' % render_inline(node.children))
        elif kind == 'link':
            # Decode exactly once, *then* apply the policy to what the browser will see.
            href = sanitize(decode(node.value))
            if href is None:
                out.append(render_inline(node.children))
            else:
                out.append('<a href="%s">%s</a>' % (escape_attr(href), render_inline(node.children)))
        elif kind == 'autolink':
            url = decode(node.value)
            href = sanitize(url)
            if href is None:
                out.append(escape_text(url))
            else:
                out.append('<a href="%s">%s</a>' % (escape_attr(href), escape_text(url)))
        elif kind == 'mention':
            out.append('<a href="/u/%s">@%s</a>' % (node.value, node.value))
        elif kind == 'break':
            out.append('<br>')
    return ''.join(out)


def to_html(source):
    """Render a comment to HTML: one <p> per paragraph, joined with newlines."""
    text = source.replace('\r\n', '\n').replace('\r', '\n')
    paragraphs = []
    for block in _BLANK.split(text):
        lines = [line.strip() for line in block.split('\n')]
        lines = [line for line in lines if line]
        if lines:
            paragraphs.append('<p>%s</p>' % render_inline(parse('\n'.join(lines))))
    return '\n'.join(paragraphs)
