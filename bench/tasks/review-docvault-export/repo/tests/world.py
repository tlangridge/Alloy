"""A shared fixture: two workspaces with a handful of users and documents."""
from docvault.models import Document, Folder, User
from docvault.service import DocumentService
from docvault.store import MemoryStore

ALICE = User('alice', 'acme', frozenset({'exporter'}))
BOB = User('bob', 'acme', frozenset({'exporter'}))
CAROL = User('carol', 'acme', frozenset({'exporter'}))
DAN = User('dan', 'acme')                                  # plain member
AUDREY = User('audrey', 'acme', frozenset({'auditor'}))
ERIN = User('erin', 'globex', frozenset({'admin'}))        # another tenant


def build():
    store = MemoryStore()
    store.add_folder(Folder('f-legal', 'acme', 'Legal', members={'alice', 'bob'}))
    store.add_folder(Folder('f-ops', 'acme', 'Ops', members={'carol'}))
    store.add_folder(Folder('f-gx', 'globex', 'Globex', members={'erin'}))
    for doc in (
        Document('d1', 'acme', 'alice', 'NDA template', 'nda body', folder_id='f-legal'),
        Document('d2', 'acme', 'carol', 'Carol notes', 'carol body', folder_id='f-legal'),
        Document('d3', 'acme', 'alice', 'Old contract', 'old body', folder_id='f-legal', archived=True),
        Document('d4', 'acme', 'carol', 'Runbook', 'runbook body', folder_id='f-ops'),
        Document('d5', 'acme', 'alice', 'Alice private', 'private body'),
        Document('d6', 'acme', 'dan', 'Shared plan', 'plan body', shared_with={'alice', 'carol'}),
        Document('d7', 'globex', 'erin', 'Globex secret', 'gx body', folder_id='f-gx'),
    ):
        store.add_document(doc)
    return DocumentService(store)
