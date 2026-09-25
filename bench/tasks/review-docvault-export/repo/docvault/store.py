"""In-memory persistence. No access control happens here."""
from .errors import NotFound


class MemoryStore:
    def __init__(self):
        self._folders = {}
        self._documents = {}

    def add_folder(self, folder):
        self._folders[folder.id] = folder
        return folder

    def add_document(self, doc):
        if doc.folder_id is not None and doc.folder_id not in self._folders:
            raise NotFound(doc.folder_id)
        self._documents[doc.id] = doc
        return doc

    def folder(self, folder_id):
        try:
            return self._folders[folder_id]
        except KeyError:
            raise NotFound(folder_id) from None

    def document(self, doc_id):
        try:
            return self._documents[doc_id]
        except KeyError:
            raise NotFound(doc_id) from None

    def folder_documents(self, folder_id):
        """Documents in a folder, ordered by id."""
        return sorted((d for d in self._documents.values() if d.folder_id == folder_id), key=lambda d: d.id)

    def workspace_documents(self, workspace_id):
        """Documents of a workspace, ordered by id."""
        return sorted((d for d in self._documents.values() if d.workspace_id == workspace_id), key=lambda d: d.id)
