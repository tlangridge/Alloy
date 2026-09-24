import unittest

from docvault.errors import NotFound, PermissionDenied

from world import ALICE, AUDREY, BOB, CAROL, DAN, ERIN, build


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc = build()

    def test_owner_reads_and_is_audited(self):
        self.assertEqual(self.svc.get_document(ALICE, 'd5').body, 'private body')
        self.assertEqual(self.svc.audit.events, [('alice', 'read', ('d5',))])

    def test_folder_member_and_share_and_auditor_read(self):
        self.assertEqual(self.svc.get_document(BOB, 'd2').body, 'carol body')
        self.assertEqual(self.svc.get_document(CAROL, 'd6').body, 'plan body')
        self.assertEqual(self.svc.get_document(AUDREY, 'd5').body, 'private body')

    def test_same_workspace_non_reader_is_denied(self):
        with self.assertRaises(PermissionDenied):
            self.svc.get_document(DAN, 'd5')

    def test_other_workspace_is_not_found(self):
        with self.assertRaises(NotFound):
            self.svc.get_document(ERIN, 'd1')
        with self.assertRaises(NotFound):
            self.svc.get_document(ALICE, 'nope')

    def test_download(self):
        self.assertEqual(self.svc.download(ALICE, 'd1'), ('d1-nda-template.txt', b'nda body'))

    def test_listing_shows_titles_to_all_members(self):
        self.assertEqual([s.id for s in self.svc.list_folder(DAN, 'f-legal')], ['d1', 'd2', 'd3'])
        with self.assertRaises(NotFound):
            self.svc.list_folder(ERIN, 'f-legal')

    def test_search(self):
        self.assertEqual([s.id for s in self.svc.search(DAN, 'PLAN')], ['d6'])
        self.assertEqual(self.svc.search(ERIN, 'plan'), [])


if __name__ == '__main__':
    unittest.main()
