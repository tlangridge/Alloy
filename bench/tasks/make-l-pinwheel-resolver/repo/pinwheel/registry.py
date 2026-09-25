"""The package index the resolver reads from."""
import re

from .constraint import Constraint
from .version import Version

_NAME = re.compile(r'[a-z0-9][a-z0-9-]*\Z')


class Registry(object):
    def __init__(self):
        self._packages = {}   # name -> {Version: (dependencies, yanked)}

    def add(self, name, version, dependencies=None, yanked=False):
        """Publish ``name`` at ``version`` with ``dependencies`` ({name: constraint text})."""
        if not _NAME.match(name):
            raise ValueError('invalid package name %r' % name)
        version = Version.parse(version)
        releases = self._packages.setdefault(name, {})
        if version in releases:
            raise ValueError('%s %s already published' % (name, version))
        deps = {}
        for dep, text in (dependencies or {}).items():
            if not _NAME.match(dep):
                raise ValueError('invalid package name %r' % dep)
            deps[dep] = Constraint.parse(text)
        releases[version] = (deps, bool(yanked))

    def has(self, name):
        return name in self._packages

    def packages(self):
        return sorted(self._packages)

    def versions(self, name):
        """All published versions of ``name`` (including yanked ones), ascending."""
        return sorted(self._packages.get(name, {}))

    def dependencies(self, name, version):
        """{dependency name: Constraint} of one release."""
        return dict(self._packages[name][Version.parse(version)][0])

    def is_yanked(self, name, version):
        return self._packages[name][Version.parse(version)][1]
