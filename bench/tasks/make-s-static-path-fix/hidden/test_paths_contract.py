import os
import posixpath
import tempfile
import unittest

from staticserve.paths import PathTraversalError, resolve_request_path

ROOT = '/srv/www'


class FindingTests(unittest.TestCase):
    def test_sibling_with_same_prefix_rejected(self):
        for url in ('/../www-private/keys.txt', '/%2e%2e/www-private/keys.txt', '/../wwwx',
                    '/../www-private', '/sub/../../www2/a'):
            with self.subTest(url=url), self.assertRaises(PathTraversalError):
                resolve_request_path(ROOT, url)

    def test_nul_byte_rejected(self):
        for url in ('/a%00b', '/%00', '/docs/x%00.html', '/a\x00b'):
            with self.subTest(url=url), self.assertRaises(PathTraversalError):
                resolve_request_path(ROOT, url)

    def test_error_is_value_error(self):
        with self.assertRaises(ValueError):
            resolve_request_path(ROOT, '/../www-private/x')


class ContainmentTests(unittest.TestCase):
    def test_escapes_rejected(self):
        for url in ('/..', '/%2e%2e', '/../../etc/passwd', '/a/../../b', '/%2E%2E/x', '/./../x'):
            with self.subTest(url=url), self.assertRaises(PathTraversalError):
                resolve_request_path(ROOT, url)

    def test_dotdot_that_stays_inside_is_allowed(self):
        self.assertEqual(resolve_request_path(ROOT, '/docs/../index.html'), '/srv/www/index.html')
        self.assertEqual(resolve_request_path(ROOT, '/a/b/../../c'), '/srv/www/c')
        self.assertEqual(resolve_request_path(ROOT, '/../www/index.html'), '/srv/www/index.html')

    def test_resolving_to_root_itself(self):
        for url in ('/', '', '//', '/.', '/docs/..', '/./'):
            with self.subTest(url=url):
                self.assertEqual(resolve_request_path(ROOT, url), '/srv/www')

    def test_names_containing_dots_are_ordinary(self):
        self.assertEqual(resolve_request_path(ROOT, '/..hidden/x'), '/srv/www/..hidden/x')
        self.assertEqual(resolve_request_path(ROOT, '/a/...'), '/srv/www/a/...')


class DecodingTests(unittest.TestCase):
    def test_escapes_decoded(self):
        self.assertEqual(resolve_request_path(ROOT, '/release%20notes.html'), '/srv/www/release notes.html')
        self.assertEqual(resolve_request_path(ROOT, '/a%2Fb'), '/srv/www/a/b')

    def test_decoded_exactly_once(self):
        self.assertEqual(resolve_request_path(ROOT, '/%252e%252e/secret'), '/srv/www/%2e%2e/secret')
        self.assertEqual(resolve_request_path(ROOT, '/100%2525'), '/srv/www/100%25')


class NormalizationTests(unittest.TestCase):
    def test_repeated_slashes_and_dots(self):
        self.assertEqual(resolve_request_path(ROOT, '//a//b/./c'), '/srv/www/a/b/c')

    def test_trailing_slash_removed(self):
        self.assertEqual(resolve_request_path(ROOT, '/guide/'), '/srv/www/guide')


class RootFormTests(unittest.TestCase):
    def test_root_with_trailing_slash(self):
        self.assertEqual(resolve_request_path('/srv/www/', '/a.html'), '/srv/www/a.html')
        self.assertEqual(resolve_request_path('/srv/www/', '/'), '/srv/www')
        self.assertEqual(resolve_request_path('/srv/www/', '/docs/../b'), '/srv/www/b')
        for url in ('/../www-private/x', '/..'):
            with self.subTest(url=url), self.assertRaises(PathTraversalError):
                resolve_request_path('/srv/www/', url)

    def test_filesystem_root(self):
        self.assertEqual(resolve_request_path('/', '/srv/data/x.txt'), '/srv/data/x.txt')
        self.assertEqual(resolve_request_path('/', '/'), '/')
        self.assertEqual(resolve_request_path('/', '/../srv/x'), '/srv/x')
        self.assertEqual(resolve_request_path('/', '/a/../..'), '/')

    def test_filesystem_root_still_rejects_nul(self):
        with self.assertRaises(PathTraversalError):
            resolve_request_path('/', '/a%00')

    def test_nested_root(self):
        self.assertEqual(resolve_request_path('/srv/www/site', '/x'), '/srv/www/site/x')
        with self.assertRaises(PathTraversalError):
            resolve_request_path('/srv/www/site', '/../site-old/x')


class LexicalTests(unittest.TestCase):
    def test_symlink_inside_root_is_not_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, 'www')
            outside = os.path.join(tmp, 'outside')
            os.mkdir(root)
            os.mkdir(outside)
            os.symlink(outside, os.path.join(root, 'link'))
            expected = posixpath.join(posixpath.normpath(root), 'link', 'file.txt')
            self.assertEqual(resolve_request_path(root, '/link/file.txt'), expected)

    def test_nonexistent_root_is_fine(self):
        self.assertEqual(resolve_request_path('/definitely/not/here', '/x/y'), '/definitely/not/here/x/y')


if __name__ == '__main__':
    unittest.main()
