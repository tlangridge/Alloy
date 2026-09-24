import unittest

from staticserve.paths import PathTraversalError, resolve_request_path


class ResolveTests(unittest.TestCase):
    def test_plain_file(self):
        self.assertEqual(resolve_request_path('/srv/www', '/guide/intro.html'), '/srv/www/guide/intro.html')

    def test_root_request(self):
        self.assertEqual(resolve_request_path('/srv/www', '/'), '/srv/www')

    def test_percent_escapes_decoded(self):
        self.assertEqual(resolve_request_path('/srv/www', '/release%20notes.html'), '/srv/www/release notes.html')

    def test_parent_escape_rejected(self):
        with self.assertRaises(PathTraversalError):
            resolve_request_path('/srv/www', '/../../etc/passwd')


if __name__ == '__main__':
    unittest.main()
