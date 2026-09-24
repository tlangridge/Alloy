"""Line layout helpers used by the table renderer and `--help` output.

Everything is measured in terminal display columns (termtext.width), and text
is only ever cut between clusters: a non-zero-width character plus the
zero-width characters (combining marks, joiners) that follow it.
"""
from termtext.width import char_width, text_width


def clusters(text):
    """Split text into clusters; leading zero-width characters join the first."""
    out = []
    for ch in text:
        if out and (char_width(ch) == 0 or text_width(out[-1]) == 0):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _check_int(value, minimum, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError('%s must be an integer >= %d' % (name, minimum))


def _chunks(word, width):
    chunks, cur, cur_w = [], '', 0
    for cl in clusters(word):
        w = text_width(cl)
        if cur and cur_w + w > width:
            chunks.append(cur)
            cur, cur_w = '', 0
        cur += cl
        cur_w += w
    if cur:
        chunks.append(cur)
    return chunks


def _wrap_paragraph(paragraph, width):
    lines, line, line_w = [], '', 0
    for word in paragraph.split(' '):
        if not word:
            continue
        w = text_width(word)
        if line and line_w + 1 + w <= width:
            line, line_w = line + ' ' + word, line_w + 1 + w
            continue
        if line:
            lines.append(line)
            line, line_w = '', 0
        if w <= width:
            line, line_w = word, w
            continue
        pieces = _chunks(word, width)
        lines.extend(pieces[:-1])
        line, line_w = pieces[-1], text_width(pieces[-1])
    lines.append(line)
    return lines


def wrap(text, width):
    """Wrap text to lines of at most `width` display columns."""
    _check_int(width, 2, 'width')
    lines = []
    for paragraph in text.split('\n'):
        lines.extend(_wrap_paragraph(paragraph, width))
    return lines


def truncate(text, width, ellipsis='…'):
    """Cut text to `width` columns, marking the cut with `ellipsis`."""
    _check_int(width, 0, 'width')
    room = width - text_width(ellipsis)
    if room < 0:
        raise ValueError('ellipsis is wider than width')
    if text_width(text) <= width:
        return text
    out, used = '', 0
    for cl in clusters(text):
        w = text_width(cl)
        if used + w > room:
            break
        out += cl
        used += w
    return out.rstrip(' ') + ellipsis


def pad(text, width, align='left'):
    """Pad text with spaces to exactly `width` display columns."""
    if align not in ('left', 'right', 'center'):
        raise ValueError('align must be left, right or center')
    extra = width - text_width(text)
    if extra <= 0:
        return text
    if align == 'left':
        return text + ' ' * extra
    if align == 'right':
        return ' ' * extra + text
    return ' ' * (extra // 2) + text + ' ' * (extra - extra // 2)
