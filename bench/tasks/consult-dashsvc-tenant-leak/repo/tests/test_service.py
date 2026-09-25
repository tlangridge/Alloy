import unittest

from dashsvc.cache import TTLCache, TenantCache
from dashsvc.service import DashboardService
from dashsvc.tenants import ANONYMOUS_TENANT, SYSTEM_TENANT, TenantError, resolve_tenant


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TenantTests(unittest.TestCase):
    def test_resolution(self):
        self.assertEqual(resolve_tenant({}, 's3cret'), ANONYMOUS_TENANT)
        self.assertEqual(resolve_tenant({'X-Tenant': ' 42 '}, 's3cret'), 42)
        self.assertEqual(resolve_tenant({'X-Tenant': 'system', 'X-Ops-Token': 's3cret'}, 's3cret'),
                         SYSTEM_TENANT)

    def test_rejections(self):
        for headers in ({'X-Tenant': '-1'}, {'X-Tenant': '0'}, {'X-Tenant': 'system'},
                        {'X-Tenant': 'system', 'X-Ops-Token': 'nope'}):
            with self.subTest(headers=headers):
                with self.assertRaises(TenantError):
                    resolve_tenant(headers, 's3cret')


class CacheTests(unittest.TestCase):
    def test_ttl_expiry(self):
        clock = Clock()
        cache = TTLCache(ttl=60, maxsize=10, clock=clock)
        cache.set('k', 'v')
        clock.now += 59
        self.assertEqual(cache.get('k'), 'v')
        clock.now += 1
        self.assertIsNone(cache.get('k'))

    def test_lru_eviction(self):
        cache = TTLCache(ttl=60, maxsize=2, clock=Clock())
        cache.set('a', 1)
        cache.set('b', 2)
        cache.get('a')
        cache.set('c', 3)
        self.assertEqual((cache.get('a'), cache.get('b'), cache.get('c')), (1, None, 3))


class ServiceTests(unittest.TestCase):
    def test_tenants_are_isolated(self):
        svc = DashboardService('s3cret', TenantCache(clock=Clock()))
        a = svc.render({'X-Tenant': '7'}, 'overview', {'region': 'eu'})
        b = svc.render({'X-Tenant': '8'}, 'overview', {'region': 'eu'})
        self.assertEqual(a['metrics']['tenant'], 7)
        self.assertEqual(b['metrics']['tenant'], 8)

    def test_second_render_is_cached(self):
        svc = DashboardService('s3cret', TenantCache(clock=Clock()))
        svc.render({'X-Tenant': '7'}, 'status')
        svc.render({'X-Tenant': '7'}, 'status', {'region': None})
        self.assertEqual(svc.builds, 1)

    def test_anonymous_gets_public_metrics(self):
        svc = DashboardService('s3cret', TenantCache(clock=Clock()))
        body = svc.render({}, 'status')
        self.assertNotIn('oncall', body['metrics'])


if __name__ == '__main__':
    unittest.main()
