"""Deployment targets."""
from shipit.targets.artifacts import ArtifactTarget
from shipit.targets.base import Target, TargetError
from shipit.targets.k8s import K8sTarget

TARGETS = {'artifacts': ArtifactTarget, 'k8s': K8sTarget}


def resolve_target(name):
    try:
        return TARGETS[name]()
    except KeyError:
        raise TargetError('unknown target %r' % name) from None


__all__ = ['Target', 'TargetError', 'TARGETS', 'resolve_target']
