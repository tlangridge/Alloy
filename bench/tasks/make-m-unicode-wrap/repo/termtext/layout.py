"""Line layout helpers used by the table renderer and `--help` output."""
import textwrap


def wrap(text, width):
    """Wrap text to lines of at most `width` columns."""
    lines = []
    for paragraph in text.split('\n'):
        lines.extend(textwrap.wrap(paragraph, width) or [''])
    return lines


def pad(text, width, align='left'):
    """Pad text with spaces to `width` columns."""
    if align == 'left':
        return text.ljust(width)
    if align == 'right':
        return text.rjust(width)
    raise ValueError('align must be left or right')
