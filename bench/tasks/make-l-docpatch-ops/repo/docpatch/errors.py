"""Errors raised by docpatch."""


class PatchError(Exception):
    """A pointer or patch could not be processed.

    ``code``    one of the documented error codes (see the specification)
    ``index``   0-based index of the offending operation, or None when the
                error is not about a specific operation
    ``pointer`` the pointer string involved, exactly as given, or None
    """

    def __init__(self, code, index=None, pointer=None, message=''):
        detail = code
        if index is not None:
            detail += ' in operation %d' % index
        if pointer is not None:
            detail += ' at %r' % (pointer,)
        if message:
            detail += ': ' + message
        super().__init__(detail)
        self.code = code
        self.index = index
        self.pointer = pointer
