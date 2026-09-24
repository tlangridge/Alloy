"""The document API used by the HTTP layer."""
from . import acl, bundle
from .audit import AuditLog
from .errors import NotFound
from .models import Summary


class DocumentService:
    def __init__(self, store, audit_log=None):
        self.store = store
        self.audit = audit_log if audit_log is not None else AuditLog()

    def _folder_of(self, doc):
        return self.store.folder(doc.folder_id) if doc.folder_id else None

    def get_document(self, user, doc_id):
        """The full document, if `user` may read it."""
        doc = self.store.document(doc_id)
        if not acl.is_visible(user, doc):
            raise NotFound(doc_id)          # never reveal other workspaces' ids
        acl.require_read(user, doc, self._folder_of(doc))
        self.audit.record(user.id, 'read', [doc.id])
        return doc

    def download(self, user, doc_id):
        """(file name, UTF-8 bytes) of one readable document."""
        doc = self.get_document(user, doc_id)
        return bundle.filename_for(doc), doc.body.encode('utf-8')

    def list_folder(self, user, folder_id):
        """Summaries of every document filed in a folder of the user's workspace."""
        folder = self.store.folder(folder_id)
        if folder.workspace_id != user.workspace_id:
            raise NotFound(folder_id)
        return [Summary(d.id, d.title, d.archived) for d in self.store.folder_documents(folder_id)
                if acl.is_visible(user, d)]

    def search(self, user, text):
        """Summaries of workspace documents whose title contains `text`."""
        needle = text.casefold()
        return [Summary(d.id, d.title, d.archived) for d in self.store.workspace_documents(user.workspace_id)
                if needle in d.title.casefold()]
