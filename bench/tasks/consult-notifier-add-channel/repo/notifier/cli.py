import argparse
import sys

from notifier import __version__, registry
from notifier.channels.base import ChannelError


def build_parser():
    parser = argparse.ArgumentParser(prog='notifier')
    parser.add_argument('--version', action='version', version='notifier ' + __version__)
    sub = parser.add_subparsers(dest='command')
    sub.required = True

    send = sub.add_parser('send', help='send one notification')
    send.add_argument('--channel', required=True, choices=registry.names())
    send.add_argument('--to', required=True, dest='recipient')
    send.add_argument('message')

    sub.add_parser('channels', help='list available channels')
    return parser


def main(argv=None, out=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    if args.command == 'channels':
        for name in registry.names():
            print(name, file=out)
        return 0
    channel = registry.create(args.channel)
    try:
        receipt = channel.send(args.recipient, args.message)
    except ChannelError as exc:
        print('notifier: %s' % exc, file=sys.stderr)
        return 1
    print(receipt, file=out)
    return 0
