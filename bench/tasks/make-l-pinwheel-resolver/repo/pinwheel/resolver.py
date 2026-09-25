"""Dependency resolution and install ordering."""


def resolve(registry, requirements, locked=None):
    """Choose one version per required package; returns {name: version string}."""
    raise NotImplementedError('resolve is not implemented yet')


def install_order(registry, resolution):
    """Order the packages of ``resolution`` so dependencies come first."""
    raise NotImplementedError('install_order is not implemented yet')
