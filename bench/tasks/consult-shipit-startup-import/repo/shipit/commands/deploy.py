from shipit.commands.registry import command
from shipit.targets import TARGETS, resolve_target


@command('deploy', help='deploy a release to a target')
class DeployCommand:
    @staticmethod
    def configure(parser):
        parser.add_argument('--target', choices=sorted(TARGETS), default='k8s')
        parser.add_argument('version')

    @staticmethod
    def run(args):
        target = resolve_target(args.target)
        print(target.deploy(args.version))
        return 0
