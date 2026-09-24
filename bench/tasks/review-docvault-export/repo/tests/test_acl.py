import unittest

from docvault import acl
from docvault.models import Document, Folder, User


class AclTests(unittest.TestCase):
    def setUp(self):
        self.folder = Folder('f', 'w', 'F', members={'m'})
        self.doc = Document('d', 'w', 'owner', 'T', 'B', folder_id='f', shared_with={'s'})

    def test_visible_is_workspace_membership(self):
        self.assertTrue(acl.is_visible(User('anyone', 'w'), self.doc))
        self.assertFalse(acl.is_visible(User('owner', 'other'), self.doc))

    def test_readers(self):
        for user_id, roles in (('owner', ()), ('s', ()), ('m', ()), ('x', ('auditor',))):
            with self.subTest(user=user_id):
                self.assertTrue(acl.can_read(User(user_id, 'w', frozenset(roles)), self.doc, self.folder))

    def test_plain_member_cannot_read(self):
        self.assertFalse(acl.can_read(User('x', 'w'), self.doc, self.folder))

    def test_folder_membership_needs_the_folder(self):
        self.assertFalse(acl.can_read(User('m', 'w'), self.doc, None))

    def test_export_roles(self):
        self.assertTrue(acl.can_export(User('a', 'w', frozenset({'exporter'}))))
        self.assertTrue(acl.can_export(User('a', 'w', frozenset({'admin'}))))
        self.assertFalse(acl.can_export(User('a', 'w', frozenset({'auditor'}))))


if __name__ == '__main__':
    unittest.main()
