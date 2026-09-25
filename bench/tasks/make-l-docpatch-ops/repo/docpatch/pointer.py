"""Pointer parsing, formatting and resolution."""


def parse_pointer(pointer):
    """Return the list of reference tokens for ``pointer``."""
    raise NotImplementedError


def format_pointer(tokens):
    """Inverse of :func:`parse_pointer`."""
    raise NotImplementedError


def resolve(document, pointer):
    """Return the value ``pointer`` refers to inside ``document``."""
    raise NotImplementedError
