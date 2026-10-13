"""Production execute integration and complete-evaluation metrics, offline."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import test_execution as fixture
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bench'))
import execute as evaluation
import test_bench as benchmark

core, e = fixture.core, fixture.e


class QualityExecutionTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixture.ExecutionTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.r = core.routing
        self.config = self.r.starter(core)
        self.config['profiles'] = [
            dict(id='maker', adapter='claude', family='anthropic', model='claude-opus-5-5',
                 effort='xhigh', tier='large', enabled=True, billing_mode='unknown', cost_rank=2),
            dict(id='checker', adapter='muse', family='meta', model='muse-wonder-full-1.0',
                 effort='xhigh', tier='large', enabled=True, billing_mode='unknown', cost_rank=3)]
        self.r.save(self.r.root() / 'routing.json', self.config)
        self.available = {n: dict(status='ready', compatible=True, version='test') for n in self.r.FAMILIES}
        self.available['muse']['image_flag'] = '--image'
        self.helper.args.task_tier = 'large'

    def create(self):
        with patch.object(self.r, 'inventory', return_value=self.available), \
                patch.object(e, 'select', side_effect=fixture.REAL_SELECT):
            return self.helper.create()

    def test_quality_pair_works_through_the_managed_lifecycle(self):
        code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        self.assertEqual(task['maker']['model'], 'claude-opus-5-5')
        self.assertEqual(task['checker']['family'], 'meta')
        self.assertEqual(task['checker']['objective'], 'quality_first')
        row = json.loads((self.r.root() / 'outcomes' / (task['id'] + '.json')).read_text())
        self.assertEqual(row['revision'], task['tip'])
        self.assertEqual(row['first_pass_review'], 'pass')
        self.assertIsNone(row['independently_verified_correctness'])
        self.assertEqual(self.helper.action(task, 'integrate'), 0)
        row = json.loads((self.r.root() / 'outcomes' / (task['id'] + '.json')).read_text())
        self.assertTrue(row['integrated_commit'])
        self.assertEqual(row['state'], 'cleaned')

    def test_actual_artifact_receipt_is_in_the_review_packet(self):
        original = e.dispatch.side_effect
        image = b'\x89PNG\r\n\x1a\n' + b'pixels'
        def produce(core_, task, role, prompt, folder):
            result = original(core_, task, role, prompt, folder)
            if role == 'maker':
                (Path(task['worktree']) / 'page.png').write_bytes(image)
            return result
        self.helper.args.artifact = ['page.png']
        self.helper.args.allow_path.append('page.png')
        with patch.object(e, 'dispatch', side_effect=produce):
            code, task = self.create()
        self.assertEqual(code, 0, task.get('error'))
        packet = json.loads((e.taskdir(core, task['id']) / 'review-0.json').read_text())
        self.assertEqual(packet['artifacts'][0]['bytes'], len(image))
        # The real dispatch stages those exact bytes and emits the verified flag.
        with patch.object(e, 'revalidate'), patch.object(e, 'worker_session', return_value=dict(supported=False, started=False, mode='fresh_context_fallback')):
            def capture(ad, prompt, folder, *args, **kwargs):
                argv = ad.build_args(prompt, '', 'review', dict(repo=task['worktree']))
                path = Path(argv[argv.index('--image') + 1])
                self.assertEqual(path.read_bytes(), image)
                self.assertIn('--disable-write', argv)
                return dict(status='ok')
            with patch.object(core, 'run_panelist', side_effect=capture):
                fixture.REAL_DISPATCH(core, task, 'checker', 'Inspect attached pixels.', e.taskdir(core, task['id']) / 'image-check')
        (Path(task['worktree']) / 'page.png').write_bytes(image + b'changed')
        with patch.object(e, 'revalidate'), patch.object(core, 'run_panelist') as paid:
            with self.assertRaisesRegex(e.ExecutionError, 'receipt changed'):
                fixture.REAL_DISPATCH(core, task, 'checker', 'Inspect pixels.', e.taskdir(core, task['id']) / 'changed-check')
            paid.assert_not_called()

    def test_ambiguity_prevents_maker_dispatch(self):
        self.helper.args.task_ambiguous = True
        with self.assertRaisesRegex(self.r.RoutingError, 'needs_clarification'):
            self.create()
        self.assertEqual(self.helper.calls, [])

    def test_dot_artifact_is_refused_before_selection(self):
        self.helper.args.artifact = ['.']
        self.helper.args.allow_path = ['.']
        with self.assertRaisesRegex(e.ExecutionError, 'Artifacts must'):
            self.create()
        self.assertEqual(self.helper.calls, [])

    def test_revalidation_preserves_failure_tier_floor(self):
        self.helper.args.task_tier = 'small'
        self.helper.args.prior_failures = 2
        _, task = self.create()
        self.config['profiles'][0]['tier'] = 'small'
        self.r.save(self.r.root() / 'routing.json', self.config)
        with patch.object(self.r, 'inventory', return_value=self.available):
            with self.assertRaisesRegex(self.r.RoutingError, 'below required tier'):
                fixture.REAL_REVALIDATE(core, task, 'maker')

    def test_artifacts_do_not_drop_other_checker_tool_requirements(self):
        maker = self.config['profiles'][0]
        maker['capabilities'] = {'web': dict(status='verified', source='offline probe',
            observed_at=time.time() - 1, expires_at=time.time() + 60,
            identity=dict(model=maker['model'], effort=maker['effort'], cli_version='test'))}
        self.r.save(self.r.root() / 'routing.json', self.config)
        self.helper.args.require_capability = ['web']
        self.helper.args.artifact = ['page.png']
        self.helper.args.allow_path.append('page.png')
        with patch.object(self.r, 'inventory', return_value=self.available):
            report = fixture.REAL_READINESS(core, self.helper.args, str(self.helper.repo))
            self.assertFalse(report['ready'])
            self.assertTrue(any('checker:' in b and 'web' in b for b in report['blockers']))
        with self.assertRaisesRegex(self.r.RoutingError, 'web'):
            self.create()
        self.assertEqual(self.helper.calls, [])

    def test_resume_revalidates_the_captured_objective(self):
        _, task = self.create()
        self.config['policy']['objective'] = 'cost_first'
        self.r.save(self.r.root() / 'routing.json', self.config)
        with patch.object(self.r, 'inventory', return_value=self.available):
            fixture.REAL_REVALIDATE(core, task, 'checker')
        self.assertEqual(task['checker']['objective'], 'quality_first')

    def test_complete_evaluation_runs_production_then_hidden_checks(self):
        directory = benchmark.make_task(self.helper.base / 'fixtures')
        task_fixture = json.loads((directory / 'task.json').read_text())
        task_fixture['dir'] = str(directory)
        args = core.build_parser().parse_args(['execute', '--host-family', 'openai', '--maker-profile', 'maker',
                                               '--checker-profile', 'checker', '--allow-path', '.', '--test', 'exit 0'])
        args.budget_minutes = 1
        original = e.dispatch.side_effect
        def produce(core_, task, role, prompt, folder):
            result = original(core_, task, role, prompt, folder)
            if role == 'maker':
                (Path(task['worktree']) / 'm.py').write_text('def f():\n    return 2\n')
                self.assertFalse((Path(task['worktree']) / '_hidden_tests').exists())
            return result
        with patch.object(self.r, 'inventory', return_value=self.available), \
                patch.object(e, 'select', side_effect=fixture.REAL_SELECT), \
                patch.object(e, 'dispatch', side_effect=produce):
            row = evaluation.run_execute(core, task_fixture, self.helper.base / 'evaluate', args)
        self.assertTrue(row['passed'])
        self.assertTrue(row['hidden_correct'])
        self.assertEqual([d['role'] for d in row['dispatches']], ['maker', 'checker'])
        self.assertIsNone(row['user_accepted'])
        for role, prompt in self.helper.calls:
            self.assertNotIn('class H(unittest.TestCase)', prompt)


class CompleteEvaluationTests(unittest.TestCase):
    def test_false_acceptance_and_retries_are_measured_separately(self):
        task = dict(id='sample', state='ready', worktree='/private/evaluation', implementation_rounds=2,
                    maker=dict(model='unknown'), checker=dict(model='other'), rounds=[
            dict(index=0, maker=dict(status='ok'), gates=[dict(exit_code=0)], review=dict(verdict='fail'),
                 checker_attempts=[dict(status='timeout'), dict(status='ok')]),
            dict(index=1, maker=dict(status='ok'), gates=[dict(exit_code=0)], review=dict(verdict='pass'),
                 checker_attempts=[dict(status='ok')])])
        fixture_ = dict(id='make-fixture', tier='large', kind='implementation', split='holdout')
        grade = dict(passed=False, score=0, hidden_passed=0, hidden_total=2, hidden_exit=1)
        with patch.object(evaluation.h, 'sut_revision', return_value='exact-revision'):
            row = evaluation.summarize(core, fixture_, task, grade, 4)
        self.assertTrue(row['process_ready'])
        self.assertFalse(row['passed'])
        self.assertFalse(row['hidden_correct'])
        self.assertEqual(len(row['dispatches']), 5)
        self.assertEqual(row['correction_rounds'], 1)
        self.assertIsNone(row['api_usd'])
        self.assertIsNone(row['first_pass_hidden_correctness'])
        self.assertIsNone(row['user_accepted'])
        self.assertNotIn('prompt', row)
        task['maker'].update(jev_model='jev-1.13.0', jev_usage={'input_tokens': 10}, jev_latency_ms=20)
        with patch.object(evaluation.h, 'cost_of', return_value={'api_usd': 2}):
            routed = evaluation.summarize(core, fixture_, task, grade, 4)
        self.assertEqual(routed['worker_api_usd'], 10)
        self.assertIsNone(routed['api_usd'])
        self.assertEqual(routed['router']['usage'], {'input_tokens': 10})
        self.assertEqual(routed['router']['latency_ms'], 20)
