from shipit.render.table import table
from shipit.targets.base import Target


class K8sTarget(Target):
    name = 'k8s'

    def deploy(self, version):
        return 'k8s rollout %s\n%s' % (version, table([('replicas', '3'), ('strategy', 'rolling')]))
