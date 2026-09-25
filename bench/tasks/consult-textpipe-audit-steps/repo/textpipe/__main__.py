import argparse
import sys

from textpipe.pipelines import PIPELINES


def main(argv=None):
    parser = argparse.ArgumentParser(prog='textpipe')
    sub = parser.add_subparsers(dest='command')
    sub.required = True
    sub.add_parser('list')
    steps = sub.add_parser('steps')
    steps.add_argument('name', choices=sorted(PIPELINES))
    run = sub.add_parser('run')
    run.add_argument('name', choices=sorted(PIPELINES))
    run.add_argument('text')
    args = parser.parse_args(argv)

    if args.command == 'list':
        for name in sorted(PIPELINES):
            print(name)
    elif args.command == 'steps':
        print(' > '.join(PIPELINES[args.name]().steps()))
    else:
        print(PIPELINES[args.name]().run(args.text))
    return 0


sys.exit(main())
