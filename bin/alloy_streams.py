"""Bounded terminal-event selection shared by JSONL provider adapters."""
from collections import deque
import json


def event(line, key):
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) and isinstance(value.get(key), str) else None


def select(path, cap, parser, groups, fallback):
    """Keep each group's newest events. Oversized lines are drained, never buffered.

    A group is (predicate, maximum event count, maximum line bytes or None).
    The first actual record distinguishes legacy plain text from a JSONL stream.
    """
    limit = cap * 4 + 4096
    kept = [deque(maxlen=count) for _predicate, count, _line_cap in groups]
    first = True
    try:
        with open(path, 'rb') as stream:
            while True:
                raw = stream.readline(limit + 1)
                if not raw:
                    break
                oversized = len(raw) > limit and not raw.endswith(b'\n')
                while oversized:
                    rest = stream.readline(65536)
                    oversized = bool(rest) and not rest.endswith(b'\n')
                if len(raw) > limit:
                    if first:
                        return fallback(path, cap)
                    continue
                if not raw.strip():
                    continue
                line = raw.decode('utf-8', errors='replace')
                value = parser(line)
                if first:
                    if value is None:
                        return fallback(path, cap)
                    first = False
                if value is not None:
                    for bucket, (predicate, _count, line_cap) in zip(kept, groups):
                        if predicate(value) and (line_cap is None or len(raw) <= line_cap):
                            bucket.append(line if line.endswith('\n') else line + '\n')
                            break
    except FileNotFoundError:
        return ''
    return fallback(path, cap) if first else ''.join(line for bucket in kept for line in bucket)
