"""Errors raised by pinwheel."""


class InvalidVersion(ValueError):
    pass


class InvalidConstraint(ValueError):
    pass


class ResolutionError(Exception):
    """No set of versions satisfies the requirements."""


class UnknownPackage(ResolutionError):
    """A root requirement names a package the registry does not know."""

    def __init__(self, name):
        super().__init__('unknown package %r' % name)
        self.name = name


class CycleError(Exception):
    """The resolved packages cannot be ordered because of dependency cycles."""

    def __init__(self, members):
        super().__init__('dependency cycle among %s' % ', '.join(members))
        self.members = list(members)
