import re
import unicodedata

PHONE_RE = re.compile(r'\b\d{3}-\d{4}\b')


def _dedupe(text):
    seen, out = set(), []
    for part in text.split(', '):
        key = part.lower()
        if key not in seen:
            seen.add(key)
            out.append(part)
    return ', '.join(out)


STEP_FUNCS = {
    'strip': str.strip,
    'normalize': lambda text: unicodedata.normalize('NFKC', text).lower(),
    'redact': lambda text: PHONE_RE.sub('[phone]', text),
    'dedupe': _dedupe,
    'truncate': lambda text: text[:200],
    'audit': lambda text: text,
}


class Stage:
    """Root of the cooperative stage hierarchy.

    Subclasses override steps() and call super().steps() so that mixins
    compose; the root contributes the 'strip' step.
    """

    def steps(self):
        return ['strip']

    def run(self, text):
        for step in self.steps():
            text = STEP_FUNCS[step](text)
        return text
