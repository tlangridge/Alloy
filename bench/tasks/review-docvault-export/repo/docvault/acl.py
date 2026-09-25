"""Access rules.

There are two levels of access to a document inside a workspace:

* visible - every member of the document's workspace can see that it exists:
  its id, title and folder appear in listings and search results. This is
  what is_visible() answers. Documents of other workspaces are invisible and
  must be reported as NotFound, never PermissionDenied, so that ids of other
  tenants cannot be probed.
* readable - the body may be shown or handed out only to the owner, users it
  is explicitly shared with, members of the folder it is filed in, and the
  workspace's auditors. This is what can_read() / require_read() answer.
"""
from .errors import PermissionDenied

EXPORT_ROLES = frozenset({'exporter', 'admin'})


def is_visible(user, doc):
    """Listing-level visibility: same workspace."""
    return user.workspace_id == doc.workspace_id


def can_read(user, doc, folder=None):
    """May `user` see the body of `doc`? `folder` is the folder doc is filed in."""
    if not is_visible(user, doc):
        return False
    if 'auditor' in user.roles or doc.owner_id == user.id or user.id in doc.shared_with:
        return True
    return folder is not None and folder.id == doc.folder_id and user.id in folder.members


def require_read(user, doc, folder=None):
    if not can_read(user, doc, folder):
        raise PermissionDenied('%s may not read %s' % (user.id, doc.id))


def can_export(user):
    """Exporting is a privileged operation on top of the per-document rules."""
    return bool(EXPORT_ROLES & user.roles)
