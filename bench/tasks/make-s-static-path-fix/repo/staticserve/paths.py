"""Map request paths onto files under a document root.

This module is pure string manipulation: it never touches the filesystem.
"""
import posixpath
from urllib.parse import unquote


class PathTraversalError(ValueError):
    """The request path does not resolve to a location inside the document root."""


def resolve_request_path(root, url_path):
    """Return the absolute path under ``root`` that ``url_path`` refers to.

    ``root`` is an absolute POSIX directory path; ``url_path`` is the raw
    path component of the request URL (no query string or fragment).
    """
    root = posixpath.normpath(root)
    decoded = unquote(url_path)
    candidate = posixpath.normpath(posixpath.join(root, decoded.lstrip('/')))
    if not candidate.startswith(root):
        raise PathTraversalError('request escapes the document root: %r' % (url_path,))
    return candidate
