"""HTML escaping for the two output contexts we produce."""


def escape_text(s):
    """Escape for element content."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def escape_attr(s):
    """Escape for a double-quoted attribute value."""
    return escape_text(s).replace('"', '&quot;').replace("'", '&#39;')
