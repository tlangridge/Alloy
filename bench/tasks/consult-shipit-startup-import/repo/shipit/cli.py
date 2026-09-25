import argparse

from shipit import __version__
from shipit.commands import REGISTRY


def build_parser():
    parser = argparse.ArgumentParser(prog='shipit', description='Internal release tool.')
    parser.add_argument('--version', action='version', version='shipit ' + __version__)
    parser.add_argument('--plugins', action='store_true', help='load optional plugins first')
    sub = parser.add_subparsers(dest='command', metavar='COMMAND')
    sub.required = True
    for name in sorted(REGISTRY):
        cmd = REGISTRY[name]
        cmd.configure(sub.add_parser(name, help=cmd.help))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.plugins:
        from shipit import plugins
        plugins.load_all()
    return REGISTRY[args.command].run(args) or 0
