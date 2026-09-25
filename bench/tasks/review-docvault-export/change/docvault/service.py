"""The document API used by the HTTP layer."""
from . import acl, bundle
from .audit import AuditLog
from .errors import NotFound, PermissionDenied
from .models import Summary


class DocumentService:
    def __init__(self, store, audit_log=None):
        self.store = store
        self.audit = audit_log if audit_log is not None else AuditLog()

    def _folder_of(self, doc):
        return self.store.folder(doc.folder_id) if doc.folder_id else None

    def _load(self, user, doc_id):
        """Fetch a document for `user`, or NotFound (also for other workspaces)."""
        doc = self.store.document(doc_id)
        if not acl.is_visible(user, doc):
            raise NotFound(doc_id)          # never reveal other workspaces' ids
        return doc

    def get_document(self, user, doc_id):
        """The full document, if `user` may read it."""
        doc = self._load(user, doc_id)
        acl.require_read(user, doc, self._folder_of(doc))
        self.audit.record(user.id, 'read', [doc.id])
        return doc

    def download(self, user, doc_id):
        """(file name, UTF-8 bytes) of one readable document."""
        doc = self.get_document(user, doc_id)
        return bundle.filename_for(doc), doc.body.encode('utf-8')

    def export(self, user, doc_ids=None, folder_id=None):
        """A zip archive (bytes) of several documents plus manifest.json.

        Pass exactly one of `doc_ids` (explicit selection, archive order is the
        request order, duplicates dropped) or `folder_id` (every readable,
        non-archived document of the folder, by id).
        """
        if (doc_ids is None) == (folder_id is None):
            raise ValueError('pass exactly one of doc_ids or folder_id')
        if not acl.can_export(user):
            raise PermissionDenied('%s may not export documents' % user.id)
        if doc_ids is not None:
            docs = self._selected(user, doc_ids)
        else:
            docs = self._folder_contents(user, folder_id)
        manifest = dict(workspace=user.workspace_id, exported_by=user.id, documents=[d.id for d in docs])
        data = bundle.make_zip([(bundle.filename_for(d), d.body) for d in docs], manifest)
        self.audit.record(user.id, 'export', [d.id for d in docs])
        return data

    def _selected(self, user, doc_ids):
        if isinstance(doc_ids, str):
            raise TypeError('doc_ids must be a collection of ids, not a string')
        docs, seen = [], set()
        for doc_id in doc_ids:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            docs.append(self._load(user, doc_id))
        return docs

    def _folder_contents(self, user, folder_id):
        folder = self.store.folder(folder_id)
        if folder.workspace_id != user.workspace_id:
            raise NotFound(folder_id)
        return [d for d in self.store.folder_documents(folder_id)
                if not d.archived and acl.can_read(user, d, folder)]

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
