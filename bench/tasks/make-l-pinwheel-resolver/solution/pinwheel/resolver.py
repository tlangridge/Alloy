"""Dependency resolution and install ordering."""
import heapq

from .constraint import Constraint
from .errors import CycleError, ResolutionError, UnknownPackage
from .version import Version


def _candidates(registry, name, constraints, locked):
    if not registry.has(name):
        return []
    allowed = [v for v in registry.versions(name) if all(c.allows(v) for c in constraints)]
    lock = locked.get(name)
    out = [lock] if lock is not None and lock in allowed else []
    out.extend(v for v in sorted(allowed, reverse=True) if v != lock and not registry.is_yanked(name, v))
    return out


def _search(registry, active, decisions, locked):
    decided = dict(decisions)
    pending = sorted({name for name, _ in active} - set(decided))
    if not pending:
        return decisions
    best = None
    for name in pending:
        cands = _candidates(registry, name, [c for n, c in active if n == name], locked)
        if best is None or len(cands) < len(best[1]):
            best = (name, cands)
    name, cands = best
    for version in cands:
        deps = registry.dependencies(name, version)
        if any(dep in decided and not c.allows(decided[dep]) for dep, c in deps.items()):
            continue
        if name in deps and not deps[name].allows(version):
            continue
        found = _search(registry, active + sorted(deps.items()), decisions + [(name, version)], locked)
        if found is not None:
            return found
    return None


def resolve(registry, requirements, locked=None):
    """Choose one version per required package; returns {name: version string}."""
    roots = [(name, Constraint.parse(text)) for name, text in sorted(requirements.items())]
    unknown = [name for name, _ in roots if not registry.has(name)]
    if unknown:
        raise UnknownPackage(unknown[0])
    locks = {name: Version.parse(text) for name, text in (locked or {}).items()}
    found = _search(registry, roots, [], locks)
    if found is None:
        raise ResolutionError('no versions satisfy %s' % ', '.join(sorted(requirements)))
    return {name: str(version) for name, version in found}


def install_order(registry, resolution):
    """Order the packages of ``resolution`` so dependencies come first."""
    versions = {name: Version.parse(v) for name, v in resolution.items()}
    deps = {name: sorted(d for d in registry.dependencies(name, versions[name]) if d in versions)
            for name in versions}

    def reaches(start, target):
        seen, stack = set(), list(deps[start])
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(deps[node])
        return False

    members = sorted(name for name in versions if reaches(name, name))
    if members:
        raise CycleError(members)
    remaining = {name: set(ds) for name, ds in deps.items()}
    heap = [name for name, ds in remaining.items() if not ds]
    heapq.heapify(heap)
    order = []
    while heap:
        name = heapq.heappop(heap)
        order.append(name)
        for other, ds in remaining.items():
            if name in ds:
                ds.discard(name)
                if not ds:
                    heapq.heappush(heap, other)
    return order
