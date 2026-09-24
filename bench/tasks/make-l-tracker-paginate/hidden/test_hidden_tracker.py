import unittest
from urllib.parse import urlencode

from tracker import FakeClock, MemoryIssueStore, Request, SqliteIssueStore, create_app

# (title, status, priority, labels, assignee, created_at)
DATA = [
    ('Crash on save', 'open', 1, ['bug', 'ui'], 'kim', 1000),            # 1
    ('Émile export fails', 'open', 2, ['bug'], None, 1000),               # 2
    ('eagle logo misaligned', 'in_progress', 3, ['ui'], 'lee', 1010),     # 3
    ('Straße field empty', 'open', 1, ['bug', 'i18n'], None, 1020),       # 4
    ('STRASSE import', 'closed', 4, ['i18n'], 'kim', 1020),               # 5
    ('alpha release notes', 'open', 3, ['docs'], 'Kim', 1030),            # 6
    ('Zeta dashboard slow', 'in_progress', 2, ['perf', 'ui'], 'lee', 1040),  # 7
    ('zeta: memory leak', 'open', 1, ['bug', 'perf'], None, 1050),        # 8
    ('Beta signup broken', 'closed', 2, ['bug'], 'kim', 1060),            # 9
    ('docs: API examples', 'open', 4, ['docs'], None, 1070),              # 10
    ('Crash on load', 'open', 1, ['bug'], 'lee', 1080),                   # 11
    ('ümlaut in names', 'open', 3, ['i18n', 'ui'], None, 1090),           # 12
]


class Contract(object):
    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.clock = FakeClock(0)
        self.app = create_app(self.make_store(), self.clock)
        for title, status, priority, labels, assignee, created in DATA:
            self.clock.value = created
            body = {'title': title, 'status': status, 'priority': priority, 'labels': labels}
            if assignee:
                body['assignee'] = assignee
            resp = self.app.handle(Request('POST', '/issues', body))
            assert resp.status == 201, resp.body
        self.clock.value = 1100
        self.patch(1, {'labels': ['bug', 'ui']})
        self.clock.value = 1200
        self.patch(3, {'priority': 3})

    # -- helpers -----------------------------------------------------------
    def patch(self, issue_id, body):
        resp = self.app.handle(Request('PATCH', '/issues/%d' % issue_id, body))
        self.assertEqual(resp.status, 200, resp.body)
        return resp.body

    def get(self, path, params=()):
        target = path + ('?' + urlencode(list(params)) if params else '')
        return self.app.handle(Request('GET', target))

    def ids(self, params=()):
        resp = self.get('/issues', params)
        self.assertEqual(resp.status, 200, resp.body)
        return [item['id'] for item in resp.body['items']]

    def error(self, params, code, param, path='/issues'):
        resp = self.get(path, params)
        self.assertEqual((resp.status, resp.body), (400, {'error': {'code': code, 'param': param}}),
                         'params %r' % (params,))

    def walk(self, params, limit):
        """Follow next_cursor to the end; returns (all ids, pages)."""
        pages, cursor = [], None
        for _ in range(100):
            query = list(params) + [('limit', str(limit))]
            if cursor is not None:
                query.append(('cursor', cursor))
            resp = self.get('/issues', query)
            self.assertEqual(resp.status, 200, resp.body)
            self.assertEqual(set(resp.body), {'items', 'next_cursor'})
            page = [i['id'] for i in resp.body['items']]
            self.assertLessEqual(len(page), limit)
            pages.append(page)
            cursor = resp.body['next_cursor']
            if cursor is None:
                break
            self.assertIsInstance(cursor, str)
        return [i for p in pages for i in p], pages

    def export_ids(self, params=()):
        resp = self.get('/issues/export.csv', params)
        self.assertEqual(resp.status, 200, resp.body)
        lines = resp.body.splitlines()
        self.assertEqual(lines[0], 'id,title,status,priority,labels,assignee')
        return [int(line.split(',', 1)[0]) for line in lines[1:]]

    # -- legacy ----------------------------------------------------------------
    def test_legacy_list_shape_and_order(self):
        resp = self.get('/issues')
        self.assertEqual(set(resp.body), {'items'})
        self.assertEqual([i['id'] for i in resp.body['items']], list(range(1, 13)))
        self.assertEqual(resp.body['items'][2]['updated_at'], 1200)
        self.assertEqual(set(self.get('/issues', [('status', 'open')]).body), {'items'})

    def test_existing_endpoints_unchanged(self):
        self.assertEqual(self.app.handle(Request('GET', '/issues/5')).body['title'], 'STRASSE import')
        self.assertEqual(self.app.handle(Request('GET', '/issues/99')).status, 404)
        bad = self.app.handle(Request('POST', '/issues', {'title': 'x', 'priority': 9}))
        self.assertEqual((bad.status, bad.body), (400, {'error': {'code': 'invalid_field', 'param': 'priority'}}))
        self.assertEqual(self.app.handle(Request('GET', '/nope')).status, 404)

    # -- filters ---------------------------------------------------------------
    def test_status_values_combine_with_or(self):
        self.assertEqual(self.ids([('status', 'closed'), ('status', 'in_progress')]), [3, 5, 7, 9])
        self.assertEqual(self.ids([('status', 'all')]), list(range(1, 13)))
        self.error([('status', 'all'), ('status', 'open')], 'invalid_filter', 'status')
        self.error([('status', '')], 'invalid_filter', 'status')
        self.error([('status', 'Open')], 'invalid_filter', 'status')

    def test_labels_combine_with_and(self):
        self.assertEqual(self.ids([('label', 'bug'), ('label', 'ui')]), [1])
        self.assertEqual(self.ids([('label', 'bug')]), [1, 2, 4, 8, 9, 11])
        self.assertEqual(self.ids([('label', 'nope')]), [])
        self.error([('label', 'bug'), ('label', '')], 'invalid_filter', 'label')

    def test_assignee_filter(self):
        self.assertEqual(self.ids([('assignee', 'kim')]), [1, 5, 9])
        self.assertEqual(self.ids([('assignee', 'none')]), [2, 4, 8, 10, 12])
        self.error([('assignee', '')], 'invalid_filter', 'assignee')

    def test_text_filter_casefolds(self):
        self.assertEqual(self.ids([('q', 'strasse')]), [4, 5])
        self.assertEqual(self.ids([('q', 'straße')]), [4, 5])
        self.assertEqual(self.ids([('q', 'ÉMILE')]), [2])
        self.assertEqual(self.ids([('q', 'CRASH on')]), [1, 11])
        self.assertEqual(self.ids([('q', '')]), list(range(1, 13)))

    def test_filters_combine(self):
        self.assertEqual(self.ids([('status', 'open'), ('label', 'bug'), ('q', 'crash'), ('assignee', 'lee')]), [11])
        self.assertEqual(self.ids([('status', 'open'), ('status', 'closed'), ('label', 'i18n')]), [4, 5, 12])

    # -- sorting -------------------------------------------------------------
    def test_sort_priority_with_implicit_id(self):
        self.assertEqual(self.ids([('sort', 'priority')]), [1, 4, 8, 11, 2, 7, 9, 3, 6, 12, 5, 10])

    def test_sort_mixed_directions_and_updated(self):
        self.assertEqual(self.ids([('sort', '-priority,created')]), [5, 10, 3, 6, 12, 2, 7, 9, 1, 4, 8, 11])
        self.assertEqual(self.ids([('sort', 'priority,-id')]), [11, 8, 4, 1, 9, 7, 2, 12, 6, 3, 10, 5])
        self.assertEqual(self.ids([('sort', '-id')]), list(range(12, 0, -1)))
        self.assertEqual(self.ids([('sort', '-updated')])[:3], [3, 1, 12])

    def test_sort_title_uses_casefold(self):
        expected = [6, 9, 11, 1, 10, 3, 4, 5, 7, 8, 2, 12]
        self.assertEqual(self.ids([('sort', 'title')]), expected)
        self.assertEqual(self.ids([('sort', '-title')]), expected[::-1])

    def test_sort_validation(self):
        for raw in ['bogus', '', 'priority,', ',priority', 'priority,-priority', '-', 'created_at', 'Priority']:
            self.error([('sort', raw)], 'invalid_sort', 'sort')

    # -- pagination ----------------------------------------------------------
    def test_limit_validation(self):
        for raw in ['0', '101', 'abc', '-1', '+5', '1.5', '', ' 5']:
            self.error([('limit', raw)], 'invalid_limit', 'limit')
        self.assertEqual(len(self.ids([('limit', '100')])), 12)

    def test_first_page_and_next_cursor_presence(self):
        resp = self.get('/issues', [('limit', '5')])
        self.assertEqual([i['id'] for i in resp.body['items']], [1, 2, 3, 4, 5])
        self.assertIsInstance(resp.body['next_cursor'], str)
        exact = self.get('/issues', [('limit', '12')])
        self.assertEqual(len(exact.body['items']), 12)
        self.assertIsNone(exact.body['next_cursor'])
        almost = self.get('/issues', [('limit', '11')])
        self.assertIsNotNone(almost.body['next_cursor'])
        empty = self.get('/issues', [('label', 'nope'), ('limit', '3')])
        self.assertEqual(empty.body, {'items': [], 'next_cursor': None})

    def test_walk_reproduces_full_order(self):
        for sort in ['id', 'priority', '-priority,created', 'title', '-title', '-updated', 'created,-id']:
            full = self.ids([('sort', sort)])
            for limit in (1, 2, 5, 6, 12, 25):
                walked, pages = self.walk([('sort', sort)], limit)
                self.assertEqual(walked, full, (sort, limit))
                self.assertTrue(all(pages[:-1]), 'empty page before the end: %r' % (pages,))
                if limit == 6:
                    self.assertEqual(len(pages), 2, (sort, pages))

    def test_walk_with_filters(self):
        params = [('status', 'open'), ('label', 'bug'), ('sort', '-priority,title')]
        full = self.ids(params)
        self.assertEqual(full, [2, 11, 1, 4, 8])
        walked, pages = self.walk(params, 2)
        self.assertEqual(walked, full)
        self.assertEqual(pages, [[2, 11], [1, 4], [8]])

    def test_cursor_only_uses_default_page_size(self):
        self.clock.value = 5000
        for n in range(30):
            self.app.handle(Request('POST', '/issues', {'title': 'bulk %02d' % n}))
        first = self.get('/issues', [('limit', '3')])
        second = self.get('/issues', [('cursor', first.body['next_cursor'])])
        self.assertEqual([i['id'] for i in second.body['items']], list(range(4, 29)))
        self.assertIsNotNone(second.body['next_cursor'])

    def test_limit_may_change_between_pages(self):
        first = self.get('/issues', [('sort', 'priority'), ('limit', '2')])
        cursor = first.body['next_cursor']
        second = self.get('/issues', [('sort', 'priority'), ('limit', '7'), ('cursor', cursor)])
        self.assertEqual([i['id'] for i in second.body['items']], [8, 11, 2, 7, 9, 3, 6])

    def test_cursor_bound_to_filters_and_sort_status_all_is_no_status(self):
        first = self.get('/issues', [('status', 'open'), ('status', 'closed'), ('sort', 'priority'), ('limit', '2')])
        cursor = first.body['next_cursor']
        self.error([('status', 'open'), ('status', 'closed'), ('sort', '-priority'), ('cursor', cursor)],
                   'cursor_mismatch', 'cursor')
        self.error([('status', 'open'), ('sort', 'priority'), ('cursor', cursor)], 'cursor_mismatch', 'cursor')
        self.error([('status', 'open'), ('status', 'closed'), ('sort', 'priority'), ('label', 'bug'),
                    ('cursor', cursor)], 'cursor_mismatch', 'cursor')
        self.error([('status', 'open'), ('status', 'closed'), ('cursor', cursor)], 'cursor_mismatch', 'cursor')
        ok = self.get('/issues', [('status', 'closed'), ('status', 'open'), ('status', 'open'),
                                  ('sort', 'priority,id'), ('cursor', cursor), ('limit', '3')])
        self.assertEqual(ok.status, 200, ok.body)
        self.assertEqual([i['id'] for i in ok.body['items']], [8, 11, 2])
        first = self.get('/issues', [('status', 'all'), ('limit', '4')])
        second = self.get('/issues', [('cursor', first.body['next_cursor']), ('limit', '4')])
        self.assertEqual(second.status, 200, second.body)
        self.assertEqual([i['id'] for i in second.body['items']], [5, 6, 7, 8])

    def test_invalid_cursor_values(self):
        self.error([('cursor', 'garbage')], 'invalid_cursor', 'cursor')
        self.error([('cursor', '')], 'invalid_cursor', 'cursor')
        self.error([('cursor', '!!!'), ('limit', '2')], 'invalid_cursor', 'cursor')

    def test_new_issues_do_not_duplicate_or_reappear(self):
        first = self.get('/issues', [('sort', '-created'), ('limit', '4')])
        self.assertEqual([i['id'] for i in first.body['items']], [12, 11, 10, 9])
        self.clock.value = 9000
        self.app.handle(Request('POST', '/issues', {'title': 'newest'}))           # id 13, sorts first
        second = self.get('/issues', [('sort', '-created'), ('limit', '4'), ('cursor', first.body['next_cursor'])])
        self.assertEqual([i['id'] for i in second.body['items']], [8, 7, 6, 4])

    def test_new_issue_after_position_appears(self):
        first = self.get('/issues', [('sort', 'priority'), ('limit', '4')])
        self.assertEqual([i['id'] for i in first.body['items']], [1, 4, 8, 11])
        self.app.handle(Request('POST', '/issues', {'title': 'urgent', 'priority': 1}))  # id 13
        second = self.get('/issues', [('sort', 'priority'), ('limit', '3'), ('cursor', first.body['next_cursor'])])
        self.assertEqual([i['id'] for i in second.body['items']], [13, 2, 7])

    def test_cursor_captures_values_of_last_item(self):
        first = self.get('/issues', [('sort', 'priority'), ('limit', '4')])
        cursor = first.body['next_cursor']
        self.patch(11, {'priority': 4})    # the item that produced the cursor moves to the end
        self.patch(2, {'priority': 1})     # an unseen item moves before the captured position
        rest = self.get('/issues', [('sort', 'priority'), ('limit', '100'), ('cursor', cursor)])
        self.assertEqual([i['id'] for i in rest.body['items']], [7, 9, 3, 6, 12, 5, 10, 11])

    # -- errors precedence ---------------------------------------------------
    def test_error_precedence(self):
        self.error([('zzz', '1'), ('limit', '0')], 'unknown_param', 'zzz')
        self.error([('b', '1'), ('a', '1')], 'unknown_param', 'a')
        self.error([('limit', '1'), ('limit', '2'), ('sort', 'bad')], 'duplicate_param', 'limit')
        self.error([('sort', 'x'), ('sort', 'y'), ('q', 'a'), ('q', 'b')], 'duplicate_param', 'q')
        self.error([('status', 'bad'), ('assignee', ''), ('sort', 'bad')], 'invalid_filter', 'status')
        self.error([('sort', 'bad'), ('limit', '0')], 'invalid_sort', 'sort')
        self.error([('limit', '0'), ('cursor', 'garbage')], 'invalid_limit', 'limit')

    # -- export ----------------------------------------------------------------
    def test_export_default_order_is_legacy(self):
        self.assertEqual(self.export_ids(), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        self.patch(2, {'title': 'Émile export fails again'})
        self.assertEqual(self.export_ids([('label', 'bug')]), [1, 2, 4, 8, 9, 11])

    def test_export_filters_sort_and_rejected_params(self):
        self.assertEqual(self.export_ids([('label', 'ui'), ('sort', 'title')]), [1, 3, 7, 12])
        self.assertEqual(self.export_ids([('status', 'open'), ('assignee', 'none'), ('sort', '-priority')]),
                         [10, 12, 2, 4, 8])
        self.assertEqual(self.export_ids([('q', 'STRASSE')]), [4, 5])
        resp = self.get('/issues/export.csv', [('q', 'straße')])
        self.assertIn('4,Straße field empty,open,1,bug;i18n,', resp.body.splitlines())
        self.error([('limit', '5')], 'unknown_param', 'limit', path='/issues/export.csv')
        self.error([('cursor', 'x')], 'unknown_param', 'cursor', path='/issues/export.csv')
        self.error([('sort', 'nope')], 'invalid_sort', 'sort', path='/issues/export.csv')
        self.error([('status', 'all'), ('status', 'closed')], 'invalid_filter', 'status', path='/issues/export.csv')


class MemoryBackendTests(Contract, unittest.TestCase):
    def make_store(self):
        return MemoryIssueStore()


class SqliteBackendTests(Contract, unittest.TestCase):
    def make_store(self):
        self.store = SqliteIssueStore()
        return self.store

    def tearDown(self):
        db = getattr(self.store, 'db', None)
        if db is not None:
            db.close()


if __name__ == '__main__':
    unittest.main()
