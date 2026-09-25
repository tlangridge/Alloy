from dashsvc import reports
from dashsvc.cache import TenantCache
from dashsvc.params import canonical_query
from dashsvc.tenants import resolve_tenant


class DashboardService:
    def __init__(self, ops_token, cache=None):
        self.ops_token = ops_token
        self.cache = cache if cache is not None else TenantCache()
        self.builds = 0

    def render(self, headers, report, params=None):
        """Resolve the caller's tenant and return the (possibly cached) report."""
        params = dict(params or {})
        tenant_id = resolve_tenant(headers, self.ops_token)
        key = (report, canonical_query(params))
        cached = self.cache.get(tenant_id, key)
        if cached is not None:
            return cached
        rendered = reports.build(tenant_id, report, params)
        self.builds += 1
        self.cache.set(tenant_id, key, rendered)
        return rendered

    def prewarm(self, header_sets, report_names):
        """Render every report for every caller once (used after deploys)."""
        for headers in header_sets:
            for report in report_names:
                self.render(headers, report)
