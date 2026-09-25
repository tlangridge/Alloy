import os
import tempfile
import unittest

from helpdesk import AttachmentAccessError, AttachmentError, AttachmentNotFound, AttachmentStore


class SaveAndListTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.store = AttachmentStore(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_writes_under_ticket_directory(self):
        path = self.store.save(42, 'screens/login.png', b'PNG')
        self.assertEqual(path, os.path.join(self.root, 'tickets', '42', 'screens', 'login.png'))
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), b'PNG')

    def test_list_is_sorted_and_relative(self):
        self.store.save(7, 'b.txt', b'b')
        self.store.save(7, 'a/c.txt', b'c')
        self.assertEqual(self.store.list(7), ['a/c.txt', 'b.txt'])

    def test_list_of_unknown_ticket_is_empty(self):
        self.assertEqual(self.store.list(99), [])

    def test_save_rejects_unsafe_paths(self):
        for bad in ('../x.txt', '/etc/passwd', '.hidden', 'a//b', '', 'x.part'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.store.save(1, bad, b'')

    def test_ticket_id_must_be_positive_int(self):
        for bad in (0, -3, '42', True, 4.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.store.ticket_dir(bad)


class ReadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, 'data')
        self.store = AttachmentStore(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_returns_saved_bytes(self):
        self.store.save(42, 'screens/login.png', b'PNG')
        self.assertEqual(self.store.read(42, 'screens/login.png'), b'PNG')

    def test_read_accepts_legacy_names(self):
        legacy = os.path.join(self.store.ticket_dir(42), '#old export (v2).csv')
        os.makedirs(os.path.dirname(legacy))
        with open(legacy, 'wb') as f:
            f.write(b'a,b')
        self.assertEqual(self.store.read(42, '#old export (v2).csv'), b'a,b')

    def test_read_allows_dotdot_that_stays_inside(self):
        self.store.save(42, 'a/b.txt', b'b')
        self.assertEqual(self.store.read(42, 'a/../a/b.txt'), b'b')

    def test_read_rejects_parent_escape(self):
        self.store.save(43, 'secret.txt', b'nope')
        with self.assertRaises(AttachmentAccessError):
            self.store.read(42, '../43/secret.txt')
        with self.assertRaises(AttachmentAccessError):
            self.store.read(42, '../../../outside.txt')

    def test_read_rejects_absolute_path(self):
        outside = os.path.join(self._tmp.name, 'outside.txt')
        with open(outside, 'wb') as f:
            f.write(b'x')
        with self.assertRaises(AttachmentAccessError):
            self.store.read(42, outside)

    def test_read_rejects_symlink_escape(self):
        outside = os.path.join(self._tmp.name, 'outside.txt')
        with open(outside, 'wb') as f:
            f.write(b'x')
        self.store.save(42, 'real.txt', b'r')
        os.symlink(outside, os.path.join(self.store.ticket_dir(42), 'link.txt'))
        with self.assertRaises(AttachmentAccessError):
            self.store.read(42, 'link.txt')

    def test_read_missing_or_directory_is_not_found(self):
        self.store.save(42, 'a/b.txt', b'b')
        for rel in ('nope.txt', 'a', '', '.'):
            with self.subTest(rel=rel):
                with self.assertRaises(AttachmentNotFound):
                    self.store.read(42, rel)

    def test_access_error_is_an_attachment_error(self):
        self.assertTrue(issubclass(AttachmentAccessError, AttachmentError))


if __name__ == '__main__':
    unittest.main()
