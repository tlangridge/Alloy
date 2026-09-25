import unittest

from docpatch import PatchError, apply_patch, diff, json_equal, parse_pointer, resolve
from docpatch.store import Conflict, DocumentStore


class PointerTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_pointer(''), [])
        self.assertEqual(parse_pointer('/a/0'), ['a', '0'])
        self.assertEqual(parse_pointer('/a~1b'), ['a/b'])

    def test_resolve(self):
        doc = {'a': [{'b': 1}]}
        self.assertEqual(resolve(doc, '/a/0/b'), 1)
        with self.assertRaises(PatchError) as ctx:
            resolve(doc, '/missing')
        self.assertEqual(ctx.exception.code, 'path-not-found')


class PatchTests(unittest.TestCase):
    def test_basic_operations(self):
        doc = {'name': 'svc', 'tags': ['a']}
        out = apply_patch(doc, [
            {'op': 'add', 'path': '/tags/-', 'value': 'b'},
            {'op': 'replace', 'path': '/name', 'value': 'svc2'},
            {'op': 'remove', 'path': '/tags/0'},
            {'op': 'test', 'path': '/tags', 'value': ['b']},
        ])
        self.assertEqual(out, {'name': 'svc2', 'tags': ['b']})
        self.assertEqual(doc, {'name': 'svc', 'tags': ['a']})

    def test_failed_test_operation(self):
        with self.assertRaises(PatchError) as ctx:
            apply_patch({'a': 1}, [{'op': 'test', 'path': '/a', 'value': 2}])
        self.assertEqual((ctx.exception.code, ctx.exception.index), ('test-failed', 0))

    def test_equality_and_diff(self):
        self.assertTrue(json_equal({'a': [1, 2]}, {'a': [1.0, 2]}))
        self.assertEqual(diff({'a': 1}, {'a': 1}), [])
        self.assertEqual(apply_patch({'a': 1}, diff({'a': 1}, {'a': 2, 'b': 3})), {'a': 2, 'b': 3})


class StoreTests(unittest.TestCase):
    def test_patch_bumps_revision(self):
        store = DocumentStore()
        store.create('cfg', {'retries': 3})
        self.assertEqual(store.patch('cfg', [{'op': 'inc', 'path': '/retries', 'by': 2}], 1), 2)
        self.assertEqual(store.get('cfg'), (2, {'retries': 5}))
        with self.assertRaises(Conflict):
            store.patch('cfg', [], 1)


if __name__ == '__main__':
    unittest.main()
