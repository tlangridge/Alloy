"""tagstats: count hashtags in a plain-text export (one post per line).

    python3 tagstats.py data/posts.txt --top 5
"""
import argparse
import collections
import re
import sys

TAG_RE = re.compile(r'#(\w+)')


def extract_tags(line):
    """Hashtags in one post, lower-cased so #Rust and #rust count together."""
    return [tag.lower() for tag in TAG_RE.findall(line)]


def count_tags(lines):
    counts = collections.Counter()
    for line in lines:
        counts.update(extract_tags(line))
    return counts


def format_row(rank, tag, count):
    return '%d. #%s (%d)' % (rank, tag, count)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='tagstats')
    parser.add_argument('path')
    parser.add_argument('--top', type=int, default=5)
    args = parser.parse_args(argv)
    with open(args.path, encoding='utf-8') as fh:
        counts = count_tags(fh)
    for rank, (tag, count) in enumerate(counts.most_common(args.top), 1):
        print(format_row(rank, tag, count))
    return 0


if __name__ == '__main__':
    sys.exit(main())
