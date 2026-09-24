import copy
import random
import unittest

from docpatch import PatchError, apply_patch, diff, format_pointer, json_equal, parse_pointer, resolve
from docpatch.store import DocumentStore


class Base(unittest.TestCase):
    def fails(self, code, index, pointer, fn, *args, check_pointer=True):
        with self.assertRaises(PatchError) as ctx:
            fn(*args)
        exc = ctx.exception
        self.assertEqual(exc.code, code, str(exc))
        self.assertEqual(exc.index, index, str(exc))
        if check_pointer:
            self.assertEqual(exc.pointer, pointer, str(exc))
        return exc

    def patch_fails(self, code, index, pointer, doc, ops, check_pointer=True):
        before = copy.deepcopy(doc)
        exc = self.fails(code, index, pointer, apply_patch, doc, ops, check_pointer=check_pointer)
        self.assertEqual(doc, before, 'input document was mutated by a failing patch')
        return exc


class PointerTests(Base):
    def test_parse_edge_tokens(self):
        self.assertEqual(parse_pointer('/'), [''])
        self.assertEqual(parse_pointer('/a//b'), ['a', '', 'b'])
        self.assertEqual(parse_pointer('/~01'), ['~1'])
        self.assertEqual(parse_pointer('/~10'), ['/0'])
        self.assertEqual(parse_pointer('/a~1b/c~0d'), ['a/b', 'c~d'])

    def test_parse_invalid(self):
        for bad in ['a', '/a~2', '/a~', '#/a', 'a/b']:
            self.fails('invalid-pointer', None, bad, parse_pointer, bad)
        self.fails('invalid-pointer', None, 5, parse_pointer, 5)

    def test_format_is_exact_inverse(self):
        self.assertEqual(format_pointer([]), '')
        self.assertEqual(format_pointer(['a/b', '~1', '']), '/a~1b/~01/')
        for tokens in (['~/'], ['', ''], ['x~0y', '/~']):
            self.assertEqual(parse_pointer(format_pointer(tokens)), tokens)

    def test_resolve_array_index_rules(self):
        doc = {'l': ['x', 'y'], 'd': {'01': 'k', '-': 'dash'}}
        for token in ['01', '-', '1.0', ' 1', '+1', '-1', 'a']:
            self.fails('invalid-index', None, '/l/' + token, resolve, doc, '/l/' + token)
        self.fails('path-not-found', None, '/l/2', resolve, doc, '/l/2')
        self.assertEqual(resolve(doc, '/l/1'), 'y')
        self.assertEqual(resolve(doc, '/d/01'), 'k')
        self.assertEqual(resolve(doc, '/d/-'), 'dash')

    def test_resolve_through_scalars(self):
        doc = {'n': 5, 's': 'str', 'z': None, 'b': True}
        for p in ['/n/0', '/s/0', '/z/a', '/b/x', '/missing']:
            self.fails('path-not-found', None, p, resolve, doc, p)
        self.assertEqual(resolve(doc, ''), doc)


class EqualityTests(Base):
    def test_booleans_are_not_numbers(self):
        self.assertFalse(json_equal(True, 1))
        self.assertFalse(json_equal(False, 0))
        self.assertFalse(json_equal([True], [1]))
        self.assertFalse(json_equal({'a': 0}, {'a': False}))
        self.assertFalse(json_equal(None, False))
        self.assertTrue(json_equal(1, 1.0))
        self.assertTrue(json_equal(True, True))

    def test_structures(self):
        self.assertTrue(json_equal({'a': 1, 'b': [1, 2]}, {'b': [1.0, 2], 'a': 1}))
        self.assertFalse(json_equal([1, 2], [2, 1]))
        self.assertFalse(json_equal({'a': 1}, {'a': 1, 'b': None}))
        self.assertFalse(json_equal([], {}))
        self.assertFalse(json_equal('1', 1))


class AddRemoveReplaceTests(Base):
    def test_add_object_key(self):
        self.assertEqual(apply_patch({'a': 1}, [{'op': 'add', 'path': '/b', 'value': 2}]), {'a': 1, 'b': 2})
        self.assertEqual(apply_patch({'a': 1}, [{'op': 'add', 'path': '/a', 'value': 9}]), {'a': 9})
        self.assertEqual(apply_patch({}, [{'op': 'add', 'path': '/01', 'value': 1}]), {'01': 1})

    def test_add_array_positions(self):
        doc = {'l': ['a', 'b']}
        self.assertEqual(apply_patch(doc, [{'op': 'add', 'path': '/l/0', 'value': 'z'}])['l'], ['z', 'a', 'b'])
        self.assertEqual(apply_patch(doc, [{'op': 'add', 'path': '/l/2', 'value': 'z'}])['l'], ['a', 'b', 'z'])
        self.assertEqual(apply_patch(doc, [{'op': 'add', 'path': '/l/-', 'value': 'z'}])['l'], ['a', 'b', 'z'])
        self.patch_fails('path-not-found', 0, '/l/3', doc, [{'op': 'add', 'path': '/l/3', 'value': 'z'}])
        self.patch_fails('invalid-index', 0, '/l/01', doc, [{'op': 'add', 'path': '/l/01', 'value': 'z'}])

    def test_add_root_replaces_document(self):
        self.assertEqual(apply_patch({'a': 1}, [{'op': 'add', 'path': '', 'value': [1]}]), [1])

    def test_add_missing_or_scalar_parent(self):
        doc = {'a': 5, 'l': [1]}
        self.patch_fails('path-not-found', 0, '/x/y/z', doc, [{'op': 'add', 'path': '/x/y/z', 'value': 1}])
        self.patch_fails('path-not-found', 0, '/a/b', doc, [{'op': 'add', 'path': '/a/b', 'value': 1}])
        self.patch_fails('invalid-index', 0, '/l/-/x', doc, [{'op': 'add', 'path': '/l/-/x', 'value': 1}])

    def test_null_value_is_present(self):
        self.assertEqual(apply_patch({}, [{'op': 'add', 'path': '/n', 'value': None}]), {'n': None})
        self.assertEqual(apply_patch({'n': 1}, [{'op': 'replace', 'path': '/n', 'value': None}]), {'n': None})
        self.assertEqual(apply_patch({'n': None}, [{'op': 'test', 'path': '/n', 'value': None}]), {'n': None})

    def test_remove(self):
        self.assertEqual(apply_patch({'l': [1, 2, 3]}, [{'op': 'remove', 'path': '/l/0'}]), {'l': [2, 3]})
        self.assertEqual(apply_patch({'a': 1, 'b': 2}, [{'op': 'remove', 'path': '/a'}]), {'b': 2})
        self.patch_fails('invalid-index', 0, '/l/-', {'l': [1]}, [{'op': 'remove', 'path': '/l/-'}])
        self.patch_fails('path-not-found', 0, '/l/1', {'l': [1]}, [{'op': 'remove', 'path': '/l/1'}])
        self.patch_fails('path-not-found', 0, '/q', {'l': [1]}, [{'op': 'remove', 'path': '/q'}])
        self.patch_fails('cannot-remove-root', 0, '', {'l': [1]}, [{'op': 'remove', 'path': ''}])

    def test_replace(self):
        self.assertEqual(apply_patch({'l': [1, 2]}, [{'op': 'replace', 'path': '/l/1', 'value': 'x'}]), {'l': [1, 'x']})
        self.assertEqual(apply_patch({'a': 1}, [{'op': 'replace', 'path': '', 'value': 'all'}]), 'all')
        self.patch_fails('path-not-found', 0, '/b', {'a': 1}, [{'op': 'replace', 'path': '/b', 'value': 1}])
        self.patch_fails('path-not-found', 0, '/l/2', {'l': [1, 2]}, [{'op': 'replace', 'path': '/l/2', 'value': 1}])


class MoveCopyTests(Base):
    def test_move_array_semantics_after_removal(self):
        doc = {'l': ['a', 'b', 'c']}
        self.assertEqual(apply_patch(doc, [{'op': 'move', 'from': '/l/0', 'path': '/l/2'}])['l'], ['b', 'c', 'a'])
        self.assertEqual(apply_patch(doc, [{'op': 'move', 'from': '/l/2', 'path': '/l/0'}])['l'], ['c', 'a', 'b'])
        self.patch_fails('path-not-found', 0, '/l/3', doc, [{'op': 'move', 'from': '/l/0', 'path': '/l/3'}])

    def test_move_into_self_is_token_wise(self):
        doc = {'a': {'b': 1}, 'ab': 2}
        self.patch_fails('move-into-self', 0, '/a/b', doc, [{'op': 'move', 'from': '/a', 'path': '/a/b'}])
        self.patch_fails('move-into-self', 0, '/x', doc, [{'op': 'move', 'from': '', 'path': '/x'}])
        out = apply_patch({'a': {'b': 1}}, [{'op': 'move', 'from': '/a/b', 'path': '/a/bc'}])
        self.assertEqual(out, {'a': {'bc': 1}})
        out = apply_patch(doc, [{'op': 'move', 'from': '/a', 'path': '/ab'}])
        self.assertEqual(out, {'ab': {'b': 1}})

    def test_move_to_same_path_is_noop_but_source_must_exist(self):
        self.assertEqual(apply_patch({'a': [1]}, [{'op': 'move', 'from': '/a', 'path': '/a'}]), {'a': [1]})
        self.patch_fails('path-not-found', 0, '/zz', {'a': 1}, [{'op': 'move', 'from': '/zz', 'path': '/zz'}])

    def test_move_errors_report_the_right_pointer(self):
        doc = {'a': 1, 'l': [1]}
        self.patch_fails('path-not-found', 0, '/nope', doc, [{'op': 'move', 'from': '/nope', 'path': '/b'}])
        self.patch_fails('invalid-index', 0, '/l/-', doc, [{'op': 'move', 'from': '/l/-', 'path': '/b'}])
        self.patch_fails('path-not-found', 0, '/x/y', doc, [{'op': 'move', 'from': '/a', 'path': '/x/y'}])

    def test_move_to_root(self):
        self.assertEqual(apply_patch({'a': {'k': 1}, 'b': 2}, [{'op': 'move', 'from': '/a', 'path': ''}]), {'k': 1})

    def test_copy_is_deep(self):
        doc = {'a': {'l': [1]}}
        out = apply_patch(doc, [
            {'op': 'copy', 'from': '/a', 'path': '/b'},
            {'op': 'add', 'path': '/b/l/-', 'value': 2},
            {'op': 'replace', 'path': '/b/l/0', 'value': 'x'},
        ])
        self.assertEqual(out, {'a': {'l': [1]}, 'b': {'l': ['x', 2]}})
        self.assertEqual(apply_patch([1, 2], [{'op': 'copy', 'from': '/0', 'path': '/-'}]), [1, 2, 1])

    def test_copy_errors(self):
        doc = {'a': 1}
        self.patch_fails('path-not-found', 0, '/nope', doc, [{'op': 'copy', 'from': '/nope', 'path': '/b'}])
        self.patch_fails('path-not-found', 0, '/q/r', doc, [{'op': 'copy', 'from': '/a', 'path': '/q/r'}])


class TestAndIncTests(Base):
    def test_test_uses_json_equality(self):
        doc = {'n': 1, 'b': True, 'o': {'x': 1, 'y': [1, 2]}}
        apply_patch(doc, [{'op': 'test', 'path': '/n', 'value': 1.0}])
        apply_patch(doc, [{'op': 'test', 'path': '/o', 'value': {'y': [1, 2.0], 'x': 1}}])
        self.patch_fails('test-failed', 0, '/b', doc, [{'op': 'test', 'path': '/b', 'value': 1}])
        self.patch_fails('test-failed', 0, '/n', doc, [{'op': 'test', 'path': '/n', 'value': True}])
        self.patch_fails('test-failed', 0, '/o/y', doc, [{'op': 'test', 'path': '/o/y', 'value': [2, 1]}])
        self.patch_fails('path-not-found', 0, '/q', doc, [{'op': 'test', 'path': '/q', 'value': None}])

    def test_inc_result_types(self):
        out = apply_patch({'i': 2, 'f': 1.5}, [
            {'op': 'inc', 'path': '/i', 'by': 3},
            {'op': 'inc', 'path': '/f', 'by': 1},
        ])
        self.assertEqual(out, {'i': 5, 'f': 2.5})
        self.assertIs(type(out['i']), int)
        self.assertIs(type(out['f']), float)
        out = apply_patch([1], [{'op': 'inc', 'path': '/0', 'by': 0.5}])
        self.assertEqual(out, [1.5])
        self.assertIs(type(out[0]), float)
        self.assertIs(type(apply_patch(3, [{'op': 'inc', 'path': '', 'by': -3}])), int)

    def test_inc_target_rules(self):
        doc = {'b': True, 's': '1', 'z': None}
        self.patch_fails('type-mismatch', 0, '/b', doc, [{'op': 'inc', 'path': '/b', 'by': 1}])
        self.patch_fails('type-mismatch', 0, '/s', doc, [{'op': 'inc', 'path': '/s', 'by': 1}])
        self.patch_fails('type-mismatch', 0, '/z', doc, [{'op': 'inc', 'path': '/z', 'by': 1}])
        self.patch_fails('path-not-found', 0, '/n', doc, [{'op': 'inc', 'path': '/n', 'by': 1}])

    def test_inc_by_must_be_a_number(self):
        for bad in [{'by': True}, {'by': '1'}, {'by': None}, {}]:
            op = dict({'op': 'inc', 'path': '/n'}, **bad)
            self.patch_fails('invalid-op', 0, None, {'n': 1}, [op], check_pointer=False)


class ValidationTests(Base):
    def test_structural_validation_precedes_application(self):
        doc = {'a': 1}
        self.patch_fails('invalid-op', 1, None, doc, [
            {'op': 'test', 'path': '/a', 'value': 2},
            {'op': 'merge', 'path': '/a'},
        ], check_pointer=False)
        self.patch_fails('invalid-pointer', 2, 'a', doc, [
            {'op': 'remove', 'path': '/missing'},
            {'op': 'add', 'path': '/ok', 'value': 1},
            {'op': 'add', 'path': 'a', 'value': 1},
        ])

    def test_lowest_invalid_operation_is_reported(self):
        self.patch_fails('invalid-op', 1, None, {}, [
            {'op': 'add', 'path': '/a', 'value': 1},
            {'op': 'add', 'path': '/b'},
            {'op': 'nope', 'path': '/c'},
        ], check_pointer=False)

    def test_required_members(self):
        cases = [
            {'op': 'add', 'path': '/x'},
            {'op': 'replace', 'path': '/x'},
            {'op': 'test', 'path': '/x'},
            {'op': 'move', 'path': '/x'},
            {'op': 'copy', 'path': '/x', 'from': 7},
            {'op': 'remove'},
            {'op': 'remove', 'path': 3},
            {'path': '/x', 'value': 1},
            {'op': 'ADD', 'path': '/x', 'value': 1},
        ]
        for op in cases:
            self.patch_fails('invalid-op', 0, None, {'x': 1}, [op], check_pointer=False)

    def test_invalid_from_pointer(self):
        self.patch_fails('invalid-pointer', 0, 'x~', {'x': 1}, [{'op': 'copy', 'from': 'x~', 'path': '/y'}])
        self.patch_fails('invalid-pointer', 0, '/x~2', {'x': 1}, [{'op': 'move', 'from': '/x~2', 'path': '/y'}])

    def test_extra_members_ignored(self):
        self.assertEqual(apply_patch({}, [{'op': 'add', 'path': '/a', 'value': 1, 'from': 5, 'note': 'x'}]), {'a': 1})

    def test_patch_shape(self):
        self.fails('invalid-op', None, None, apply_patch, {}, {'op': 'add'}, check_pointer=False)
        self.patch_fails('invalid-op', 1, None, {}, [{'op': 'add', 'path': '/a', 'value': 1}, 'remove'], check_pointer=False)


class AtomicityTests(Base):
    def test_failure_leaves_input_untouched(self):
        doc = {'l': [1, 2], 'o': {'k': 'v'}}
        self.patch_fails('path-not-found', 3, '/nope', doc, [
            {'op': 'add', 'path': '/l/-', 'value': 3},
            {'op': 'remove', 'path': '/o/k'},
            {'op': 'replace', 'path': '/l/0', 'value': 'x'},
            {'op': 'remove', 'path': '/nope'},
        ])

    def test_success_does_not_mutate_or_share(self):
        doc = {'l': [1, {'deep': [1]}], 'keep': {'x': []}}
        value = {'v': [1]}
        patch = [{'op': 'add', 'path': '/new', 'value': value}]
        out = apply_patch(doc, patch)
        self.assertEqual(doc, {'l': [1, {'deep': [1]}], 'keep': {'x': []}})
        out['l'][1]['deep'].append(2)
        out['keep']['x'].append(1)
        self.assertEqual(doc, {'l': [1, {'deep': [1]}], 'keep': {'x': []}})
        value['v'].append(2)
        self.assertEqual(out['new'], {'v': [1]})
        out['new']['v'].append(3)
        self.assertEqual(patch[0]['value'], {'v': [1, 2]})

    def test_operations_see_previous_results(self):
        out = apply_patch({}, [
            {'op': 'add', 'path': '/a', 'value': {'l': []}},
            {'op': 'add', 'path': '/a/l/-', 'value': 1},
            {'op': 'test', 'path': '/a/l/0', 'value': 1},
            {'op': 'move', 'from': '/a/l', 'path': '/l'},
            {'op': 'inc', 'path': '/l/0', 'by': 1},
        ])
        self.assertEqual(out, {'a': {}, 'l': [2]})

    def test_store_patch_is_atomic(self):
        store = DocumentStore()
        store.create('d', {'l': [1], 'n': 1})
        with self.assertRaises(PatchError):
            store.patch('d', [{'op': 'add', 'path': '/l/-', 'value': 2},
                              {'op': 'inc', 'path': '/n', 'by': 1},
                              {'op': 'remove', 'path': '/missing'}], 1)
        self.assertEqual(store.get('d'), (1, {'l': [1], 'n': 1}))
        self.assertEqual(store.patch('d', [{'op': 'inc', 'path': '/n', 'by': 1}], 1), 2)
        self.assertEqual(store.get('d'), (2, {'l': [1], 'n': 2}))


def _random_value(rng, depth):
    kind = rng.randrange(8 if depth < 3 else 6)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.randrange(-3, 4)
    if kind == 3:
        return rng.choice([0.5, 1.0, 2.0, -1.5])
    if kind in (4, 5):
        return rng.choice(['', 'a', 'b', 'x/y', '~'])
    if kind == 6:
        return [_random_value(rng, depth + 1) for _ in range(rng.randrange(5))]
    keys = ['a', 'b', 'c', 'a/b', '~0', '', '-', '01']
    return {k: _random_value(rng, depth + 1) for k in rng.sample(keys, rng.randrange(5))}


def _mutate(rng, value, depth=0):
    roll = rng.random()
    if roll < 0.15:
        return _random_value(rng, depth)
    if isinstance(value, list):
        out = [_mutate(rng, v, depth + 1) if rng.random() < 0.5 else copy.deepcopy(v) for v in value]
        for _ in range(rng.randrange(3)):
            if out and rng.random() < 0.5:
                del out[rng.randrange(len(out))]
            else:
                out.insert(rng.randrange(len(out) + 1), _random_value(rng, depth + 1))
        return out
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            r = rng.random()
            if r < 0.2:
                continue
            out[k] = _mutate(rng, v, depth + 1) if r < 0.6 else copy.deepcopy(v)
        for k in rng.sample(['a', 'z', 'a/b', '~1', '', 'n'], rng.randrange(3)):
            out.setdefault(k, _random_value(rng, depth + 1))
        return out
    if roll < 0.5:
        return _random_value(rng, depth)
    return copy.deepcopy(value)


class DiffTests(Base):
    def test_equal_documents_produce_empty_patch(self):
        self.assertEqual(diff(1, 1.0), [])
        self.assertEqual(diff({'a': [1, {'b': 2}]}, {'a': [1.0, {'b': 2.0}]}), [])
        self.assertEqual(diff(True, 1), [{'op': 'replace', 'path': '', 'value': 1}])
        self.assertEqual(diff(0, False), [{'op': 'replace', 'path': '', 'value': False}])

    def test_type_change_is_single_replace(self):
        self.assertEqual(diff({'a': 1}, [1]), [{'op': 'replace', 'path': '', 'value': [1]}])
        self.assertEqual(diff({'k': {'x': 1}}, {'k': 'x'}), [{'op': 'replace', 'path': '/k', 'value': 'x'}])
        self.assertEqual(diff({'k': None}, {'k': 0}), [{'op': 'replace', 'path': '/k', 'value': 0}])

    def test_object_diff_order(self):
        source = {'x': 1, 'gone': 2, 'n': {'k': 1, 'old': 0}, 'b': 'same', 'a': 1}
        target = {'x': 1, 'n': {'k': 2, 'new': [1]}, 'b': 'same', 'a': 2, 'c': True}
        self.assertEqual(diff(source, target), [
            {'op': 'remove', 'path': '/gone'},
            {'op': 'replace', 'path': '/a', 'value': 2},
            {'op': 'remove', 'path': '/n/old'},
            {'op': 'replace', 'path': '/n/k', 'value': 2},
            {'op': 'add', 'path': '/n/new', 'value': [1]},
            {'op': 'add', 'path': '/c', 'value': True},
        ])

    def test_keys_are_escaped(self):
        self.assertEqual(diff({}, {'a/b': 1}), [{'op': 'add', 'path': '/a~1b', 'value': 1}])
        self.assertEqual(diff({'~x': 1, '': 2}, {}), [{'op': 'remove', 'path': '/'}, {'op': 'remove', 'path': '/~0x'}])
        src, dst = {'a/b': {'~': [1]}, '': 0}, {'a/b': {'~': [1, 2]}, '': 1}
        self.assertTrue(json_equal(apply_patch(src, diff(src, dst)), dst))

    def test_array_round_trips(self):
        cases = [([1, 2, 3], []), ([], [1, 2]), ([1, 2, 3, 4], [4]), (['a', 'b'], ['b', 'a', 'c']),
                 ([[1], [2, 3]], [[1, 2], [3]]), ({'l': [1, 2, 3, 4, 5]}, {'l': [5]})]
        for src, dst in cases:
            patch = diff(src, dst)
            self.assertTrue(json_equal(apply_patch(src, patch), dst), (src, dst, patch))

    def test_random_round_trips(self):
        rng = random.Random(20260924)
        for _ in range(300):
            src = _random_value(rng, 0)
            dst = _mutate(rng, src)
            src_before, dst_before = copy.deepcopy(src), copy.deepcopy(dst)
            patch = diff(src, dst)
            self.assertEqual((src, dst), (src_before, dst_before), 'diff mutated its input')
            for op in patch:
                self.assertIn(op['op'], ('add', 'remove', 'replace'))
                expected = {'op', 'path', 'value'} if op['op'] != 'remove' else {'op', 'path'}
                self.assertEqual(set(op), expected)
            result = apply_patch(src, patch)
            self.assertTrue(json_equal(result, dst), (src, dst, patch, result))
            if json_equal(src, dst):
                self.assertEqual(patch, [])

    def test_diff_values_are_copies(self):
        dst = {'a': {'l': [1]}}
        patch = diff({}, dst)
        patch[0]['value']['l'].append(2)
        self.assertEqual(dst, {'a': {'l': [1]}})


if __name__ == '__main__':
    unittest.main()
