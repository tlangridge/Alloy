import io
import json
import unittest
import zipfile

from docvault.errors import NotFound, PermissionDenied

from world import ALICE, CAROL, DAN, ERIN, build


def unzip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        return names, {n: archive.read(n).decode('utf-8') for n in names}


class ExportSelectionTests(unittest.TestCase):
    def setUp(self):
        self.svc = build()

    def test_selected_documents_in_request_order(self):
        names, files = unzip(self.svc.export(ALICE, doc_ids=['d5', 'd1']))
        self.assertEqual(names, ['manifest.json', 'd5-alice-private.txt', 'd1-nda-template.txt'])
        self.assertEqual(files['d5-alice-private.txt'], 'private body')
        manifest = json.loads(files['manifest.json'])
        self.assertEqual(manifest, dict(workspace='acme', exported_by='alice', documents=['d5', 'd1']))

    def test_duplicates_are_dropped(self):
        names, _ = unzip(self.svc.export(ALICE, doc_ids=['d1', 'd1', 'd5', 'd1']))
        self.assertEqual(names, ['manifest.json', 'd1-nda-template.txt', 'd5-alice-private.txt'])

    def test_shared_and_archived_documents_can_be_selected(self):
        names, _ = unzip(self.svc.export(CAROL, doc_ids=['d6']))
        self.assertEqual(names, ['manifest.json', 'd6-shared-plan.txt'])
        names, _ = unzip(self.svc.export(ALICE, doc_ids=['d3']))
        self.assertEqual(names, ['manifest.json', 'd3-old-contract.txt'])

    def test_other_workspace_and_missing_ids_are_not_found(self):
        with self.assertRaises(NotFound):
            self.svc.export(ALICE, doc_ids=['d1', 'd7'])
        with self.assertRaises(NotFound):
            self.svc.export(ALICE, doc_ids=['nope'])
        with self.assertRaises(NotFound):
            self.svc.export(ERIN, doc_ids=['d1'])

    def test_export_role_required(self):
        with self.assertRaises(PermissionDenied):
            self.svc.export(DAN, doc_ids=['d6'])

    def test_exactly_one_selector(self):
        with self.assertRaises(ValueError):
            self.svc.export(ALICE)
        with self.assertRaises(ValueError):
            self.svc.export(ALICE, doc_ids=['d1'], folder_id='f-legal')
        with self.assertRaises(TypeError):
            self.svc.export(ALICE, doc_ids='d1')

    def test_export_is_audited_and_deterministic(self):
        first = self.svc.export(ALICE, doc_ids=['d1'])
        self.assertEqual(first, self.svc.export(ALICE, doc_ids=['d1']))
        self.assertEqual(self.svc.audit.events[-1], ('alice', 'export', ('d1',)))


class ExportFolderTests(unittest.TestCase):
    def setUp(self):
        self.svc = build()

    def test_member_gets_readable_non_archived_documents(self):
        names, _ = unzip(self.svc.export(ALICE, folder_id='f-legal'))
        self.assertEqual(names, ['manifest.json', 'd1-nda-template.txt', 'd2-carol-notes.txt'])

    def test_non_member_only_gets_what_they_can_read(self):
        names, _ = unzip(self.svc.export(CAROL, folder_id='f-legal'))
        self.assertEqual(names, ['manifest.json', 'd2-carol-notes.txt'])

    def test_other_workspace_folder_is_not_found(self):
        with self.assertRaises(NotFound):
            self.svc.export(ERIN, folder_id='f-legal')


if __name__ == '__main__':
    unittest.main()
