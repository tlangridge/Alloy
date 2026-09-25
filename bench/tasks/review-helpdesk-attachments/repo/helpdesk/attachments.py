"""Filesystem storage for ticket attachments.

Layout: ``<root>/tickets/<ticket id>/<relative path>``. Each ticket owns exactly
one directory and nothing outside it.
"""
import os
import re

# One path segment as accepted by save(): starts with a letter or digit, so
# '.', '..' and hidden files are impossible.
_SEGMENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._ -]{0,127}')
_PARTIAL = '.part'


class AttachmentError(Exception):
    """Base class for attachment storage errors."""


class AttachmentNotFound(AttachmentError):
    """The ticket has no attachment at that path."""


def _ticket_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('ticket id must be a positive integer, got %r' % (value,))
    return value


def _clean_relpath(relpath):
    """Validate a relative path made only of safe segments; return it OS-joined."""
    if not isinstance(relpath, str):
        raise TypeError('attachment path must be a string')
    parts = relpath.replace('\\', '/').split('/')
    if any(not _SEGMENT.fullmatch(p) or p.endswith(_PARTIAL) for p in parts):
        raise ValueError('invalid attachment path: %r' % relpath)
    return os.path.join(*parts)


class AttachmentStore:
    def __init__(self, root):
        self.root = os.path.abspath(root)

    def ticket_dir(self, ticket_id):
        """Absolute directory holding one ticket's attachments."""
        return os.path.join(self.root, 'tickets', str(_ticket_id(ticket_id)))

    def save(self, ticket_id, relpath, data):
        """Atomically write `data` (bytes) and return the absolute path written."""
        path = os.path.join(self.ticket_dir(ticket_id), _clean_relpath(relpath))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        partial = path + _PARTIAL
        with open(partial, 'wb') as f:
            f.write(data)
        os.replace(partial, path)
        return path

    def list(self, ticket_id):
        """Sorted relative paths ('/'-separated) of a ticket's attachments."""
        base = self.ticket_dir(ticket_id)
        found = []
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(_PARTIAL):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), base)
                found.append(rel.replace(os.sep, '/'))
        return sorted(found)
