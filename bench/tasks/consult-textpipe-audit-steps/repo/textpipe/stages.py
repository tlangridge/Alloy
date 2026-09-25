from textpipe.base import Stage


class Normalize(Stage):
    """Unicode-normalize and lower-case before the rest of the chain."""

    def steps(self):
        return ['normalize'] + super().steps()


class Redact(Stage):
    """Mask phone numbers after everything else has run."""

    def steps(self):
        return super().steps() + ['redact']


class Dedupe(Normalize):
    """Drop repeated comma-separated fragments (needs normalized text)."""

    def steps(self):
        return ['dedupe'] + super().steps()


class Truncate(Stage):
    """Cap the length right after the first step of the chain."""

    def steps(self):
        chain = super().steps()
        return chain[:1] + ['truncate'] + chain[1:]
