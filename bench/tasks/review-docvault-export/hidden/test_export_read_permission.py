import unittest

from docvault.errors import PermissionDenied
from docvault.models import Document, Folder, User
from docvault.service import DocumentService
from docvault.store import MemoryStore

ALICE = User('alice', 'acme', frozenset({'exporter'}))
BOB = User('bob', 'acme', frozenset({'exporter'}))


def build():
    store = MemoryStore()
    store.add_folder(Folder('f-legal', 'acme', 'Legal', members={'alice', 'bob'}))
    store.add_folder(Folder('f-ops', 'acme', 'Ops', members={'carol'}))
    store.add_document(Document('d1', 'acme', 'alice', 'NDA', 'nda body', folder_id='f-legal'))
    store.add_document(Document('d4', 'acme', 'carol', 'Runbook', 'runbook body', folder_id='f-ops'))
    store.add_document(Document('d5', 'acme', 'alice', 'Alice private', 'private body'))
    return DocumentService(store)


class ExplicitSelectionNeedsReadAccessTests(unittest.TestCase):
    """Selecting ids must enforce the same read rules as get_document."""

    def setUp(self):
        self.svc = build()

    def test_same_workspace_exporter_cannot_export_private_document(self):
        with self.assertRaises(PermissionDenied):
            self.svc.get_document(BOB, 'd5')           # the rule get_document enforces
        with self.assertRaises(PermissionDenied):
            self.svc.export(BOB, doc_ids=['d5'])

    def test_unreadable_document_fails_whole_selection(self):
        with self.assertRaises(PermissionDenied):
            self.svc.export(BOB, doc_ids=['d1', 'd5'])

    def test_document_in_folder_user_is_not_member_of(self):
        with self.assertRaises(PermissionDenied):
            self.svc.export(ALICE, doc_ids=['d4'])

    def test_readable_selection_still_works(self):
        self.assertTrue(self.svc.export(BOB, doc_ids=['d1']).startswith(b'PK'))


if __name__ == '__main__':
    unittest.main()
