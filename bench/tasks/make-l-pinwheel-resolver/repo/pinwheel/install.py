"""Install plans for the deploy tool."""
from .resolver import install_order, resolve


def plan(registry, requirements, locked=None):
    """``['name==version', ...]`` in installation order."""
    resolution = resolve(registry, requirements, locked)
    return ['%s==%s' % (name, resolution[name]) for name in install_order(registry, resolution)]
