"""Managed lifecycle tests: real temporary Git repos, fake CLIs, no paid calls."""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('execution_core', str(ROOT / 'bin/alloy'))
spec = importlib.util.spec_from_loader(loader.name, loader)
core = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = core
loader.exec_module(core)
e = core.execution
REAL_SELECT, REAL_DISPATCH, REAL_REVALIDATE = e.select, e.dispatch, e.revalidate
REAL_READINESS = e.readiness
REAL_PROBE = e.probe


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'; self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        e.git(self.repo, 'checkout', '-b', 'main')
        e.git(self.repo, 'config', 'user.name', 'Test')
        e.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'file.txt').write_text('old\n')
        e.git(self.repo, 'add', '.'); e.git(self.repo, 'commit', '-qm', 'base')
        self.env = patch.dict(os.environ, {'ALLOY_RUN_ROOT': str(self.base / 'state/runs'),
            'ALLOY_ROUTING_HOME': str(self.base / 'config'), 'ALLOY_CONFIG': '/dev/null', 'ALLOY_USAGE': 'off'})
        self.env.start(); self.addCleanup(self.env.stop)
        patch.object(core, '_CONFIG', {}).start()
        self.maker = dict(cli='claude', family='anthropic', model='sonnet', effort=None, profile='maker')
        self.checker = dict(cli='grok', family='xai', model='grok-4.6', effort=None, profile='checker')
        patch.object(e, 'readiness', return_value=dict(ready=True, blockers=[])).start()
        self.select = patch.object(e, 'select', return_value=(self.maker, self.checker)).start()
        patch.object(e, 'probe').start()
        patch.object(e, 'revalidate').start()
        self.addCleanup(patch.stopall)
        self.prompt = self.base / 'task.txt'; self.prompt.write_text('Change file.txt to new. Test it.')
        self.args = argparse.Namespace(repo=str(self.repo), prompt_file=str(self.prompt), route=False,
            maker_profile='maker', checker_profile='checker', host_family='openai', allow_path=['file.txt'],
            test=[sys.executable + ' -c "from pathlib import Path; assert Path(\'file.txt\').read_text()==\'new\\n\'"'],
            max_fix_rounds=2, timeout=10, test_timeout=5, max_estimated_usd=None)
        self.verdicts = []
        self.calls = []
        def dispatch(core, task, role, prompt, folder):
            self.calls.append((role, prompt))
            folder.mkdir(parents=True, exist_ok=True)
            if role == 'maker':
                (Path(task['worktree']) / 'file.txt').write_text('new\n')
                text = 'Updated file and ran checks.'
            else:
                verdict = self.verdicts.pop(0) if self.verdicts else dict(verdict='pass', findings=[])
                receipt = task['rounds'][-1]['packet']
                verdict.update(packet_id=receipt['id'], revision=receipt['revision'], context_complete=True)
                text = json.dumps(verdict)
            result = folder / 'result.md'; result.write_text(text)
            return dict(status='ok', result_path=str(result))
        patch.object(e, 'dispatch', side_effect=dispatch).start()

    def create(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = e.create(core, self.args)
        ids = list((e.home(core) / 'tasks').glob('*/task.json'))
        return code, e.load(core, ids[-1].parent.name)

    def action(self, task, command, **kw):
        args = argparse.Namespace(task_id=task['id'], command=command, squash=False, integrated_commit=None, dry_run=False)
        for k,v in kw.items(): setattr(args,k,v)
        with contextlib.redirect_stdout(io.StringIO()):
            return e.lifecycle(core, args)

    def test_usage_table_exposes_role_effort(self):
        task = dict(maker=dict(self.maker, effort='medium'), checker=dict(self.checker, effort='high'))
        with patch.object(core.routing.usage, 'get', return_value={}):
            e.round_usage(core, task, self.base, 0)
        table = (self.base / 'usage.md').read_text()
        self.assertIn('effort medium', table)
        self.assertIn('effort high', table)

    def test_readiness_collects_dirty_auth_and_capacity_without_inference(self):
        self.args.max_fix_rounds = 0
        self.args.test = ['exit 1']
        for _ in range(4): self.create()
        (self.repo / 'file.txt').write_text('dirty')
        r = core.routing
        config = r.starter(core)
        r.save(r.root() / 'routing.json', config)
        available = {n: dict(status='auth', compatible=False) for n in r.FAMILIES}
        with patch.object(r, 'inventory', return_value=available), patch.object(r, 'request') as request:
            report = REAL_READINESS(core, self.args, str(self.repo))
        self.assertFalse(report['ready'])
        self.assertTrue(any('repository:' in x for x in report['blockers']))
        self.assertTrue(any('capacity:' in x for x in report['blockers']))
        self.assertTrue(any('maker:' in x for x in report['blockers']))
        self.assertTrue(any('checker:' in x for x in report['blockers']))
        request.assert_not_called()

    def test_readiness_preserves_independence_pins_and_permissions(self):
        r = core.routing
        config = r.starter(core)
        base = config['profiles'][0]
        config['profiles'] = [dict(base, id='maker', adapter='claude', family='anthropic', model='test-maker', tier='large', effort=None),
                              dict(base, id='checker', adapter='grok', family='anthropic', model='test-checker', tier='large', effort=None)]
        r.save(r.root() / 'routing.json', config)
        available = {n: dict(status='ready', compatible=True) for n in r.FAMILIES}
        with patch.object(r, 'inventory', return_value=available):
            report = REAL_READINESS(core, self.args, str(self.repo))
            self.assertFalse(report['ready'])  # no independent Maker/Checker pair
            config['profiles'][1]['family'] = 'xai'
            r.save(r.root() / 'routing.json', config)
            self.assertTrue(REAL_READINESS(core, self.args, str(self.repo))['ready'])
            with patch.dict(os.environ, ALLOY_CLAUDE_MODEL='different'):
                self.assertFalse(REAL_READINESS(core, self.args, str(self.repo))['ready'])
            with patch.object(e, 'probe', side_effect=e.ExecutionError('permission flag missing')):
                report = REAL_READINESS(core, self.args, str(self.repo))
            self.assertTrue(any('permission flag missing' in x for x in report['blockers']))

    def test_preflight_reports_without_creating_task_or_selecting(self):
        self.args.check = True
        with patch.object(e, 'readiness', return_value=dict(ready=False, blockers=['maker: login needed'])):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(e.create(core, self.args), 2)
        self.assertEqual(json.loads(output.getvalue())['blockers'], ['maker: login needed'])
        self.select.assert_not_called()
        self.assertFalse((e.home(core) / 'worktrees').exists())

    def test_packet_receipt_required_and_bound_to_revision(self):
        original = e.dispatch.side_effect
        def missing(core, task, role, prompt, folder):
            result = original(core, task, role, prompt, folder)
            if role == 'checker':
                Path(result['result_path']).write_text(json.dumps(dict(verdict='pass', findings=[])))
            return result
        with patch.object(e, 'dispatch', side_effect=missing):
            code, task = self.create()
        self.assertEqual(code, 3)
        self.assertIn('context receipt', task['error'])
        self.assertTrue(Path(task['worktree']).exists())
        receipt = task['rounds'][0]['packet']
        verdict = dict(verdict='pass', findings=[], packet_id=receipt['id'], revision='wrong', context_complete=True)
        with self.assertRaises(e.ExecutionError): e.review_json(json.dumps(verdict), receipt)
        verdict.update(revision=receipt['revision'], context_complete=False)
        with self.assertRaises(e.ExecutionError): e.review_json(json.dumps(verdict), receipt)
        # A verdict wrapped in prose or a fence is accepted only with a valid receipt.
        verdict.update(context_complete=True)
        wrapped = 'ExitPlanMode is disabled, so here is the result:\n```json\n' + json.dumps(verdict) + '\n```\nDone.'
        self.assertEqual(e.review_json(wrapped, receipt)['verdict'], 'pass')
        with self.assertRaises(e.ExecutionError):
            e.review_json(wrapped.replace(receipt['revision'], 'wrong'), receipt)
        # Two different embedded verdicts, or none, fail closed.
        other = dict(verdict, verdict='fail', findings=[dict(path='a', evidence='b', fix='c')])
        with self.assertRaises(e.ExecutionError):
            e.review_json('First ' + json.dumps(verdict) + ' then ' + json.dumps(other), receipt)
        with self.assertRaises(e.ExecutionError): e.review_json('Looks good to me, pass.', receipt)

    def test_review_packet_contains_actual_code_and_gate_output(self):
        self.args.test += ['echo acceptance-evidence']
        _, task = self.create()
        packet = json.loads((e.taskdir(core, task['id']) / 'review-0.json').read_text())
        self.assertEqual(packet['revision'], task['tip'])
        self.assertEqual(packet['changed_files'], ['file.txt'])
        self.assertIn('+new', packet['diff'])
        self.assertIn('acceptance-evidence', packet['tests'][1]['output'])
        self.assertTrue(all(g['revision'] == task['tip'] for g in task['rounds'][0]['gates']))
        self.assertIn('REVIEW PACKET:', self.calls[1][1])

    def test_large_review_packet_retains_work_without_truncation(self):
        original = e.dispatch.side_effect
        def large(core, task, role, prompt, folder):
            result = original(core, task, role, prompt, folder)
            if role == 'maker': (Path(task['worktree']) / 'file.txt').write_text('x' * 100000)
            return result
        self.args.test = ['exit 0']
        with patch.object(e, 'dispatch', side_effect=large): code, task = self.create()
        self.assertEqual(code, 3)
        self.assertIn('split the task', task['error'])
        self.assertEqual([role for role, _ in self.calls], ['maker'])
        self.assertTrue(Path(task['worktree']).exists())

    def test_native_sessions_reused_with_same_permissions_and_short_updates(self):
        binary = self.base / 'session-cli'
        binary.write_text('#!' + sys.executable + '\n' + r'''
import json, sys, re
from pathlib import Path
if '--version' in sys.argv: print('test'); raise SystemExit(0)
if '--help' in sys.argv:
    print('--resume --session-id acceptEdits --allowedTools --allow --tools'); raise SystemExit(0)
mode = sys.argv[sys.argv.index('--permission-mode') + 1]
role = 'maker' if mode == 'acceptEdits' else 'checker'
resumed = '--resume' in sys.argv
assert not (resumed and '--session-id' in sys.argv)
sid = sys.argv[sys.argv.index('--resume' if resumed else '--session-id') + 1]
state = Path.cwd().parent.parent / (role + '-session.json')
if resumed:
    assert json.loads(state.read_text()) == sid
else:
    assert not state.exists()
    state.write_text(json.dumps(sid))
prompt = Path(sys.argv[sys.argv.index('--prompt-file') + 1]).read_text() if '--prompt-file' in sys.argv else sys.stdin.read()
if role == 'maker':
    assert '--tools' in sys.argv and 'Bash' in sys.argv
    if resumed:
        assert 'TASK / ACCEPTANCE CRITERIA:' not in prompt
        assert '-F1' in prompt
    Path('file.txt').write_text('new\n')
    print('Changed and tested')
else:
    packet = json.loads(prompt.split('REVIEW PACKET:' + chr(10))[1])
    receipt = dict(packet_id=re.search(r'"packet_id":"([^"]+)"', prompt).group(1), revision=packet['revision'], context_complete=True)
    print(json.dumps(dict(verdict='pass' if resumed else 'fail', findings=[] if resumed else [dict(path='file.txt',evidence='Concrete example',fix='Verify newline')], **receipt)))
''')
        binary.chmod(0o700)
        with patch.dict(os.environ, ALLOY_BIN_CLAUDE=str(binary), ALLOY_BIN_GROK=str(binary)), patch.object(e, 'dispatch', side_effect=REAL_DISPATCH):
            code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(len(task['rounds']), 2)
        for role in ('maker', 'checker'):
            first, second = [record[role] for record in task['rounds']]
            self.assertEqual(first['session_id'], second['session_id'])
            self.assertEqual(second['session_mode'], 'resumed')
            self.assertEqual(first['permissions'], second['permissions'])
        self.assertNotEqual(task['sessions']['maker']['id'], task['sessions']['checker']['id'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output): e.finish(core, task)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary['metrics']['resumed_worker_calls'], 2)
        self.assertEqual(summary['metrics']['review_retries'], 1)
        self.assertGreater(summary['metrics']['verified_result_ms'], 0)
        self.assertFalse(summary['verification']['deployed'])
        self.assertFalse(summary['verification']['live_behavior_verified'])

    def test_interrupted_native_dispatch_keeps_exact_session_identity(self):
        _, task = self.create()
        task['sessions']['maker'] = dict(id='12345678-1234-1234-1234-123456789abc', supported=True, started=False, mode='native')
        folder = e.taskdir(core, task['id']) / 'interrupted-maker'
        with patch.object(core, 'run_panelist', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                REAL_DISPATCH(core, task, 'maker', 'TASK / ACCEPTANCE CRITERIA: task', folder)
        saved = e.load(core, task['id'])
        self.assertTrue(saved['sessions']['maker']['started'])
        def resumed(ad, prompt, directory, *args, **kwargs):
            argv = ad.build_args(prompt, str(Path(directory) / 'last'), 'make',
                                 dict(session_id=ad.managed_session_id))
            self.assertIn('--resume', argv)
            self.assertNotIn('--session-id', argv)
            self.assertIn('acceptEdits', argv)
            self.assertIn(saved['sessions']['maker']['id'], argv)
            return dict(status='error')
        with patch.object(core, 'run_panelist', side_effect=resumed) as call:
            result = REAL_DISPATCH(core, saved, 'maker', 'TASK / ACCEPTANCE CRITERIA: task', folder)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(call.call_count, 1)  # No silent fresh-session fallback.

    def test_full_execute_integrate_and_cleanup(self):
        code, task = self.create()
        self.assertEqual(code, 0); self.assertEqual(task['state'], 'ready')
        self.assertEqual((self.repo / 'file.txt').read_text(), 'old\n')
        self.assertEqual([c[0] for c in self.calls], ['maker', 'checker'])
        self.assertTrue(task['permissions']['maker']['repository_write'])
        self.assertFalse(task['permissions']['checker']['repository_write'])
        self.assertEqual(self.action(task, 'integrate'), 0)
        self.assertFalse(Path(task['worktree']).exists())
        self.assertEqual((self.repo / 'file.txt').read_text(), 'new\n')
        self.assertEqual(e.load(core, task['id'])['state'], 'cleaned')
        self.assertNotEqual(e.git(self.repo, 'show-ref', '--verify', 'refs/heads/' + task['branch'], check=False).returncode, 0)
        self.assertTrue((e.taskdir(core, task['id']) / 'changes.patch').exists())
        self.assertEqual(self.action(task, 'cleanup'), 0)

    def test_squash_integrate_cleanup_proof(self):
        _, task = self.create()
        self.assertEqual(self.action(task, 'integrate', squash=True), 0)
        record = e.load(core, task['id'])
        self.assertEqual(record['integration']['method'], 'exact_squash_diff')
        self.assertFalse(Path(task['worktree']).exists())

    def test_unmerged_task_not_cleaned(self):
        _, task = self.create()
        with self.assertRaisesRegex(e.ExecutionError, 'not proven'):
            self.action(task, 'cleanup')
        self.assertTrue(Path(task['worktree']).exists())

    def test_local_edits_and_new_commits_prevent_cleanup(self):
        _, task = self.create()
        e.git(self.repo, 'merge', '--ff-only', task['tip'])
        p = Path(task['worktree']) / 'file.txt'; p.write_text('unfinished')
        with self.assertRaisesRegex(e.ExecutionError, 'local edits'):
            self.action(task, 'cleanup')
        e.git(task['worktree'], 'add', '.'); e.git(task['worktree'], 'commit', '-qm', 'extra')
        with self.assertRaisesRegex(e.ExecutionError, 'new commits'):
            self.action(task, 'cleanup')

    def test_external_squash_exact_match_required(self):
        _, task = self.create()
        e.git(self.repo, 'merge', '--squash', task['tip']); e.git(self.repo, 'commit', '-qm', 'squashed')
        merged = e.git(self.repo, 'rev-parse', 'HEAD')
        with self.assertRaises(e.ExecutionError): self.action(task, 'cleanup')
        self.assertEqual(self.action(task, 'cleanup', integrated_commit=merged, dry_run=True), 0)
        self.assertTrue(Path(task['worktree']).exists())
        self.assertEqual(self.action(task, 'cleanup', integrated_commit=merged), 0)

    def test_unrelated_or_partial_squash_refused(self):
        _, task = self.create()
        (self.repo / 'file.txt').write_text('different\n')
        e.git(self.repo, 'commit', '-qam', 'other')
        sha = e.git(self.repo, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(e.ExecutionError, 'exactly match'):
            self.action(task, 'cleanup', integrated_commit=sha)
        self.assertTrue(Path(task['worktree']).exists())

    def test_target_advanced_or_dirty_refuses_integration(self):
        _, task = self.create()
        e.git(self.repo, 'commit', '--allow-empty', '-qm', 'advanced')
        with self.assertRaisesRegex(e.ExecutionError, 'Target advanced'):
            self.action(task, 'integrate')
        (self.repo / 'file.txt').write_text('local')
        with self.assertRaisesRegex(e.ExecutionError, 'must be clean'):
            self.action(task, 'integrate')

    def test_review_failure_drives_correction_without_host(self):
        self.verdicts = [dict(verdict='fail', findings=[dict(path='file.txt', evidence='Example failure', fix='Check exact newline')])]
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code, task = self.create()
        self.assertEqual(output.getvalue().count('ALLOY_ROUND_USAGE'), 2)
        for index, record in enumerate(task['rounds']):
            text = Path(record['usage']['markdown_path']).read_text()
            self.assertIn('round %s' % (index + 1), text)
            self.assertIn('tracking is disabled', text)
            self.assertIn('claude · sonnet', text)
        self.assertEqual(code, 0); self.assertEqual(len(task['rounds']), 2)
        self.assertIn('Example failure', self.calls[2][1])
        self.assertEqual([c[0] for c in self.calls], ['maker','checker','maker','checker'])

    def test_round_usage_repeats_unchanged_table_without_auth_metadata(self):
        snapshot = dict(enabled=True, providers={'claude': dict(
            status='ready', binding='private-auth-binding', windows=[])})
        task = dict(maker=self.maker, checker=self.checker)
        output = io.StringIO()
        with patch.object(core.routing.usage, 'get', return_value=snapshot), contextlib.redirect_stderr(output):
            for index in range(2):
                folder = self.base / str(index); folder.mkdir()
                record = e.round_usage(core, task, folder, index)
                self.assertNotIn('binding', record['snapshot']['providers']['claude'])
                self.assertIn('| Provider / pool |', Path(record['markdown_path']).read_text())
        self.assertEqual(output.getvalue().count('| Provider / pool |'), 2)
        self.assertNotIn('private-auth-binding', output.getvalue())

    def test_failed_gates_bounded_and_retained(self):
        self.args.test = [sys.executable + ' -c "raise SystemExit(1)"']
        code, task = self.create()
        self.assertEqual(code, 3); self.assertEqual(task['state'], 'needs_attention')
        self.assertEqual(len(task['rounds']), 3)
        self.assertTrue(all(c[0] == 'maker' for c in self.calls))
        self.assertTrue(Path(task['worktree']).exists())
        with self.assertRaises(e.ExecutionError): self.action(task,'cleanup')

    def test_scope_violation_stops_before_review(self):
        self.args.allow_path = ['elsewhere']
        code, task = self.create()
        self.assertEqual(code, 3); self.assertIn('outside allowed', task['error'])
        self.assertEqual(len(self.calls), 1)

    def test_no_false_pass_on_malformed_review(self):
        self.verdicts = [dict(verdict='pass', findings=[dict(path='file.txt', evidence='Bug', fix='Fix')])]
        code, task = self.create()
        self.assertEqual(code, 3); self.assertIn('Inconsistent', task['error'])

    def test_active_task_lock_blocks_cleanup(self):
        _, task = self.create()
        with e.locked(e.taskdir(core, task['id']) / 'task.lock'):
            with self.assertRaisesRegex(e.ExecutionError, 'busy'):
                self.action(task, 'cleanup')

    def test_recovery_after_worktree_removal(self):
        _, task = self.create()
        e.git(self.repo, 'merge', '--ff-only', task['tip'])
        task.update(state='integrated', integration=e.proof(task)); e.save(core,task)
        e.git(self.repo,'worktree','remove',task['worktree'])
        self.assertEqual(self.action(task,'cleanup'), 0)

    def test_managed_paths_and_ids_validated(self):
        with self.assertRaises(e.ExecutionError): e.load(core,'../repo')
        _, task = self.create()
        task['worktree'] = str(self.repo); e.save(core,task)
        with self.assertRaisesRegex(e.ExecutionError, 'ownership'): e.load(core,task['id'])

    def test_orphaned_worker_blocks_resume(self):
        _, task = self.create()
        task['state']='interrupted'; e.save(core,task)
        status=e.taskdir(core,task['id'])/'round-0/maker/status.json'
        core.routing.save(status,dict(status='running',pid=os.getpgrp()))
        with self.assertRaisesRegex(e.ExecutionError,'still be running'): self.action(task,'resume')

    @patch.object(core.AntigravityAdapter, '_enforced', return_value=True)
    def test_adapter_write_flags_keep_read_only_defaults(self, _enforced):
        for name in ('codex','claude','grok','antigravity'):
            decision=dict(cli=name, model='test-model', effort=None)
            ad=e.worker_adapter(core,decision,True)
            prompt=self.base/'prompt.txt';prompt.write_text('Task')
            with patch.object(core, 'setting', return_value=None):
                args=ad.build_args(str(prompt),str(self.base/'out'),'make',dict(repo=str(self.repo),pdir=str(self.base/name),timeout_s=10))
            self.assertFalse(ad.read_only)
            self.assertNotIn('bypassPermissions',args)
            self.assertNotIn('--dangerously-skip-permissions',args)
            self.assertTrue(core.ADAPTERS[name].read_only)
            if name=='codex':self.assertIn('workspace-write',args)
            elif name in ('claude','grok'):self.assertIn('acceptEdits',args)
            else:self.assertIn('accept-edits',args)
            if name=='grok':
                # Headless grok needs explicit edit allow rules beyond acceptEdits.
                allowed=[args[i+1] for i,a in enumerate(args) if a=='--allow']
                self.assertEqual(set(allowed),{'Bash','Edit','Write','WebFetch'})
                self.assertEqual(args.count('--tools'),1)
                self.assertEqual(args[args.index('--tools')+1],'Read,Glob,Grep,Edit,Write,Bash')

    def test_real_subprocess_writes_worktree_and_records_boundary(self):
        binary = self.base / 'mock-cli'
        binary.write_text('#!' + sys.executable + "\n" + """
import json, os, sys
from pathlib import Path
if '--version' in sys.argv:
    print('1.2.3'); raise SystemExit(0)
if '--help' in sys.argv:
    print('acceptEdits --allowedTools --allow --tools --permission-mode --prompt-file --output-format'); raise SystemExit(0)
assert 'TYPESAFE_API_KEY' not in os.environ
mode = sys.argv[sys.argv.index('--permission-mode') + 1]
if mode == 'acceptEdits':
    assert '--tools' in sys.argv and 'Bash' in sys.argv
    Path('file.txt').write_text('new\\n')
    print('Changed file.txt and tested it.')
else:
    assert mode == 'plan'
    assert Path('file.txt').read_text() == 'new\\n'
    prompt = Path(sys.argv[sys.argv.index('--prompt-file')+1]).read_text()
    import re
    receipt = dict(packet_id=re.search(r'"packet_id":"([^"]+)"', prompt).group(1), revision=re.search(r'"revision":"([^"]+)"', prompt).group(1), context_complete=True)
    print(json.dumps(dict(verdict='pass', findings=[], **receipt)))
""")
        binary.chmod(0o700)
        with patch.dict(os.environ, ALLOY_BIN_CLAUDE=str(binary), ALLOY_BIN_GROK=str(binary), TYPESAFE_API_KEY='fake-test-key'), patch.object(e, 'dispatch', side_effect=REAL_DISPATCH):
            code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual((self.repo/'file.txt').read_text(), 'old\n')
        m, c = task['rounds'][0]['maker'], task['rounds'][0]['checker']
        self.assertEqual(m['cwd'], task['worktree'])
        self.assertFalse(m['read_only']); self.assertTrue(c['read_only'])
        self.assertEqual(m['permissions']['command_execution'], 'allowed')
        self.assertEqual(c['permissions']['command_execution'], 'provider_read_only_policy')
        self.assertEqual(self.action(task, 'integrate'), 0)

    def test_interruption_resumes_with_shared_attempt_limit(self):
        original = e.dispatch.side_effect
        def interrupt(core, task, role, prompt, folder):
            if role == 'maker':
                (Path(task['worktree'])/'file.txt').write_text('partial')
                raise KeyboardInterrupt()
            return original(core,task,role,prompt,folder)
        with patch.object(e, 'dispatch', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt): self.create()
        path = next((e.home(core)/'tasks').glob('*/task.json'))
        task=e.load(core,path.parent.name)
        self.assertEqual(task['state'],'interrupted')
        self.assertEqual(self.action(task,'resume'),0)
        task=e.load(core,task['id'])
        self.assertEqual(len(task['rounds']),2)
        task['state']='needs_attention'; task['max_fix_rounds']=1; e.save(core,task)
        before=len(self.calls)
        self.assertEqual(self.action(task,'resume'),3)
        self.assertEqual(len(self.calls),before)

    def test_checker_tampering_rejects_pass(self):
        original=e.dispatch.side_effect
        def tamper(core,task,role,prompt,folder):
            out=original(core,task,role,prompt,folder)
            if role=='checker': (Path(task['worktree'])/'file.txt').write_text('tampered')
            return out
        with patch.object(e,'dispatch',side_effect=tamper): code,task=self.create()
        self.assertEqual(code,3); self.assertIn('Checker changed',task['error'])

    def test_retained_worktree_cap(self):
        self.args.max_fix_rounds=0
        self.args.test=['exit 1']
        for _ in range(4): self.create()
        with self.assertRaisesRegex(e.ExecutionError,'Four retained'): self.create()
        self.assertEqual(len(list((e.home(core)/'worktrees').iterdir())),4)

    def test_dirty_source_stops_before_selection(self):
        (self.repo/'file.txt').write_text('uncommitted')
        with self.assertRaisesRegex(e.ExecutionError,'clean committed'): self.create()
        self.select.assert_not_called()

    def test_test_timeout_preserves_work(self):
        self.args.test=[sys.executable + ' -c "import time; time.sleep(10)"']
        self.args.test_timeout=1; self.args.max_fix_rounds=0
        code,task=self.create()
        self.assertEqual(code,3); self.assertEqual(task['rounds'][0]['gates'][0]['exit_code'],124)
        self.assertTrue(Path(task['worktree']).exists())

    def test_selection_and_resume_preserve_independence_and_pins(self):
        r=core.routing
        config=r.starter(core)
        base=config['profiles'][0]
        config['profiles']=[dict(base,id='maker',adapter='claude',family='anthropic',model='test-maker',tier='large',effort=None,billing_mode='subscription'),
                            dict(base,id='checker',adapter='grok',family='xai',model='test-checker',tier='large',effort=None,billing_mode='subscription')]
        r.save(r.root()/'routing.json',config)
        available={n:dict(status='ready',compatible=True) for n in r.FAMILIES}
        with patch.object(r,'inventory',return_value=available):
            maker,checker=REAL_SELECT(core,self.args,'Task')
            self.assertEqual({maker['family'],checker['family'],self.args.host_family},{'openai','anthropic','xai'})
            task=dict(maker=maker,checker=checker,host_family='openai',max_estimated_usd=None)
            REAL_REVALIDATE(core,task,'maker')
            with patch.dict(os.environ,ALLOY_CLAUDE_MODEL='different'):
                with self.assertRaises(r.RoutingError): REAL_REVALIDATE(core,task,'maker')
            config['profiles'][0]['billing_mode']='metered'
            r.save(r.root()/'routing.json',config)
            with self.assertRaisesRegex(e.ExecutionError,'billing changed'): REAL_REVALIDATE(core,task,'maker')
            config['profiles'][1]['family']='anthropic'; r.save(r.root()/'routing.json',config)
            with self.assertRaises(r.RoutingError): REAL_SELECT(core,self.args,'Task')

    def test_cli_execute_to_integrate_offline(self):
        binary=self.base/'mock-cli'
        binary.write_text('#!' + sys.executable + '\n' + """
import json,sys
from pathlib import Path
if '--version' in sys.argv:
    print('1.2.3'); raise SystemExit(0)
if '--help' in sys.argv:
    print('--permission-mode --model --output-format --prompt-file acceptEdits --allowedTools --allow --tools'); raise SystemExit(0)
mode=sys.argv[sys.argv.index('--permission-mode')+1]
if mode=='acceptEdits':
    Path('file.txt').write_text('new\\n'); print('Done')
else:
    assert mode=='plan' and Path('file.txt').read_text()=='new\\n'
    prompt = Path(sys.argv[sys.argv.index('--prompt-file')+1]).read_text()
    import re
    receipt = dict(packet_id=re.search(r'"packet_id":"([^"]+)"', prompt).group(1), revision=re.search(r'"revision":"([^"]+)"', prompt).group(1), context_complete=True)
    print(json.dumps(dict(verdict='pass', findings=[], **receipt)))
""")
        binary.chmod(0o700)
        r=core.routing;config=r.starter(core); base=config['profiles'][0]
        config['profiles']=[dict(base,id='maker',adapter='claude',model='test-maker',family='anthropic',tier='large',effort=None,billing_mode='subscription'),
                            dict(base,id='checker',adapter='grok',model='test-checker',family='xai',tier='large',effort=None,billing_mode='subscription')]
        r.save(r.root()/'routing.json',config)
        env=dict(PATH=os.environ['PATH'], HOME=str(self.base/'home'), ALLOY_CONFIG='/dev/null',ALLOY_USAGE='off',
                 ALLOY_RUN_ROOT=str(self.base/'state/runs'),ALLOY_ROUTING_HOME=str(self.base/'config'),
                 ALLOY_BIN_CLAUDE=str(binary),ALLOY_BIN_GROK=str(binary),ALLOY_BIN_CODEX='/nonexistent',ALLOY_BIN_ANTIGRAVITY='/nonexistent',
                 ANTHROPIC_API_KEY='test-only',XAI_API_KEY='test-only')
        command=[sys.executable,str(ROOT/'bin/alloy')]
        result=subprocess.run(command+['execute','--repo',str(self.repo),'--prompt-file',str(self.prompt),'--host-family','openai',
            '--maker-profile','maker','--checker-profile','checker','--allow-path','file.txt','--test',self.args.test[0]],
            env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        task=json.loads(result.stdout)
        self.assertEqual(task['state'],'ready')
        result=subprocess.run(command+['integrate',task['id']],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'],'cleaned')
        self.assertFalse(Path(task['worktree']).exists())

    def test_jev_selection_uses_one_fake_assessment_for_both_roles(self):
        r=core.routing;config=r.starter(core);base=config['profiles'][0]
        config['profiles']=[dict(base,id='maker',adapter='claude',family='anthropic',model='test-maker',tier='large',effort=None,billing_mode='subscription'),
                            dict(base,id='checker',adapter='grok',family='xai',model='test-checker',tier='large',effort=None,billing_mode='subscription')]
        r.save(r.root()/'routing.json',config)
        self.args.route=True
        answers={}
        for name,q in r.questions().items():
            if q['type']=='choice':
                choice='small' if name=='complexity' else 'implementation'
                answers[name]=dict(type='choice',choice=choice,confidence=1,probabilities={k:int(k==choice) for k in q['criteria']})
            else: answers[name]=dict(type='noul',noul=0)
        available={n:dict(status='ready',compatible=True) for n in r.FAMILIES}
        with patch.object(r,'inventory',return_value=available), patch.object(r,'request',return_value=(dict(model='jev-test',answers=answers,usage=dict(input_tokens=1,output_tokens=1)),1)) as request:
            maker,checker=REAL_SELECT(core,self.args,'Task')
        self.assertEqual(request.call_count,1)
        self.assertEqual(maker['family'],'anthropic'); self.assertEqual(checker['family'],'xai')

    def test_resume_quota_reserve_and_budget_fail_closed(self):
        r=core.routing;config=r.starter(core);base=config['profiles'][0]
        config['profiles']=[dict(base,id='maker',adapter='claude',family='anthropic',model='test-maker',tier='large',effort=None,billing_mode='subscription',quota_pool='claude'),
                            dict(base,id='checker',adapter='grok',family='xai',model='test-checker',tier='large',effort=None,billing_mode='subscription',quota_pool='grok')]
        r.save(r.root()/'routing.json',config)
        available={n:dict(status='ready',compatible=True) for n in r.FAMILIES}
        with patch.object(r,'inventory',return_value=available):
            maker,checker=REAL_SELECT(core,self.args,'Task')
            task=dict(maker=maker,checker=checker,host_family='openai',max_estimated_usd=None)
            config['quota_pools']['claude']=dict(remaining_fraction=0,reserve_fraction=.1)
            r.save(r.root()/'routing.json',config)
            with self.assertRaises(r.RoutingError): REAL_REVALIDATE(core,task,'maker')
            config['quota_pools']={};config['profiles'][0]['billing_mode']='metered';r.save(r.root()/'routing.json',config)
            task['max_estimated_usd']=0
            with self.assertRaises(r.RoutingError): REAL_REVALIDATE(core,task,'maker')

    def test_scope_preserves_leading_whitespace_in_names(self):
        original=e.dispatch.side_effect
        def maker(core,task,role,prompt,folder):
            result=original(core,task,role,prompt,folder)
            if role=='maker': (Path(task['worktree'])/' secret.txt').write_text('out of scope')
            return result
        self.args.allow_path=['file.txt','secret.txt']
        with patch.object(e,'dispatch',side_effect=maker): code,task=self.create()
        self.assertEqual(code,3); self.assertIn('outside allowed',task['error'])

    def test_non_utf8_diff_is_preserved(self):
        original=e.dispatch.side_effect
        def maker(core,task,role,prompt,folder):
            result=original(core,task,role,prompt,folder)
            if role=='maker': (Path(task['worktree'])/'file.txt').write_bytes(b'new\xff\n')
            return result
        self.args.test=['exit 0']
        with patch.object(e,'dispatch',side_effect=maker): code,task=self.create()
        self.assertEqual(code,0,task.get('error'))
        self.assertIn(b'new\xff', (e.taskdir(core,task['id'])/'changes.patch').read_bytes())
        self.assertEqual(self.action(task,'integrate',squash=True),0)

    def test_antigravity_staged_prompt_and_private_settings(self):
        prompt=self.base/'prompt.txt';prompt.write_text('Task')
        ctx=dict(repo=str(self.repo),pdir=str(self.base/'agy'),timeout_s=10,managed_worktree=True)
        ad=e.worker_adapter(core,dict(cli='antigravity',model='test',effort=None),True)
        args=ad.build_args(str(prompt),str(self.base/'last'),'make',ctx)
        self.assertIn(str(self.base/'agy/prompt_in/prompt.md'),args[args.index('-p')+1])
        with patch.object(core.AntigravityAdapter,'_AUTH_LINKS',()), patch.object(core.AntigravityAdapter,'_keychain_plist',return_value=None):
            env=ad.prepare_env(ctx)
        self.assertTrue(Path(env['HOME']).is_relative_to(self.base) if hasattr(Path,'is_relative_to') else str(env['HOME']).startswith(str(self.base)))
        self.assertIn('command',ad._settings()['permissions']['allow'])
        self.assertIn('command(*)',ad._settings()['permissions']['allow'])  # agy >= 1.2 grammar
        self.assertNotIn('command(*)',core.ADAPTERS['antigravity']._settings()['permissions']['allow'])
        self.assertNotIn('command',core.ADAPTERS['antigravity']._settings()['permissions']['allow'])

    def test_antigravity_checker_grants_only_the_private_gate_log_root(self):
        prompt=self.base/'prompt.txt';prompt.write_text('Review')
        ctx=dict(repo=str(self.repo),pdir=str(self.base/'agy-review'),timeout_s=10,
                 managed_worktree=False)
        ad=e.worker_adapter(core,dict(cli='antigravity',model='test',effort=None),False)
        with patch.object(core.AntigravityAdapter,'_agy_version',return_value=(1,2,13)):
            args=ad.build_args(str(prompt),str(self.base/'last'),'review',ctx)
            with patch.object(core.AntigravityAdapter,'_AUTH_LINKS',()), patch.object(core.AntigravityAdapter,'_keychain_plist',return_value=None):
                env=ad.prepare_env(ctx)
        gate_logs=core.gate_log_dir()
        self.assertEqual(gate_logs,str(Path.home()/'.local/state/alloy/gate-logs'))
        add_dirs=[args[i+1] for i,value in enumerate(args[:-1]) if value=='--add-dir']
        self.assertIn(gate_logs,add_dirs)
        self.assertEqual(os.stat(gate_logs).st_mode & 0o777,0o700)
        settings=json.loads((Path(env['HOME'])/'.gemini/antigravity-cli/settings.json').read_text())
        allow=settings['permissions']['allow']
        self.assertIn('read_file('+gate_logs+')',allow)
        self.assertNotIn('read_file(/tmp)',allow)
        self.assertNotIn('read_file(/private/tmp)',allow)
        self.assertNotIn('/tmp',add_dirs)
        self.assertNotIn('/private/tmp',add_dirs)

    def test_antigravity_checker_prompt_confines_absolute_reads(self):
        self.checker=dict(cli='antigravity',family='google',model='gemini-test',effort=None,profile='checker')
        self.select.return_value=(self.maker,self.checker)
        code,task=self.create()
        self.assertEqual(code,0,task.get('error'))
        checker_prompt=self.calls[1][1]
        self.assertIn('The Checker reads files only inside the task worktree '+task['worktree'],checker_prompt)
        self.assertIn('and the gate-log directory '+core.gate_log_dir(),checker_prompt)
        self.assertIn('never opens another absolute path',checker_prompt)
        self.assertIn('use the text of the gate output that is in this prompt',checker_prompt)


    def test_gate_status_write_failure_reaps_child(self):
        children=[]
        launch=subprocess.Popen
        def capture(*args,**kwargs):
            child=launch(*args,**kwargs);children.append(child);return child
        with patch.object(subprocess,'Popen',side_effect=capture), patch.object(core.routing,'save',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):
                e.gate(core,dict(worktree=str(self.repo),test_timeout=5),
                       sys.executable+' -c "import time; time.sleep(30)"',self.base/'gate.log')
        self.assertEqual(len(children),1)
        self.assertIsNotNone(children[0].poll())
        self.assertNotIn(children[0].pid,core._LIVE_PGIDS)

    def test_worker_status_write_failure_reaps_child(self):
        children=[]
        launch=subprocess.Popen
        def capture(*args,**kwargs):
            child=launch(*args,**kwargs);children.append(child);return child
        ad=e.worker_adapter(core,self.maker,True)
        ad.resolved_bin=lambda:sys.executable
        ad.cli_version=lambda:'test'
        ad.build_args=lambda *args:['-c','import time; time.sleep(30)']
        with patch.object(subprocess,'Popen',side_effect=capture), patch.object(core,'write_atomic',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):
                core.run_panelist(ad,str(self.prompt),str(self.base/'worker'),5,1000,'make',
                                  repo=str(self.repo),managed_worktree=True)
        self.assertEqual(len(children),1)
        self.assertIsNotNone(children[0].poll())
        self.assertNotIn(children[0].pid,core._LIVE_PGIDS)



# --------------------------------------------------------------------------- #
# Cursor managed Maker and Checker
# --------------------------------------------------------------------------- #
# Everything below runs against the production modules with the MOCK sandbox-exec
# (tests/mocks/mock_panelist.py, patched in as core.SANDBOX_EXEC) and a fake cursor-agent
# written here. The real /usr/bin/sandbox-exec, the real cursor-agent, the network and the
# macOS keychain are never touched, and HOME is never set or changed. The one test that
# exercises the real OS profile is the Lane 6 release gate, not this file.
MOCK = ROOT / 'tests/mocks/mock_panelist.py'
GOOD_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJmYWtlIjoiZml4dHVyZSJ9.c2lnbmF0dXJlLWZpeHR1cmU'
# recognised secret shapes -> (text as it appears in a source, the value that must never leave)
SECRETS = dict(jwt=('token ' + GOOD_JWT, GOOD_JWT),
               assignment=('API_KEY=hunter2hunter2hunter2', 'hunter2hunter2hunter2'),
               header=('Authorization: Bearer abc123def456ghi789', 'abc123def456ghi789'))
FORBIDDEN_FLAGS = ('--force', '-f', '--yolo', '--auto-review', '--approve-mcps', '--resume', '--continue',
                   '--plugin-dir', '--add-dir', '-w', '--worktree', '--worktree-base', '--plan',
                   '--endpoint', '--api-key', '--header')
BUILTIN_DENIALS = ('.ssh', '.aws', '.gnupg', '.config/gh', '.netrc', '.docker/config.json', '.kube', '.npmrc',
                   '.pypirc', '.git-credentials', 'Library/Keychains', '.openclaw/secrets', '.cswarm',
                   '.codex/auth.json', '.claude/.credentials.json', '.gemini', '.grok', '.config/op')


def load_mock():
    spec = importlib.util.spec_from_file_location('mock_panelist_exec', str(MOCK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOCKMOD = load_mock()

# The fake `cursor-agent`. What it does is set by a plan file next to it (see plan()); it
# understands the metadata calls and the print-mode inference call, edits the worktree like a
# Maker, or answers like a Checker (with the packet receipt), and can simulate every escape the
# managed tripwires must catch. It runs only behind the mock sandbox-exec.
FAKE_CURSOR = r'''
import json, os, re, sys
from pathlib import Path
me = Path(__file__).resolve()
side = lambda ext: Path(str(me) + ext)
plan = json.loads(side('.plan.json').read_text()) if side('.plan.json').exists() else {}
argv = sys.argv[1:]
HELP = '--print --output-format --mode --model --list-models --sandbox --workspace --skip-worktree-setup --trust'
def log(kind):
    if plan.get('log'):
        with open(plan['log'], 'a') as f:
            f.write(json.dumps(dict(kind=kind, argv=argv, cwd=os.getcwd(), env_names=sorted(os.environ))) + '\n')
if argv == ['--version']:
    print('2026.09.28-64d2043'); raise SystemExit(0)
if argv == ['--help']:
    log('help'); print(plan.get('help', HELP)); raise SystemExit(plan.get('help_exit', 0))
if argv == ['status']:
    log('status'); print('\u2713 Logged in as tl***@gmail.com'); raise SystemExit(0)
role = 'checker' if '--mode' in argv else 'maker'
m = re.match(r'Read ("(?:[^"\\]|\\.)*") in full', argv[-1])
staged = Path(json.loads(m.group(1))).read_text()
log(role)
for item in plan.get(role + '_writes', []):
    path = Path(item['path']); path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a' if item.get('append') else 'w') as f:
        f.write(item['text'])
for item in plan.get(role + '_git_writes', []):          # cwd is the worktree
    if item['base'] == 'pointer':
        target = Path('.git')
    else:
        gitdir = Path(Path('.git').read_text().strip().split(': ', 1)[1])
        base = gitdir if item['base'] == 'gitdir' else (gitdir / (gitdir / 'commondir').read_text().strip()).resolve()
        target = base / item['rel']
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'a') as f:
        f.write(item['text'])
if plan.get(role + '_tamper_canary'):
    with open(os.path.join(os.path.dirname(os.path.dirname(os.environ['TMPDIR'])), 'canary', 'canary.txt'), 'w') as f:
        f.write('tampered\n')
if role == 'maker':
    result = plan.get('maker_result', 'Changed and tested.')
else:
    counter = side('.count'); n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    verdicts = plan.get('verdicts') or [dict(verdict='pass', findings=[])]
    verdict = dict(verdicts[min(n, len(verdicts) - 1)])
    if not plan.get('no_receipt'):
        verdict.update(packet_id=re.search(r'"packet_id":"([^"]+)"', staged).group(1),
                       revision=re.search(r'"revision":"([^"]+)"', staged).group(1), context_complete=True)
    result = json.dumps(verdict)
print(json.dumps(dict(type='result', subtype='success', is_error=False, duration_ms=1, result=result,
                      session_id='fake-session-1', usage=dict(inputTokens=10, outputTokens=5))))
raise SystemExit(plan.get('exit', 0))
'''
HELP_ALL = ('--print --output-format --mode --model --list-models --sandbox --workspace '
            '--skip-worktree-setup --trust')


class CursorManagedBase(unittest.TestCase):
    """Shared fixture: a real temporary Git repo, the fake cursor-agent behind the mock
    sandbox-exec, and patched selection/readiness. Subclasses add tests only."""

    @classmethod
    def setUpClass(cls):
        cls.cli_dir = os.path.realpath(tempfile.mkdtemp(prefix='alloy-exec-cursor-'))
        cls.cli = os.path.join(cls.cli_dir, 'cursor-agent')
        Path(cls.cli).write_text('#!' + sys.executable + '\n' + FAKE_CURSOR)
        os.chmod(cls.cli, 0o755)
        os.chmod(str(MOCK), 0o755)
        # Fixed, so the cached sandbox self-test verdict is shared by every test in the class:
        # the verdict is keyed on the denial set, and that set includes Alloy's own state paths.
        cls.routing_home = os.path.join(cls.cli_dir, 'routing')
        cls.xdg = os.path.join(cls.cli_dir, 'xdg')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.cli_dir, True)

    def patch_core(self, **kw):
        for key, value in kw.items():
            patcher = patch.object(core, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def patch_e(self, name, *args, **kw):
        patcher = patch.object(e, name, *args, **kw)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(os.path.realpath(self.tmp.name))
        self.repo = self.base / 'repo'
        self.init_repo()
        shutil.rmtree(self.routing_home, True)
        self.dump, self.sblog, self.clog = (str(self.base / n) for n in ('sb-dump', 'sandbox.log', 'cursor.log'))
        env = patch.dict(os.environ, {
            'ALLOY_RUN_ROOT': str(self.base / 'state/runs'), 'ALLOY_ROUTING_HOME': self.routing_home,
            'ALLOY_CONFIG': '/dev/null', 'ALLOY_USAGE': 'off', 'XDG_STATE_HOME': self.xdg,
            'ALLOY_BIN_CURSOR': self.cli, 'MOCK_SANDBOX_DUMP': self.dump, 'MOCK_SANDBOX_LOG': self.sblog})
        env.start()
        self.addCleanup(env.stop)
        for name in ('ALLOY_BIN_CURSOR_AGENT', 'ALLOY_CURSOR_MODEL', 'ALLOY_CURSOR_AGENT_MODEL',
                     'ALLOY_CURSOR_EFFORT', 'ALLOY_CURSOR_AGENT_EFFORT', 'ALLOY_CURSOR_DENY_READ_PATHS',
                     'CURSOR_API_KEY', 'CURSOR_API_ENDPOINT', 'ALLOY_PANELISTS', 'ALLOY_ALLOW_UNSANDBOXED',
                     'ALLOY_CAPTURE_USAGE', 'MOCK_SANDBOX_PREFLIGHT', 'MOCK_VERSION'):
            os.environ.pop(name, None)
        self.patch_core(_CONFIG={}, SANDBOX_EXEC=str(MOCK), SANDBOX_TRUSTED_UID=os.getuid(),
                        CURSOR_PLATFORM=sys.platform, CURSOR_ENV_ALLOW_PREFIXES=('LC_', 'MOCK_'),
                        log=lambda msg: None)
        core.ADAPTERS['cursor'].__dict__.pop('_auth_cache', None)
        self.addCleanup(lambda: core.ADAPTERS['cursor'].__dict__.pop('_auth_cache', None))
        self.addCleanup(lambda: [os.path.exists(f) and os.remove(f) for f in
                                 (self.cli + '.plan.json', self.cli + '.count')])
        self.plan()
        if os.path.exists(self.cli + '.count'):
            os.remove(self.cli + '.count')
        # Selection, readiness, probing and revalidation are patched as in ExecutionTests;
        # tests that exercise one of them restore the real function.
        self.maker = self.decision('composer-2.5', 'cursor-maker')
        self.checker = self.decision('claude-opus-5-5-high', 'cursor-checker')
        self.patch_e('readiness', return_value=dict(ready=True, blockers=[]))
        self.select = self.patch_e('select', return_value=(self.maker, self.checker))
        self.patch_e('probe')
        self.patch_e('revalidate')
        self.prompt = self.base / 'task.txt'
        self.prompt.write_text('Change file.txt to new. Test it.')
        self.args = argparse.Namespace(
            repo=str(self.repo), prompt_file=str(self.prompt), route=False, maker_profile='cursor-maker',
            checker_profile='cursor-checker', host_family='openai', allow_path=['file.txt'],
            test=['exit 0'], max_fix_rounds=2, timeout=30, test_timeout=10, max_estimated_usd=None)
        self.verdicts = []
        self.calls = []
        self.maker_hook = self.checker_hook = None
        self.maker_extra, self.checker_extra = {}, {}
        self.patch_e('dispatch', side_effect=self.fake_dispatch)

    # -- fixtures ------------------------------------------------------------------ #
    def init_repo(self):
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        e.git(self.repo, 'checkout', '-b', 'main')
        e.git(self.repo, 'config', 'user.name', 'Test')
        e.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'file.txt').write_text('old\n')
        (self.repo / '.gitignore').write_text('ignored.txt\nignored-dir/\n')
        e.git(self.repo, 'add', '.')
        e.git(self.repo, 'commit', '-qm', 'base')

    def reset(self):
        """A pristine repo and no retained tasks: a case that tampers with Git internals
        must not poison the next one (or hit the four-retained-worktree cap)."""
        shutil.rmtree(self.repo, True)
        shutil.rmtree(e.home(core), True)
        self.init_repo()
        self.calls.clear()

    def decision(self, model, profile):
        effective = core.cursor_effective_model(model)
        return dict(cli='cursor', profile=profile, family=core.cursor_model_family(model), model=model,
                    effective_model=effective, effort=core.cursor_split_model(effective)[1].get('effort'),
                    cursor_fast=False, billing_mode='subscription')

    def plan(self, **kw):
        Path(self.cli + '.plan.json').write_text(json.dumps(dict(kw, log=self.clog)))

    def fake_dispatch(self, core_, task, role, prompt, folder):
        """Stands in for the provider call: edits/answers directly in the worktree (no
        sandbox, no process), with optional per-role tamper hooks and extra result fields."""
        self.calls.append((role, prompt))
        folder.mkdir(parents=True, exist_ok=True)
        hook = self.maker_hook if role == 'maker' else self.checker_hook
        if role == 'maker':
            (Path(task['worktree']) / 'file.txt').write_text('new\n')
        if hook:
            hook(task)
        if role == 'maker':
            text = 'Updated file and ran checks.'
        else:
            verdict = self.verdicts.pop(0) if self.verdicts else dict(verdict='pass', findings=[])
            receipt = task['rounds'][-1]['packet']
            verdict.update(packet_id=receipt['id'], revision=receipt['revision'], context_complete=True)
            text = json.dumps(verdict)
        result = folder / 'result.md'
        result.write_text(text)
        return dict(status='ok', result_path=str(result), **(self.maker_extra if role == 'maker' else self.checker_extra))

    def real_dispatch(self):
        self.patch_e('dispatch', side_effect=REAL_DISPATCH)

    def create(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = e.create(core, self.args)
        ids = list((e.home(core) / 'tasks').glob('*/task.json'))
        return code, e.load(core, ids[-1].parent.name)

    def action(self, task, command, **kw):
        args = argparse.Namespace(task_id=task['id'], command=command, squash=False, integrated_commit=None, dry_run=False)
        for k, v in kw.items():
            setattr(args, k, v)
        with contextlib.redirect_stdout(io.StringIO()):
            return e.lifecycle(core, args)

    def linked_worktree(self, name='wt'):
        path = self.base / name
        e.git(self.repo, 'worktree', 'add', '-q', '-b', 'branch-' + name, str(path))
        return str(path)

    # -- observations -------------------------------------------------------------- #
    def cursor_calls(self, kind=None):
        path = Path(self.clog)
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
        return [r for r in rows if kind is None or r['kind'] == kind]

    def sandbox_calls(self):
        path = Path(self.sblog)
        return [json.loads(line)['cmd'] for line in path.read_text().splitlines() if line.strip()] if path.exists() else []

    def inference(self):
        """[(profile text, sandbox command)] for every print-mode inference call."""
        return [(Path(self.dump, '%03d.sb' % i).read_text(), cmd)
                for i, cmd in enumerate(self.sandbox_calls()) if '--skip-worktree-setup' in cmd]

    def git_locations(self, task):
        return core.cursor_git_locations(task['worktree'])


class CursorManagedGitTests(CursorManagedBase):
    def test_every_parent_git_call_disables_hooks_fsmonitor_and_system_config(self):
        real, seen = subprocess.Popen, []

        def spy(argv, *args, **kwargs):
            if isinstance(argv, (list, tuple)) and argv and argv[0] == 'git':
                seen.append((list(argv), kwargs))
            return real(argv, *args, **kwargs)
        with patch.object(subprocess, 'Popen', side_effect=spy):
            code, task = self.create()
            self.assertEqual(code, 0, task.get('error'))
            self.assertEqual(self.action(task, 'integrate'), 0)
        self.assertGreater(len(seen), 20)
        subcommands = set()
        for argv, kwargs in seen:
            self.assertEqual(argv[:2], ['git', '-C'], argv)
            self.assertEqual(argv[3:7], ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false'], argv)
            self.assertEqual(kwargs['env']['GIT_CONFIG_NOSYSTEM'], '1', argv)
            self.assertEqual(kwargs['env']['GIT_OPTIONAL_LOCKS'], '0', argv)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL, argv)
            subcommands.add(next(a for a in argv[7:] if not a.startswith('-') and '=' not in a))
        # clean (status), scope (diff, ls-files), worktree, add and commit are all covered ...
        self.assertTrue({'status', 'diff', 'ls-files', 'worktree', 'add', 'commit', 'merge'} <= subcommands, subcommands)
        # ... and so are the tripwire's own Git calls (bin/alloy _git: Git-location resolution)
        self.assertTrue(any('--absolute-git-dir' in argv for argv, _ in seen))

    def test_hooks_fsmonitor_and_system_config_are_ignored_behaviourally(self):
        marker = self.base / 'ran'
        hook = self.repo / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\ntouch %s\nexit 1\n' % marker)
        hook.chmod(0o755)
        e.git(self.repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '--allow-empty', '-qm', 'x')
        self.assertFalse(marker.exists(), 'a repository hook ran in the parent')
        monitor = self.base / 'monitor.sh'
        monitor.write_text('#!/bin/sh\ntouch %s\nprintf "\\0"\n' % marker)
        monitor.chmod(0o755)
        e.git(self.repo, 'config', 'core.fsmonitor', str(monitor))
        e.clean(self.repo)
        self.assertFalse(marker.exists(), 'a command-valued fsmonitor ran in the parent')
        self.assertEqual(e.git(self.repo, 'config', '--get', 'core.hooksPath'), '/dev/null')
        self.assertEqual(e.git(self.repo, 'config', '--get', 'core.fsmonitor'), 'false')
        system = self.base / 'system.cfg'
        system.write_text('[alloy]\n\tprobe = fromsystem\n')
        with patch.dict(os.environ, GIT_CONFIG_SYSTEM=str(system)):
            plain = subprocess.run(['git', '-C', str(self.repo), 'config', '--get', 'alloy.probe'],
                                   capture_output=True, text=True)
            if plain.returncode != 0:
                self.skipTest('this Git ignores GIT_CONFIG_SYSTEM')
            self.assertEqual(e.git(self.repo, 'config', '--get', 'alloy.probe', check=False).returncode, 1)

    def test_repository_aliases_cannot_replace_the_builtin_commands_alloy_runs(self):
        marker = self.base / 'alias-ran'
        for command in ('status', 'diff', 'ls-files', 'add', 'commit', 'worktree', 'rev-parse', 'symbolic-ref',
                        'merge-base', 'update-ref', 'merge'):
            e.git(self.repo, 'config', 'alias.' + command, '!touch ' + str(marker))
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(self.action(task, 'integrate'), 0)
        self.assertFalse(marker.exists(), 'a repository alias replaced a built-in Git command')

    def test_no_git_path_invokes_an_external_diff_or_textconv_helper(self):
        marker = self.base / 'helper-ran'
        helper = self.base / 'helper.sh'
        helper.write_text('#!/bin/sh\ntouch %s\nexit 0\n' % marker)
        helper.chmod(0o755)
        e.git(self.repo, 'config', 'diff.external', str(helper))
        e.git(self.repo, 'config', 'diff.evil.textconv', str(helper))
        (self.repo / '.gitattributes').write_text('*.txt diff=evil\n')
        e.git(self.repo, 'add', '.gitattributes')
        e.git(self.repo, 'commit', '-qm', 'attributes')
        with patch.dict(os.environ, GIT_EXTERNAL_DIFF=str(helper)):
            code, task = self.create()
            self.assertEqual(code, 0, task.get('error'))
            self.assertEqual(self.action(task, 'integrate', squash=True), 0)
        self.assertFalse(marker.exists(), 'an external diff or textconv helper ran')

    def test_git_contract_is_the_same_as_the_bin_alloy_helper(self):
        self.assertEqual(e.git_argv('/x', 'status'), core._git_argv('/x', ('status',)))
        poisoned = {name: 'poison' for name in core._GIT_STRIPPED_ENV}
        with patch.dict(os.environ, dict(poisoned, GIT_CONFIG_NOSYSTEM='0', GIT_OPTIONAL_LOCKS='1')):
            mine, theirs = e.git_env(), core._git_env()
        self.assertFalse(set(core._GIT_STRIPPED_ENV) & set(mine))
        for key in ('GIT_CONFIG_NOSYSTEM', 'GIT_OPTIONAL_LOCKS'):
            self.assertEqual(mine[key], theirs[key])

    def test_git_output_and_runtime_are_bounded(self):
        with patch.object(e, 'GIT_STDOUT_CAP', 10):
            with self.assertRaisesRegex(e.ExecutionError, 'size limit'):
                e.git(self.repo, 'rev-parse', 'HEAD')
        import time
        started = time.monotonic()
        with self.assertRaisesRegex(e.ExecutionError, 'timed out'):
            e.run_git(['git', '-c', 'alias.slow=!sleep 30', 'slow'], timeout=0.3)
        self.assertLess(time.monotonic() - started, 10)
        # An ordinary failure still reports Git's own message and honours check=False.
        with self.assertRaisesRegex(e.ExecutionError, 'Git failed'):
            e.git(self.repo, 'rev-parse', '--verify', 'no-such-ref')
        self.assertNotEqual(e.git(self.repo, 'rev-parse', '--verify', 'no-such-ref', check=False).returncode, 0)


class CursorManagedContractTests(CursorManagedBase):
    def test_permissions_report_the_real_allowlist(self):
        ad = core.ADAPTERS['cursor']
        maker, checker = e.permissions(ad, True), e.permissions(ad, False)
        for perms in (maker, checker):
            self.assertEqual(perms['enforcement'], 'macos_sandbox_exec')
            self.assertTrue(perms['os_isolation'])
            self.assertTrue(perms['git_metadata_isolated'])
            self.assertFalse(perms['approval_bypass'])
            self.assertEqual(perms['scope_validation'], 'content_fingerprint_tripwire')
        self.assertTrue(maker['repository_write'])
        self.assertFalse(checker['repository_write'])
        self.assertEqual(maker['command_execution'], 'allowed_in_worktree')
        self.assertEqual(checker['command_execution'], 'denied')
        self.assertEqual(maker['write_allowlist'], ['owned_worktree_non_git_content', 'private_runtime_state',
                                                    'private_runtime_cache', 'private_runtime_tmp'])
        self.assertEqual(checker['write_allowlist'], ['private_runtime_state', 'private_runtime_cache',
                                                      'private_runtime_tmp'])
        self.assertEqual(maker['cursor_mode'], 'agent_default')
        self.assertEqual(checker['cursor_mode'], 'ask')
        # Other providers keep exactly their previous shape.
        claude = e.permissions(core.ADAPTERS['claude'], True)
        self.assertFalse(claude['os_isolation'])
        self.assertNotIn('write_allowlist', claude)
        self.assertEqual(e.permissions(core.ADAPTERS['codex'], True)['enforcement'], 'codex_workspace_sandbox')
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(task['permissions']['maker'], maker)
        self.assertEqual(task['permissions']['checker'], checker)

    def build(self, decision, write):
        wt = self.linked_worktree('wt-' + ('maker' if write else 'checker'))
        ad = e.worker_adapter(core, decision, write)
        ctx = dict(repo=wt, pdir=str(self.base / ('pdir-m' if write else 'pdir-c')), cwd=wt, timeout_s=10,
                   managed_worktree=write)
        return ad, ad.build_args(str(self.prompt), str(self.base / 'last'), 'make' if write else 'review', ctx), wt

    def test_maker_argv_is_the_closed_non_force_form(self):
        ad, argv, wt = self.build(self.maker, True)
        self.assertNotIn('--mode', argv)
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'enabled')
        for flag in ('--skip-worktree-setup', '--trust', '-p'):
            self.assertEqual(argv.count(flag), 1)
        self.assertEqual(argv[argv.index('--workspace') + 1], wt)
        self.assertEqual(argv[argv.index('--model') + 1], self.maker['effective_model'])
        self.assertEqual(argv[argv.index('--output-format') + 1], 'json')
        self.assertFalse(set(FORBIDDEN_FLAGS) & set(argv))
        self.assertNotIn('Change file.txt', ' '.join(argv))       # only a pointer to the staged file
        self.assertFalse(ad.read_only)
        self.assertTrue(core.ADAPTERS['cursor'].read_only)          # the shared adapter is untouched

    def test_checker_argv_is_ask_mode_and_never_the_maker_form(self):
        ad, argv, wt = self.build(self.checker, False)
        self.assertEqual(argv[argv.index('--mode') + 1], 'ask')
        self.assertEqual(argv.count('--mode'), 1)
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'enabled')
        self.assertIn('--skip-worktree-setup', argv)
        self.assertFalse(set(FORBIDDEN_FLAGS) & set(argv))
        self.assertTrue(ad.read_only)
        self.assertEqual(argv[argv.index('--model') + 1], self.checker['effective_model'])

    def test_role_flag_does_not_change_boundary_readiness_or_bypass_wrapping(self):
        maker = e.worker_adapter(core, self.maker, True)
        checker = e.worker_adapter(core, self.checker, False)
        self.assertFalse(maker.read_only)
        self.assertTrue(checker.read_only)
        self.assertTrue(maker.cursor_boundary_ready)
        self.assertTrue(checker.cursor_boundary_ready)
        with patch.object(core, '_CURSOR_PREFLIGHT', {}), patch.dict(os.environ, MOCK_SANDBOX_PREFLIGHT='write_leak'):
            for ad in (e.worker_adapter(core, self.maker, True), e.worker_adapter(core, self.checker, False)):
                self.assertFalse(ad.cursor_boundary_ready)
                self.assertTrue(ad.requires_os_boundary)

    def run_panelist(self, ad, role, name, wt):
        return core.run_panelist(ad, str(self.prompt), str(self.base / 'runs' / name), 30, 100000,
                                 'make' if role == 'maker' else 'review', repo=wt, managed_worktree=role == 'maker')

    def test_unmodified_maker_and_checker_run_through_the_gateway(self):
        wt = self.linked_worktree()
        self.plan(no_receipt=True)         # the staged prompt here is not a review packet
        for role, decision in (('maker', self.maker), ('checker', self.checker)):
            ad = e.worker_adapter(core, decision, role == 'maker')
            status = self.run_panelist(ad, role, 'control-' + role, wt)
            self.assertEqual(status['status'], 'ok', status.get('error'))
        self.assertEqual(len(self.inference()), 2)

    def assert_refused(self, role, mutate, name):
        wt = self.linked_worktree(name)
        ad = e.worker_adapter(core, self.maker if role == 'maker' else self.checker, role == 'maker')
        build = ad.build_args
        ad.build_args = lambda *a, **k: mutate(list(build(*a, **k)))
        before = len(self.inference())
        status = self.run_panelist(ad, role, name, wt)
        self.assertEqual(status['status'], 'error', name)
        self.assertTrue(str(status['error']).startswith('refused'), (name, status['error']))
        self.assertEqual(len(self.inference()), before, name + ': sandbox-exec must not start')

    def insert(self, *extra):
        return lambda argv: argv[:-1] + list(extra) + argv[-1:]

    def test_argv_injection_after_every_rewrite_is_refused_before_sandbox_exec(self):
        maker_cases = dict(
            yolo=self.insert('--yolo'), force=self.insert('--force'), f=self.insert('-f'),
            auto_review=self.insert('--auto-review'), approve_mcps=self.insert('--approve-mcps'),
            resume=self.insert('--resume', 'abc'), cont=self.insert('--continue'),
            plugin=self.insert('--plugin-dir', 'p'), add_dir=self.insert('--add-dir', 'd'),
            worktree=self.insert('-w'), worktree_long=self.insert('--worktree', 'n'),
            worktree_base=self.insert('--worktree-base', 'main'), plan=self.insert('--plan'),
            mode_ask=self.insert('--mode', 'ask'), mode_plan=self.insert('--mode', 'plan'),
            sandbox_duplicate=self.insert('--sandbox', 'enabled'), model_duplicate=self.insert('--model', 'composer-2.5'),
            endpoint=self.insert('--endpoint', 'https://x.invalid'), endpoint_eq=self.insert('--endpoint=https://x.invalid'),
            attached_e=self.insert('-ehttps://x.invalid'), header=self.insert('--header', 'X: y'),
            attached_h=self.insert('-HX:y'), api_key=self.insert('--api-key', 'k'),
            sandbox_disabled=lambda a: [('disabled' if a[i - 1] == '--sandbox' else x) for i, x in enumerate(a)],
            no_sandbox=lambda a: [x for i, x in enumerate(a) if x != '--sandbox' and a[i - 1] != '--sandbox'],
            no_setup_skip=lambda a: [x for x in a if x != '--skip-worktree-setup'],
            subcommand=lambda a: ['worker'] + a, extra_positional=lambda a: a + ['also do this'])
        for name, mutate in maker_cases.items():
            with self.subTest(role='maker', case=name):
                self.assert_refused('maker', mutate, 'maker-' + name)
        checker_cases = dict(
            drop_mode=lambda a: [x for i, x in enumerate(a) if x != '--mode' and a[i - 1] != '--mode'],
            plan_mode=lambda a: [('plan' if a[i - 1] == '--mode' else x) for i, x in enumerate(a)],
            duplicate_mode=self.insert('--mode', 'ask'), yolo=self.insert('--yolo'), force=self.insert('--force'),
            plugin=self.insert('--plugin-dir', 'p'), worktree=self.insert('--worktree', 'n'),
            resume=self.insert('--resume', 'abc'), sandbox_disabled=lambda a: [
                ('disabled' if a[i - 1] == '--sandbox' else x) for i, x in enumerate(a)],
            subcommand=lambda a: ['persist'] + a, header=self.insert('-H', 'X: y'))
        for name, mutate in checker_cases.items():
            with self.subTest(role='checker', case=name):
                self.assert_refused('checker', mutate, 'checker-' + name)

    def test_injection_in_dispatch_is_refused_before_the_process_starts(self):
        _, task = self.create()          # a real, retained worktree (the provider call is stubbed)
        real_worker = e.worker_adapter
        cases = dict(
            maker_yolo=('maker', self.insert('--yolo')), maker_resume=('maker', self.insert('--resume', 'x')),
            maker_mode=('maker', self.insert('--mode', 'ask')), maker_worktree=('maker', self.insert('-w')),
            checker_no_mode=('checker', lambda a: [x for i, x in enumerate(a) if x != '--mode' and a[i - 1] != '--mode']),
            checker_plugin=('checker', self.insert('--plugin-dir', 'p')),
            checker_force=('checker', self.insert('-f')))
        for name, (role, mutate) in cases.items():
            with self.subTest(case=name):
                def wrapper(core_, decision, write=False, mutate=mutate):
                    ad = real_worker(core_, decision, write)
                    build = ad.build_args
                    ad.build_args = lambda *a, **k: mutate(list(build(*a, **k)))
                    return ad
                before = len(self.inference())
                with patch.object(e, 'worker_adapter', side_effect=wrapper):
                    result = REAL_DISPATCH(core, task, role, 'prompt', e.taskdir(core, task['id']) / ('inj-' + name))
                self.assertEqual(result['status'], 'error')
                self.assertTrue(str(result['error']).startswith('refused'), result['error'])
                self.assertEqual(len(self.inference()), before)

    def test_unknown_provider_never_inherits_another_providers_maker_permissions(self):
        with self.assertRaisesRegex(e.ExecutionError, 'No managed write adapter'):
            e.worker_adapter(core, dict(cli='llm', model='x', effort=None), True)
        # A member of the writer list without its own branch reaches the final `else`.
        with patch.object(e, 'MANAGED_WRITERS', e.MANAGED_WRITERS + ('llm',)):
            ad = e.worker_adapter(core, dict(cli='llm', model='x', effort=None), True)
            with self.assertRaisesRegex(e.ExecutionError, 'No managed write adapter'):
                ad.build_args(str(self.prompt), str(self.base / 'last'), 'make', {})

    def test_cursor_sessions_are_fresh_context_and_never_resumed(self):
        def forbidden(*a, **k):
            raise AssertionError('worker_session must not spawn the Cursor CLI: %r' % (a,))
        task = dict(maker=self.maker, checker=self.checker)
        with patch.object(subprocess, 'run', side_effect=forbidden), patch.object(subprocess, 'Popen', side_effect=forbidden):
            for role in ('maker', 'checker'):
                session = e.worker_session(core, task, role)
                self.assertEqual((session['supported'], session['mode']), (False, 'fresh_context_fallback'))
            # an edited or stale record cannot turn resume on
            task['sessions']['maker'] = dict(id='12345678-1234-1234-1234-123456789abc', supported=True,
                                             started=True, mode='native')
            session = e.worker_session(core, task, 'maker')
            self.assertEqual((session['supported'], session['mode']), (False, 'fresh_context_fallback'))

    def test_probe_requires_the_boundary_and_every_help_flag_through_the_gateway(self):
        REAL_PROBE(core, self.maker, True)
        REAL_PROBE(core, self.checker, False)
        self.assertTrue(self.cursor_calls('help'))
        self.assertTrue(any('--help' in cmd for cmd in self.sandbox_calls()))      # only via sandbox-exec
        for flag in e.CURSOR_MAKER_FLAGS:
            with self.subTest(flag=flag):
                self.plan(help=HELP_ALL.replace(flag, ''))
                for decision, write in ((self.maker, True), (self.checker, False)):
                    with self.assertRaisesRegex(e.ExecutionError, 'compatibility check failed'):
                        REAL_PROBE(core, decision, write)
        # `--mode` is not satisfied by `--model`; only the Checker needs it
        self.plan(help=HELP_ALL.replace('--mode ', ''))
        REAL_PROBE(core, self.maker, True)
        with self.assertRaisesRegex(e.ExecutionError, 'compatibility check failed'):
            REAL_PROBE(core, self.checker, False)
        self.plan(help=HELP_ALL, help_exit=2)
        with self.assertRaisesRegex(e.ExecutionError, 'compatibility check failed'):
            REAL_PROBE(core, self.maker, True)

    def test_probe_accepts_the_recorded_real_help_text(self):
        facts = (ROOT / 'docs/design/cursor/CURSOR-FACTS.md').read_text()
        self.plan(help=facts[facts.index('## --help'):facts.index('## --list-models')])
        REAL_PROBE(core, self.maker, True)
        REAL_PROBE(core, self.checker, False)

    def test_dispatch_rederives_the_decision_and_scrubs_the_checker_prompt(self):
        _, task = self.create()
        folder = e.taskdir(core, task['id'])
        before = len(self.inference())
        for label, changes in (('auto', dict(model='auto', effective_model='auto')),
                               ('unknown', dict(model='kimi-k3', effective_model='kimi-k3', family='cursor')),
                               ('relabelled', dict(family='openai')), ('fast', dict(cursor_fast=True))):
            with self.subTest(label):
                tampered = dict(task, checker=dict(task['checker'], **changes))
                with self.assertRaises((e.ExecutionError, core.routing.RoutingError)):
                    REAL_DISPATCH(core, tampered, 'checker', 'prompt', folder / ('bad-' + label))
        self.assertEqual(len(self.inference()), before)
        # Anything recognisable in the Checker prompt is scrubbed before it is saved or staged,
        # even outside the packet (a second line of defence after review_packet).
        self.plan(no_receipt=True)
        for kind, (text, value) in SECRETS.items():
            with self.subTest(kind=kind):
                result = REAL_DISPATCH(core, task, 'checker', 'Review this. ' + text, folder / ('scrub-' + kind))
                self.assertEqual(result['status'], 'ok', result.get('error'))
                for path in ('prompt.txt', 'prompt_in/prompt.md'):
                    body = (folder / ('scrub-' + kind) / path).read_text()
                    self.assertNotIn(value, body)
                    self.assertIn('[REDACTED', body)
        # the Maker prompt is the task itself and is not rewritten
        result = REAL_DISPATCH(core, task, 'maker', 'Task: ' + SECRETS['jwt'][0], folder / 'maker-unscrubbed')
        self.assertIn(GOOD_JWT, (folder / 'maker-unscrubbed' / 'prompt.txt').read_text())

    def test_a_boundary_error_raised_inside_a_run_is_needs_attention_not_interrupted(self):
        self.patch_e('dispatch', side_effect=core.CursorBoundaryError('uncertain path'))
        code, task = self.create()
        self.assertEqual(code, 3)
        self.assertEqual(task['state'], 'needs_attention')
        self.assertIn('uncertain path', task['error'])

    def test_probe_refuses_both_roles_without_a_validated_boundary(self):
        for env in ({}, {'ALLOY_ALLOW_UNSANDBOXED': '1'}):
            with patch.object(core, '_CURSOR_PREFLIGHT', {}), patch.dict(os.environ, dict(env, MOCK_SANDBOX_PREFLIGHT='write_leak')):
                core.ADAPTERS['cursor'].__dict__.pop('_auth_cache', None)
                for decision, write in ((self.maker, True), (self.checker, False)):
                    with self.assertRaisesRegex(e.ExecutionError, 'sandbox unavailable.*Cursor roles are refused'):
                        REAL_PROBE(core, decision, write)
                self.assertEqual(self.cursor_calls(), [])                       # no CLI call of any kind
        with patch.object(core, 'CURSOR_PLATFORM', 'no-such-platform'), patch.object(core, '_CURSOR_PREFLIGHT', {}):
            with self.assertRaisesRegex(e.ExecutionError, 'Cursor roles are refused'):
                REAL_PROBE(core, self.maker, True)


class CursorManagedTamperTests(CursorManagedBase):
    """The provider call is stubbed (fake_dispatch edits the worktree directly), so these
    prove the managed run's OWN content/Git-internals verification, independent of the runner."""

    def write(self, task, name, text, append=False):
        with open(Path(task['worktree']) / name, 'a' if append else 'w') as f:
            f.write(text)

    def git_tamper(self, base, rel):
        def tamper(task):
            loc = self.git_locations(task)
            path = Path(loc[base]) / rel if base != 'pointer' else Path(loc['dotgit'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a') as f:
                f.write('\n# tampered\n')
        return tamper

    # -- Maker: scope over tracked, untracked AND ignored paths ---------------------- #
    def test_maker_ignored_file_outside_scope_fails_before_gates_and_review(self):
        self.maker_hook = lambda task: self.write(task, 'ignored.txt', 'scratch')
        code, task = self.create()
        self.assertEqual(code, 3)
        self.assertEqual(task['state'], 'needs_attention')
        self.assertIn('outside allowed', task['error'])
        self.assertIn('ignored.txt', task['error'])
        self.assertEqual([c[0] for c in self.calls], ['maker'])
        self.assertNotIn('gates', task['rounds'][0])
        self.assertTrue(Path(task['worktree']).exists())            # retained for inspection

    def test_maker_ignored_file_and_directory_inside_scope_are_allowed(self):
        self.args.allow_path = ['file.txt', 'ignored.txt', 'ignored-dir', 'src/new.txt']

        def hook(task):
            self.write(task, 'ignored.txt', 'scratch')
            os.makedirs(Path(task['worktree']) / 'ignored-dir/deep')
            self.write(task, 'ignored-dir/deep/x.txt', 'x')
            os.makedirs(Path(task['worktree']) / 'src')             # `src` is an ancestor of an allowed path
            self.write(task, 'src/new.txt', 'n')
        self.maker_hook = hook
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))

    def test_maker_unrelated_new_directory_or_symlink_or_mode_change_fails(self):
        cases = dict(
            empty_directory=lambda task: os.makedirs(Path(task['worktree']) / 'emptydir'),
            ignored_directory=lambda task: os.makedirs(Path(task['worktree']) / 'ignored-dir'),
            symlink=lambda task: os.symlink('/etc/passwd', Path(task['worktree']) / 'link'),
            mode_change=lambda task: os.chmod(Path(task['worktree']) / '.gitignore', 0o755))
        for name, hook in cases.items():
            with self.subTest(case=name):
                self.reset()
                self.maker_hook = hook
                code, task = self.create()
                self.assertEqual(code, 3)
                self.assertIn('outside allowed', task['error'])
                self.assertEqual([c[0] for c in self.calls], ['maker'])

    def test_maker_git_internals_change_fails_before_gates_and_review(self):
        cases = [('gitdir', 'commondir'), ('gitdir', 'info/attributes'), ('gitdir', 'info/sparse-checkout'),
                 ('gitdir', 'info/exclude'), ('gitdir', 'config.worktree'), ('gitdir', 'HEAD'),
                 ('common', 'info/attributes'), ('common', 'config'), ('common', 'hooks/post-checkout'),
                 ('common', 'packed-refs'), ('common', 'refs/heads/planted'), ('pointer', '.git')]
        for base, rel in cases:
            with self.subTest(base=base, rel=rel):
                self.reset()
                self.maker_hook = self.git_tamper(base, rel)
                code, task = self.create()
                self.assertEqual(code, 3)
                self.assertEqual(task['state'], 'needs_attention')
                self.assertRegex(task['error'], 'protected Git internals|uncertain')
                self.assertEqual([c[0] for c in self.calls], ['maker'])
                self.assertNotIn('gates', task['rounds'][0])
        # the ordinary (layout-preserving) cases are named precisely, not just "uncertain"
        self.reset()
        self.maker_hook = self.git_tamper('common', 'hooks/post-checkout')
        self.assertIn('protected Git internals', self.create()[1]['error'])

    def test_every_protected_git_internal_class_is_detected_for_both_roles(self):
        """Direct, per-case check of the two verifiers against every entry the fingerprint
        covers in BOTH Git locations, so the list cannot drift from bin/alloy's own constants."""
        rels = list(core._GIT_FILES) + [t + '/planted' for t in core._GIT_TREES]
        cases = [(base, rel) for base in ('gitdir', 'common') for rel in rels] + [('pointer', '.git')]
        self.assertGreaterEqual(len(cases), 21)

        def fresh():
            self.reset()
            shutil.rmtree(self.base / 'wt', True)
            wt = self.linked_worktree('wt')
            return dict(worktree=wt, allow_paths=['file.txt'])
        task = fresh()
        before = e.tripwire_manifest(core, task)
        e.verify_cursor_maker(core, task, {}, before)                        # controls: nothing changed
        e.verify_cursor_checker(core, task, {}, before)
        for base, rel in cases:
            for role, verify in (('maker', e.verify_cursor_maker), ('checker', e.verify_cursor_checker)):
                with self.subTest(base=base, rel=rel, role=role):
                    task = fresh()
                    before = e.tripwire_manifest(core, task)
                    self.git_tamper(base, rel)(task)
                    with self.assertRaisesRegex(e.ExecutionError, 'protected Git internals|Checker changed|uncertain'):
                        verify(core, task, {}, before)

    def test_maker_reported_canary_git_or_out_of_scope_changes_fail_even_with_status_ok(self):
        cases = [(dict(canary_changes=['out/canary.txt']), 'sandbox canary'),
                 (dict(workspace_changes=['git:gitdir:HEAD']), 'protected Git internals'),
                 (dict(changed_paths=['elsewhere.txt']), 'outside allowed')]
        for extra, message in cases:
            with self.subTest(extra=extra):
                self.reset()
                self.maker_extra = extra
                code, task = self.create()
                self.assertEqual(code, 3)
                self.assertIn(message, task['error'])
                self.assertEqual([c[0] for c in self.calls], ['maker'])

    def test_maker_edit_inside_scope_passes_and_only_cursor_workers_are_fingerprinted(self):
        with patch.object(core, 'cursor_fingerprint', wraps=core.cursor_fingerprint) as fingerprint:
            code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(fingerprint.call_count, 4)                  # Maker before/after, Checker before/after
        # A non-Cursor pair keeps its previous behaviour: no fingerprint, ignored files unchecked.
        self.reset()
        self.select.return_value = (dict(cli='claude', family='anthropic', model='sonnet', effort=None, profile='m'),
                                    dict(cli='grok', family='xai', model='grok-4.6', effort=None, profile='c'))
        self.maker_hook = lambda task: self.write(task, 'ignored.txt', 'scratch')
        with patch.object(core, 'cursor_fingerprint', wraps=core.cursor_fingerprint) as fingerprint:
            code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        fingerprint.assert_not_called()

    # -- Checker: nothing may change --------------------------------------------------- #
    def test_checker_same_size_ignored_file_edit_fails_before_review(self):
        self.args.allow_path = ['file.txt', 'ignored.txt']
        self.maker_hook = lambda task: self.write(task, 'ignored.txt', 'aaaa')
        self.checker_hook = lambda task: self.write(task, 'ignored.txt', 'bbbb')   # same name, same length
        code, task = self.create()
        self.assertEqual(code, 3)
        self.assertIn('Checker changed', task['error'])
        self.assertNotIn('review', task['rounds'][0])
        self.assertEqual(e.git(task['worktree'], 'status', '--porcelain'), '')     # status alone cannot see it

    def test_checker_any_worktree_change_or_commit_fails(self):
        cases = dict(
            tracked=lambda task: self.write(task, 'file.txt', 'tampered\n'),
            untracked=lambda task: self.write(task, 'untracked.txt', 'x'),
            new_ignored=lambda task: self.write(task, 'ignored.txt', 'x'),
            commit=lambda task: e.git(task['worktree'], '-c', 'user.name=x', '-c', 'user.email=x@example.invalid',
                                      'commit', '--allow-empty', '-qm', 'sneaky'))
        for name, hook in cases.items():
            with self.subTest(case=name):
                self.reset()
                self.checker_hook = hook
                code, task = self.create()
                self.assertEqual(code, 3)
                self.assertIn('Checker changed', task['error'])
                self.assertNotIn('review', task['rounds'][0])

    def test_checker_git_internals_change_fails_before_review(self):
        cases = [('gitdir', 'commondir'), ('gitdir', 'info/attributes'), ('gitdir', 'info/sparse-checkout'),
                 ('gitdir', 'config.worktree'), ('common', 'info/attributes'), ('common', 'config'),
                 ('common', 'hooks/pre-commit'), ('common', 'refs/heads/planted'), ('common', 'packed-refs'),
                 ('gitdir', 'HEAD'), ('pointer', '.git')]
        for base, rel in cases:
            with self.subTest(base=base, rel=rel):
                self.reset()
                self.checker_hook = self.git_tamper(base, rel)
                code, task = self.create()
                self.assertEqual(code, 3)
                self.assertRegex(task['error'], 'Checker changed|uncertain')
                self.assertNotIn('review', task['rounds'][0])
        self.reset()
        self.checker_hook = self.git_tamper('gitdir', 'info/attributes')
        self.assertIn('Checker changed worktree', self.create()[1]['error'])

    def test_checker_reported_canary_or_workspace_change_fails_even_with_status_ok(self):
        for extra, message in ((dict(canary_changes=['out/canary.txt']), 'protected canary'),
                               (dict(workspace_changes=['tree:ignored.txt']), 'Checker changed worktree')):
            with self.subTest(extra=extra):
                self.reset()
                self.checker_extra = extra
                code, task = self.create()
                self.assertEqual(code, 3)
                self.assertIn(message, task['error'])
                self.assertNotIn('review', task['rounds'][0])

    def test_cursor_checker_receipt_and_verdict_checks_still_fail_closed(self):
        original = self.fake_dispatch

        def missing(core_, task, role, prompt, folder):
            result = original(core_, task, role, prompt, folder)
            if role == 'checker':
                Path(result['result_path']).write_text(json.dumps(dict(verdict='pass', findings=[])))
            return result
        self.patch_e('dispatch', side_effect=missing)
        code, task = self.create()
        self.assertEqual(code, 3)
        self.assertIn('context receipt', task['error'])
        self.assertTrue(Path(task['worktree']).exists())

    def test_checker_failed_status_is_not_a_pass_and_names_the_reason(self):
        def failed(core_, task, role, prompt, folder):
            result = self.fake_dispatch(core_, task, role, prompt, folder)
            if role == 'checker':
                result['status'] = 'error'
                result['error'] = 'refused: no supported boundary'
            return result
        self.patch_e('dispatch', side_effect=failed)
        code, task = self.create()
        self.assertEqual(code, 3)
        self.assertIn('Checker failed; no pass inferred', task['error'])
        self.assertIn('refused: no supported boundary', task['error'])

    # -- uncertainty fails closed as needs_attention, never as an interrupted task ------- #
    def test_a_task_that_failed_a_tamper_check_is_never_resumed_in_place(self):
        # The check is delta-based: resuming would take the planted state as its baseline.
        hooks = dict(maker=lambda task: self.write(task, 'ignored.txt', 'scratch'),
                     checker=self.git_tamper('gitdir', 'info/attributes'))
        for role, hook in hooks.items():
            with self.subTest(role=role):
                self.reset()
                self.maker_hook = hook if role == 'maker' else None
                self.checker_hook = hook if role == 'checker' else None
                code, task = self.create()
                self.assertEqual(code, 3)
                self.assertTrue(task['tripwire'])
                self.maker_hook = self.checker_hook = None
                before = len(self.calls)
                self.assertEqual(self.action(task, 'resume'), 3)
                task = e.load(core, task['id'])
                self.assertEqual(task['state'], 'needs_attention')
                self.assertIn('tamper check failed', task['error'])
                self.assertEqual(len(self.calls), before)              # nothing was dispatched
                self.assertTrue(Path(task['worktree']).exists())
                with self.assertRaises(e.ExecutionError):
                    self.action(task, 'cleanup')

    def test_fingerprint_uncertainty_fails_closed_before_dispatch_and_before_acceptance(self):
        real = core.cursor_fingerprint
        for fail_at, expected_calls in ((1, []), (2, ['maker']), (3, ['maker']), (4, ['maker', 'checker'])):
            with self.subTest(fail_at=fail_at):
                counter = []

                def uncertain(path, *a, **k):
                    counter.append(path)
                    if len(counter) == fail_at:
                        raise core.CursorBoundaryError('fingerprint refused: cannot read a file')
                    return real(path, *a, **k)
                self.reset()
                with patch.object(core, 'cursor_fingerprint', side_effect=uncertain):
                    code, task = self.create()
                self.assertEqual(code, 3)
                self.assertEqual(task['state'], 'needs_attention')       # not `interrupted`
                self.assertIn('uncertain', task['error'])
                self.assertEqual([c[0] for c in self.calls], expected_calls)
                self.assertNotIn('review', task['rounds'][0])
                self.assertTrue(Path(task['worktree']).exists())


class CursorManagedPacketTests(CursorManagedBase):
    def packet(self, task, index, spec='goal', diff='diff', gate_text='ok', command='true'):
        log = self.base / ('gate-%d.log' % index)
        log.write_text(gate_text)                     # a raw log: gate() itself would have scrubbed it
        record = dict(index=index, gates=[dict(command=command, exit_code=0, log=str(log))])
        encoded, packet_id = e.review_packet(core, task, record, task['tip'], diff, spec)
        saved = (e.taskdir(core, task['id']) / ('review-%d.json' % index)).read_text()
        return encoded, saved, packet_id, record

    def test_secrets_in_any_packet_source_never_reach_the_saved_packet(self):
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        index = 10
        for kind, (text, value) in SECRETS.items():
            for source in ('spec', 'diff', 'gate_output', 'gate_command'):
                with self.subTest(kind=kind, source=source):
                    index += 1
                    kw = {'spec': dict(spec='fix it: ' + text), 'diff': dict(diff='+ ' + text + '\n'),
                          'gate_output': dict(gate_text='running\n' + text + '\n'),
                          'gate_command': dict(command='echo ' + text)}[source]
                    encoded, saved, packet_id, record = self.packet(task, index, **kw)
                    self.assertNotIn(value, encoded)
                    self.assertNotIn(value, saved)
                    self.assertIn('[REDACTED', encoded)
                    self.assertEqual(json.loads(encoded), json.loads(saved))     # what is sent is what is saved
                    self.assertEqual(packet_id, __import__('hashlib').sha256(encoded.encode()).hexdigest())
                    self.assertEqual(record['packet']['id'], packet_id)
        # a packet with nothing to hide is unchanged apart from carrying the same fields
        encoded, saved, packet_id, _ = self.packet(task, 99, spec='plain goal', diff='+ plain\n')
        self.assertNotIn('REDACTED', encoded)
        self.assertEqual(set(json.loads(encoded)), {'goal', 'base', 'revision', 'changed_files', 'diff', 'tests',
                                                    'allowed_paths', 'dependencies'})

    def test_secrets_in_spec_and_diff_never_reach_the_checker_prompt_or_saved_packet(self):
        for kind, (text, value) in SECRETS.items():
            with self.subTest(kind=kind):
                self.prompt.write_text('Change file.txt to new. ' + text)
                self.maker_hook = lambda task, text=text: (Path(task['worktree']) / 'file.txt').write_text('new ' + text + '\n')
                self.calls.clear()
                code, task = self.create()
                self.assertEqual(code, 0, task.get('error'))
                checker_prompt = self.calls[1][1]
                saved = (e.taskdir(core, task['id']) / 'review-0.json').read_text()
                self.assertNotIn(value, checker_prompt)
                self.assertNotIn(value, saved)
                self.assertIn('[REDACTED', checker_prompt)
                # the receipt still works: the id is the hash of what was actually sent
                self.assertEqual(task['rounds'][0]['packet']['id'],
                                 __import__('hashlib').sha256(json.dumps(json.loads(saved), sort_keys=True).encode()).hexdigest())

    def test_a_packet_that_cannot_be_redacted_safely_is_never_sent(self):
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        real = core.redact_secrets
        with patch.object(core, 'redact_secrets', side_effect=lambda t: ('{"broken', 1) if t.startswith('{') else real(t)):
            with self.assertRaisesRegex(e.ExecutionError, 'redacted safely'):
                self.packet(task, 5)
        self.assertFalse((e.taskdir(core, task['id']) / 'review-5.json').exists())


class CursorManagedSelectionTests(CursorManagedBase):
    def setUp(self):
        super().setUp()
        r = self.r = core.routing
        config = r.enable_cursor(core, r.starter(core))
        self.codex = next(p for p in config['profiles'] if p['adapter'] == 'codex')
        self.codex['enabled'] = True
        r.save(r.root() / 'routing.json', config)
        self.config = config
        self.available = {n: dict(status='ready', compatible=True) for n in r.FAMILIES}
        patcher = patch.object(r, 'inventory', return_value=self.available)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.args.host_family = 'openai'

    def choose(self, maker, checker, host='openai'):
        self.args.maker_profile, self.args.checker_profile, self.args.host_family = maker, checker, host
        return REAL_SELECT(core, self.args, 'Task')

    COMPOSER = 'cursor-large-composer-2-5'
    GPT = 'cursor-large-gpt-5-6-sol'
    CLAUDE = 'cursor-large-claude-opus-5-5'
    GEMINI = 'cursor-medium-gemini-3-8-flash'
    GROK = 'cursor-large-grok-4-7'

    def test_cursor_served_models_take_the_family_of_their_model(self):
        maker, checker = self.choose(self.COMPOSER, self.CLAUDE, host='openai')
        self.assertEqual((maker['family'], checker['family']), ('cursor', 'anthropic'))
        self.assertEqual((maker['cli'], checker['cli']), ('cursor', 'cursor'))
        self.assertEqual(checker['effective_model'], 'claude-opus-5-5[effort=high,fast=false]')

    def test_composer_is_independent_of_every_native_family(self):
        for host, checker in (('openai', self.CLAUDE), ('anthropic', self.GPT), ('google', self.CLAUDE),
                              ('xai', self.GPT)):
            with self.subTest(host=host):
                maker, checked = self.choose(self.COMPOSER, checker, host=host)
                self.assertEqual(maker['family'], 'cursor')
                self.assertNotIn(checked['family'], (host, 'cursor'))
        with self.assertRaises(self.r.RoutingError):                # Composer is its own family: a Composer host
            self.choose(self.COMPOSER, self.CLAUDE, host='cursor')

    def test_an_anthropic_host_never_gets_cursor_claude_as_maker_or_checker(self):
        with self.assertRaises(self.r.RoutingError):
            self.choose(self.CLAUDE, self.GPT, host='anthropic')
        with self.assertRaises(self.r.RoutingError):
            self.choose(self.COMPOSER, self.CLAUDE, host='anthropic')
        maker, checker = self.choose(self.COMPOSER, self.GPT, host='anthropic')      # the control
        self.assertEqual((maker['family'], checker['family']), ('cursor', 'openai'))

    def test_an_openai_maker_never_gets_cursor_gpt_as_checker(self):
        with self.assertRaises(self.r.RoutingError):
            self.choose(self.codex['id'], self.GPT, host='google')
        maker, checker = self.choose(self.codex['id'], self.CLAUDE, host='google')   # the control
        self.assertEqual((maker['family'], checker['family']), ('openai', 'anthropic'))
        # the same holds for every family a Cursor profile can serve: a Checker of the Maker's family is refused
        for profile in (self.GPT, self.CLAUDE, self.GEMINI, self.GROK):
            with self.subTest(profile=profile):
                with self.assertRaises(self.r.RoutingError):
                    self.choose(profile, profile, host='cursor')

    def test_select_rederives_and_refuses_relabelled_or_unroutable_decisions(self):
        good = self.decision('composer-2.5', 'a')
        self.assertEqual(e.check_decision(core, good), 'cursor')
        bad = {
            'auto': dict(good, model='auto', effective_model='auto', family='cursor'),
            'unknown prefix': dict(good, model='kimi-k3', effective_model='kimi-k3', family='cursor'),
            'relabelled': dict(good, family='anthropic'),
            'gpt as cursor': dict(good, model='gpt-5.6-sol-high', effective_model='gpt-5.6-sol[effort=high,fast=false]',
                                  family='cursor', effort='high'),
            'fast without opt-in': dict(good, effective_model='composer-2.5[fast=true]'),
            'denormalised': dict(good, effective_model='composer-2.5'),
            'non-cursor adapter claims cursor': dict(cli='codex', family='cursor', model='gpt-5.6-sol')}
        for label, decision in bad.items():
            with self.subTest(label):
                with self.assertRaises(e.ExecutionError):
                    e.check_decision(core, decision)
        self.assertEqual(e.check_decision(core, dict(cli='codex', family='openai', model='gpt-5.6-sol')), 'openai')

    def test_select_uses_the_rederived_family_for_the_independence_check(self):
        # A resolved decision that lies about its family (as an edited record could) is refused.
        liar = dict(self.decision('claude-opus-5-5-high', 'x'), family='openai')
        with patch.object(core.routing, 'resolve', side_effect=lambda *a, **k: dict(liar)):
            with self.assertRaisesRegex(e.ExecutionError, 'family'):
                self.choose(self.CLAUDE, self.GPT, host='google')

    def test_pins_are_rederived_and_cannot_relabel_a_role(self):
        for key in ('ALLOY_CURSOR_MODEL', 'ALLOY_CURSOR_AGENT_MODEL'):
            with self.subTest(key=key):
                with patch.dict(os.environ, {key: 'claude-opus-5-5-high'}):
                    with self.assertRaises(self.r.RoutingError):
                        self.choose(self.COMPOSER, self.GPT, host='anthropic')
                # A Cursor pin applies to every Cursor profile, so the control pairs the matching
                # Composer Maker with a non-Cursor Checker: a matching pin is not a change.
                with patch.dict(os.environ, {key: 'composer-2.5'}):
                    maker, checker = self.choose(self.COMPOSER, self.codex['id'], host='anthropic')
                    self.assertEqual((maker['family'], checker['family']), ('cursor', 'openai'))

    def revalidation_task(self):
        maker, checker = self.choose(self.COMPOSER, self.CLAUDE, host='openai')
        return dict(maker=maker, checker=checker, host_family='openai', max_estimated_usd=None)

    def test_revalidation_covers_the_effective_model_and_fast_state(self):
        task = self.revalidation_task()
        REAL_REVALIDATE(core, task, 'maker')
        REAL_REVALIDATE(core, task, 'checker')
        # an edited stored decision is re-derived and refused
        for label, changes in (('effective model', dict(effective_model='composer-2.5[effort=max,fast=false]')),
                               ('fast flag', dict(cursor_fast=True)), ('family', dict(family='anthropic')),
                               ('auto', dict(effective_model='auto'))):
            with self.subTest(label):
                tampered = dict(task, maker=dict(task['maker'], **changes))
                with self.assertRaises(e.ExecutionError):
                    REAL_REVALIDATE(core, tampered, 'maker')
        # a changed profile (fast opt-in) or effort pin changes the effective model: start a new task
        profile = next(p for p in self.config['profiles'] if p['id'] == self.COMPOSER)
        profile['cursor_fast'] = True
        self.r.save(self.r.root() / 'routing.json', self.config)
        with self.assertRaisesRegex(e.ExecutionError, 'changed'):
            REAL_REVALIDATE(core, task, 'maker')
        profile['cursor_fast'] = False
        self.r.save(self.r.root() / 'routing.json', self.config)
        REAL_REVALIDATE(core, task, 'maker')
        for key in ('ALLOY_CURSOR_EFFORT', 'ALLOY_CURSOR_AGENT_EFFORT'):
            with patch.dict(os.environ, {key: 'max'}):
                with self.assertRaisesRegex(e.ExecutionError, 'changed'):
                    REAL_REVALIDATE(core, task, 'maker')
        for key in ('ALLOY_CURSOR_MODEL', 'ALLOY_CURSOR_AGENT_MODEL'):
            with patch.dict(os.environ, {key: 'claude-opus-5-5-high'}):
                with self.assertRaises(self.r.RoutingError):
                    REAL_REVALIDATE(core, task, 'maker')

    def test_revalidation_and_readiness_rederive_even_when_routing_agrees_with_a_bad_record(self):
        liar = dict(self.decision('claude-opus-5-5-high', 'x'), family='openai', answers=None)
        task = dict(maker=dict(liar), checker=dict(liar), host_family='google', max_estimated_usd=None)
        with patch.object(core.routing, 'resolve', side_effect=lambda *a, **k: dict(liar)):
            for role in ('maker', 'checker'):
                with self.assertRaisesRegex(e.ExecutionError, 'family'):        # stored == fresh, both wrong
                    REAL_REVALIDATE(core, task, role)
            self.args.maker_profile = self.args.checker_profile = self.CLAUDE
            self.args.check, self.args.host_family, self.args.max_estimated_usd = False, 'google', None
            report = REAL_READINESS(core, self.args, str(self.repo))
        self.assertFalse(report['ready'])
        self.assertTrue(any('family' in b for b in report['blockers']), report['blockers'])

    def test_older_task_records_without_cursor_fields_still_revalidate(self):
        maker, checker = self.choose(self.codex['id'], self.CLAUDE, host='google')
        task = dict(maker=dict(maker), checker=dict(checker), host_family='google', max_estimated_usd=None)
        for role in ('maker', 'checker'):
            for key in ('effective_model', 'cursor_fast'):
                task[role].pop(key, None)            # a record written before these fields existed
        REAL_REVALIDATE(core, task, 'maker')

    def test_real_select_probes_both_cursor_roles_through_the_gateway(self):
        self.patch_e('probe', side_effect=REAL_PROBE)
        maker, checker = self.choose(self.COMPOSER, self.CLAUDE, host='openai')
        self.assertEqual(len(self.cursor_calls('help')), 2)
        self.plan(help=HELP_ALL.replace('--skip-worktree-setup', ''))
        with self.assertRaisesRegex(e.ExecutionError, 'compatibility check failed'):
            self.choose(self.COMPOSER, self.CLAUDE, host='openai')

    def test_readiness_refuses_a_cursor_role_without_a_boundary_and_names_the_reason(self):
        self.patch_e('readiness', side_effect=REAL_READINESS)
        self.patch_e('probe', side_effect=REAL_PROBE)
        self.args.host_family, self.args.check = 'openai', False
        self.args.maker_profile, self.args.checker_profile = self.COMPOSER, self.CLAUDE
        report = REAL_READINESS(core, self.args, str(self.repo))
        self.assertTrue(report['ready'], report['blockers'])
        with patch.object(core, '_CURSOR_PREFLIGHT', {}), patch.dict(
                os.environ, MOCK_SANDBOX_PREFLIGHT='write_leak', ALLOY_ALLOW_UNSANDBOXED='1'):
            core.ADAPTERS['cursor'].__dict__.pop('_auth_cache', None)
            report = REAL_READINESS(core, self.args, str(self.repo))
        self.assertFalse(report['ready'])
        for role in ('maker', 'checker'):
            self.assertTrue(any(b.startswith(role + ':') and 'Cursor roles are refused' in b
                                for b in report['blockers']), report['blockers'])


class CursorManagedEndToEndTests(CursorManagedBase):
    """The real dispatch, runner, spawn gateway and tripwires, behind the mock sandbox-exec and
    the fake cursor-agent: a complete managed task with a Cursor Maker and a Cursor Checker."""

    def setUp(self):
        super().setUp()
        self.real_dispatch()
        self.plan(maker_writes=[dict(path='file.txt', text='new\n')])

    def home(self):
        return core.cursor_login_home()

    def writes(self, profile, path):
        return MOCKMOD.sbpl_decision(profile, 'file-write-create', path)

    def test_full_cursor_execute_integrate_and_cleanup(self):
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(task['state'], 'ready')
        self.assertEqual((self.repo / 'file.txt').read_text(), 'old\n')      # the source checkout is untouched
        record = task['rounds'][0]
        maker, checker = record['maker'], record['checker']
        for call, role, decision in ((maker, 'maker', self.maker), (checker, 'checker', self.checker)):
            self.assertEqual(call['status'], 'ok', call.get('error'))
            self.assertEqual(call['name'], 'cursor')
            self.assertEqual(call['effective_model'], decision['effective_model'])
            self.assertEqual(call['session_mode'], 'fresh_context_fallback')
            self.assertEqual(call['permissions']['enforcement'], 'macos_sandbox_exec')
            self.assertTrue(call['permissions']['os_isolation'])
            self.assertEqual(call['provider_session_id'], 'fake-session-1')
        self.assertFalse(maker['read_only'])
        self.assertTrue(checker['read_only'])
        self.assertEqual(maker['permissions']['write_allowlist'], list(e.CURSOR_MAKER_WRITES))
        self.assertEqual(checker['permissions']['write_allowlist'], list(e.CURSOR_CHECKER_WRITES))
        self.assertEqual(maker['changed_paths'], ['file.txt'])
        self.assertEqual(maker['canary_changes'], [])
        self.assertEqual(checker['workspace_changes'], [])
        self.assertEqual(checker['canary_changes'], [])
        self.assertEqual(task['sessions']['maker']['mode'], 'fresh_context_fallback')
        self.assertEqual(task['sessions']['checker']['mode'], 'fresh_context_fallback')
        self.assertEqual(self.action(task, 'integrate'), 0)
        self.assertEqual((self.repo / 'file.txt').read_text(), 'new\n')
        self.assertFalse(Path(task['worktree']).exists())

    def test_each_process_gets_only_the_sandboxed_role_contract(self):
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        (maker_profile, maker_cmd), (checker_profile, checker_cmd) = self.inference()
        for cmd, role, decision in ((maker_cmd, 'maker', self.maker), (checker_cmd, 'checker', self.checker)):
            tail = cmd[1:]
            self.assertEqual(cmd[0], os.path.realpath(self.cli))
            self.assertEqual(tail[tail.index('--model') + 1], decision['effective_model'])
            self.assertEqual(tail[tail.index('--sandbox') + 1], 'enabled')
            self.assertEqual(tail[tail.index('--workspace') + 1], task['worktree'])
            for flag in ('-p', '--trust', '--skip-worktree-setup'):
                self.assertEqual(tail.count(flag), 1, (role, flag))
            self.assertFalse(set(FORBIDDEN_FLAGS) & set(tail), role)
            self.assertNotIn('Change file.txt', ' '.join(tail))                # task text is never on argv
            self.assertRegex(tail[-1], r'^Read ".*/prompt_in/prompt\.md" in full for your instructions')
        self.assertNotIn('--mode', maker_cmd)
        self.assertEqual(checker_cmd[checker_cmd.index('--mode') + 1], 'ask')
        self.assertEqual(checker_cmd.count('--mode'), 1)

    def test_maker_profile_allows_only_the_worktree_content_and_the_private_runtime(self):
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        (profile, _), _ = self.inference()
        wt, loc, home = task['worktree'], self.git_locations(task), self.home()
        runtime = re.findall(r'\(subpath "([^"]*/runtime/(?:state|cache|tmp))"\)', profile)
        self.assertEqual(sorted(p.rsplit('/', 1)[1] for p in runtime), ['cache', 'state', 'tmp'])
        for allowed in [wt + '/file.txt', wt + '/new/dir/file.txt'] + [p + '/x' for p in runtime]:
            self.assertEqual(self.writes(profile, allowed), 'allow', allowed)
        for denied in [loc['dotgit'], loc['gitdir'] + '/x', loc['gitdir'] + '/info/attributes',
                       loc['common'] + '/x', loc['common'] + '/hooks/pre-commit', str(self.repo / 'file.txt'),
                       str(self.base / 'sibling'), '/private/tmp/x', '/private/var/tmp/x', home + '/x',
                       home + '/.cursor/x', home + '/.local/share/cursor-agent/x', home + '/Library/Caches/x',
                       str(e.home(core) / 'tasks' / 'x')]:
            self.assertEqual(self.writes(profile, denied), 'deny', denied)
        self.assertEqual(MOCKMOD.sbpl_decision(profile, 'file-link', wt + '/link'), 'deny')
        for rel in BUILTIN_DENIALS:
            self.assertEqual(MOCKMOD.sbpl_decision(profile, 'file-read-data', home + '/' + rel + '/secret'), 'deny', rel)

    def test_checker_profile_allows_only_the_private_runtime_and_no_process_execution(self):
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        _, (profile, _) = self.inference()
        wt, loc, home = task['worktree'], self.git_locations(task), self.home()
        runtime = re.findall(r'\(subpath "([^"]*/runtime/(?:state|cache|tmp))"\)', profile)
        self.assertEqual(len(runtime), 3)
        for p in runtime:
            self.assertEqual(self.writes(profile, p + '/x'), 'allow')
        for denied in (wt + '/file.txt', wt + '/new.txt', loc['dotgit'], loc['gitdir'] + '/x', loc['common'] + '/x',
                       home + '/x', '/private/tmp/x'):
            self.assertEqual(self.writes(profile, denied), 'deny', denied)
        self.assertEqual(MOCKMOD.sbpl_decision(profile, 'process-exec', '/bin/sh'), 'deny')
        self.assertEqual(MOCKMOD.sbpl_decision(profile, 'file-link', wt + '/link'), 'deny')
        for rel in BUILTIN_DENIALS:
            self.assertEqual(MOCKMOD.sbpl_decision(profile, 'file-read-data', home + '/' + rel + '/secret'), 'deny', rel)

    def test_configured_sensitive_read_denials_reach_both_roles_and_never_widen_a_grant(self):
        extra = self.base / 'extra-secret'
        extra.mkdir()
        (extra / 'sentinel.txt').write_text('sentinel\n')
        with patch.dict(os.environ, ALLOY_CURSOR_DENY_READ_PATHS=str(extra)):
            code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        for profile, _ in self.inference():
            self.assertEqual(MOCKMOD.sbpl_decision(profile, 'file-read-data', str(extra / 'sentinel.txt')), 'deny')
            self.assertEqual(MOCKMOD.sbpl_decision(profile, 'file-read-data', str(extra) + '/nested/x'), 'deny')
            for rel in BUILTIN_DENIALS:                                   # additive: the built-ins stay
                self.assertEqual(MOCKMOD.sbpl_decision(
                    profile, 'file-read-data', self.home() + '/' + rel + '/secret'), 'deny', rel)
        # an extra denial that covers the worktree the roles must read fails closed (no dispatch)
        self.reset()
        with patch.dict(os.environ, ALLOY_CURSOR_DENY_READ_PATHS=str(e.home(core))):
            before = len(self.inference())
            code, task = self.create()
        self.assertEqual(code, 3)
        self.assertEqual(len(self.inference()), before)
        self.assertEqual((self.repo / 'file.txt').read_text(), 'old\n')

    def test_a_correction_round_starts_a_fresh_context_and_never_resumes(self):
        self.plan(maker_writes=[dict(path='file.txt', text='new\n')], verdicts=[
            dict(verdict='fail', findings=[dict(path='file.txt', evidence='Concrete failure', fix='Fix it')]),
            dict(verdict='pass', findings=[])])
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(len(task['rounds']), 2)
        modes = [r[role]['session_mode'] for r in task['rounds'] for role in ('maker', 'checker')]
        self.assertEqual(modes, ['fresh_context_fallback'] * 4)
        for _, cmd in self.inference():
            self.assertFalse({'--resume', '--continue', '--session-id'} & set(cmd))
        staged = (e.taskdir(core, task['id']) / 'round-1/maker/prompt_in/prompt.md').read_text()
        self.assertIn('TASK / ACCEPTANCE CRITERIA:', staged)               # a full prompt, not a resume update
        self.assertIn('Concrete failure', staged)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            e.finish(core, task)
        metrics = json.loads(output.getvalue())['metrics']
        self.assertEqual((metrics['resumed_worker_calls'], metrics['fresh_worker_starts']), (0, 4))

    def test_maker_writes_outside_scope_or_to_git_internals_fail_before_gates_and_review(self):
        cases = [
            ('ignored file', dict(maker_writes=[dict(path='file.txt', text='new\n'), dict(path='ignored.txt', text='x')]),
             'outside allowed'),
            ('gitdir attributes', dict(maker_writes=[dict(path='file.txt', text='new\n')],
                                       maker_git_writes=[dict(base='gitdir', rel='info/attributes', text='* text\n')]),
             'protected Git internals'),
            ('gitdir commondir', dict(maker_git_writes=[dict(base='gitdir', rel='commondir', text=' ')]),
             'protected Git internals|uncertain'),
            ('common hook', dict(maker_git_writes=[dict(base='common', rel='hooks/post-checkout', text='#!/bin/sh\n')]),
             'protected Git internals'),
            ('pointer', dict(maker_git_writes=[dict(base='pointer', rel='', text='\n')]),
             'protected Git internals|uncertain'),
            ('outside canary', dict(maker_writes=[dict(path='file.txt', text='new\n')], maker_tamper_canary=True),
             'canary')]
        for label, plan, message in cases:
            with self.subTest(label):
                self.reset()
                self.plan(**plan)
                before = len(self.inference())
                code, task = self.create()
                self.assertEqual(code, 3, task.get('error'))
                self.assertEqual(task['state'], 'needs_attention')
                self.assertRegex(task['error'], message)
                self.assertEqual(len(self.inference()) - before, 1)         # the Maker only: no review call
                self.assertNotIn('gates', task['rounds'][0])
                self.assertTrue(Path(task['worktree']).exists())

    def test_checker_tampering_fails_before_review(self):
        self.args.allow_path = ['file.txt', 'ignored.txt']
        cases = [
            ('ignored file', dict(maker_writes=[dict(path='file.txt', text='new\n'), dict(path='ignored.txt', text='aaaa')],
                                  checker_writes=[dict(path='ignored.txt', text='bbbb')]), 'Checker changed worktree'),
            ('git internals', dict(maker_writes=[dict(path='file.txt', text='new\n')],
                                   checker_git_writes=[dict(base='common', rel='info/attributes', text='x\n')]),
             'Checker changed worktree'),
            ('outside canary', dict(maker_writes=[dict(path='file.txt', text='new\n')], checker_tamper_canary=True),
             'protected canary')]
        for label, plan, message in cases:
            with self.subTest(label):
                self.reset()
                self.plan(**plan)
                code, task = self.create()
                self.assertEqual(code, 3, task.get('error'))
                self.assertIn(message, task['error'])
                self.assertNotIn('review', task['rounds'][0])

    def test_no_boundary_means_no_cursor_process_and_unsandboxed_override_never_helps(self):
        for env in ({}, {'ALLOY_ALLOW_UNSANDBOXED': '1'}):
            with self.subTest(env=env):
                self.reset()
                with patch.object(core, '_CURSOR_PREFLIGHT', {}), patch.dict(
                        os.environ, dict(env, MOCK_SANDBOX_PREFLIGHT='write_leak')):
                    code, task = self.create()
                self.assertEqual(code, 3)
                self.assertEqual(task['state'], 'needs_attention')
                self.assertRegex(task['error'], 'sandbox unavailable.*Cursor roles are refused')
                self.assertEqual(self.cursor_calls(), [])
                self.assertEqual(self.inference(), [])
                self.assertEqual((self.repo / 'file.txt').read_text(), 'old\n')
                self.assertNotIn('maker', task['rounds'][0])

    def test_cursor_api_overrides_and_router_keys_never_reach_any_cursor_process(self):
        poison = dict(CURSOR_API_KEY='poison-key', CURSOR_API_ENDPOINT='https://poison.invalid/api',
                      TYPESAFE_API_KEY='poison-router', OPENROUTER_API_KEY='poison-router', SSH_AUTH_SOCK='/tmp/poison.sock')
        self.patch_e('probe', side_effect=REAL_PROBE)              # status and help calls too
        with patch.dict(os.environ, poison), patch.object(core, '_CONFIG', dict(poison)):
            code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        calls = self.cursor_calls()
        self.assertTrue({c['kind'] for c in calls} >= {'status', 'help', 'maker', 'checker'})
        for call in calls:
            self.assertFalse(set(poison) & set(call['env_names']), call['kind'])
        self.assertNotIn('poison', json.dumps(self.sandbox_calls()))

    def test_secrets_never_reach_the_staged_or_saved_checker_prompt(self):
        text = '; '.join(v[0] for v in SECRETS.values())
        self.prompt.write_text('Change file.txt to new. ' + text)
        self.args.test = ["echo '%s'" % text]
        self.plan(maker_writes=[dict(path='file.txt', text='new\n' + text + '\n')])
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        folder = e.taskdir(core, task['id']) / 'round-0/checker'
        for path in (folder / 'prompt.txt', folder / 'prompt_in/prompt.md',
                     e.taskdir(core, task['id']) / 'review-0.json'):
            body = path.read_text()
            for _, value in SECRETS.values():
                self.assertNotIn(value, body, str(path))
            self.assertIn('[REDACTED', body)
        self.assertEqual(oct((folder / 'prompt_in/prompt.md').stat().st_mode & 0o777), '0o600')
        for status_path in e.taskdir(core, task['id']).glob('round-*/*/status.json'):
            for _, value in SECRETS.values():
                self.assertNotIn(value, status_path.read_text())

    def test_real_probe_readiness_and_dispatch_share_one_boundary(self):
        self.patch_e('probe', side_effect=REAL_PROBE)
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(len(self.cursor_calls('help')), 2)         # run() probes the Maker and the Checker
        core.ADAPTERS['cursor'].__dict__.pop('_auth_cache', None)
        with patch.object(core, '_CURSOR_PREFLIGHT', {}), patch.dict(os.environ, MOCK_SANDBOX_PREFLIGHT='write_leak'):
            self.reset()
            code, task = self.create()
        self.assertEqual(code, 3)
        self.assertRegex(task['error'], 'Cursor roles are refused')
