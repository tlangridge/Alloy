#!/usr/bin/env python3
"""Offline tests for the alloy-bench evaluator (bench/): parsing, grading,
pricing, the Maker loop through production code (mock CLI) and replay scoring.
No provider CLI is ever invoked."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'bench'))
import harness as h  # noqa: E402
import score  # noqa: E402

MOCK = HERE / 'mocks' / 'mock_panelist.py'


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_task(root, tid='make-x'):
    d = Path(root) / tid
    write(d / 'task.json', json.dumps(dict(
        id=tid, type='make', tier='small', kind='implementation', split='dev', title='t',
        allow_paths=['.'], visible_test='python3 -m unittest discover -s tests -v',
        hidden_test='python3 -m unittest discover -s _hidden_tests -v', hidden_checks='c')))
    write(d / 'spec.md', 'Goal: implement f() returning 2.')
    write(d / 'repo' / 'm.py', 'def f():\n    return 1\n')
    write(d / 'repo' / 'tests' / 'test_v.py', 'import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n')
    write(d / 'hidden' / '__init__.py', '')
    write(d / 'hidden' / 'test_h.py', 'import unittest\nfrom m import f\nclass H(unittest.TestCase):\n'
          '    def test_a(self): self.assertEqual(f(), 2)\n    def test_b(self): self.assertTrue(f())\n')
    write(d / 'solution' / 'm.py', 'def f():\n    return 2\n')
    return d


class ParsingTests(unittest.TestCase):
    def test_unittest_counts(self):
        self.assertEqual(h.test_counts('Ran 5 tests in 0.1s\n\nOK\n'), (5, 5))
        self.assertEqual(h.test_counts('Ran 5 tests in 0.1s\n\nFAILED (failures=2, errors=1)\n'), (2, 5))
        self.assertEqual(h.test_counts('Ran 1 test in 0.0s\nFAILED (errors=1)'), (0, 1))
        self.assertEqual(h.test_counts('nothing'), (0, 0))

    def test_bench_score_line_wins(self):
        self.assertEqual(h.test_counts('Ran 3 tests\nOK\nBENCH_SCORE: 7/9\n'), (7, 9))

    def test_consult_grading(self):
        t = dict(answers=['ValueError'], match='exact')
        self.assertTrue(h.grade_consult(t, 'blah\nANSWER: `ValueError`.')['passed'])
        self.assertTrue(h.grade_consult(t, '**ANSWER:** valueerror')['passed'])
        self.assertFalse(h.grade_consult(t, 'ANSWER: TypeError')['passed'])
        self.assertFalse(h.grade_consult(t, 'ValueError')['passed'])  # no ANSWER line
        # The last ANSWER line counts.
        self.assertFalse(h.grade_consult(t, 'ANSWER: ValueError\nANSWER: KeyError')['passed'])
        n = dict(answers=['1024'], match='number')
        self.assertTrue(h.grade_consult(n, 'ANSWER: 1,024')['passed'])
        self.assertTrue(h.grade_consult(n, 'ANSWER: 1024.0')['passed'])
        r = dict(answers=[r'(pkg\.)?mod\.run'], match='regex')
        self.assertTrue(h.grade_consult(r, 'ANSWER: pkg.mod.run')['passed'])
        self.assertFalse(h.grade_consult(r, 'ANSWER: pkg.mod.running')['passed'])

    def test_review_grading(self):
        bug = dict(bug=True, ground_truth=dict(path='src/pager.py', keywords=['off-by-one', 'last page']))
        hit = dict(verdict='fail', findings=[dict(path='./src/pager.py', evidence='The Last Page is dropped', fix='x')])
        wrong_file = dict(verdict='fail', findings=[dict(path='src/other.py', evidence='last page', fix='x')])
        wrong_issue = dict(verdict='fail', findings=[dict(path='src/pager.py', evidence='style nit', fix='rename')])
        self.assertTrue(h.grade_review(bug, hit)['passed'])
        for loc in ('src/pager.py:84', 'src/pager.py:84:3', '`src/pager.py#L84-L90`', 'src/pager.py (line 84)'):
            located = dict(verdict='fail', findings=[dict(path=loc, evidence='drops the last page', fix='x')])
            self.assertTrue(h.grade_review(bug, located)['passed'], loc)
        self.assertFalse(h.grade_review(bug, wrong_file)['passed'])
        self.assertFalse(h.grade_review(bug, wrong_issue)['passed'])
        self.assertFalse(h.grade_review(bug, dict(verdict='pass', findings=[]))['passed'])
        self.assertFalse(h.grade_review(bug, None, 'bad json')['passed'])
        clean = dict(bug=False)
        self.assertTrue(h.grade_review(clean, dict(verdict='pass', findings=[]))['passed'])
        fp = h.grade_review(clean, wrong_issue)
        self.assertFalse(fp['passed'])
        self.assertTrue(fp['false_positive'])


class CostTests(unittest.TestCase):
    def usage(self, **kw):
        base = dict(input_tokens=0, cache_read_tokens=0, cache_write_tokens=0, output_tokens=0,
                    reasoning_tokens=0, reported_cost_usd=None)
        base.update(kw)
        return base

    def test_prices_every_bench_profile(self):
        table = h.prices()
        for pid, p in h.bench_profiles().items():
            self.assertIsNotNone(h.api_usd(p['model'], self.usage(input_tokens=1), table)[0], pid)

    def test_api_usd_components(self):
        usd, key = h.api_usd('gpt-5.6-luna', self.usage(input_tokens=1_000_000, cache_read_tokens=1_000_000,
                                                          output_tokens=1_000_000))
        self.assertEqual(key, 'gpt-5.6-luna')
        self.assertAlmostEqual(usd, 0.2 + 0.02 + 1.2)
        usd, key = h.api_usd('sonnet', self.usage(cache_write_tokens=1_000_000))
        self.assertEqual(key, 'claude-sonnet-5')
        self.assertAlmostEqual(usd, 4.0)  # 1h cache write = 2x input
        self.assertEqual(h.api_usd('no-such-model', self.usage(input_tokens=5)), (None, None))

    def test_reported_cost_preferred(self):
        c = h.cost_of('claude-sonnet-5', self.usage(output_tokens=1000, reported_cost_usd=0.5))
        self.assertEqual(c['api_usd'], 0.5)
        self.assertAlmostEqual(c['computed_usd'], 0.01)

    def test_add_usage(self):
        a = h.add_usage(None, self.usage(input_tokens=3, reported_cost_usd=0.1))
        a = h.add_usage(a, self.usage(input_tokens=4, output_tokens=2))
        a = h.add_usage(a, None)
        self.assertEqual((a['input_tokens'], a['output_tokens'], a['dispatches']), (7, 2, 2))
        self.assertEqual(a['reported_cost_usd'], 0.1)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='benchtest-'))
        self.tasks = self.tmp / 'tasks'
        make_task(self.tasks)
        self.patch = mock.patch.object(h, 'TASKS', self.tasks)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_materialize_and_grade(self):
        t = h.load_task('make-x')
        wt = self.tmp / 'wt'
        base = h.materialize(t, wt)
        self.assertEqual(len(base), 40)
        g = h.grade_make(t, wt)
        self.assertFalse(g['passed'])
        self.assertEqual((g['hidden_passed'], g['hidden_total']), (1, 2))
        self.assertFalse((wt / h.HIDDEN_DIR).exists())  # hidden tests never left behind
        ref = self.tmp / 'ref'
        h.materialize(t, ref, overlays=('solution',))
        self.assertTrue(h.grade_make(t, ref)['passed'])

    def test_validator_accepts_and_rejects(self):
        import validate
        t = h.load_task('make-x')
        self.assertEqual(validate.validate(t), [])
        write(self.tasks / 'make-x' / 'solution' / 'm.py', 'def f():\n    return 1\n')
        self.assertTrue(any('reference fails hidden' in e for e in validate.validate(t)))


class MakerLoopTests(unittest.TestCase):
    """run_make through production dispatch/gate/scope with a mock CLI that never edits."""
    def test_three_rounds_then_graded_fail(self):
        tmp = Path(tempfile.mkdtemp(prefix='benchloop-'))
        make_task(tmp / 'tasks')
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'bench'))
        code = r'''
import json, os, sys
from pathlib import Path
from unittest import mock
import harness as h
h.TASKS = Path(sys.argv[1]) / 'tasks'
state = h.configure(Path(sys.argv[1]) / 'state')
os.environ.update(ALLOY_BIN_CODEX=sys.argv[2], CODEX_API_KEY='x', ALLOY_USAGE='off')
core = h.load_core()
core.execution.probe = lambda *a, **k: None
with mock.patch.object(core.routing, 'inventory', lambda core: {n: dict(status='ready', compatible=True) for n in core.routing.FAMILIES}):
    w = state / 'work' / 'x'; w.mkdir(parents=True)
    row = h.run_make(core, h.load_task('make-x'), 'codex-luna-medium', w)
print(json.dumps(row, default=str))
'''
        cp = subprocess.run([sys.executable, '-c', code, str(tmp), str(MOCK)], capture_output=True, text=True,
                            env=env, timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        row = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertFalse(row['passed'])
        self.assertTrue(row['gates_ok'])      # the mock never edits; visible tests already pass
        self.assertEqual(row['rounds'], 1)
        self.assertEqual(row['grade']['hidden_total'], 2)
        self.assertEqual(row['usage']['input_tokens'], 600)  # captured through the codex JSONL path
        self.assertIsNotNone(row['api_usd'])


class ReplayTests(unittest.TestCase):
    def test_references_and_gate(self):
        tasks = {'a': dict(type='make', tier='small'), 'b': dict(type='make', tier='small')}
        run = lambda p, u: [dict(passed=p, api_usd=u, score=float(p), wall_s=1)]
        data = {('a', 'codex-luna-medium'): run(True, .01), ('b', 'codex-luna-medium'): run(False, .01),
                ('a', 'claude-sonnet'): run(True, 1.0), ('b', 'claude-sonnet'): run(True, 1.0)}
        refs = score.references(tasks, data)
        self.assertEqual(refs['make']['profile'], 'claude-sonnet')
        self.assertEqual(refs['make']['q'], 1.0)
        cheap = [dict(type='make', q=1.0, usd=.01), dict(type='make', q=0.0, usd=.01)]
        s = score.summarize(cheap, refs)
        self.assertTrue(s['make']['gate'])  # within one task of the reference (n=2)
        worse = [dict(type='make', q=0.0, usd=.01), dict(type='make', q=0.0, usd=.01)]
        self.assertFalse(score.summarize(worse, refs)['make']['gate'])


if __name__ == '__main__':
    unittest.main()
