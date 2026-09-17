"""Stable-release updates for official, clean Git installations (stdlib only)."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

REMOTE = 'https://github.com/tlangridge/Alloy.git'
RELEASE = 'https://api.github.com/repos/tlangridge/Alloy/releases/latest'
STABLE = re.compile(r'^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')


def git(root, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '-C', str(root), '-c', 'core.hooksPath=/dev/null',
                             *args], capture_output=True, text=True, timeout=15,
                            stdin=subprocess.DEVNULL, env=env)
    if result.returncode:
        raise ValueError('Git operation failed')
    return result.stdout.strip()


def acquire(root, exclusive=False):
    """Caller retains this descriptor for its entire invocation. Never unlink it."""
    directory = Path(root) / '.git'
    if not directory.is_dir():
        return None  # Copied installs and worktrees are not auto-updated.
    handle = open(str(directory / 'alloy-update.lock'), 'a')
    try:
        fcntl.flock(handle, (fcntl.LOCK_EX | fcntl.LOCK_NB) if exclusive else fcntl.LOCK_SH)
    except BaseException:
        handle.close()
        raise
    return handle


def latest():
    request = urllib.request.Request(RELEASE, headers={'Accept': 'application/vnd.github+json',
                                                       'User-Agent': 'Alloy-update-check'})
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Oversize release response')
    data = json.loads(raw)
    tag = data.get('tag_name', '')
    if data.get('draft') or data.get('prerelease') or not STABLE.fullmatch(tag):
        raise ValueError('Not a stable release')
    return tag


def check(root, version, force=False, install=True):
    """Requires the caller's exclusive installation lock. No credentials or prompts sent."""
    root = Path(root)
    if not (root / '.git').is_dir():
        return 'UPDATE_UNSUPPORTED (copied install/worktree; use your original installer)'
    try:
        remote = git(root, 'remote', 'get-url', 'origin').lower().rstrip('/')
        if remote not in ('https://github.com/tlangridge/alloy.git',
                          'https://github.com/tlangridge/alloy',
                          'git@github.com:tlangridge/alloy.git'):
            return 'UPDATE_SKIPPED (origin is not the official Alloy repository)'
        if git(root, 'symbolic-ref', '--short', 'HEAD') not in ('main', 'master'):
            return 'UPDATE_SKIPPED (developer branch)'
        if git(root, 'status', '--porcelain', '--untracked-files=normal'):
            return 'UPDATE_SKIPPED (local changes)'
        head = git(root, 'rev-parse', 'HEAD')
        # Only advance a released checkout, never unpublished local commits.
        if head != git(root, 'rev-parse', 'v' + version + '^{commit}'):
            return 'UPDATE_SKIPPED (checkout is not at its released version)'
        stamp = root / '.git' / 'alloy-update-check.json'
        try:
            checked = json.loads(stamp.read_text())
            if not force and 0 <= time.time() - checked['checked_at'] < 86400:
                return 'UPDATE_CHECK_SKIPPED (checked < 24h ago; --force to recheck)'
        except (OSError, ValueError, KeyError, TypeError):
            pass
        # Throttle failed network checks too. Exclusive lock serializes writers.
        stamp.write_text(json.dumps({'checked_at': time.time()}))
        tag = latest()
        current = STABLE.fullmatch('v' + version)
        if current is None or tuple(map(int, STABLE.fullmatch(tag).groups())) <= tuple(map(int, current.groups())):
            return 'UP_TO_DATE'
        if not install:
            return 'UPDATE_AVAILABLE ' + tag + ' (automatic installation disabled)'
        git(root, 'fetch', '--quiet', '--no-tags', REMOTE, 'refs/tags/' + tag + ':refs/tags/' + tag)
        target = git(root, 'rev-parse', 'FETCH_HEAD^{commit}')
        # Recheck after network access; never reset, stash, rebase or force.
        if git(root, 'rev-parse', 'HEAD') != head or git(root, 'status', '--porcelain', '--untracked-files=normal'):
            return 'UPDATE_SKIPPED (checkout changed during check)'
        git(root, 'merge-base', '--is-ancestor', head, target)
        declared = git(root, 'show', target + ':bin/alloy')
        if not re.search(r'^ALLOY_VERSION = "' + re.escape(tag[1:]) + r'"$', declared, re.M):
            return 'UPDATE_SKIPPED (release version mismatch)'
        git(root, 'merge', '--ff-only', '--no-edit', '--no-overwrite-ignore', target)
        return 'UPDATED ' + tag + ' (reload SKILL.md before continuing)'
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return 'UPDATE_UNAVAILABLE (offline, incompatible checkout, or Git operation failed; continuing installed version)'
