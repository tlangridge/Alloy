"""Event routing configuration: event type -> channel name."""

DEFAULT_ROUTES = {
    'invoice.paid': 'billing',
    'invoice.voided': 'billing',
    'user.created': 'crm',
    'user.deleted': 'compliance',
}

# While staging is being validated, a few event types go to other channels.
STAGING_OVERRIDES = {
    'user.deleted': 'privacy-review',
    'invoice.paid': 'finance-ledger',
}


def routes_for(env):
    """The effective routes for an environment (defaults plus overrides)."""
    routes = dict(DEFAULT_ROUTES)
    if env == 'staging':
        routes.update(STAGING_OVERRIDES)
    return routes
