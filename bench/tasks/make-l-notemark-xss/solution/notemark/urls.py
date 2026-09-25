"""Link destination policy."""
import re

SAFE_SCHEMES = frozenset(['http', 'https', 'mailto'])
_SCHEME = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*):')
_TAB_OR_NEWLINE = re.compile(r'[\t\n\r]')
_C0_AND_SPACE = ''.join(chr(c) for c in range(0x21))


def sanitize(url):
    """Return the URL to use as an href, or None when it must not be linked.

    Relative URLs (no scheme) are allowed; absolute URLs must use one of
    SAFE_SCHEMES (case-insensitive).
    """
    # Browsers drop tabs/newlines anywhere in a URL and C0 controls/spaces at its
    # ends before looking at the scheme, so the policy must do the same.
    url = _TAB_OR_NEWLINE.sub('', url).strip(_C0_AND_SPACE)
    if not url:
        return None
    m = _SCHEME.match(url)
    if m and m.group(1).lower() not in SAFE_SCHEMES:
        return None
    return url
