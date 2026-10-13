"""Bounded receipts for actual rendered artifacts, not model descriptions."""
import hashlib
import os
import stat
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024
MAX_IMAGES = 8
MAX_TOTAL_BYTES = 80 * 1024 * 1024


def capture(worktree, paths, allowed_paths):
    root = Path(worktree).resolve()
    if len(paths) > MAX_IMAGES:
        raise ValueError('At most 8 rendered artifacts may be attached')
    result, images = [], []
    total = 0
    for name in paths:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or not name:
            raise ValueError('Artifact paths must be relative to the owned worktree')
        actual = relative.as_posix()
        if not any(a == '.' or actual == a or actual.startswith(a.rstrip('/') + '/') for a in allowed_paths):
            raise ValueError('Artifact is outside the allowed task paths')
        # Walk directory descriptors without following symlinks. A concurrent
        # replacement of an ancestor cannot redirect the read outside this tree.
        fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            image_fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(image_fd, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                    raise ValueError('Artifact must be a regular image no larger than 20 MiB')
                data = stream.read(MAX_BYTES + 1)
                after = os.fstat(stream.fileno())
            current = os.stat(relative.parts[-1], dir_fd=fd, follow_symlinks=False)
            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if signature(before) != signature(after) or signature(after) != signature(current):
                raise ValueError('Artifact changed while preparing its receipt')
        finally:
            os.close(fd)
        if len(data) > MAX_BYTES:
            raise ValueError('Artifact exceeded its size limit')
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError('Rendered artifacts exceed the total 80 MiB limit')
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            mime = 'image/webp'
        else:
            raise ValueError('Artifact must contain PNG, JPEG or WebP image bytes')
        if after.st_size != len(data):
            raise ValueError('Artifact changed while preparing its receipt')
        result.append(dict(path=actual, mime_type=mime, bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest()))
        images.append(data)
    return result, images


def receipts(worktree, paths, allowed_paths):
    return capture(worktree, paths, allowed_paths)[0]
