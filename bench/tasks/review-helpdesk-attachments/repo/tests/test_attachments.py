import os
import tempfile
import unittest

from helpdesk import AttachmentStore


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


if __name__ == '__main__':
    unittest.main()
