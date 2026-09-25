"""logprune: delete rotated log files that are older than a retention window.

Usage:
    python3 logprune.py --keep 14d /var/log/myapp
    python3 logprune.py --keep 36h --dry-run /var/log/myapp
"""
import argparse
import os
import sys
import time

UNIT_SECONDS = {
    'h': 60 * 60,
    'd': 24 * 60 * 60,
    'w': 7 * 24 * 60 * 60,
}

# Only files that logrotate has already rotated are ever considered.
ROTATED_SUFFIXES = ('.1', '.2', '.3', '.gz', '.old')


def parse_keep(text):
    """Parse a retention window such as '14d', '36h' or '2w' into seconds."""
    text = text.strip().lower()
    if len(text) < 2:
        raise ValueError('retention must look like 14d, 36h or 2w')
    amount, unit = text[:-1], text[-1]
    seconds = int(amount) * UNIT_SECONDS[unit]
    if seconds <= 0:
        raise ValueError('retention must be positive')
    return seconds


def rotated_files(directory):
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path) and name.endswith(ROTATED_SUFFIXES):
            yield path


def prune(directory, keep_seconds, now=None, dry_run=False):
    """Remove (or with dry_run just list) rotated files older than keep_seconds."""
    now = time.time() if now is None else now
    removed = []
    for path in rotated_files(directory):
        if now - os.path.getmtime(path) > keep_seconds:
            removed.append(path)
            if not dry_run:
                os.remove(path)
    return removed


def build_parser():
    parser = argparse.ArgumentParser(prog='logprune', description=__doc__.splitlines()[0])
    parser.add_argument('--keep', type=parse_keep, default='14d',
                        help='retention window, e.g. 14d, 36h or 2w (default: 14d)')
    parser.add_argument('--dry-run', action='store_true',
                        help='only print what would be removed')
    parser.add_argument('directory', help='directory holding the rotated logs')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not os.path.isdir(args.directory):
        print('logprune: not a directory: %s' % args.directory, file=sys.stderr)
        return 2
    for path in prune(args.directory, args.keep, dry_run=args.dry_run):
        print(('would remove ' if args.dry_run else 'removed ') + path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
