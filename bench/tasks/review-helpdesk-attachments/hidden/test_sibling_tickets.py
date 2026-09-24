import os
import tempfile
import unittest

from helpdesk import AttachmentAccessError, AttachmentStore


class SiblingTicketTests(unittest.TestCase):
    """Ticket 42 must not reach tickets whose id merely starts with '42'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = AttachmentStore(os.path.join(self._tmp.name, 'data'))
        self.store.save(42, 'mine.txt', b'mine')
        self.store.save(420, 'invoice.pdf', b'other customer')
        self.store.save(4217, 'notes/x.txt', b'other customer')

    def tearDown(self):
        self._tmp.cleanup()

    def test_own_file_still_readable(self):
        self.assertEqual(self.store.read(42, 'mine.txt'), b'mine')

    def test_prefix_sibling_ticket_is_rejected(self):
        with self.assertRaises(AttachmentAccessError):
            self.store.read(42, '../420/invoice.pdf')

    def test_longer_prefix_sibling_nested_file_is_rejected(self):
        with self.assertRaises(AttachmentAccessError):
            self.store.read(42, '../4217/notes/x.txt')


if __name__ == '__main__':
    unittest.main()
