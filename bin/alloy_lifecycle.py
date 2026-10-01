"""Durable execution identity, budgets and archive-before-delete hygiene (stdlib only)."""
from contextlib import contextmanager
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import uuid

import alloy_execution as e

CLOSED = ('integrated', 'failed', 'interrupted', 'needs_attention', 'abandoned')
SKIP = {'.git', 'node_modules', '.next', 'dist', 'build', 'coverage'}


def number(core, key, default):
    try:
        value = float(core.setting(key, str(default)))
    except (TypeError, ValueError):
        raise e.ExecutionError(key + ' must be a finite nonnegative number')
    if not math.isfinite(value) or value < 0:
        raise e.ExecutionError(key + ' must be a finite nonnegative number')
    return value


def repo_key(repo):
    remote = e.git(repo, 'config', '--get', 'remote.origin.url', check=False)
    url = remote.stdout.decode(errors='surrogateescape').strip() if not remote.returncode else ''
    # SSH and HTTPS clones of the same host/path share their limits and logical tasks.
    if url:
        url = re.sub(r'^\w+://(?:[^/@]+@)?', '', url)
        url = re.sub(r'^[^/@]+@([^:]+):', r'\1/', url).rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
    else:
        url = e.git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    return hashlib.sha256(url.encode(errors='surrogateescape')).hexdigest()


def identity(core, args, repo, prompt):
    key = repo_key(repo)
    logical = getattr(args, 'logical_task_id', None) or hashlib.sha256(prompt.encode()).hexdigest()
    logical = hashlib.sha256((key + '\0' + logical).encode()).hexdigest()
    return key, logical, getattr(args, 'owner', None) or core.setting('ALLOY_OWNER') or getpass.getuser()


def ledger_path(core, task):
    return e.home(core) / 'logical' / (task['logical_task_id'] + '.json')


def logical_lock(core, logical):
    return e.home(core) / 'logical' / (logical + '.lock')


def all_tasks(core):
    return [e.load(core, p.parent.name) for p in (e.home(core) / 'tasks').glob('*/task.json')]


def retained(core, key):
    count = 0
    for t in all_tasks(core):
        if t['state'] == 'cleaned' or not Path(t['worktree']).exists():
            continue
        saved_key = t.get('repo_key')
        if not saved_key:
            try:
                saved_key = repo_key(t['repo'])
            except (e.ExecutionError, OSError):
                saved_key = t['git_common_dir']
        count += saved_key == key
    return count


def workspace_bytes(core):
    total = 0
    for root, dirs, files in os.walk(e.home(core) / 'worktrees', followlinks=False):
        for name in files:
            path = Path(root) / name
            if not path.is_symlink():
                total += path.stat().st_size
    return total


def resources(core):
    location = e.home(core)
    while not location.exists():
        location = location.parent
    free = shutil.disk_usage(location).free / (1 << 30)
    used = workspace_bytes(core) / (1 << 30)
    problems = []
    minimum = number(core, 'ALLOY_MIN_FREE_GB', 15)
    maximum = number(core, 'ALLOY_RETAINED_BUDGET_GB', 10)
    if free < minimum:
        problems.append('free disk %.2f GiB < %.2f GiB minimum' % (free, minimum))
    if used > maximum:
        problems.append('retained workspace %.2f GiB > %.2f GiB budget' % (used, maximum))
    return problems


def resource_guard(core):
    problems = resources(core)
    if problems:
        cleanup_finished(core, automatic=True)
        problems = resources(core)
    if problems:
        raise e.ExecutionError('Resource guard after automatic hygiene: ' + '; '.join(problems) +
                               '. Archive closed tasks or extend the configured resource thresholds.')


def default_target(task):
    repo = task['repo']
    ref = e.git(repo, 'symbolic-ref', 'refs/remotes/origin/HEAD', check=False)
    if ref.returncode == 0:
        return ref.stdout.decode().strip()
    for branch in ('main', 'master', task['target_branch']):
        ref = 'refs/heads/' + branch
        if e.git(repo, 'rev-parse', '--verify', ref, check=False).returncode == 0:
            return ref
    raise e.ExecutionError('Default branch cannot be resolved')


def merged_elsewhere(task):
    """Prove full task content, including file modes/deletions, on the default branch."""
    repo, tip, base = task['repo'], task.get('tip'), task['base']
    if not tip:
        return None
    target = default_target(task)
    commit = e.git(repo, 'rev-parse', target)
    if e.git(repo, 'merge-base', '--is-ancestor', tip, target, check=False).returncode == 0:
        return dict(method='ancestry', commit=commit, target=target)
    paths = e.git(repo, 'diff', '--name-only', '--no-renames', '-z', base, tip).split('\0')[:-1]
    if paths and all(not e.git(repo, 'diff', '--quiet', '--no-ext-diff', '--no-textconv', tip, target,
                             '--', p, check=False).returncode for p in paths):
        return dict(method='content_match', commit=commit, target=target)
    # A later edit can change the final content. Exact patch equivalence to a commit
    # on the branch still proves the task was integrated (squash or cherry-pick).
    expected = e.git(repo, 'diff', '--binary', '--no-ext-diff', '--no-textconv', base, tip)
    if not expected:
        return None
    def patch_id(patch):
        cp = subprocess.run(e.git_argv(repo, 'patch-id', '--stable'), input=patch.encode(errors='surrogateescape'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e.git_env(), timeout=e.GIT_TIMEOUT)
        if cp.returncode:
            raise e.ExecutionError('Cannot compute integration patch-id')
        return cp.stdout.split()[0] if cp.stdout.split() else None
    wanted = patch_id(expected)
    for candidate in e.git(repo, 'rev-list', base + '..' + target).splitlines():
        parents = e.git(repo, 'rev-list', '--parents', '-n', '1', candidate).split()
        if len(parents) != 2:
            continue
        actual = e.git(repo, 'diff', '--binary', '--no-ext-diff', '--no-textconv', parents[1], candidate)
        if wanted and patch_id(actual) == wanted:
            return dict(method='patch_id', commit=candidate, target=target)
    return None


def files_under(root):
    """Never traverse symlinks or include regenerable caches or Git metadata."""
    if not root.exists():
        return []
    paths = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in sorted(files + [d for d in dirs if (Path(directory) / d).is_symlink()]):
            if name not in SKIP:
                paths.append(Path(directory) / name)
    return paths


def file_digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1 << 20), b''):
            h.update(data)
    return h.hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)): [p.lstat().st_mode, os.readlink(p) if p.is_symlink() else file_digest(p)]
            for p in files_under(root)}


def verify_archive(core, task, directory):
    manifest = core.routing.read_json(directory / 'MANIFEST.json', {})
    if manifest.get('task_id') != task['id'] or not manifest.get('files'):
        raise e.ExecutionError('Archive manifest is missing or belongs to another task')
    for name, digest in manifest['files'].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or file_digest(path) != digest:
            raise e.ExecutionError('Archive verification failed: ' + str(path))
    with tarfile.open(directory / 'files.tar.gz', 'r:gz') as tar:
        for entry in tar:
            if entry.isfile():
                f = tar.extractfile(entry)
                while f.read(1 << 20):
                    pass
    if manifest.get('bundle'):
        # Bundle checksum alone cannot prove it is recoverable. Verify prerequisites
        # against the repository before deleting any branch or worktree.
        e.git(task['repo'], 'bundle', 'verify', str(directory / 'commits.bundle'))
    return manifest


def archive(core, task):
    root = Path(core.setting('ALLOY_ARCHIVE_DIR') or str(e.home(core) / 'archive')).expanduser().resolve()
    wt = Path(task['worktree'])
    # Archiving into a tree that is about to be removed is never valid.
    if root == wt or wt in root.parents or root == Path(task['repo']) or Path(task['repo']) in root.parents:
        raise e.ExecutionError('Archive directory must be outside task and source worktrees')
    directory = root / (task['id'] + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    before = snapshot(wt)
    core.routing.save(directory / 'task.json', task)
    valid = False
    branch_tip = None
    if Path(task['repo']).exists():
        ref = e.git(task['repo'], 'rev-parse', '--verify', 'refs/heads/' + task['branch'], check=False)
        if not ref.returncode:
            branch_tip = ref.stdout.decode().strip()
    try:
        e.validate_tree(task)
        valid = True
    except (e.ExecutionError, OSError):
        pass
    head = e.git(wt, 'rev-parse', 'HEAD') if valid else None
    if valid:
        patch = e.git(wt, 'diff', '--binary', '--no-ext-diff', '--no-textconv', task['base']).encode(errors='surrogateescape')
    elif branch_tip:
        patch = e.git(task['repo'], 'diff', '--binary', '--no-ext-diff', '--no-textconv', task['base'], branch_tip).encode(errors='surrogateescape')
    else:
        saved_patch = e.taskdir(core, task['id']) / 'changes.patch'
        patch = saved_patch.read_bytes() if saved_patch.exists() else b''
    patch_path = directory / 'changes.patch'
    with patch_path.open('wb') as f:
        f.write(patch)
    patch_path.chmod(0o600)
    bundle = False
    if valid and e.git(wt, 'rev-list', task['base'] + '..HEAD'):
        e.git(wt, 'bundle', 'create', str(directory / 'commits.bundle'), 'HEAD', '^' + task['base'])
        bundle = True
    # A broken linked worktree may still have its branch in the surviving repo.
    elif Path(task['repo']).exists():
        ref = 'refs/heads/' + task['branch']
        if e.git(task['repo'], 'rev-parse', '--verify', ref, check=False).returncode == 0:
            if e.git(task['repo'], 'rev-list', task['base'] + '..' + ref):
                e.git(task['repo'], 'bundle', 'create', str(directory / 'commits.bundle'), ref, '^' + task['base'])
                bundle = True
    with tarfile.open(directory / 'files.tar.gz', 'w:gz', dereference=False) as tar:
        for path in files_under(wt):
            tar.add(str(path), arcname=str(path.relative_to(wt)), recursive=False)
    if snapshot(wt) != before or (valid and e.git(wt, 'rev-parse', 'HEAD') != head):
        raise e.ExecutionError('Worktree changed during archive; retained')
    artifacts = list(directory.iterdir())
    for p in artifacts:
        p.chmod(0o600)
    manifest = dict(task_id=task['id'], owner=task['owner'], logical_task_id=task['logical_task_id'],
                    created_at=time.time(), kind='git' if valid else 'files', bundle=bundle,
                    bundle_prerequisite=task['base'] if bundle else None,
                    branch_tip=branch_tip, worktree_head=head,
                    worktree_snapshot=before, excluded=sorted(SKIP),
                    files={p.name: file_digest(p) for p in artifacts})
    core.routing.save(directory / 'MANIFEST.json', manifest)
    verify_archive(core, task, directory)
    hook = core.setting('ALLOY_ARCHIVE_UPLOAD_HOOK')
    if hook:
        # Trusted operator config only. The path is an environment value, never
        # interpolated into shell source. A failed upload retains local work.
        env = core.routing.clean_env()
        env['ALLOY_ARCHIVE_PATH'] = str(directory)
        cp = subprocess.run(hook, shell=True, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        if cp.returncode:
            raise e.ExecutionError('Archive upload hook failed; worktree retained')
        verify_archive(core, task, directory)
    task['archive'] = str(directory)
    e.save(core, task)
    return directory, manifest


def remove_archived(core, task, receipt=None):
    wt = Path(task['worktree'])
    directory, manifest = archive(core, task)
    verify_archive(core, task, directory)
    if snapshot(wt) != manifest['worktree_snapshot']:
        raise e.ExecutionError('Worktree changed after archive; retained')
    repo = task['repo']
    if Path(repo).exists() and e.git(repo, 'rev-parse', '--git-common-dir', check=False).returncode == 0:
        ref = e.git(repo, 'rev-parse', '--verify', 'refs/heads/' + task['branch'], check=False)
        current = ref.stdout.decode().strip() if ref.returncode == 0 else None
        if current != manifest['branch_tip'] or (manifest['worktree_head'] and
                e.git(wt, 'rev-parse', 'HEAD') != manifest['worktree_head']):
            raise e.ExecutionError('Task commits changed after archive; retained')
        listing = e.git(repo, 'worktree', 'list', '--porcelain')
        for entry in listing.split('\n\n'):
            if 'branch refs/heads/' + task['branch'] in entry.splitlines() and 'worktree ' + str(wt) not in entry.splitlines():
                raise e.ExecutionError('Task branch is attached to another worktree; retained')
        if 'worktree ' + str(wt) in listing.splitlines():
            e.git(repo, 'worktree', 'remove', '--force', str(wt))
        elif wt.exists():
            guarded_remove(wt)
        e.git(repo, 'worktree', 'prune')
        if manifest['branch_tip']:
            e.git(repo, 'update-ref', '-d', 'refs/heads/' + task['branch'], manifest['branch_tip'])
    elif wt.exists():
        guarded_remove(wt)
    if wt.exists():
        raise e.ExecutionError('Worktree removal could not be verified')
    task.update(state='cleaned', cleaned_at=time.time(), closure=dict(
        disposition='merged' if receipt else 'abandoned', proof=receipt, archive=str(directory), at=time.time()))
    if receipt:
        task['integration'] = receipt
    e.save(core, task)
    return task


def guarded_remove(path):
    cp = subprocess.run(['rm', '-r', '--', str(path)], capture_output=True, text=True)
    if cp.returncode:
        raise e.ExecutionError('Cleanup refused for %s: %s' % (path, cp.stderr.strip()))


def duration(text):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([smhd])', text)
    if not match:
        raise e.ExecutionError('Age must be a nonnegative duration such as 24h or 7d')
    return float(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2]]


def cleanup_finished(core, dry_run=False, older_than=None, automatic=False):
    now, rows = time.time(), []
    age = duration(older_than) if older_than else (86400 if automatic else 0)
    for saved in sorted(all_tasks(core), key=lambda t: t.get('updated_at', 0)):
        if saved['state'] == 'cleaned' or now - saved.get('updated_at', now) < age:
            continue
        try:
            with e.locked(e.taskdir(core, saved['id']) / 'task.lock'):
                task = e.load(core, saved['id'])
                e.ensure_no_children(core, task)
                if task['state'] in e.ACTIVE:
                    # A PID is only a conservative extra check; the task/logical
                    # locks are the authority. Never retire a live process.
                    try:
                        os.kill(task.get('pid', 0), 0)
                        continue
                    except ProcessLookupError:
                        if not dry_run:
                            task['state'] = 'interrupted'
                    except (PermissionError, OSError):
                        continue
                if now - task.get('updated_at', now) < age:
                    continue
                receipt = None
                try:
                    if Path(task['worktree']).exists():
                        e.validate_tree(task)
                        if e.clean(task['worktree']) and e.git(task['worktree'], 'rev-parse', 'HEAD') == task.get('tip'):
                            receipt = merged_elsewhere(task)
                    elif task['state'] == 'integrated':
                        receipt = merged_elsewhere(task)
                except (e.ExecutionError, OSError):
                    pass
                if automatic and not receipt and task['state'] not in CLOSED:
                    continue
                if task['state'] not in CLOSED + ('ready', 'creating', 'running'):
                    continue
                grace = number(core, 'ALLOY_CLEANUP_GRACE_HOURS', 0) * 3600
                if automatic and not receipt and grace:
                    notice = task.get('owner_notice_at')
                    if not notice:
                        if not dry_run:
                            task['owner_notice_at'] = now
                            core.routing.save(e.taskdir(core, task['id']) / 'owner-notice.json', dict(
                                owner=task['owner'], task_id=task['id'], respond_before=now + grace,
                                action='resume/extend this task to retain it'))
                            # A notice is not execution activity; preserve the idle age.
                            core.routing.save(e.taskdir(core, task['id']) / 'task.json', task)
                        rows.append(dict(id=task['id'], owner_notice=True))
                        continue
                    if now < notice + grace:
                        continue
                if dry_run:
                    rows.append(dict(id=task['id'], cleanup_eligible=True,
                                     disposition='merged' if receipt else 'abandoned'))
                    continue
                with e.locked(logical_lock(core, task['logical_task_id'])):
                    # Lock the surviving repository too; a missing source is a
                    # files-only archive, not a reason to strand the workspace.
                    if Path(task['repo']).exists() and e.git(task['repo'], 'rev-parse', '--git-common-dir', check=False).returncode == 0:
                        with e.locked(e.repo_lock(core, task['repo'])):
                            remove_archived(core, task, receipt)
                    else:
                        remove_archived(core, task, receipt)
                rows.append(dict(id=task['id'], state='cleaned', closure=task['closure']))
        except (e.ExecutionError, OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
            rows.append(dict(id=saved['id'], retained=True, error=str(exc)))
    return rows


@contextmanager
def active_budget(core, task):
    """Only active execution counts; durable heartbeat includes interrupted work."""
    import threading
    path = ledger_path(core, task)
    ledger = core.routing.read_json(path) if path.exists() else {}
    seconds = ledger.get('active_seconds', task.get('active_seconds', 0))
    task['implementation_rounds'] = ledger.get('implementation_rounds', len(task['rounds']))
    if ledger.get('acceptance_blockers'):
        task.setdefault('acceptance_blockers', ledger['acceptance_blockers'])
    started, stop = time.monotonic(), threading.Event()
    mutex = threading.Lock()
    def update():
        with mutex:
            task['active_seconds'] = seconds + time.monotonic() - started
            task['lease_heartbeat_at'] = time.time()
            core.routing.save(path, dict(logical_task_id=task['logical_task_id'], owner=task['owner'],
                active_seconds=task['active_seconds'], implementation_rounds=task['implementation_rounds'],
                acceptance_blockers=task.get('acceptance_blockers', []),
                attempt=task['id'], heartbeat_at=task['lease_heartbeat_at']))
    task['_budget_tick'] = update
    update()
    def heartbeat():
        while not stop.wait(1):
            update()
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        update()
        task.pop('_budget_tick', None)
        e.save(core, task)


def remaining(task):
    tick = task.get('_budget_tick')
    if tick:
        tick()
    left = task.get('budget_seconds', 2700) - task.get('active_seconds', 0)
    if left <= 0:
        raise e.ExecutionError('Logical task active budget expired; extend --budget-minutes to continue')
    return left
