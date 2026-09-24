"""Managed lifecycle tests: real temporary Git repos, fake CLIs, no paid calls."""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
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
            self.assertTrue(any('independence:' in x for x in report['blockers']))
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
                self.assertEqual(set(allowed),{'Bash','Edit','Write'})

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
