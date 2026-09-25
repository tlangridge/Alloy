class TargetError(Exception):
    pass


class Target:
    name = 'base'

    def deploy(self, version):
        raise NotImplementedError
