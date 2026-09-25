"""Tenant resolution for dashboard requests."""
import hmac

SYSTEM_TENANT = -1       # internal operations account
ANONYMOUS_TENANT = -2    # unauthenticated visitors of the public status page


class TenantError(ValueError):
    pass


def resolve_tenant(headers, ops_token):
    """Map request headers to a tenant id.

    * missing or blank ``X-Tenant``                       -> ANONYMOUS_TENANT
    * ``X-Tenant: system`` with the correct ``X-Ops-Token`` -> SYSTEM_TENANT
    * ``X-Tenant: <positive decimal integer>``             -> that tenant id
    Anything else raises TenantError.
    """
    raw = (headers.get('X-Tenant') or '').strip()
    if not raw:
        return ANONYMOUS_TENANT
    if raw.lower() == 'system':
        supplied = (headers.get('X-Ops-Token') or '').encode('utf-8')
        if not ops_token or not hmac.compare_digest(supplied, ops_token.encode('utf-8')):
            raise TenantError('invalid ops token')
        return SYSTEM_TENANT
    if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
        raise TenantError('invalid tenant id %r' % raw)
    return int(raw)


def is_internal(tenant_id):
    return tenant_id == SYSTEM_TENANT
