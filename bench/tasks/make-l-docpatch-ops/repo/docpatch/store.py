"""A tiny revisioned document store with optimistic concurrency."""
import copy

from .ops import apply_patch


class NotFound(KeyError):
    pass


class Conflict(Exception):
    """The caller's expected revision is not the current revision."""


class DocumentStore(object):
    def __init__(self):
        self._docs = {}

    def create(self, doc_id, document):
        if doc_id in self._docs:
            raise Conflict('document %r already exists' % doc_id)
        self._docs[doc_id] = (1, copy.deepcopy(document))
        return 1

    def get(self, doc_id):
        """Return ``(revision, document)``; the document is a private copy."""
        if doc_id not in self._docs:
            raise NotFound(doc_id)
        revision, document = self._docs[doc_id]
        return revision, copy.deepcopy(document)

    def patch(self, doc_id, operations, expected_revision):
        """Apply ``operations`` atomically; return the new revision.

        Raises Conflict when ``expected_revision`` is stale and lets
        PatchError propagate unchanged. The stored document is handed to
        apply_patch directly (no defensive copy): apply_patch never mutates
        its input.
        """
        if doc_id not in self._docs:
            raise NotFound(doc_id)
        revision, document = self._docs[doc_id]
        if revision != expected_revision:
            raise Conflict('expected revision %d, current is %d' % (expected_revision, revision))
        updated = apply_patch(document, operations)
        self._docs[doc_id] = (revision + 1, updated)
        return revision + 1
