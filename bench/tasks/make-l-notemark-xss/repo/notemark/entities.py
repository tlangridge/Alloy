"""Character references that authors may type (``&amp;``, ``&#38;``, ``&#x26;``...)."""
import re

NAMED = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}
_REF = re.compile(r'&(?:#([0-9]{1,7})|#[xX]([0-9a-fA-F]{1,6})|([A-Za-z]+));')


def decode(s):
    """Decode character references in ``s`` exactly once (a single left-to-right pass).

    Named references are limited to NAMED (case-sensitive); numeric references
    must name a valid, non-surrogate, non-zero code point. Anything else is left
    untouched.
    """
    def replace(m):
        if m.group(3) is not None:
            return NAMED.get(m.group(3), m.group(0))
        cp = int(m.group(1)) if m.group(1) is not None else int(m.group(2), 16)
        if cp == 0 or cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
            return m.group(0)
        return chr(cp)
    return _REF.sub(replace, s)
