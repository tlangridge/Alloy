class DocvaultError(Exception):
    """Base class for service errors."""


class NotFound(DocvaultError):
    """No such object (or it belongs to another workspace)."""


class PermissionDenied(DocvaultError):
    """The acting user may not perform this operation."""
