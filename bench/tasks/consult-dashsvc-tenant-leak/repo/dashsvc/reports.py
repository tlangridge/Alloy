"""Report builders (offline stubs returning deterministic numbers)."""
from dashsvc.tenants import ANONYMOUS_TENANT, SYSTEM_TENANT

PUBLIC_METRICS = {'uptime_pct': 99.95, 'open_incidents': 1}
INTERNAL_METRICS = {'uptime_pct': 99.95, 'open_incidents': 1,
                    'error_budget_burn': 0.62, 'oncall': 'r.kim', 'pager_alerts_24h': 17}


class UnknownReport(KeyError):
    pass


def _tenant_metrics(tenant_id, params):
    region = params.get('region') or 'all'
    return {'tenant': tenant_id, 'region': region, 'requests_24h': 1000 * tenant_id + len(region)}


def build(tenant_id, report, params):
    """Render `report` for `tenant_id`. Only SYSTEM_TENANT gets internal metrics."""
    if report not in ('overview', 'status'):
        raise UnknownReport(report)
    if tenant_id == SYSTEM_TENANT:
        body = dict(INTERNAL_METRICS)
    elif tenant_id == ANONYMOUS_TENANT:
        body = dict(PUBLIC_METRICS)
    else:
        body = _tenant_metrics(tenant_id, params)
    return {'report': report, 'params': dict(params), 'metrics': body}
