import unittest

from tracker import FakeClock, MemoryIssueStore, Request, SqliteIssueStore, create_app


class TrackerContract(object):
    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.clock = FakeClock(1000)
        self.app = create_app(self.make_store(), self.clock)

    def create(self, **body):
        resp = self.app.handle(Request('POST', '/issues', body))
        self.assertEqual(resp.status, 201, resp.body)
        self.clock.advance(10)
        return resp.body

    def get(self, target):
        return self.app.handle(Request('GET', target))

    def test_create_and_list(self):
        a = self.create(title='Crash on save', priority=1, labels=['bug', 'ui'])
        b = self.create(title='Docs typo', status='closed')
        resp = self.get('/issues')
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, {'items': [a, b]})
        self.assertEqual(a['labels'], ['bug', 'ui'])
        self.assertEqual(a['created_at'], 1000)

    def test_status_filter(self):
        self.create(title='one')
        closed = self.create(title='two', status='closed')
        self.assertEqual(self.get('/issues?status=closed').body, {'items': [closed]})
        self.assertEqual(len(self.get('/issues?status=all').body['items']), 2)
        resp = self.get('/issues?status=nope')
        self.assertEqual((resp.status, resp.body), (400, {'error': {'code': 'invalid_filter', 'param': 'status'}}))

    def test_unknown_param(self):
        resp = self.get('/issues?colour=red')
        self.assertEqual((resp.status, resp.body), (400, {'error': {'code': 'unknown_param', 'param': 'colour'}}))

    def test_patch_sets_updated_at(self):
        a = self.create(title='x')
        self.clock.advance(5)
        resp = self.app.handle(Request('PATCH', '/issues/%d' % a['id'], {'priority': 2}))
        self.assertEqual(resp.status, 200)
        self.assertEqual((resp.body['priority'], resp.body['updated_at']), (2, 1015))

    def test_export(self):
        self.clock.value = 2000
        late = self.create(title='late, with comma', labels=['b', 'a'])
        self.clock.value = 1000
        early = self.create(title='early', assignee='kim')
        resp = self.get('/issues/export.csv')
        self.assertEqual(resp.content_type, 'text/csv')
        self.assertEqual(resp.body.splitlines(), [
            'id,title,status,priority,labels,assignee',
            '%d,early,open,3,,kim' % early['id'],
            '%d,"late, with comma",open,3,a;b,' % late['id'],
        ])


class MemoryTrackerTests(TrackerContract, unittest.TestCase):
    def make_store(self):
        return MemoryIssueStore()


class SqliteTrackerTests(TrackerContract, unittest.TestCase):
    def make_store(self):
        return SqliteIssueStore()


if __name__ == '__main__':
    unittest.main()
