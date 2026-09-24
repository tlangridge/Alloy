"""Link destination policy."""
import re

SAFE_SCHEMES = frozenset(['http', 'https', 'mailto'])
_SCHEME = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*):')


def sanitize(url):
    """Return the URL to use as an href, or None when it must not be linked.

    Relative URLs (no scheme) are allowed; absolute URLs must use one of
    SAFE_SCHEMES (case-insensitive).
    """
    url = url.strip()
    if not url:
        return None
    m = _SCHEME.match(url)
    if m and m.group(1).lower() not in SAFE_SCHEMES:
        return None
    return url
