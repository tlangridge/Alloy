"""Recover new files without changing an index or accepting escaping symlinks."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import os
from unittest.mock import patch

import test_execution as fixtures

e = fixtures.e


class RecoveryContractsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='alloy-recovery-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'work'
        self.root.mkdir()
        e.git(self.root, 'init', '-q')
        e.git(self.root, 'config', 'user.name', 'Fixture')
        e.git(self.root, 'config', 'user.email', 'fixture@example.invalid')
        (self.root / 'allowed').mkdir()
        (self.root / 'allowed/base.txt').write_text('base\n')
        (self.root / '.gitignore').write_text('ignored.txt\n')
        e.git(self.root, 'add', '.')
        e.git(self.root, 'commit', '-qm', 'fixture')
        self.task = dict(worktree=str(self.root), base=e.git(self.root, 'rev-parse', 'HEAD'), allow_paths=['allowed'])

    def test_recovery_includes_untracked_binary_and_preserves_real_index(self):
        (self.root / 'allowed/new.txt').write_text('new\n')
        (self.root / 'allowed/data.bin').write_bytes(b'\x00binary\xff\n')
        (self.root / 'ignored.txt').write_text('ignored\n')
        (self.root / 'allowed/base.txt').write_text('changed\n')
        before = (self.root / '.git/index').read_bytes()
        patch = e.recovery_diff(self.task)
        self.assertIn(b'new file mode', patch)
        self.assertIn(b'new.txt', patch)
        self.assertIn(b'GIT binary patch', patch)
        self.assertNotIn(b'ignored.txt', patch)
        self.assertEqual((self.root / '.git/index').read_bytes(), before)
        self.assertIn('?? allowed/new.txt', e.git(self.root, 'status', '--porcelain'))
        clone = Path(self.tmp.name) / 'recover'
        subprocess.run(e.git_argv(self.root, 'clone', '-q', str(self.root), str(clone)),
                       env=e.git_env(), check=True, capture_output=True)
        result = subprocess.run(e.git_argv(clone, 'apply', '--binary', '-'), input=patch,
                                env=e.git_env(), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((clone / 'allowed/data.bin').read_bytes(), b'\x00binary\xff\n')
        self.assertEqual((clone / 'allowed/base.txt').read_text(), 'changed\n')

    def test_only_changed_links_with_in_scope_targets_are_accepted(self):
        link = self.root / 'allowed/link'
        for target, failure in ((str(Path(self.tmp.name) / 'outside'), 'worktree'),
                                ('../forbidden/file', 'scope')):
            link.symlink_to(target)
            with self.assertRaisesRegex(e.ExecutionError, failure):
                e.scope(self.task)
            link.unlink()
        link.symlink_to('base.txt')
        e.scope(self.task)

    def test_linked_worktree_recovery_keeps_shared_objects_and_outside_files_untouched(self):
        worktree = Path(self.tmp.name) / 'linked'
        e.git(self.root, 'worktree', 'add', '-qb', 'task', str(worktree), self.task['base'])
        self.task['worktree'] = str(worktree)
        (worktree / 'allowed/new.txt').write_text('private recovery data\n')
        (worktree / 'outside.txt').write_text('outside scope\n')
        objects = self.root / '.git/objects'
        before = {str(p.relative_to(objects)): p.read_bytes() for p in objects.rglob('*') if p.is_file()}
        patch = e.recovery_diff(self.task)
        after = {str(p.relative_to(objects)): p.read_bytes() for p in objects.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn(b'new.txt', patch)
        self.assertNotIn(b'outside.txt', patch)

    def test_embedded_empty_repository_retains_tracked_patch_with_visible_warning(self):
        (self.root / 'allowed/base.txt').write_text('current tracked change\n')
        nested = self.root / 'allowed/fixture'
        nested.mkdir()
        e.git(nested, 'init', '-q')
        patch = e.recovery_diff(self.task)
        self.assertIn(b'current tracked change', patch)
        self.assertIn('Untracked files omitted', self.task['recovery_warning'])

    def test_recovery_treats_scope_paths_literally_and_ignores_ambient_pathspec_flags(self):
        for folder in ('a*', 'another'):
            target = self.root / 'allowed' / folder
            target.mkdir()
            (target / 'new.txt').write_text(folder + '\n')
        self.task['allow_paths'] = ['allowed/a*']
        with patch.dict(os.environ, GIT_LITERAL_PATHSPECS='1', GIT_GLOB_PATHSPECS='1', GIT_ICASE_PATHSPECS='1'):
            data = e.recovery_diff(self.task)
        self.assertIn(b'allowed/a*/new.txt', data)
        self.assertNotIn(b'allowed/another/new.txt', data)

    def test_absent_or_ignored_scope_siblings_do_not_drop_other_untracked_changes(self):
        (self.root / 'allowed/new.txt').write_text('recover this new file\n')
        (self.root / 'ignored.txt').write_text('ignored\n')
        (self.root / 'allowed/base.txt').unlink()
        self.task['allow_paths'] = ['allowed', 'not-yet-created.py', 'ignored.txt']
        data = e.recovery_diff(self.task)
        self.assertIn(b'recover this new file', data)
        self.assertIn(b'deleted file mode', data)
        self.assertNotIn(b'ignored.txt', data)
        self.assertNotIn('recovery_warning', self.task)

    def test_non_cursor_worker_failure_retains_its_reason(self):
        message = e.worker_failure(dict(maker={'cli': 'claude'}), 'maker',
                                   dict(error='Claude result failed: credit balance too low'), 'Maker failed')
        self.assertIn('credit balance', message)
