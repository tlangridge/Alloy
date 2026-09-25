"""Offline regressions for the evaluator; no inference or user config access."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench_score', ROOT / 'bench' / 'score.py')
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)


class RoutingError(Exception):
    pass


class BenchScoreTests(unittest.TestCase):
    def setUp(self):
        self.task = dict(id='make-task', type='make', tier='large', kind='implementation')
        self.review = dict(id='review-task', type='review', tier='large', kind='review')
        self.profiles = {
            'maker': dict(cli='antigravity', model='maker', effort='high'),
            'checker': dict(cli='codex', model='checker', effort='medium')}
        self.decisions = [dict(cli=p['cli'], model=p['model'], effort=p['effort'], profile=k, family=k)
                          for k, p in self.profiles.items()]
        self.core = types.SimpleNamespace(
            routing=types.SimpleNamespace(FAMILIES=['codex', 'antigravity'], RoutingError=RoutingError,
                                          resolve=Mock(side_effect=self.decisions), model_fits=Mock(return_value={'maker': .9})),
            execution=types.SimpleNamespace(host_assessment=Mock(return_value={})))
        self.config = {'policy': {}, 'profiles': [dict(id=k, **p) for k, p in self.profiles.items()]}
        self.data = {('make-task', 'maker'): [dict(passed=True, api_usd=2)]}

    def replay(self, data=None, answers=None, classifier_only=False):
        with patch.object(score.h, 'bench_profiles', return_value=self.profiles):
            return score.replay(self.core, self.config,
                                {'make-task': self.task, 'review-task': self.review},
                                self.data if data is None else data, ['host'], answers, classifier_only)

    def test_routing_failures_stay_in_denominator(self):
        self.core.routing.resolve.side_effect = RoutingError('no eligible provider')
        rows, _ = self.replay()
        self.assertEqual([r['type'] for r in rows], ['make', 'review'])
        summary = score.summarize(rows, {'make': {'q': 1, 'n': 12}})
        self.assertEqual(summary['overall']['q'], 0)
        self.assertEqual(summary['overall']['n'], 2)
        self.assertFalse(summary['overall']['gate'])
        self.assertEqual(score.bootstrap(rows, {}, n=10)['overall']['q'], (0, 0))

    def test_missing_checker_invalidates_aggregate(self):
        self.core.routing.resolve.side_effect = self.decisions + [self.decisions[1]]
        rows, missing = self.replay()
        self.assertIn(('make-task', 'checker:checker', 'host'), missing)
        self.assertIsNone(rows[0]['q'])
        self.assertIsNone(rows[0]['usd'])
        result = score.summarize(rows, {})['overall']
        self.assertFalse(result['gate'])
        self.assertFalse(result['complete'])
        self.assertIsNone(result['cps'])
        self.assertNotIn('overall', score.bootstrap(rows, {}, n=10))

    def test_checker_correctness_not_json_validity(self):
        self.core.routing.resolve.side_effect = self.decisions + [self.decisions[1]]
        self.data[('review-task', 'checker')] = [dict(passed=False, api_usd=1, grade={'malformed': False})]
        rows, missing = self.replay()
        self.assertFalse(missing)
        self.assertEqual(rows[0]['q'], 0)
        self.assertEqual(rows[0]['usd'], 3)

    def test_checker_routing_error_is_a_failed_task(self):
        self.core.routing.resolve.side_effect = [self.decisions[0], RoutingError('no independent checker'), self.decisions[1]]
        rows, _ = self.replay()
        self.assertEqual(rows[0]['q'], 0)
        self.assertEqual(rows[0]['usd'], 2)
        self.assertIn('independent checker', rows[0]['error'])

    def test_missing_cost_is_unknown_not_free(self):
        self.assertIsNone(score.stat([dict(passed=True, api_usd=1), dict(passed=False, api_usd=None)])['usd'])
        self.core.routing.resolve.side_effect = self.decisions + [self.decisions[1]]
        self.data[('review-task', 'checker')] = [dict(passed=True, api_usd=None)]
        rows, missing = self.replay()
        self.assertIsNone(rows[0]['usd'])
        self.assertIn(('make-task', 'checker-cost:checker', 'host'), missing)
        self.assertFalse(score.summarize(rows, {})['overall']['gate'])

    def test_fit_answers_require_original_cards(self):
        entry = {'answers': {'fit_0': {'type': 'noul', 'noul': .9}}}
        with self.assertRaisesRegex(ValueError, 'original model_context'):
            score.replay_fits(self.core, self.config, entry)
        self.assertEqual(score.replay_fits(self.core, self.config, entry, True), {})

    def test_card_identity_and_effort_must_match(self):
        entry = {'answers': {'fit_0': {'type': 'noul', 'noul': .9}},
                 'model_context': [{'profile': 'maker', 'model': 'new-model', 'effort': 'high'}]}
        with self.assertRaisesRegex(ValueError, 'does not match'):
            score.replay_fits(self.core, self.config, entry)

    def test_fit_answers_reach_both_resolvers(self):
        entry = {'answers': {'fit_0': {'type': 'noul', 'noul': .9}},
                 'model_context': [{'profile': 'maker', 'model': 'maker', 'effort': 'high'}]}
        self.core.routing.resolve.side_effect = self.decisions + [self.decisions[1]]
        self.data[('review-task', 'checker')] = [dict(passed=True, api_usd=1)]
        self.replay(answers={'make-task': entry, 'review-task': entry})
        for call in self.core.routing.resolve.call_args_list:
            self.assertEqual(call.args[-1], {'maker': .9})
        self.core.routing.model_fits.assert_called_with(entry, entry['model_context'])

    def test_missing_fit_answer_is_rejected(self):
        entry = {'answers': {}, 'model_context': [{'profile': 'maker', 'model': 'maker', 'effort': 'high'}]}
        with self.assertRaisesRegex(ValueError, 'one model-fit answer'):
            score.replay_fits(self.core, self.config, entry)

    def test_partial_coverage_and_empty_runs_never_pass(self):
        rows = [dict(task='ok', type='make', q=1, usd=1), dict(task='unknown', type='make', q=None, usd=None)]
        s = score.summarize(rows, {'make': {'q': 1, 'n': 2}})
        self.assertEqual(s['make']['n'], 2)
        self.assertFalse(s['overall']['gate'])
        self.assertIsNone(s['overall']['q'])
        self.assertFalse(score.summarize([], {})['overall']['gate'])
