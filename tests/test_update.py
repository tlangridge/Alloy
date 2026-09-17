"""Real local Git fixtures; release metadata and network transport are mocked."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import alloy_update as u
REAL_LATEST = u.latest


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'install'
        self.remote = Path(self.tmp.name) / 'remote'
        self.git = u.git
        subprocess.run(['git', 'init', '-q', str(self.remote)], check=True)
        self.git(self.remote, 'checkout', '-b', 'master')
        self.git(self.remote, 'config', 'user.email', 'test@example.invalid')
        self.git(self.remote, 'config', 'user.name', 'Test')
        (self.remote / 'bin').mkdir()
        (self.remote / 'bin/alloy').write_text('ALLOY_VERSION = "1.0.0"\n')
        self.git(self.remote, 'add', '.')
        self.git(self.remote, 'commit', '-qm', 'one')
        self.git(self.remote, 'tag', 'v1.0.0')
        subprocess.run(['git', 'clone', '-q', str(self.remote), str(self.root)], check=True)
        self.git(self.root, 'remote', 'set-url', 'origin', u.REMOTE)
        (self.remote / 'bin/alloy').write_text('ALLOY_VERSION = "1.1.0"\n')
        self.git(self.remote, 'commit', '-qam', 'two')
        self.git(self.remote, 'tag', 'v1.1.0')
        self.metadata = patch.object(u, 'latest', return_value='v1.1.0').start()
        self.addCleanup(patch.stopall)
        def local_git(root, *args):
            return self.git(root, *(str(self.remote) if a == u.REMOTE else a for a in args))
        patch.object(u, 'git', side_effect=local_git).start()

    def check(self, **kwargs):
        return u.check(self.root, '1.0.0', **kwargs)

    def test_install_release_and_next_check(self):
        self.assertTrue(self.check().startswith('UPDATED v1.1.0'))
        self.assertIn('1.1.0', (self.root / 'bin/alloy').read_text())
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.git(self.remote, 'rev-parse', 'v1.1.0'))
        self.assertTrue(u.check(self.root, '1.1.0', force=True).startswith('UP_TO_DATE'))

    def test_dirty_and_untracked_skip_before_network(self):
        (self.root / 'notes').write_text('local work')
        self.assertIn('local changes', self.check())
        self.metadata.assert_not_called()

    def test_developer_branch_skipped(self):
        self.git(self.root, 'checkout', '-b', 'codex/work')
        self.assertIn('developer branch', self.check())
        self.metadata.assert_not_called()

    def test_unpublished_commit_skipped(self):
        self.git(self.root, 'config', 'user.email', 'test@example.invalid')
        self.git(self.root, 'config', 'user.name', 'Test')
        self.git(self.root, 'commit', '--allow-empty', '-qm', 'local')
        self.assertIn('not at its released', self.check())
        self.metadata.assert_not_called()

    def test_wrong_origin_skipped(self):
        self.git(self.root, 'remote', 'set-url', 'origin', 'https://example.invalid/repo')
        self.assertIn('not the official', self.check())
        self.metadata.assert_not_called()

    def test_check_only_and_daily_cache(self):
        self.assertIn('UPDATE_AVAILABLE', self.check(install=False))
        self.assertIn('CHECK_SKIPPED', self.check())
        self.assertEqual(self.metadata.call_count, 1)
        self.assertIn('UPDATED', self.check(force=True))

    def test_offline_failure_throttled_and_head_unchanged(self):
        self.metadata.side_effect = OSError('offline')
        before = self.git(self.root, 'rev-parse', 'HEAD')
        self.assertIn('UNAVAILABLE', self.check())
        self.assertIn('CHECK_SKIPPED', self.check())
        self.assertEqual(before, self.git(self.root, 'rev-parse', 'HEAD'))

    def test_declared_release_version_must_match(self):
        (self.remote / 'bin/alloy').write_text('ALLOY_VERSION = "9.0.0"\n')
        self.git(self.remote, 'commit', '-qam', 'bad metadata')
        self.git(self.remote, 'tag', '-f', 'v1.1.0')
        self.assertIn('version mismatch', self.check())
        self.assertIn('1.0.0', (self.root / 'bin/alloy').read_text())

    def test_no_downgrade(self):
        self.metadata.return_value = 'v0.9.0'
        self.assertEqual(self.check(), 'UP_TO_DATE')

    def test_copied_install_unsupported(self):
        self.assertIn('UNSUPPORTED', u.check(self.root / 'bin', '1.0.0'))
        self.metadata.assert_not_called()

    def test_active_invocation_blocks_updater(self):
        with u.acquire(self.root):
            with self.assertRaises(BlockingIOError):
                u.acquire(self.root, exclusive=True)
        with u.acquire(self.root, exclusive=True):
            with self.assertRaises(BlockingIOError):
                u.acquire(self.root, exclusive=True)

    def test_local_edits_during_fetch_are_preserved(self):
        def edit_during_fetch(root, *args):
            result = self.git(root, *(str(self.remote) if a == u.REMOTE else a for a in args))
            if args[0] == 'fetch':
                (self.root / 'bin/alloy').write_text('local edit')
            return result
        with patch.object(u, 'git', side_effect=edit_during_fetch):
            self.assertIn('checkout changed', self.check())
        self.assertEqual((self.root / 'bin/alloy').read_text(), 'local edit')

    def test_release_metadata_rejects_prerelease_and_bad_tag(self):
        for data in ({'tag_name': 'v1.2.0', 'prerelease': True},
                     {'tag_name': 'v1.2.0', 'draft': True},
                     {'tag_name': 'v1.2.0-rc1'}, {'tag_name': '--unsafe'}):
            with patch.object(u.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(data).encode())):
                # setUp patches the function, so call its original implementation.
                with self.assertRaises(ValueError):
                    REAL_LATEST()

    def test_ignored_local_file_is_not_overwritten(self):
        (self.root / '.git/info/exclude').write_text('private.txt\n')
        (self.root / 'private.txt').write_text('local data')
        (self.remote / 'private.txt').write_text('release data')
        self.git(self.remote, 'add', 'private.txt')
        self.git(self.remote, 'commit', '-qm', 'new file')
        self.git(self.remote, 'tag', '-f', 'v1.1.0')
        self.assertIn('UNAVAILABLE', self.check())
        self.assertEqual((self.root / 'private.txt').read_text(), 'local data')
        self.assertIn('1.0.0', (self.root / 'bin/alloy').read_text())

    def test_diverged_release_is_not_installed(self):
        self.git(self.remote, 'checkout', '--orphan', 'unrelated')
        self.git(self.remote, 'commit', '-qm', 'unrelated release')
        self.git(self.remote, 'tag', '-f', 'v1.1.0')
        self.assertIn('UNAVAILABLE', self.check())
        self.assertIn('1.0.0', (self.root / 'bin/alloy').read_text())
