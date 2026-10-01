"""Routing invariants: no paid inference, private temporary configuration."""
import argparse
import contextlib
import copy
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
import urllib.error

REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('alloy_test_core', str(REPO / 'bin/alloy'))
spec = importlib.util.spec_from_loader(loader.name, loader)
core = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = core
loader.exec_module(core)
r = core.routing


def response(tier='small', confidence=1, risk=0, ambiguous=0):
    answers = {}
    for name, question in r.questions().items():
        if question['type'] == 'choice':
            choice = tier if name == 'complexity' else 'implementation'
            answers[name] = dict(type='choice', choice=choice, confidence=confidence,
                probabilities={k: int(k == choice) for k in question['criteria']})
        else:
            answers[name] = dict(type='noul', noul=risk if name == 'risk' else ambiguous)
    return dict(model='jev-test', answers=answers, usage=dict(input_tokens=100, output_tokens=50))


class RoutingCase(unittest.TestCase):
    """Shared scaffolding: a private routing home, the shipped starter config, and no way to
    reach a real Cursor process (the OS boundary and every metadata call are mocked)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'ALLOY_ROUTING_HOME': self.tmp.name, 'ALLOY_CONFIG': '/dev/null', 'ALLOY_USAGE': 'off'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.settings = patch.object(core, '_CONFIG', {})
        self.settings.start(); self.addCleanup(self.settings.stop)
        # The real gateway would run the macOS sandbox preflight (Lane 6 owns that gate) and
        # spawn cursor-agent when it is installed. Tests never do: refuse unless a test opts in.
        refused = core.CursorBoundary(False, 'mocked in tests', '', None)
        self.boundary = patch.object(core, 'cursor_boundary', return_value=refused)
        self.boundary.start(); self.addCleanup(self.boundary.stop)
        self.metadata = patch.object(core, 'cursor_metadata',
                                     side_effect=core.CursorBoundaryError('mocked in tests'))
        self.metadata.start(); self.addCleanup(self.metadata.stop)
        for k in list(os.environ):
            if k.startswith('ALLOY_') and k not in ('ALLOY_ROUTING_HOME', 'ALLOY_CONFIG', 'ALLOY_USAGE'):
                os.environ.pop(k)
        self.config = r.starter(core)
        # Generic tier tests use consult mode; the shipped consult floor has its own test.
        self.config['policy'].pop('min_tier_by_mode', None)
        r.save(r.root() / 'routing.json', self.config)
        self.available = {n: dict(status='ready', compatible=True, version='test') for n in r.FAMILIES}
        r.save(r.root() / 'models-cache.json', dict(refreshed_at=r.time.time(), adapters=self.available))
        self.args = argparse.Namespace(mode='consult', exclude_family='', host_family=None,
            panelists=None, profile=None, max_estimated_usd=None)

    def decide(self, answer=None):
        return r.route(core, 'Change the README title to Alloy.', self.args,
            transport=lambda payload: (answer or response(), 5), available=self.available)

    def live(self, **pools):
        """A fresh usage snapshot: adapter -> (remaining fraction, share of a 7d window still to run)."""
        now = r.time.time()
        return dict(enabled=True, ttl_seconds=120, providers={
            name: dict(status='fresh', observed_at=now, windows=[dict(
                pool=name, window='7d', remaining_fraction=left, resets_at=now + share * 7 * 86400)])
            for name, (left, share) in pools.items()})


class RouterTests(RoutingCase):
    def test_role_effort_applies_before_evidence_and_preserves_pins(self):
        p = next(p for p in self.config['profiles'] if p['id'] == 'claude-large')
        p['effort_by_mode'] = {'make': 'low', 'review': 'high'}
        self.args.profile = p['id']
        self.args.mode = 'make'; self.args.host_family = 'openai'
        maker = r.resolve(core, self.config, response('large')['answers'], self.available, self.args)
        self.assertEqual(maker['effort'], 'low')
        self.assertEqual(maker['model_evidence']['status'], 'effort-unverified')
        self.args.mode = 'review'; self.args.exclude_family = 'openai'
        review = r.resolve(core, self.config, response('large')['answers'], self.available, self.args)
        self.assertEqual(review['effort'], 'high')
        self.assertEqual(review['effort_source'], 'mode')
        argv = r.routed_adapter(core, review).build_args('prompt', 'last', 'review')
        self.assertEqual(argv[argv.index('--effort') + 1], 'high')
        self.assertEqual(review['model_evidence']['status'], 'matched')
        for override, expected in [('medium', 'medium'), ('inherit', None)]:
            with patch.dict(os.environ, ALLOY_CLAUDE_EFFORT=override):
                decision = r.resolve(core, self.config, response('large')['answers'], self.available, self.args)
            self.assertEqual(decision['effort'], expected)
            self.assertEqual(decision['effort_source'], 'override')
        self.assertEqual(p['effort'], 'medium')  # config never mutated

    def test_role_effort_validation(self):
        for value in ([], {'unknown': 'high'}, {'review': 'unlimited'}, {'review': 1}):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config['profiles'][0]['effort_by_mode'] = value
                with self.assertRaisesRegex(r.RoutingError, 'effort_by_mode'):
                    r.validate(config)

    def test_jev_receives_both_efforts_in_one_request(self):
        self.args.mode = 'make'; self.args.host_family = 'openai'
        captured = []
        def transport(payload):
            captured.append(payload)
            reply = response('large')
            for key in payload['questions']:
                if key.startswith(('fit_', 'review_fit_')):
                    reply['answers'][key] = dict(type='noul', noul=.9 if key.startswith('review_') else .1)
            return reply, 1
        decision = r.route(core, 'Implement a scoped feature', self.args,
                           transport=transport, available=self.available, usage_snapshot={})
        self.assertEqual(len(captured), 1)
        payload = captured[0]
        maker = next(c for c in payload['state']['models'] if c['profile'] == 'claude-large')
        checker = next(c for c in payload['state']['review_models'] if c['profile'] == 'claude-large')
        self.assertEqual(maker['effort'], 'medium')
        self.assertEqual(checker['effort'], 'high')
        self.assertEqual(checker['mode'], 'review')
        self.assertIn('effort_guidance', checker)
        self.assertEqual(decision['review_model_fits']['claude-large'], .9)
        self.assertIn('review_fit_0', decision['answers'])
        self.assertIn('independent review', payload['questions']['review_fit_0']['instructions'])

    def test_execute_uses_review_specific_jev_judgments(self):
        maker = dict(family='google', answers=response()['answers'], review_model_fits={'claude-large': .9})
        checker = dict(family='anthropic')
        args = argparse.Namespace(max_estimated_usd=None, route=True, maker_profile=None,
                                  checker_profile=None, host_family='openai')
        with patch.object(r, 'inventory', return_value=self.available), patch.object(r.usage, 'get', return_value={}), \
             patch.object(r, 'route', return_value=maker), patch.object(r, 'resolve', return_value=checker) as resolve, \
             patch.object(core.execution, 'probe'):
            core.execution.select(core, args, 'task')
        self.assertEqual(resolve.call_args.args[-1], {'claude-large': .9})
        self.assertEqual(resolve.call_args.args[4].mode, 'review')

    def test_grok_47_default_preserves_pins_and_separates_fast_evidence(self):
        with patch.dict(os.environ, {'ALLOY_GROK_MODEL': ''}):
            profiles = r.starter(core)['profiles']
            self.assertEqual(next(p['model'] for p in profiles if p['adapter'] == 'grok'), 'grok-4.7')
        with patch.dict(os.environ, {'ALLOY_GROK_MODEL': 'grok-4.6'}):
            self.assertEqual(next(p['model'] for p in r.starter(core)['profiles'] if p['adapter'] == 'grok'), 'grok-4.6')
        data = r.evidence.catalog()
        data['status'] = 'current'
        profile = dict(adapter='grok', model='grok-4.7', family='xai', effort='high')
        self.assertEqual(r.evidence.assessment(profile, data)['status'], 'matched')
        profile['model'] = 'grok-4.7-build-fast'
        self.assertEqual(r.evidence.assessment(profile, data)['status'], 'unmatched')

    def test_opus_efficiency_and_price_advice_do_not_change_billing(self):
        profile = next(p for p in self.config['profiles'] if p['id'] == 'claude-large')
        self.assertEqual(profile['model'], 'claude-opus-5-5')
        self.assertEqual(profile['effort'], 'medium')
        data = r.evidence.catalog(); data['status'] = 'current'
        advice = r.evidence.assessment(profile, data)
        self.assertIn('implementation', advice['preferred_tasks'])
        self.assertEqual(advice['api_pricing']['output_per_million'], 20)
        self.assertEqual(profile['billing_mode'], 'unknown')
        self.assertIsNone(r.estimate(profile, self.config))
        profile['billing_mode'] = 'metered'
        profile.update(input_per_million=7, output_per_million=30)
        self.assertEqual(r.estimate(profile, self.config), .13)
        r.evidence.advise(core, self.config, data, {})
        self.assertEqual(profile['input_per_million'], 7)
        profile['model'] = 'opus'
        self.assertEqual(r.evidence.assessment(profile, data)['status'], 'unmatched')

    def test_current_models_are_routable_with_explicit_pins(self):
        wanted = {'gpt-6-sol', 'claude-opus-5-5', 'grok-4.7',
                  'gemini-3.8-flash-low', 'gemini-3.8-flash-medium',
                  'gemini-3.8-flash-high', 'gemini-3.1-pro-low', 'gemini-3.1-pro-high'}
        self.assertTrue(wanted <= {p['model'] for p in self.config['profiles']})
        # gpt-6-sol ships disabled (ChatGPT-account Codex rejects it) but routes once enabled.
        sol = next(p for p in self.config['profiles'] if p['model'] == 'gpt-6-sol')
        self.assertFalse(sol['enabled'])
        sol['enabled'] = True
        r.save(r.root() / 'routing.json', self.config)
        for model in wanted:
            p = next(p for p in self.config['profiles'] if p['model'] == model)
            self.args.profile = p['id']
            with patch.dict(os.environ, {r.MODEL_KEYS[p['adapter']]: model}):
                decision = self.decide()
            self.assertEqual(decision['model'], model)
        data = r.evidence.catalog(); data['status'] = 'current'
        low = dict(model='gemini-3.8-flash-low', family='google', effort='low')
        self.assertEqual(r.evidence.assessment(low, data)['status'], 'unmatched')

    def test_verified_failures_escalate_and_reach_jev(self):
        for count, tier in ((0, 'small'), (1, 'medium'), (2, 'large')):
            self.args.prior_failures = count
            captured = []
            def transport(payload):
                captured.append(payload['state']['retry_context'])
                return response(), 1
            decision = r.route(core, 'Fix typo', self.args, transport=transport, available=self.available)
            self.assertEqual(decision['required_tier'], tier)
            self.assertEqual(captured[0]['verified_quality_failures'], count)
            self.assertEqual(decision['retry_context'], captured[0])

    def test_failed_profiles_excluded_without_overriding_pin(self):
        self.args.prior_failures = 2
        chosen = self.decide()['profile']
        self.args.failed_profile = [chosen]
        self.assertNotEqual(self.decide()['profile'], chosen)
        self.args.profile = chosen
        with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
            self.decide()

    def test_invalid_failure_context_rejected_before_inference(self):
        for count, failed in ((-1, []), (101, []), (True, []), (0, ['codex-small']), (1, ['missing'])):
            self.args.prior_failures = count
            self.args.failed_profile = failed
            transport = Mock()
            with self.assertRaises(r.RoutingError):
                r.route(core, 'Task', self.args, transport=transport, available=self.available)
            transport.assert_not_called()

    def test_failed_checker_cannot_satisfy_independence(self):
        checker = self.checker_fixture()
        self.args.prior_failures = 1
        self.args.failed_profile = [checker['id']]
        r.save(r.root() / 'routing.json', self.config)
        with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
            self.decide()

    def evidence_pair(self):
        data = r.evidence.catalog(); data['status'] = 'current'
        catalog_patch = patch.object(r.evidence, 'catalog', return_value=data)
        catalog_patch.start(); self.addCleanup(catalog_patch.stop)
        base = self.config['profiles'][0]
        self.config['profiles'] = [dict(base, id='cheap', model='gpt-5.6-terra', tier='large', effort='high', cost_rank=2),
            dict(base, id='fit', model='gpt-5.6-sol', tier='large', effort='high', cost_rank=2.4)]
        return self.config['profiles']

    def kind_answer(self, kind, tier='medium', confidence=1):
        reply = response(tier)
        reply['answers']['kind'].update(choice=kind, confidence=confidence,
            probabilities={k: int(k == kind) for k in r.questions()['kind']['criteria']})
        return reply

    def test_jev_receives_model_metrics_and_fit_changes_bounded_choice(self):
        self.evidence_pair(); r.save(r.root() / 'routing.json', self.config)
        captured = []
        def transport(payload):
            captured.append(payload)
            reply = self.kind_answer('implementation')
            reply['answers'].update(fit_0=dict(type='noul', noul=.1),
                                    fit_1=dict(type='noul', noul=.9))
            return reply, 1
        decision = r.route(core, 'Implement a complex change', self.args,
                           transport=transport, available=self.available)
        self.assertEqual(len(captured), 1)
        self.assertEqual(decision['profile'], 'fit')
        self.assertEqual(decision['jev_task_fit'], .9)
        card = captured[0]['state']['models'][0]
        self.assertEqual(card['billing_mode'], 'unknown')
        self.assertIsNone(card['estimated_api_usd'])
        self.assertIsNone(card['measured_success_rate'])
        self.assertIn('strengths', card)
        self.config['profiles'][1]['cost_rank'] = 3
        r.save(r.root() / 'routing.json', self.config)
        decision = r.route(core, 'Implement a complex change', self.args,
                           transport=transport, available=self.available)
        self.assertEqual(decision['profile'], 'cheap')

    def test_model_cards_are_bounded_allowlisted_and_honor_effort(self):
        self.config['profiles'][0]['secret'] = 'DO-NOT-SEND'
        self.available['codex']['auth'] = 'DO-NOT-SEND'
        with patch.dict(os.environ, {'ALLOY_CODEX_EFFORT': 'low'}):
            cards = r.model_context(core, self.config, self.available, {},
                                    dict(failed_profiles=[]))
        self.assertNotIn('DO-NOT-SEND', json.dumps(cards))
        self.assertEqual(cards[0]['effort'], 'low')
        self.assertEqual(cards[0]['evidence_status'], 'effort-unverified')
        self.assertEqual(r.model_fits(dict(answers={'fit_0':dict(type='noul',noul=.99)}), cards), {})
        self.config['profiles'] = [dict(self.config['profiles'][0], id=str(i)) for i in range(100)]
        self.assertEqual(len(r.model_context(core, self.config, self.available, {},
                         dict(failed_profiles=[]))), 32)

    def test_invalid_model_fit_fails_closed(self):
        for value in (True, -1, float('nan'), 1.1):
            reply = response(); reply['answers']['fit_0'] = dict(type='noul', noul=value)
            with self.assertRaisesRegex(r.RoutingError, 'model-fit'):
                self.decide(reply)

    def test_task_fit_prefers_documented_debugger_with_bounded_premium(self):
        self.evidence_pair(); r.save(r.root() / 'routing.json', self.config)
        with patch.object(r.evidence.time, 'time', return_value=1789680000):
            decision = self.decide(self.kind_answer('debugging'))
        self.assertEqual(decision['profile'], 'fit')
        self.assertEqual(decision['cheapest_eligible'], 'cheap')
        self.assertEqual(decision['recommendations'][0]['profile'], 'fit')
        self.assertTrue(decision['model_evidence']['sources'])
        self.assertEqual(decision['evidence_revision'], r.evidence.catalog()['revision'])

    def test_fit_does_not_overpay_or_escalate_small_tasks(self):
        rows = self.evidence_pair(); rows[1]['cost_rank'] = 3
        r.save(r.root() / 'routing.json', self.config)
        self.assertEqual(self.decide(self.kind_answer('debugging'))['profile'], 'cheap')
        rows[1]['cost_rank'] = 2.4; r.save(r.root() / 'routing.json', self.config)
        self.assertEqual(self.decide(self.kind_answer('debugging', 'small'))['profile'], 'cheap')

    def test_low_kind_confidence_stale_and_disabled_evidence_abstain(self):
        self.evidence_pair(); r.save(r.root() / 'routing.json', self.config)
        self.assertEqual(self.decide(self.kind_answer('debugging', confidence=.3))['profile'], 'cheap')
        stale = dict(r.evidence.catalog(), status='stale')
        with patch.object(r.evidence, 'catalog', return_value=stale):
            self.assertEqual(self.decide(self.kind_answer('debugging'))['profile'], 'cheap')
        self.config['policy']['use_model_evidence'] = False
        r.save(r.root() / 'routing.json', self.config)
        self.assertEqual(self.decide(self.kind_answer('debugging'))['profile'], 'cheap')

    def test_wrong_model_family_alias_or_effort_gets_no_benchmark_credit(self):
        data = r.evidence.catalog(); data['status'] = 'current'
        for changes in (dict(model='gpt-5.6-sol-new'), dict(model='sonnet'),
                        dict(family='google'), dict(effort='none')):
            p = dict(model='gpt-5.6-sol', family='openai', effort='high'); p.update(changes)
            self.assertEqual(r.evidence.assessment(p, data)['preferred_tasks'], [])

    def test_fit_respects_pin_and_price_ceiling(self):
        self.evidence_pair(); r.save(r.root() / 'routing.json', self.config)
        with patch.dict(os.environ, {'ALLOY_CODEX_MODEL': 'gpt-5.6-terra'}):
            self.assertEqual(self.decide(self.kind_answer('debugging'))['profile'], 'cheap')
        self.args.max_estimated_usd = .1
        with self.assertRaises(r.RoutingError): self.decide(self.kind_answer('debugging'))

    def test_effort_override_disables_unverified_preference(self):
        self.evidence_pair(); r.save(r.root() / 'routing.json', self.config)
        with patch.dict(os.environ, {'ALLOY_CODEX_EFFORT': 'none'}):
            self.assertEqual(self.decide(self.kind_answer('debugging'))['profile'], 'cheap')

    def test_comparable_metered_prices_override_ordinal_ranks(self):
        rows = self.evidence_pair()
        rows[0].update(billing_mode='metered', input_per_million=10, output_per_million=50)
        rows[1].update(billing_mode='metered', input_per_million=1, output_per_million=5, cost_rank=100)
        r.save(r.root() / 'routing.json', self.config)
        d = self.decide()
        self.assertEqual(d['profile'], 'fit')
        self.assertEqual(d['cost_basis'], 'estimated_usd')
        self.assertAlmostEqual(d['selection_cost'], .02)

    def test_user_task_preferences_and_configuration_validation(self):
        rows = self.evidence_pair(); rows[1]['model'] = 'custom-model'
        rows[1]['task_preferences'] = ['debugging']
        r.save(r.root() / 'routing.json', self.config)
        self.assertEqual(self.decide(self.kind_answer('debugging'))['profile'], 'fit')
        rows[1]['task_preferences'] = ['invented']
        with self.assertRaises(r.RoutingError): r.validate(self.config)
        rows[1]['task_preferences'] = []
        for field in ('task_fit_cost_slack', 'kind_confidence_floor'):
            self.config['policy'][field] = float('nan')
            with self.assertRaises(r.RoutingError): r.validate(self.config)
            self.config['policy'].pop(field)

    def test_catalog_expiry_and_missing_file_are_explicit(self):
        with patch.object(r.evidence.time, 'time', return_value=1900000000):
            self.assertEqual(r.evidence.catalog()['status'], 'stale')
        with patch.object(r.evidence, 'PATH', Path(self.tmp.name)/'absent'):
            self.assertEqual(r.evidence.catalog()['status'], 'unavailable')

    def test_models_advice_is_read_only_and_explains_pins(self):
        before = (r.root() / 'routing.json').read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.dict(os.environ, {'ALLOY_CODEX_MODEL': 'gpt-5.6-sol'}):
            self.assertEqual(core.main(['models', 'advise']), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(any(p['blocked_by_pin'] for p in result['profiles']))
        self.assertTrue(result['candidates'])
        self.assertEqual(before, (r.root() / 'routing.json').read_bytes())

    def test_small_and_large_choose_different_profiles(self):
        small = self.decide()
        self.assertEqual(small['required_tier'], 'small')
        self.assertEqual(self.decide(response('large'))['required_tier'], 'large')
        self.assertNotEqual(self.decide(response('large'))['profile'], small['profile'])

    def test_uncertainty_and_risk_raise_floor(self):
        for reply in (response(confidence=.2), response(risk=.9), response(ambiguous=.9), response('unknown')):
            self.assertEqual(self.decide(reply)['required_tier'], 'large')

    def test_unknown_billing_is_not_free(self):
        self.assertIsNone(self.decide()['estimated_usd'])
        self.args.max_estimated_usd = .1
        with self.assertRaises(r.RoutingError): self.decide()

    def test_metered_budget_filters_cost_and_keeps_ranks(self):
        for p in self.config['profiles']:
            p.update(billing_mode='metered', input_per_million=1, output_per_million=2)
        r.save(r.root() / 'routing.json', self.config)
        self.args.max_estimated_usd = .02
        self.assertAlmostEqual(self.decide()['estimated_usd'], .014)
        self.args.max_estimated_usd = .001
        with self.assertRaises(r.RoutingError): self.decide()

    def test_shared_quota_reserve(self):
        for p in self.config['profiles']:
            if p['adapter'] in ('codex', 'antigravity'):
                p.update(billing_mode='subscription', quota_pool='shared')
        self.config['quota_pools']['shared'] = dict(remaining_fraction=.05, reserve_fraction=.1)
        r.save(r.root() / 'routing.json', self.config)
        self.assertNotIn(self.decide()['cli'], ('codex', 'antigravity'))

    def test_unavailable_or_incompatible_excluded(self):
        self.available['codex']['compatible'] = False
        self.available['antigravity']['status'] = 'not_installed'
        self.assertEqual(self.decide()['cli'], 'claude')

    def test_profile_and_environment_override(self):
        self.args.profile = 'claude-medium'
        self.assertEqual(self.decide()['cli'], 'claude')
        with patch.dict(os.environ, {'ALLOY_CLAUDE_MODEL': 'different-model'}):
            with self.assertRaises(r.RoutingError): self.decide()

    def test_explicit_make_requires_host_and_other_checker(self):
        self.args.mode = 'make'
        with self.assertRaises(r.RoutingError): self.decide()
        self.args.host_family = 'openai'
        d = self.decide()
        self.assertNotEqual(d['family'], 'openai')
        for name in ('claude', 'grok'): self.available[name]['status'] = 'not_installed'
        with self.assertRaises(r.RoutingError): self.decide()

    def test_family_is_model_family_even_on_agy(self):
        self.config['profiles'] = [dict(self.config['profiles'][-1], family='anthropic', model='claude-future')]
        r.save(r.root() / 'routing.json', self.config)
        self.args.exclude_family = 'anthropic'
        with self.assertRaises(r.RoutingError): self.decide()

    def checker_fixture(self):
        self.config['profiles'] = [p for p in self.config['profiles']
            if p['adapter'] == 'antigravity' or p['id'] == 'claude-medium']
        self.args.mode = 'make'
        self.args.host_family = 'openai'
        self.args.profile = 'antigravity-medium'
        self.args.panelists = 'antigravity'
        return next(p for p in self.config['profiles'] if p['adapter'] == 'claude')

    def test_checker_respects_model_pin_but_not_maker_selection(self):
        self.checker_fixture()
        r.save(r.root() / 'routing.json', self.config)
        self.assertEqual(self.decide()['cli'], 'antigravity')
        with patch.dict(os.environ, {'ALLOY_CLAUDE_MODEL': 'opus'}):
            with self.assertRaises(r.RoutingError): self.decide()

    def test_checker_respects_manual_quota_reserve(self):
        checker = self.checker_fixture()
        checker.update(billing_mode='subscription', quota_pool='claude')
        self.config['quota_pools']['claude'] = dict(remaining_fraction=.05, reserve_fraction=.1)
        r.save(r.root() / 'routing.json', self.config)
        with self.assertRaises(r.RoutingError): self.decide()

    def test_checker_respects_explicit_family_exclusion(self):
        self.checker_fixture()
        self.args.exclude_family = 'anthropic'
        r.save(r.root() / 'routing.json', self.config)
        with self.assertRaises(r.RoutingError): self.decide()

    def test_checker_meets_task_tier(self):
        checker = self.checker_fixture()
        checker['tier'] = 'small'
        r.save(r.root() / 'routing.json', self.config)
        with self.assertRaises(r.RoutingError): self.decide(response('medium'))

    def test_checker_respects_estimated_spend_ceiling(self):
        checker = self.checker_fixture()
        for p in self.config['profiles']:
            p['billing_mode'] = 'subscription'
        checker.update(billing_mode='metered', input_per_million=100, output_per_million=100)
        self.args.max_estimated_usd = .1
        r.save(r.root() / 'routing.json', self.config)
        with self.assertRaises(r.RoutingError): self.decide()

    def test_new_model_needs_only_catalog_data(self):
        p = dict(self.config['profiles'][0], id='new-model', model='gpt-next', cost_rank=0)
        self.config['profiles'].append(p)
        r.save(r.root() / 'routing.json', self.config)
        self.assertEqual(self.decide()['model'], 'gpt-next')

    def test_catalog_commands_add_update_disable(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(core.main(['models', 'add', '--id', 'future', '--cli', 'antigravity',
                '--model', 'claude-future', '--family', 'anthropic', '--tier', 'large', '--cost-rank', '2']), 0)
            self.assertEqual(core.main(['models', 'add', '--id', 'future', '--cost-rank', '3']), 0)
            self.assertEqual(core.main(['models', 'disable', '--id', 'future']), 0)
        profile = next(p for p in r.load()['profiles'] if p['id'] == 'future')
        self.assertEqual(profile['cost_rank'], 3)
        self.assertFalse(profile['enabled'])
        self.assertEqual(profile['family'], 'anthropic')

    def test_cli_help_change_excludes_adapter(self):
        ad = core.ADAPTERS['codex']
        def output(argv, **kwargs):
            self.assertNotIn('TYPESAFE_API_KEY', kwargs['env'])
            return Mock(returncode=0, stdout='new-version' if '--version' in argv else '--model ONLY', stderr='')
        with patch.object(ad, 'resolved_bin', return_value='/usr/local/bin/mock'), patch.object(r.subprocess, 'run', side_effect=output), patch.dict(os.environ, {'TYPESAFE_API_KEY': 'secret'}):
            result = r.probe(core, 'codex')
        self.assertFalse(result['compatible'])

    def test_discovery_new_model_keeps_profiles_unchanged(self):
        before = (r.root() / 'routing.json').read_text()
        def output(argv, **kwargs):
            model = 'grok-new' if 'grok' in argv[0] else 'gemini-new'
            return Mock(returncode=0, stdout=model, stderr='')
        with patch.object(r.subprocess, 'run', side_effect=output), \
             patch.object(core.ADAPTERS['grok'], 'resolved_bin', return_value='/mock/grok'), \
             patch.object(core.ADAPTERS['antigravity'], 'resolved_bin', return_value='/mock/agy'):
            cache = r.refresh(core, self.available)
        self.assertIn('grok-new', cache['discovered']['grok']['models'])
        self.assertEqual(before, (r.root() / 'routing.json').read_text())

    def test_response_rejects_nan_wrong_keys_and_wrong_choice(self):
        variants = []
        a = response(); a['answers']['risk']['noul'] = float('nan'); variants.append(a)
        a = response(); a['answers']['complexity']['probabilities']['extra'] = 0; variants.append(a)
        a = response(); a['answers']['complexity']['choice'] = 'large'; variants.append(a)
        a = response(); a['usage']['input_tokens'] = -1; variants.append(a)
        for a in variants:
            with self.assertRaises(r.RoutingError): self.decide(a)

    def test_config_rejects_duplicates_bad_values_and_future_schema(self):
        variants = []
        a = copy.deepcopy(self.config); a['profiles'].append(a['profiles'][0]); variants.append(a)
        a = copy.deepcopy(self.config); a['profiles'][0]['cost_rank'] = float('nan'); variants.append(a)
        a = copy.deepcopy(self.config); a['schema'] = 99; variants.append(a)
        for a in variants:
            with self.assertRaises(r.RoutingError): r.validate(a)

    def test_log_does_not_contain_task_or_key(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'private-value'}): self.decide()
        log = next((r.root() / 'routing-history').glob('*.json'))
        self.assertNotIn('Change the README', log.read_text())
        self.assertNotIn('private-value', log.read_text())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_key_file_permissions_and_env_precedence(self):
        r.save(r.root() / 'jev-key', 'file-value')
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'env-value'}):
            self.assertEqual(r.key(), 'env-value')
            self.assertNotIn('TYPESAFE_API_KEY', r.clean_env())
        with patch.dict(os.environ, {}, clear=True):
            os.environ['ALLOY_ROUTING_HOME'] = self.tmp.name
            self.assertEqual(r.key(), 'file-value')
            (r.root() / 'jev-key').chmod(0o644)
            with self.assertRaises(r.RoutingError): r.key()

    def test_openrouter_transport_uses_decisions_and_separate_key(self):
        r.save(r.root() / 'openrouter-key', 'router-secret')
        r.save(r.root() / 'jev-key', 'direct-secret')
        result = response()
        result['usage']['cost'] = 0.00001
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=Mock(read=Mock(return_value=json.dumps(result).encode())))
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': '', 'TYPESAFE_API_KEY': ''}), patch.object(r.urllib.request, 'build_opener', return_value=opener):
            actual, latency = r.request({'model': '~typesafe/jev-latest'}, provider='openrouter')
        req = opener.open.call_args[0][0]
        self.assertEqual(req.full_url, 'https://openrouter.ai/api/alpha/decisions')
        self.assertEqual(req.get_header('Authorization'), 'Bearer router-secret')
        self.assertEqual(json.loads(req.data)['model'], '~typesafe/jev-latest')
        self.assertEqual(actual, result)
        r.checked_answers(actual)

    def test_openrouter_key_never_falls_back_to_typesafe(self):
        r.save(r.root() / 'jev-key', 'direct-secret')
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': '', 'TYPESAFE_API_KEY': 'direct-env'}):
            with self.assertRaisesRegex(r.RoutingError, 'openrouter key missing'):
                r.key('openrouter')
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'router-env'}):
            self.assertEqual(r.key('openrouter'), 'router-env')
            self.assertNotIn('OPENROUTER_API_KEY', r.clean_env())
            self.assertNotIn('OPENROUTER_API_KEY', r.usage.provider_env(core))
        r.save(r.root() / 'openrouter-key', 'file-secret')
        (r.root() / 'openrouter-key').chmod(0o644)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            with self.assertRaisesRegex(r.RoutingError, 'owner-only'):
                r.key('openrouter')

    def test_provider_switch_preserves_profiles_and_direct_model_pin(self):
        self.config['jev_model'] = 'jev-pinned'
        r.save(r.root() / 'routing.json', self.config)
        args = argparse.Namespace(non_interactive=True, skip_live_test=True, billing=[], jev_provider='openrouter')
        with patch.object(r, 'inventory', return_value=self.available), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            r.setup(core, args)
        config = r.load()
        self.assertEqual(config['profiles'], self.config['profiles'])
        self.assertEqual(config['jev_model'], 'jev-pinned')
        self.assertEqual(r.jev_model(config), '~typesafe/jev-latest')
        with patch.object(r, 'request', return_value=(response(), 1)) as request:
            decision = r.route(core, 'Fix typo', self.args, available=self.available)
        self.assertEqual(request.call_args[1], {'provider': 'openrouter'})
        self.assertEqual(request.call_args[0][0]['model'], '~typesafe/jev-latest')
        self.assertEqual(decision['jev_provider'], 'openrouter')
        config['openrouter_model'] = '~typesafe/jev-1.13'
        self.assertEqual(r.jev_model(config), '~typesafe/jev-1.13')
        config['jev_provider'] = 'typesafe'
        self.assertEqual(r.jev_model(config), 'jev-pinned')
        for invalid in ('other', None, []):
            config['jev_provider'] = invalid
            with self.assertRaises(r.RoutingError): r.validate(config)

    def test_openrouter_incomplete_probabilities_fail_closed(self):
        result = response()
        del result['answers']['complexity']['probabilities']
        self.config['jev_provider'] = 'openrouter'
        r.save(r.root() / 'routing.json', self.config)
        with self.assertRaises(r.RoutingError): self.decide(result)

    def test_http_retry_bounded_and_error_body_not_exposed(self):
        error = lambda: urllib.error.HTTPError('url', 429, 'secret-body', {'Retry-After': '0'}, io.BytesIO(b'secret-body'))
        opener = Mock(); opener.open.side_effect = [error(), error(), error()]
        with patch.object(r, 'key', return_value='secret'), patch.object(r.urllib.request, 'build_opener', return_value=opener), patch.object(r.time, 'sleep'):
            with self.assertRaisesRegex(r.RoutingError, 'HTTP 429'): r.request({})
        self.assertEqual(opener.open.call_count, 3)

    def test_http_401_does_not_retry_or_reveal_body(self):
        opener = Mock(); opener.open.side_effect = urllib.error.HTTPError('url', 401, 'secret', {}, io.BytesIO(b'secret-body'))
        with patch.object(r, 'key', return_value='secret'), patch.object(r.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(r.RoutingError, 'HTTP 401'): r.request({})
        self.assertEqual(opener.open.call_count, 1)

    def test_route_adapter_does_not_mutate_default(self):
        self.args.profile = 'codex-small'
        before = core.ADAPTERS['codex'].model()
        decision = self.decide()
        ad = r.routed_adapter(core, decision)
        argv = ad.build_args('p', 'out', 'consult')
        self.assertIn(decision['model'], argv)
        self.assertIn('model_reasoning_effort=medium', argv)
        self.assertEqual(core.ADAPTERS['codex'].model(), before)

    def test_shipped_defaults_refresh_is_additive_private_and_idempotent(self):
        original = dict(self.config['profiles'][0], model='custom-pinned',
                        enabled=False, billing_mode='subscription', cost_rank=17)
        disabled = dict(self.config['profiles'][1], model='gpt-6-sol',
                        enabled=False, effort='low', billing_mode='subscription')
        self.config['profiles'] = [original, disabled]
        r.save(r.root() / 'routing.json', self.config)
        args = argparse.Namespace(non_interactive=True, skip_live_test=True,
                                  billing=[], refresh_defaults=True)
        with patch.object(r, 'inventory', return_value=self.available), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            r.setup(core, args)
            first = r.load()
            r.setup(core, args)
        self.assertEqual(first, r.load())
        self.assertEqual(first['profiles'][:2], [original, disabled])
        self.assertEqual(sum(p['model'] == 'gpt-6-sol' for p in first['profiles']), 1)
        self.assertTrue(any(p['model'] == 'claude-opus-5-5' for p in first['profiles']))
        self.assertTrue(all(p['billing_mode'] == 'subscription' for p in first['profiles'] if p['adapter'] == 'codex'))
        self.assertEqual((r.root() / 'routing.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse((r.root() / 'jev-key').exists())
        self.assertFalse((r.root() / 'openrouter-key').exists())

    def test_keyless_setup_and_context_never_read_key_or_call_jev(self):
        args = argparse.Namespace(non_interactive=False, skip_live_test=False,
                                  billing=[], keyless=True)
        unavailable = {name:dict(status='missing', compatible=False) for name in r.FAMILIES}
        with patch.object(r, 'inventory', return_value=unavailable), patch.object(r.sys.stdin, 'isatty', return_value=True), patch.object(r.getpass, 'getpass') as prompt, patch.object(r, 'key') as key, patch.object(r, 'request') as request, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(r.setup(core, args), 0)
            self.assertEqual(core.main(['models', 'context']), 0)
        prompt.assert_not_called(); key.assert_not_called(); request.assert_not_called()
        self.assertFalse((r.root() / 'jev-key').exists())
        self.assertFalse((r.root() / 'openrouter-key').exists())

    def test_host_assessment_enforces_large_floor_without_jev(self):
        self.args.profile = 'codex-small'
        for assessment in (dict(task_tier='large'), dict(task_risk=True), dict(task_ambiguous=True)):
            answers = core.execution.host_assessment(argparse.Namespace(**assessment))
            with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
                r.resolve(core, self.config, answers, self.available, self.args, {})

    def test_min_tier_by_mode_floors_only_that_mode(self):
        answers = core.execution.host_assessment(argparse.Namespace(task_tier='small', task_kind='research'))
        self.config['policy']['min_tier_by_mode'] = {'consult': 'medium'}
        self.args.mode = 'consult'
        d = r.resolve(core, self.config, answers, self.available, self.args, {})
        self.assertEqual(d['required_tier'], 'medium')
        self.assertIn('mode consult requires at least medium', d['reason'])
        self.assertEqual(r.starter(core)['policy']['min_tier_by_mode'], {'consult': 'medium'})
        self.args.mode = 'review'
        self.assertEqual(r.resolve(core, self.config, answers, self.available, self.args, {})['required_tier'], 'small')
        for bad in ({'consult': 'huge'}, {'chat': 'large'}, ['consult']):
            self.config['policy']['min_tier_by_mode'] = bad
            with self.assertRaises(r.RoutingError):
                r.validate(self.config)

    def test_tier_by_mode_lets_a_small_maker_review_large_work(self):
        answers = core.execution.host_assessment(argparse.Namespace(task_tier='large'))
        for p in self.config['profiles']:
            p['enabled'] = p['id'] in ('codex-small', 'codex-large')
            p.pop('tier_by_mode', None)
        self.args.mode = 'review'
        self.assertEqual(r.resolve(core, self.config, answers, self.available, self.args, {})['profile'], 'codex-large')
        next(p for p in self.config['profiles'] if p['id'] == 'codex-small')['tier_by_mode'] = {'review': 'large'}
        self.assertEqual(r.resolve(core, self.config, answers, self.available, self.args, {})['profile'], 'codex-small')
        self.args.mode = 'consult'  # other modes keep the base tier
        self.assertEqual(r.resolve(core, self.config, answers, self.available, self.args, {})['profile'], 'codex-large')
        next(p for p in self.config['profiles'] if p['id'] == 'codex-small')['tier_by_mode'] = {'review': 'huge'}
        with self.assertRaises(r.RoutingError):
            r.validate(self.config)
        shipped = {p['id']: p for p in r.starter(core)['profiles']}
        self.assertEqual(shipped['codex-small']['tier_by_mode'], {'review': 'large'})
        self.assertEqual(shipped['antigravity-small']['tier_by_mode'], {'review': 'large'})

    def test_quota_pacing_is_opt_in_and_spares_the_host(self):
        self.assertEqual(r.usage.window_seconds('5h'), 5 * 3600)
        self.assertEqual(r.usage.window_seconds('weekly'), 7 * 86400)
        self.assertIsNone(r.usage.window_seconds('someday'))
        for p in self.config['profiles']:
            p['enabled'] = p['id'] in ('codex-small', 'antigravity-small')
            p['cost_rank'] = 1
        # Codex: 30% left but resets in 5% of the window (surplus); agy: 60% left, 90% to run (deficit).
        snap = self.live(codex=(.3, .05), antigravity=(.6, .9))
        answers = core.execution.host_assessment(argparse.Namespace(task_tier='small'))
        self.assertAlmostEqual(r.usage.pacing(dict(adapter='codex', model='x'), snap), .05 / .3, places=4)
        choose = lambda: r.resolve(core, self.config, answers, self.available, self.args, snap)['profile']
        self.assertEqual(choose(), 'antigravity-small')  # default: more headroom wins
        self.config['policy']['quota_pacing'] = True
        self.assertEqual(choose(), 'codex-small')        # pacing: use quota that will reset unused
        self.args.host_family = 'openai'                 # ... but never discount the host's own CLI
        self.assertEqual(choose(), 'antigravity-small')
        self.config['policy']['quota_pacing'] = 'yes'
        with self.assertRaises(r.RoutingError):
            r.validate(self.config)

    def test_reset_defaults_adopts_shipped_routing_and_keeps_account_choices(self):
        self.config['profiles'][0]['model'] = 'gpt-custom'
        self.config['profiles'].append(dict(self.config['profiles'][0], id='mine'))
        for p in self.config['profiles']:
            if p['adapter'] == 'codex':
                p['billing_mode'] = 'subscription'
        self.config['jev_provider'] = 'openrouter'
        self.config['quota_pools'] = {'plan': dict(remaining_fraction=.5, reserve_fraction=.1)}
        r.save(r.root() / 'routing.json', self.config)
        args = argparse.Namespace(non_interactive=True, skip_live_test=True, billing=[], reset_defaults=True)
        with patch.object(r, 'inventory', return_value=self.available), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            r.setup(core, args)
        new = r.load()
        shipped = r.starter(core)
        self.assertEqual([p['id'] for p in new['profiles']], [p['id'] for p in shipped['profiles']])
        self.assertEqual(new['policy'], shipped['policy'])
        self.assertEqual(new['jev_provider'], 'openrouter')
        self.assertIn('plan', new['quota_pools'])
        self.assertTrue(all(p['billing_mode'] == 'subscription' for p in new['profiles'] if p['adapter'] == 'codex'))
        self.assertTrue(all(p['billing_mode'] == 'unknown' for p in new['profiles'] if p['adapter'] == 'claude'))
        self.assertIn('gpt-custom', (r.root() / 'routing.json.bak').read_text())

    def test_setup_preserves_profiles_and_backs_up(self):
        self.config['profiles'][0]['model'] = 'gpt-custom'
        r.save(r.root() / 'routing.json', self.config)
        args = argparse.Namespace(non_interactive=True, skip_live_test=True, billing=['codex=subscription'])
        with patch.object(r, 'inventory', return_value=self.available), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            r.setup(core, args)
            r.setup(core, args)
        self.assertEqual(r.load()['profiles'][0]['model'], 'gpt-custom')
        self.assertEqual(r.load()['profiles'][0]['billing_mode'], 'subscription')
        self.assertTrue((r.root() / 'routing.json.bak').exists())

    def test_refresh_preserves_user_profiles_on_discovery_failure(self):
        before = (r.root() / 'routing.json').read_text()
        previous = dict(discovered={'grok': dict(models=['grok-cached'], observed_at=1)})
        r.save(r.root() / 'models-cache.json', previous)
        with patch.object(r, 'inventory', return_value=self.available), patch.object(r.subprocess, 'run', side_effect=OSError):
            cache = r.refresh(core)
        self.assertEqual(cache['discovered'], previous['discovered'])
        self.assertEqual((r.root() / 'routing.json').read_text(), before)

    def test_routed_panel_dispatch_manifest_and_key_isolation(self):
        # Real dispatcher with a fake executable; inspect actual argv and env.
        executable = Path(self.tmp.name) / 'mock'
        executable.write_text('#!/usr/bin/env python3\nimport os,sys,json\nprint(json.dumps({"argv":sys.argv[1:],"key_present":any(k in os.environ for k in ("TYPESAFE_API_KEY","OPENROUTER_API_KEY"))}))\n')
        executable.chmod(0o755)
        task = Path(self.tmp.name) / 'task'; task.write_text('Rename README heading')
        output = io.StringIO()
        with patch.dict(os.environ, {'ALLOY_BIN_CODEX': str(executable), 'CODEX_API_KEY': 'test', 'TYPESAFE_API_KEY': 'private', 'OPENROUTER_API_KEY': 'private-router', 'ALLOY_REPO': 'none'}), patch.object(r, 'inventory', return_value=self.available), patch.object(r, 'request', return_value=(response(), 1)), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = core.main(['panel', '--route', '--profile', 'codex-small', '--prompt-file', str(task), '--no-repo', '--run-dir', str(Path(self.tmp.name) / 'runs')])
        self.assertEqual(code, 0)
        manifest = json.loads(Path(output.getvalue().strip().splitlines()[-1]).read_text())
        self.assertEqual(manifest['routing']['model'], 'gpt-5.6-luna')
        body = Path(manifest['panelists'][0]['result_path']).read_text()
        self.assertIn('"key_present": false', body)
        self.assertIn('gpt-5.6-luna', body)


CURSOR_HELP = ('Usage: agent [options] [command] [prompt...]\n  -p, --print  Print responses\n'
               '  --output-format <format>  text | json\n  --mode <mode>  plan | ask\n'
               '  --model <model>  Model to use\n  --list-models  List available models and exit\n')
CURSOR_MODELS = '''Available models

auto - Auto (current, default)
gpt-5.3-codex-low - Codex 5.3 Low
composer-2.5 - Composer 2.5
claude-opus-5-thinking-high - Claude Opus 5 1M Thinking
gpt-5.6-sol-high - GPT-5.6 Sol 1M High
gpt-5.6-sol-high-fast - GPT-5.6 Sol 1M High Fast
cursor-grok-4.5-low - Grok 4.5 Low
gemini-3.8-flash-high - Gemini 3.8 Flash High
muse-spark-1.3-minimal - Muse Spark 1.3 1M Minimal
kimi-k3-low - Kimi K3 Low
glm-5.2-high - GLM 5.2

Tip: use --model <id> (or /model <id> in interactive mode) to switch.
'''


class CursorRoutingTests(RoutingCase):
    """Lane 2: Cursor families, independence, profiles, evidence identity, discovery, setup,
    effort/fast rewriting and dispatch. Mocks only: no Cursor process, sandbox or network."""
    SHIPPED = {'cursor-large-composer-2-5': ('composer-2.5', 'cursor', 'large'),
               'cursor-large-gpt-5-6-sol': ('gpt-5.6-sol-high', 'openai', 'large'),
               'cursor-large-claude-opus-5-5': ('claude-opus-5-5-high', 'anthropic', 'large'),
               'cursor-medium-gemini-3-8-flash': ('gemini-3.8-flash-high', 'google', 'medium'),
               'cursor-large-grok-4-7': ('grok-4.7-high', 'xai', 'large')}

    def profile(self, pid):
        return next(p for p in self.config['profiles'] if p['id'] == pid)

    def only(self, *ids):
        """Enable exactly these profiles (saved without validation, so tests can bypass it)."""
        for p in self.config['profiles']:
            p['enabled'] = p['id'] in ids
        r.save(r.root() / 'routing.json', self.config)

    def resolve(self, tier='large', **changes):
        args = copy.copy(self.args)
        for key, value in changes.items():
            setattr(args, key, value)
        answers = core.execution.host_assessment(argparse.Namespace(task_tier=tier))
        return r.resolve(core, self.config, answers, self.available, args, {})

    def reasons(self, decision):
        return {row['profile']: row['reason'] for row in decision['rejected']}

    def cards(self, mode='consult'):
        return r.model_context(core, self.config, self.available, {}, dict(failed_profiles=[]), mode)

    def quiet(self):
        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.addCleanup(stack.close)

    # -- registry, families, independence ---------------------------------------------------
    def test_registry_rubric_and_family_parser_mirror_the_gateway(self):
        self.assertEqual(r.RUBRIC_VERSION, 5)
        self.assertEqual(list(r.FAMILIES).count('cursor'), 1)
        self.assertEqual(r.MODEL_KEYS['cursor'], 'ALLOY_CURSOR_MODEL')
        self.assertEqual(r.EFFORT_KEYS['cursor'], 'ALLOY_CURSOR_EFFORT')
        table = {'claude-opus-5-5-high': 'anthropic', 'claude-opus-4-8[context=1m,effort=high,fast=false]': 'anthropic',
                 'gpt-5.6-sol-high': 'openai', 'gpt-5.3-codex-low-fast': 'openai', 'gpt-6.1-sol': 'openai',
                 'gpt-6.1-sol-high-fast': 'openai', 'gpt-6.1-future-thing': 'openai', 'gpt-5.5-extra-high': 'openai',
                 'codex': 'openai', 'codex-mini': 'openai',
                 'gemini-3.8-flash-high': 'google', 'grok-4.7-high': 'xai', 'cursor-grok-4.5-low-fast': 'xai',
                 'composer-2.5': 'cursor', 'composer-3-fast': 'cursor',
                 'auto': None, 'auto-fast': None, 'auto[fast=false]': None, '': None, 'muse-spark-1.3-high': None,
                 'kimi-k3-low': None, 'glm-5.2-max': None, 'made-up-1': None, 'claude': None, 'gpt': None,
                 'codexa': None, 'gpt-5[a=1': None, 'gpt-5[a=1,a=2]': None, 'gpt-5[a]': None, 'gpt 5': None,
                 None: None, 5: None}
        for model, expected in table.items():
            with self.subTest(model=model):
                self.assertEqual(r.cursor_model_family(model), expected)
                if isinstance(model, str):
                    self.assertEqual(core.cursor_model_family(model), expected)  # the spawn gateway agrees
        for pid, (model, fam, _tier) in self.SHIPPED.items():
            self.assertEqual(r.family(self.profile(pid)), fam)
        # A Cursor profile's family comes from its model, never from its label.
        self.assertEqual(r.family(dict(adapter='cursor', model='claude-opus-5-5-high', family='cursor')), 'anthropic')
        self.assertEqual(r.family(dict(adapter='cursor-agent', model='composer-2.5')), 'cursor')
        self.assertEqual(r.family(dict(adapter='codex', model='gpt-6.1-sol', family='openai')), 'openai')

    def test_shipped_cursor_profiles_are_disabled_subscription_and_pooled(self):
        shipped = {p['id']: p for p in r.starter(core)['profiles'] if p['adapter'] == 'cursor'}
        self.assertEqual(set(shipped), set(self.SHIPPED))
        for pid, (model, fam, tier) in self.SHIPPED.items():
            p = shipped[pid]
            with self.subTest(profile=pid):
                self.assertEqual((p['model'], p['family'], p['tier'], p['effort']), (model, fam, tier, 'high'))
                self.assertIs(p['enabled'], False)
                self.assertEqual(p['billing_mode'], 'subscription')
                self.assertEqual(p['quota_pool'], 'cursor')
                self.assertEqual(p['evidence'], 'Cursor discovery only; not benchmarked')
                self.assertNotIn('cursor_fast', p)
                self.assertNotIn('task_preferences', p)
                self.assertEqual(r.family(p), p['family'])
        # Nothing routes to Cursor until it is enabled, whatever the CLI reports.
        self.assertEqual([c for c in self.cards() if c['profile'] in self.SHIPPED], [])
        self.assertEqual({self.reasons(self.resolve())[pid] for pid in self.SHIPPED}, {'disabled'})

    def test_gpt_6_1_sol_is_the_preferred_large_codex_profile(self):
        profiles = {p['id']: p for p in r.starter(core)['profiles']}
        sol = profiles['codex-large-gpt-6-1-sol']
        self.assertEqual((sol['adapter'], sol['model'], sol['family'], sol['tier']), ('codex', 'gpt-6.1-sol', 'openai', 'large'))
        self.assertIs(sol['enabled'], True)
        self.assertEqual(sol['quota_pool'], 'codex')
        others = [p for p in profiles.values() if p['adapter'] == 'codex' and p['tier'] == 'large' and p is not sol]
        self.assertTrue(others and all(sol['cost_rank'] < p['cost_rank'] for p in others))
        self.assertTrue({'codex-large', 'codex-large-gpt-6-sol', 'codex-large-gpt-6-astra'} <= set(profiles))  # older profiles kept
        self.assertEqual(profiles['codex-large']['model'], 'gpt-5.6-sol')
        order = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
        efforts = {mode: r.role_profile(core, sol, mode)['effort'] for mode in r.MODES}
        self.assertIn(efforts['review'], order[order.index('high'):])
        self.assertTrue(all(order.index(e) >= order.index('medium') for e in efforts.values()))
        self.assertEqual(r.cursor_model_family('gpt-6.1-sol'), 'openai')  # a future Cursor 6.1 ID is OpenAI too
        self.args.panelists = 'codex'
        self.assertEqual(self.decide(response('large'))['profile'], 'codex-large-gpt-6-1-sol')
        pin = 'codex-large-gpt-6-1-sol'
        make = self.resolve(mode='make', host_family='anthropic', profile=pin)
        self.assertEqual((make['profile'], make['effort'], make['effort_source']), (pin, 'medium', 'profile'))
        review = self.resolve(mode='review', exclude_family='anthropic', profile=pin)
        self.assertEqual((review['profile'], review['effort'], review['effort_source']), (pin, 'high', 'mode'))
        with patch.dict(os.environ, {'ALLOY_CODEX_EFFORT': 'medium'}):  # an explicit pin is the user's to lower
            self.assertEqual(self.resolve(mode='review', exclude_family='anthropic', profile=pin)['effort'], 'medium')

    def test_anthropic_host_never_selects_cursor_claude_as_maker_or_checker(self):
        self.only('cursor-large-claude-opus-5-5', 'cursor-large-composer-2-5', 'cursor-large-gpt-5-6-sol')
        with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
            self.resolve(mode='make', host_family='anthropic', profile='cursor-large-claude-opus-5-5')
        maker = self.resolve(mode='make', host_family='anthropic')
        self.assertNotEqual(maker['family'], 'anthropic')
        self.assertEqual(self.reasons(maker)['cursor-large-claude-opus-5-5'], 'family excluded')
        # The Checker after an OpenAI Maker under an Anthropic host: only Composer remains.
        checker = self.resolve(mode='review', exclude_family='anthropic,openai')
        self.assertEqual((checker['profile'], checker['family']), ('cursor-large-composer-2-5', 'cursor'))
        self.assertEqual(self.reasons(checker)['cursor-large-claude-opus-5-5'], 'family excluded')
        self.assertEqual(self.reasons(checker)['cursor-large-gpt-5-6-sol'], 'family excluded')
        with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
            self.resolve(mode='review', exclude_family='anthropic,openai', profile='cursor-large-claude-opus-5-5')

    def test_openai_maker_never_receives_cursor_gpt_as_checker(self):
        self.only('codex-large', 'cursor-large-gpt-5-6-sol')
        with self.assertRaisesRegex(r.RoutingError, 'No eligible'):  # the only remaining Checker is OpenAI too
            self.resolve(mode='make', host_family='anthropic')
        self.only('codex-large', 'cursor-large-gpt-5-6-sol', 'cursor-large-composer-2-5')
        maker = self.resolve(mode='make', host_family='anthropic', profile='codex-large')
        self.assertEqual((maker['profile'], maker['family']), ('codex-large', 'openai'))
        checker = self.resolve(mode='review', exclude_family='anthropic,openai')
        self.assertEqual(checker['profile'], 'cursor-large-composer-2-5')
        self.assertEqual(self.reasons(checker)['cursor-large-gpt-5-6-sol'], 'family excluded')

    def test_composer_is_its_own_host_family_and_independent_of_the_other_four(self):
        parser = argparse.ArgumentParser()
        r.add_route_options(parser)
        self.assertEqual(parser.parse_args(['--host-family', 'cursor']).host_family, 'cursor')
        self.only('cursor-large-composer-2-5', 'cursor-large-gpt-5-6-sol', 'cursor-large-claude-opus-5-5')
        maker = self.resolve(mode='make', host_family='cursor')
        self.assertIn(maker['family'], ('openai', 'anthropic'))
        self.assertEqual(self.reasons(maker)['cursor-large-composer-2-5'], 'family excluded')
        self.only('cursor-large-composer-2-5')
        for other in ('openai', 'anthropic', 'google', 'xai'):
            with self.subTest(other=other):
                self.assertEqual(self.resolve(host_family=other, exclude_family=other)['family'], 'cursor')
        with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
            self.resolve(exclude_family='cursor')

    def test_auto_and_unknown_ids_never_route_card_or_dispatch(self):
        for model in ('auto', 'auto-fast', 'muse-spark-1.3-high', 'kimi-k3-low', 'glm-5.2-max', 'made-up-1'):
            for label in ('cursor', 'openai', 'anthropic', None):
                config = copy.deepcopy(self.config)
                config['profiles'].append(dict(self.profile('cursor-large-composer-2-5'), id='bad', model=model,
                                               family=label, enabled=True))
                with self.subTest(model=model, family=label):
                    with self.assertRaisesRegex(r.RoutingError, 'known family|family'):
                        r.validate(config)
            # Validation bypassed (an in-memory or hand-edited config): the boundaries still refuse.
            self.config['profiles'].append(dict(self.profile('cursor-large-composer-2-5'), id='bad', model=model,
                                                family='openai', enabled=True))
            self.only('bad', 'cursor-large-composer-2-5')
            with self.subTest(model=model, boundary='exposure'):
                self.assertNotIn('bad', [c['profile'] for c in self.cards()])
                decision = self.resolve()
                self.assertEqual(decision['profile'], 'cursor-large-composer-2-5')
                self.assertIn('no known family', self.reasons(decision)['bad'])
                self.only('bad')
                with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
                    self.resolve()
                self.only('bad', 'codex-large')  # nor can it be the independent Checker a Maker needs
                with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
                    self.resolve(mode='make', host_family='anthropic')
            self.config['profiles'].pop()
            forged = dict(cli='cursor', model=model, effective_model=model + '[fast=false]', family='cursor',
                          effort=None, cursor_fast=False)
            with self.subTest(model=model, boundary='dispatch'):
                with self.assertRaises(r.RoutingError):
                    r.routed_adapter(core, forged)

    def test_only_composer_may_claim_family_cursor(self):
        def rejects(**changes):
            config = copy.deepcopy(self.config)
            config['profiles'].append(dict(self.profile('cursor-large-composer-2-5'), id='claim', **changes))
            with self.assertRaises(r.RoutingError):
                r.validate(config)
        rejects(model='gpt-5.6-sol-high', family='cursor')      # a GPT model cannot be labelled cursor
        rejects(model='claude-opus-5-5-high', family='cursor')  # nor a Claude model
        rejects(model='composer-2.5', family='openai')          # nor may Composer wear another family
        rejects(family=None)                                    # the family is explicit and must match
        for base in ('codex-large', 'claude-large', 'antigravity-large', 'grok-large'):  # no other adapter may claim it
            config = copy.deepcopy(self.config)
            next(p for p in config['profiles'] if p['id'] == base)['family'] = 'cursor'
            with self.subTest(adapter=base):
                with self.assertRaisesRegex(r.RoutingError, 'reserved'):
                    r.validate(config)
                # ... and the exposure boundaries refuse it when validation is bypassed.
                bad = self.profile(base)
                bad['family'] = 'cursor'
                self.only(base)
                self.assertNotIn(base, [c['profile'] for c in self.cards()])
                with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
                    self.resolve()
                bad['family'] = r.FAMILIES[bad['adapter']]
        ok = copy.deepcopy(self.config)
        self.assertIs(r.validate(ok), ok)  # the shipped Composer profile is the valid claim

    def test_malformed_bracket_models_raise_routing_error_never_a_crash(self):
        for model in ('gpt-5[a]', 'gpt-5[a=]', 'gpt-5[=1]', 'gpt-5[a=1,a=2]', 'gpt-5[a=1,,b=2]', 'gpt-5[[a=1]]',
                      'gpt-5[a=1', 'gpt-5[a=1]x', 'gpt-5[ a = 1 ]', 'gpt-5[fast=maybe]'):
            config = copy.deepcopy(self.config)
            config['profiles'].append(dict(self.profile('cursor-large-gpt-5-6-sol'), id='br', model=model,
                                           cursor_fast=True))
            with self.subTest(model=model):
                with self.assertRaises(r.RoutingError):  # a TypeError here would be an error, not a pass
                    r.validate(config)
                r.profile_problem(config['profiles'][-1])  # must not raise, whatever it returns
        # The unpacking guard itself: even if the family parser accepted such an ID, the profile
        # rules return a problem and the exposure boundary raises RoutingError.
        broken = dict(self.profile('cursor-large-gpt-5-6-sol'), model='gpt-5[a]')
        with patch.object(r, 'cursor_model_family', return_value='openai'):
            self.assertRegex(r.profile_problem(broken), 'bracket')
            with self.assertRaisesRegex(r.RoutingError, 'bracket'):
                r.effective_profile(core, broken, 'consult')
        self.quiet()
        self.assertEqual(core.main(['models', 'add', '--id', 'br', '--cli', 'cursor', '--model', 'gpt-5[a]',
                                    '--family', 'openai', '--tier', 'large']), 2)

    def test_canonical_and_legacy_pins_are_rederived_at_every_boundary(self):
        self.only('cursor-large-composer-2-5', 'cursor-large-gpt-5-6-sol', 'cursor-large-claude-opus-5-5')
        with patch.dict(os.environ, {'ALLOY_CURSOR_AGENT_MODEL': 'gpt-5.6-sol-high'}):  # legacy alone
            decision = self.resolve()
            self.assertEqual(decision['profile'], 'cursor-large-gpt-5-6-sol')
            self.assertEqual(self.reasons(decision)['cursor-large-composer-2-5'], 'model override differs; add a matching profile')
            self.assertEqual([c['profile'] for c in self.cards()], ['cursor-large-gpt-5-6-sol'])
        with patch.dict(os.environ, {'ALLOY_CURSOR_MODEL': 'composer-2.5', 'ALLOY_CURSOR_AGENT_MODEL': 'gpt-5.6-sol-high'}):
            self.assertEqual(self.resolve()['profile'], 'cursor-large-composer-2-5')  # canonical wins
            self.assertEqual([c['profile'] for c in self.cards()], ['cursor-large-composer-2-5'])
        with patch.dict(os.environ, {'ALLOY_CURSOR_AGENT_MODEL': 'claude-opus-5-5-high'}):
            with self.assertRaises(r.RoutingError):  # a pin cannot move a Maker into the host's family ...
                self.resolve(mode='make', host_family='anthropic')
            with self.assertRaises(r.RoutingError):  # ... or a Checker into the host's or Maker's
                self.resolve(mode='review', exclude_family='anthropic,openai')
        for pin in ('auto', 'composer-2.5[effort=low]', 'gpt-5.6-sol', 'unknown-9'):
            with self.subTest(pin=pin), patch.dict(os.environ, {'ALLOY_CURSOR_MODEL': pin}):
                self.assertEqual(self.cards(), [])
                with self.assertRaisesRegex(r.RoutingError, 'No eligible'):
                    self.resolve()
        env = {'ALLOY_CURSOR_AGENT_MODEL': 'gpt-5.6-sol-high'}
        with patch.dict(os.environ, env):
            self.assertEqual(r.setting_for(core, 'cursor', 'model'), 'gpt-5.6-sol-high')
            with patch.dict(os.environ, {'ALLOY_CURSOR_MODEL': 'composer-2.5'}):
                self.assertEqual(r.setting_for(core, 'cursor', 'model'), 'composer-2.5')
        self.assertIsNone(r.setting_for(core, 'cursor', 'model'))
        with patch.dict(os.environ, {'ALLOY_CODEX_MODEL': 'x', 'ALLOY_CURSOR_AGENT_MODEL': 'y'}):
            self.assertEqual(r.setting_for(core, 'codex', 'model'), 'x')  # no legacy key for other adapters

    # -- evidence identity -------------------------------------------------------------------
    def data(self):
        data = copy.deepcopy(r.evidence.catalog())
        data['status'] = 'current'
        return data

    def test_evidence_rows_declare_native_adapters_and_fast_state(self):
        data = self.data()
        native = {'openai': 'codex', 'anthropic': 'claude', 'xai': 'grok', 'google': 'antigravity'}
        self.assertTrue(data['models'])
        for row in data['models']:
            with self.subTest(models=row['models']):
                self.assertEqual(row['adapters'], [native[row['family']]])
                self.assertIs(row['fast'], False)
        self.assertNotIn('cursor', json.dumps([row['adapters'] for row in data['models']]))  # no Cursor benchmark row

    def test_every_shipped_cursor_profile_stays_evidence_unmatched(self):
        data = self.data()
        for pid in self.SHIPPED:
            p = r.effective_profile(core, self.profile(pid), 'consult')
            with self.subTest(profile=pid):
                assessed = r.evidence.assessment(r.evidence_view(p), data)
                self.assertEqual((assessed['status'], assessed['preferred_tasks']), ('unmatched', []))
        # The normalized identities of three collide with native rows on model, family and effort;
        # only the adapter keeps them apart.
        for native, cursor in (('codex-large', 'cursor-large-gpt-5-6-sol'), ('claude-large', 'cursor-large-claude-opus-5-5'),
                               ('grok-large', 'cursor-large-grok-4-7')):
            n = r.evidence_view(r.effective_profile(core, dict(self.profile(native), effort='high'), 'consult'))
            c = r.evidence_view(r.effective_profile(core, self.profile(cursor), 'consult'))
            with self.subTest(native=native):
                self.assertEqual((n['model'], n['family'], n['effort']), (c['model'], c['family'], c['effort']))
                self.assertEqual(r.evidence.assessment(n, data)['status'], 'matched')
                self.assertEqual(r.evidence.assessment(c, data)['status'], 'unmatched')

    def test_evidence_never_crosses_adapter_effort_or_fast_boundaries(self):
        data = self.data()
        status = lambda **p: r.evidence.assessment(dict(dict(adapter='codex', model='gpt-5.6-sol', family='openai',
                                                            effort='high', fast=False), **p), data)
        self.assertEqual(status()['status'], 'matched')
        self.assertTrue(status()['preferred_tasks'])
        # The Cursor Gemini profile's identity collides with the antigravity row: model text, family, effort.
        collide = dict(model='gemini-3.8-flash-high', family='google', effort='high')
        self.assertEqual(status(adapter='antigravity', **collide)['status'], 'matched')
        for adapter in ('cursor', 'codex', 'claude', 'grok', 'cursor-agent', None):
            with self.subTest(adapter=adapter):
                self.assertEqual(status(adapter=adapter, **collide), dict(status='unmatched', preferred_tasks=[], sources=[]))
        self.assertEqual(status(adapter='cursor')['status'], 'unmatched')
        for effort in ('low', 'none', 'minimal', None):                # another effort borrows no task preference
            with self.subTest(effort=effort):
                self.assertEqual((status(effort=effort)['status'], status(effort=effort)['preferred_tasks']), ('effort-unverified', []))
        self.assertEqual(status(fast=True)['status'], 'unmatched')     # a fast variant is another identity
        # A row must state its adapters (as a list) and its fast state, or it covers nothing.
        for damage in (lambda row: row.pop('adapters'), lambda row: row.update(adapters='codex'),
                       lambda row: row.update(adapters=[]), lambda row: row.pop('fast'),
                       lambda row: row.update(fast='false')):
            broken = self.data()
            damage(next(row for row in broken['models'] if 'gpt-5.6-sol' in row['models']))
            self.assertEqual(r.evidence.assessment(dict(adapter='codex', model='gpt-5.6-sol', family='openai', effort='high'),
                                                   broken)['status'], 'unmatched')
        # Only an explicit future row can cover Cursor, and then all four parts must agree.
        future = self.data()
        future['models'].append(dict(models=['gpt-5.6-sol'], family='openai', adapters=['cursor'], fast=False,
                                     applicable_efforts=['high'], preferred_tasks=['review'], strengths='s',
                                     limitations='l', sources=['x'], basis='b', suggested_tier='large'))
        view = dict(adapter='cursor', model='gpt-5.6-sol', family='openai', effort='high', fast=False)
        self.assertEqual(r.evidence.assessment(view, future)['status'], 'matched')
        self.assertEqual(r.evidence.assessment(dict(view, effort='low'), future)['status'], 'effort-unverified')
        self.assertEqual(r.evidence.assessment(dict(view, fast=True), future)['status'], 'unmatched')
        self.assertEqual(r.evidence.assessment(dict(view, adapter='codex'), future)['preferred_tasks'],
                         status()['preferred_tasks'])  # the native row is unchanged
        self.assertEqual(r.evidence.assessment(dict(view, adapter='grok'), future)['status'], 'unmatched')
        self.assertEqual(r.evidence.assessment(dict(view, model='gpt-5.6-sol-new'), future)['status'], 'unmatched')

    def test_cursor_evidence_flows_unmatched_through_cards_and_decisions(self):
        self.config['profiles'].append(dict(self.profile('cursor-large-gpt-5-6-sol'), id='cursor-gpt-bare',
                                            model='gpt-5.6-sol', effort='high', cost_rank=.5))
        self.only('cursor-large-gpt-5-6-sol', 'cursor-large-claude-opus-5-5', 'cursor-gpt-bare', 'codex-large')
        cards = {c['profile']: c for c in self.cards()}
        self.assertEqual(cards['codex-large']['evidence_status'], 'matched')
        for pid in ('cursor-large-gpt-5-6-sol', 'cursor-large-claude-opus-5-5', 'cursor-gpt-bare'):
            self.assertEqual((cards[pid]['evidence_status'], cards[pid]['preferred_tasks']), ('unmatched', []), pid)
            self.assertEqual(cards[pid]['shared_quota_pool'], 'cursor')
            self.assertEqual(cards[pid]['billing_mode'], 'subscription')
        reply = response('large')
        reply['answers']['kind'].update(choice='debugging', probabilities={k: int(k == 'debugging') for k in r.questions()['kind']['criteria']})
        decision = r.resolve(core, self.config, reply['answers'], self.available, self.args, {})
        for row in decision['recommendations']:
            if row['cli'] == 'cursor':
                self.assertEqual(row['evidence']['status'], 'unmatched')
                self.assertFalse(row['task_fit'])
        self.assertEqual(r.model_fits(dict(answers=dict(fit_0=dict(type='noul', noul=.99))), [cards['cursor-gpt-bare']]), {})

    def test_models_advise_normalizes_the_adapter_before_reading_pins(self):
        data = self.data()
        aliased = dict(self.profile('cursor-large-gpt-5-6-sol'), adapter='cursor-agent')  # in-memory, never through load()
        config = dict(self.config, profiles=[aliased])
        with patch.dict(os.environ, {'ALLOY_CURSOR_AGENT_MODEL': 'composer-2.5'}):  # a legacy pin still applies
            advice = r.evidence.advise(core, config, data, {})
        row = advice['profiles'][0]
        self.assertEqual((row['model_pin'], row['blocked_by_pin']), ('composer-2.5', True))
        self.assertEqual(row['evidence']['status'], 'unmatched')
        with patch.dict(os.environ, {'ALLOY_CURSOR_MODEL': 'gpt-5.6-sol-high'}):
            self.assertFalse(r.evidence.advise(core, config, data, {})['profiles'][0]['blocked_by_pin'])
        self.assertEqual(r.evidence.advise(core, dict(config, profiles=[dict(aliased, model='auto', family='openai')]),
                                           data, {})['profiles'][0]['evidence']['status'], 'unroutable')

    def test_models_advise_scopes_configured_and_discovered_rows_to_their_adapter(self):
        data = self.data()
        gemini = next(row for row in data['models'] if row['models'] == ['gemini-3.8-flash-high'])
        config = copy.deepcopy(self.config)
        config['profiles'] = [p for p in config['profiles'] if p['id'] == 'cursor-medium-gemini-3-8-flash']
        cursor_only = r.evidence.advise(core, config, data, dict(discovered=dict(cursor=dict(models=['gemini-3.8-flash-high']))))
        candidate = next(c for c in cursor_only['candidates'] if c['models'] == gemini['models'])
        self.assertFalse(candidate['discovered'])  # Cursor's listing is not the native antigravity listing
        self.assertEqual(cursor_only['profiles'][0]['evidence']['status'], 'unmatched')
        native = r.evidence.advise(core, config, data, dict(discovered=dict(antigravity=dict(models=['gemini-3.8-flash-high']))))
        self.assertTrue(next(c for c in native['candidates'] if c['models'] == gemini['models'])['discovered'])
        config['profiles'] = [dict(self.profile('antigravity-large'))]
        configured = r.evidence.advise(core, config, data, {})
        self.assertNotIn(gemini['models'], [c['models'] for c in configured['candidates']])
        self.assertEqual(configured['profiles'][0]['evidence']['status'], 'matched')
        bad = dict(self.profile('cursor-large-composer-2-5'), id='bad', model='auto', family='openai')
        config['profiles'] = [bad]
        self.assertEqual(r.evidence.advise(core, config, data, {})['profiles'][0]['evidence']['status'], 'unroutable')
        with patch.dict(os.environ, {'ALLOY_CURSOR_AGENT_MODEL': 'composer-2.5'}):
            config['profiles'] = [self.profile('cursor-large-gpt-5-6-sol')]
            self.assertTrue(r.evidence.advise(core, config, data, {})['profiles'][0]['blocked_by_pin'])  # legacy pin seen

    # -- effort and fast ---------------------------------------------------------------------
    def effective(self, model='gpt-5.6-sol-high', mode='consult', **fields):
        p = dict(self.profile('cursor-large-gpt-5-6-sol'), model=model, family=r.cursor_model_family(model), effort=None)
        p.update(fields)
        return r.effective_profile(core, p, mode)

    def test_cursor_effort_precedence_has_four_steps(self):
        base = 'gpt-5.6-sol'
        with patch.dict(os.environ, {'ALLOY_CURSOR_EFFORT': 'low'}):   # 1: environment pin beats everything below
            got = self.effective(effort='max', effort_by_mode={'review': 'medium'}, mode='review')
            self.assertEqual((got['effective_model'], got['effort'], got['effort_source']),
                             (base + '[effort=low,fast=false]', 'low', 'override'))
        got = self.effective(effort='medium', effort_by_mode={'review': 'max'}, mode='review')   # 2: role effort
        self.assertEqual((got['effective_model'], got['effort_source']), (base + '[effort=max,fast=false]', 'mode'))
        got = self.effective(effort='medium', effort_by_mode={'review': 'max'}, mode='consult')  # 3: profile effort beats the ID's
        self.assertEqual((got['effective_model'], got['effort_source']), (base + '[effort=medium,fast=false]', 'profile'))
        got = self.effective()                                          # 4: the model ID's own suffix effort
        self.assertEqual((got['effective_model'], got['effort'], got['effort_source']),
                         (base + '[effort=high,fast=false]', 'high', 'model'))
        got = self.effective('claude-opus-4-8[context=1m,effort=high]')  # 4: a bracket effort, other fields kept
        self.assertEqual((got['effective_model'], got['effort_source']),
                         ('claude-opus-4-8[context=1m,effort=high,fast=false]', 'model'))
        got = self.effective('claude-opus-4-8[context=1m,effort=high]', effort='low')  # a higher step replaces it
        self.assertEqual(got['effective_model'], 'claude-opus-4-8[context=1m,effort=low,fast=false]')
        got = self.effective('composer-2.5')                            # 5: no level says anything: no override
        self.assertEqual((got['effective_model'], got['effort'], got['effort_source']),
                         ('composer-2.5[fast=false]', None, 'profile'))
        for mode in ('inherit', 'default'):                              # inherit = the model ID's own default
            with patch.dict(os.environ, {'ALLOY_CURSOR_EFFORT': mode}):
                got = self.effective(effort='low')
                self.assertEqual((got['effective_model'], got['effort_source']), (base + '[effort=high,fast=false]', 'model'))

    def test_cursor_effort_pins_canonical_wins_and_legacy_works(self):
        with patch.dict(os.environ, {'ALLOY_CURSOR_AGENT_EFFORT': 'XHIGH'}):
            got = self.effective(effort='low')
            self.assertEqual((got['effort'], got['effort_source'], got['effective_model']),
                             ('xhigh', 'override', 'gpt-5.6-sol[effort=xhigh,fast=false]'))
            with patch.dict(os.environ, {'ALLOY_CURSOR_EFFORT': 'minimal'}):
                self.assertEqual(self.effective(effort='low')['effort'], 'minimal')
            self.assertEqual([c['effort'] for c in self.cards_for('cursor-large-gpt-5-6-sol')], ['xhigh'])
        self.assertEqual(self.effective(effort='low')['effort'], 'low')

    def cards_for(self, pid):
        self.only(pid)
        return self.cards()

    def test_cursor_compound_and_thinking_ids_keep_their_base(self):
        got = self.effective('gpt-5.5-extra-high')                      # one indivisible base, not gpt-5.5-extra + high
        self.assertEqual((got['effective_model'], got['evidence_model'], got['family'], got['effort']),
                         ('gpt-5.5-extra-high[fast=false]', 'gpt-5.5-extra-high', 'openai', None))
        self.assertEqual(self.effective('gpt-5.5-extra-high', effort='high')['effective_model'],
                         'gpt-5.5-extra-high[effort=high,fast=false]')
        fast = self.effective('gpt-5.5-extra-high-fast', cursor_fast=True)
        self.assertEqual((fast['effective_model'], fast['evidence_model']), ('gpt-5.5-extra-high[fast=true]', 'gpt-5.5-extra-high'))
        for model, base, effort, fam in (('claude-opus-5-thinking-high', 'claude-opus-5-thinking', 'high', 'anthropic'),
                                          ('claude-fable-5-1-thinking-max', 'claude-fable-5-1-thinking', 'max', 'anthropic'),
                                          ('gpt-5.4-mini-xhigh', 'gpt-5.4-mini', 'xhigh', 'openai'),
                                          ('gpt-5.6-terra-none', 'gpt-5.6-terra', 'none', 'openai'),
                                          ('muse-x', None, None, None)):
            with self.subTest(model=model):
                if base is None:
                    with self.assertRaises(r.RoutingError):
                        self.effective(model)
                    continue
                got = self.effective(model)
                self.assertEqual((got['evidence_model'], got['effort'], got['family']), (base, effort, fam))
                self.assertEqual(got['effective_model'], '%s[effort=%s,fast=false]' % (base, effort))

    def test_cursor_ultra_and_unknown_efforts_fail_instead_of_downgrading(self):
        for changes in (dict(effort='ultra'), dict(effort='enormous'), dict(effort_by_mode={'review': 'ultra'})):
            config = copy.deepcopy(self.config)
            config['profiles'].append(dict(self.profile('cursor-large-gpt-5-6-sol'), id='u', **changes))
            with self.subTest(changes=changes), self.assertRaisesRegex(r.RoutingError, 'effort'):
                r.validate(config)
        with patch.dict(os.environ, {'ALLOY_CURSOR_EFFORT': 'ultra'}):  # an environment pin cannot smuggle it in
            with self.assertRaises(r.RoutingError):
                self.effective()
            self.only('cursor-large-gpt-5-6-sol', 'codex-large')
            self.assertEqual([c['profile'] for c in self.cards()], ['codex-large'])
            decision = self.resolve()
            self.assertEqual(decision['profile'], 'codex-large')
            self.assertIn('ultra', self.reasons(decision)['cursor-large-gpt-5-6-sol'])
        # The non-Cursor efforts stay exactly as they were: ultra is a valid Codex effort.
        self.profile('codex-large')['effort'] = 'ultra'
        self.assertIs(r.validate(self.config), self.config)

    def test_cursor_fast_variants_need_an_explicit_profile_opt_in(self):
        def config_with(**changes):
            config = copy.deepcopy(self.config)
            config['profiles'].append(dict(self.profile('cursor-large-gpt-5-6-sol'), id='f', **changes))
            return config
        for model in ('gpt-5.6-sol-high-fast', 'gpt-5.6-sol[fast=true]', 'gpt-5.6-sol-high-fast[effort=high]'):
            with self.subTest(model=model):
                with self.assertRaisesRegex(r.RoutingError, 'fast'):
                    r.validate(config_with(model=model))
                r.validate(config_with(model=model, cursor_fast=True))
        with self.assertRaisesRegex(r.RoutingError, 'fast'):
            r.validate(config_with(model='gpt-5.6-sol[fast=maybe]', cursor_fast=True))
        for junk in ('yes', 1, None, []):
            with self.subTest(cursor_fast=junk), self.assertRaises(r.RoutingError):
                r.validate(config_with(cursor_fast=junk))
        r.validate(config_with(model='gpt-5.6-sol[fast=false]'))       # an explicit false needs no opt-in
        self.assertEqual(self.effective()['effective_model'], 'gpt-5.6-sol[effort=high,fast=false]')  # default: false
        on = self.effective(cursor_fast=True)
        self.assertEqual((on['effective_model'], on['cursor_fast']), ('gpt-5.6-sol[effort=high,fast=true]', True))
        self.assertEqual(self.effective('gpt-5.6-sol-high-fast', cursor_fast=True)['effective_model'],
                         'gpt-5.6-sol[effort=high,fast=true]')
        # The opt-in is per profile: a sibling on the same base ID stays non-fast, and non-Cursor profiles cannot carry it.
        self.config['profiles'].append(dict(self.profile('cursor-large-gpt-5-6-sol'), id='fast-one', cursor_fast=True))
        self.only('cursor-large-gpt-5-6-sol', 'fast-one')
        cards = {c['profile']: c for c in self.cards()}
        self.assertTrue(cards['fast-one']['effective_model'].endswith('fast=true]'))
        self.assertTrue(cards['cursor-large-gpt-5-6-sol']['effective_model'].endswith('fast=false]'))
        decision = self.resolve(profile='fast-one')
        self.assertIs(decision['cursor_fast'], True)
        self.assertEqual(decision['effective_model'], 'gpt-5.6-sol[effort=high,fast=true]')
        self.assertEqual(decision['model'], 'gpt-5.6-sol-high')  # the configured ID is unchanged
        self.assertFalse(self.resolve(profile='cursor-large-gpt-5-6-sol')['cursor_fast'])
        codex = copy.deepcopy(self.config)
        next(p for p in codex['profiles'] if p['id'] == 'codex-large')['cursor_fast'] = True
        with self.assertRaisesRegex(r.RoutingError, 'cursor_fast'):
            r.validate(codex)

    def test_profiles_are_never_mutated_by_routing(self):
        self.only('cursor-large-gpt-5-6-sol', 'cursor-large-claude-opus-5-5', 'codex-large')
        before = copy.deepcopy(self.config)
        self.cards()
        self.resolve()
        r.evidence.advise(core, self.config, self.data(), {})
        self.assertEqual(self.config, before)

    # -- dispatch -------------------------------------------------------------------------------
    def routed(self, pid='cursor-large-gpt-5-6-sol', **changes):
        p = self.profile(pid)
        saved = copy.deepcopy(p)
        try:
            p.update(changes)
            self.only(pid)
            return self.resolve(profile=pid)
        finally:
            p.clear()
            p.update(saved)

    def stage(self):
        root = os.path.realpath(self.tmp.name)
        repo = os.path.join(root, 'repo')
        os.makedirs(repo, exist_ok=True)
        prompt = os.path.join(root, 'prompt.txt')
        Path(prompt).write_text('task text')
        ctx = dict(pdir=os.path.join(root, 'pdir'), repo=repo, cwd=repo)
        return prompt, ctx

    def test_routed_cursor_adapter_rewrites_one_model_and_never_emits_effort(self):
        default = core.ADAPTERS['cursor']
        before = (default.model(), default.effort())
        for extra, expected in ((dict(), 'gpt-5.6-sol[effort=high,fast=false]'),
                                (dict(cursor_fast=True), 'gpt-5.6-sol[effort=high,fast=true]'),
                                (dict(effort='xhigh', effort_by_mode={'consult': 'low'}), 'gpt-5.6-sol[effort=low,fast=false]')):
            with self.subTest(extra=extra):
                decision = self.routed(**extra)
                self.assertEqual(decision['effective_model'], expected)
                prompt, ctx = self.stage()
                ad = r.routed_adapter(core, decision)
                argv = ad.build_args(prompt, os.path.join(self.tmp.name, 'last'), 'consult', ctx)
                self.assertEqual(argv.count('--model'), 1)
                self.assertEqual(argv[argv.index('--model') + 1], expected)
                self.assertEqual(ctx['cursor_expected_model'], expected)  # what the gateway will compare against
                self.assertEqual(argv[argv.index('--mode') + 1], 'ask')
                for flag in ('--effort', '--reasoning-effort'):
                    self.assertNotIn(flag, argv)
                self.assertFalse([a for a in argv if a.startswith('model_reasoning_effort')])
                self.assertEqual(ad.effective_model(), expected)
                shutil.rmtree(ctx['pdir'], ignore_errors=True)
        self.assertEqual((default.model(), default.effort()), before)  # the shared adapter is never mutated
        self.assertNotIn('effective_model', vars(default))

    def test_routed_cursor_adapter_refuses_forged_or_unnormalized_decisions(self):
        good = self.routed()
        r.routed_adapter(core, good)
        for label, changes in (('no effective model', dict(effective_model=None)),
                               ('auto', dict(effective_model='auto[fast=false]', model='auto')),
                               ('unknown family', dict(effective_model='kimi-k3[fast=false]', model='kimi-k3')),
                               ('relabelled family', dict(family='cursor')),
                               ('other family model', dict(model='claude-opus-5-5-high')),
                               ('fast without opt-in', dict(effective_model='gpt-5.6-sol[effort=high,fast=true]')),
                               ('effort mismatch', dict(effort='low')),
                               ('unnormalized', dict(effective_model='gpt-5.6-sol-high')),
                               ('unsupported effort', dict(effective_model='gpt-5.6-sol[effort=ultra,fast=false]', effort='ultra'))):
            with self.subTest(label):
                with self.assertRaises(r.RoutingError):
                    r.routed_adapter(core, dict(good, **changes))

    def test_routed_effort_flags_are_explicit_per_provider(self):
        mystery = types.SimpleNamespace(name='mystery', build_args=lambda *a, **k: ['--model', 'm'])
        with patch.dict(core.ADAPTERS, {'mystery': mystery}):
            self.assertEqual(r.routed_adapter(core, dict(cli='mystery', model='m', effort=None)).build_args('p', 'l', 'consult'),
                             ['--model', 'm'])
            with self.assertRaisesRegex(r.RoutingError, 'No effort mapping'):
                r.routed_adapter(core, dict(cli='mystery', model='m', effort='high')).build_args('p', 'l', 'consult')
        for bad in ('nope', None, ''):
            with self.subTest(cli=bad), self.assertRaisesRegex(r.RoutingError, 'unknown CLI'):
                r.routed_adapter(core, dict(cli=bad, model='m'))
        for cli in r.EFFORT_FLAG_ADAPTERS:  # the providers that took --effort still do
            fake = types.SimpleNamespace(name=cli, build_args=lambda *a, **k: ['--effort', 'old', '--model', 'm'])
            with patch.dict(core.ADAPTERS, {cli: fake}):
                argv = r.routed_adapter(core, dict(cli=cli, model='m', effort='high')).build_args('p', 'l', 'consult')
                self.assertEqual(argv, ['--model', 'm', '--effort', 'high'])
        self.assertEqual(set(r.EFFORT_FLAG_ADAPTERS) | {'codex', 'cursor'}, set(r.FAMILIES))

    # -- probe, environment, discovery ---------------------------------------------------------
    def cursor_ready(self, help_text=CURSOR_HELP, version='2026.09.28-64d2043', code=0):
        ad = core.ADAPTERS['cursor']
        calls = []
        def metadata(kind, binary, *a, **k):
            calls.append((kind, binary))
            return (0, version) if kind == 'version' else (code, help_text)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, value in (('detect', True), ('resolved_bin', '/opt/mock/cursor-agent'),
                            ('bin_override', '/opt/mock/cursor-agent'), ('auth_state', 'ready')):
            stack.enter_context(patch.object(ad, name, return_value=value))
        stack.enter_context(patch.object(core, 'cursor_boundary', return_value=core.CursorBoundary(True, '', 'v', '/opt/mock/cursor-agent')))
        stack.enter_context(patch.object(ad.__class__, 'cursor_boundary_ready', True))
        stack.enter_context(patch.object(core, 'cursor_metadata', side_effect=metadata))
        spawn = stack.enter_context(patch.object(r.subprocess, 'run', side_effect=AssertionError('direct spawn')))
        return calls, spawn

    def test_cursor_probe_uses_only_the_sandbox_gateway(self):
        calls, spawn = self.cursor_ready()
        result = r.probe(core, 'cursor')
        self.assertEqual((result['status'], result['compatible'], result['version']), ('ready', True, '2026.09.28-64d2043'))
        self.assertEqual(calls, [('version', '/opt/mock/cursor-agent'), ('help', '/opt/mock/cursor-agent')])
        spawn.assert_not_called()

    def test_cursor_probe_fails_closed(self):
        for flag in r.PROBE_FLAGS['cursor']:
            with self.subTest(missing=flag):
                calls, _ = self.cursor_ready(help_text=CURSOR_HELP.replace(flag, '--other'))
                self.assertFalse(r.probe(core, 'cursor')['compatible'])
        calls, _ = self.cursor_ready(code=1)
        self.assertFalse(r.probe(core, 'cursor')['compatible'])
        ad = core.ADAPTERS['cursor']
        with patch.object(core, 'cursor_metadata', side_effect=core.CursorBoundaryError('refused')):
            self.assertEqual(r.probe(core, 'cursor'), dict(status='probe_failed', compatible=False))
        with patch.object(ad.__class__, 'cursor_boundary_ready', False), patch.object(ad, 'auth_state', return_value='sandbox_unavailable'), \
             patch.object(core, 'cursor_metadata') as metadata:
            self.assertEqual(r.probe(core, 'cursor'), dict(status='sandbox_unavailable', compatible=False))
            metadata.assert_not_called()  # no boundary, no process
        with patch.object(ad, 'detect', return_value=False):
            self.assertEqual(r.probe(core, 'cursor'), dict(status='not_installed', compatible=False))

    def test_unknown_adapter_probe_is_incompatible_not_a_key_error(self):
        self.assertEqual(r.probe(core, 'made-up'), dict(status='unsupported_adapter', compatible=False))
        with patch.dict(core.ADAPTERS):  # restored on exit
            del core.ADAPTERS['grok']
            self.assertEqual(r.probe(core, 'grok'), dict(status='unsupported_adapter', compatible=False))

    def test_inventory_has_cursor_exactly_once_without_live_processes(self):
        self.cursor_ready()
        real = r.probe
        with patch.object(r, 'probe', side_effect=lambda c, n: real(c, n) if n == 'cursor' else dict(status='not_installed', compatible=False)):
            found = r.inventory(core)
        self.assertEqual(list(found).count('cursor'), 1)
        self.assertEqual(list(found), list(r.FAMILIES))
        self.assertTrue(found['cursor']['compatible'])

    def test_routing_subprocesses_never_receive_cursor_overrides(self):
        poison = {'CURSOR_API_KEY': 'poison-key', 'CURSOR_API_ENDPOINT': 'https://evil.invalid', 'TYPESAFE_API_KEY': 'k1',
                  'OPENROUTER_API_KEY': 'k2', 'KEEP_ME': 'yes'}
        with patch.dict(os.environ, poison):
            env = r.clean_env()
            self.assertEqual({k for k in poison if k in env}, {'KEEP_ME'})
            seen = []
            ad = core.ADAPTERS['codex']
            def output(argv, **kwargs):
                seen.append(kwargs['env'])
                return Mock(returncode=0, stdout='v1' if '--version' in argv else '--sandbox --model', stderr='')
            with patch.object(ad, 'resolved_bin', return_value='/usr/local/bin/mock'), patch.object(r.subprocess, 'run', side_effect=output):
                self.assertTrue(r.probe(core, 'codex')['compatible'])
            with patch.object(core.ADAPTERS['grok'], 'resolved_bin', return_value='/mock/grok'), \
                 patch.object(r.subprocess, 'run', side_effect=output):
                r.refresh(core, dict(grok=dict(status='ready', compatible=True)))
        self.assertTrue(seen)
        for env in seen:
            self.assertFalse({'CURSOR_API_KEY', 'CURSOR_API_ENDPOINT', 'TYPESAFE_API_KEY', 'OPENROUTER_API_KEY'} & set(env))

    def test_cursor_model_list_parser_accepts_only_full_id_label_lines(self):
        entries = r.parse_cursor_models(CURSOR_MODELS)
        byid = {e['id']: e for e in entries}
        self.assertEqual(list(byid), sorted(byid))
        self.assertEqual({i: (e['family'], e['routable']) for i, e in byid.items()},
                         {'auto': (None, False), 'composer-2.5': ('cursor', True), 'gpt-5.3-codex-low': ('openai', True),
                          'claude-opus-5-thinking-high': ('anthropic', True), 'gpt-5.6-sol-high': ('openai', True),
                          'gpt-5.6-sol-high-fast': ('openai', True), 'cursor-grok-4.5-low': ('xai', True),
                          'gemini-3.8-flash-high': ('google', True), 'muse-spark-1.3-minimal': (None, False),
                          'kimi-k3-low': (None, False), 'glm-5.2-high': (None, False)})
        # The family comes from the ID, never from the human label; junk and the trailing tip are ignored.
        junk = 'Available models\nkimi-k3-low - GPT 5 label\ngpt-5.6-sol-high - Claude Sonnet\nnot a model line\n' \
               ' indented-id - label\nid-only\nBad!Id - x\nTip: use --model <id> - to switch\ncomposer-2.5 - C\ncomposer-2.5 - again\n'
        self.assertEqual({e['id']: (e['family'], e['routable']) for e in r.parse_cursor_models(junk)},
                         {'kimi-k3-low': (None, False), 'gpt-5.6-sol-high': ('openai', True), 'composer-2.5': ('cursor', True)})
        for text in ('', 'gpt-5.6-sol-high - GPT\n', 'Available models\n\nTip: nothing\n', 'Available models\nnot a model\n'):
            self.assertIsNone(r.parse_cursor_models(text))

    def refresh_cursor(self, result, previous=None):
        if previous is not None:
            r.save(r.root() / 'models-cache.json', dict(discovered=previous))
        available = dict(self.available, grok=dict(status='not_installed', compatible=False),
                         antigravity=dict(status='not_installed', compatible=False))
        with patch.object(core.ADAPTERS['cursor'], 'resolved_bin', return_value='/opt/mock/cursor-agent'), \
             patch.object(core, 'cursor_metadata', side_effect=result) as metadata, \
             patch.object(r.subprocess, 'run', side_effect=AssertionError('direct spawn')):
            cache = r.refresh(core, available)
        return cache, metadata

    def test_cursor_discovery_records_routability_and_touches_no_profile(self):
        before = (r.root() / 'routing.json').read_text()
        cache, metadata = self.refresh_cursor(lambda *a, **k: (0, CURSOR_MODELS))
        metadata.assert_called_once_with('models', '/opt/mock/cursor-agent')
        found = cache['discovered']['cursor']
        self.assertFalse(found['authoritative'])
        self.assertEqual(found['models'], sorted(e['id'] for e in found['entries'] if e['routable']))
        self.assertNotIn('auto', found['models'])
        self.assertIn(dict(id='auto', family=None, routable=False), found['entries'])
        self.assertIn(dict(id='kimi-k3-low', family=None, routable=False), found['entries'])
        self.assertNotIn('cursor', cache['errors'])
        self.assertEqual((r.root() / 'routing.json').read_text(), before)  # discovery never creates or enables a profile
        self.assertEqual(json.loads((r.root() / 'models-cache.json').read_text())['discovered']['cursor']['models'], found['models'])

    def test_cursor_discovery_retains_the_cache_on_every_failure(self):
        previous = dict(cursor=dict(models=['composer-2.5'], entries=[], observed_at=1), grok=dict(models=['grok-old'], observed_at=1))
        for label, result in (('non-zero exit', lambda *a, **k: (1, CURSOR_MODELS)),
                              ('unrecognized', lambda *a, **k: (0, 'weird output\n')),
                              ('no valid line', lambda *a, **k: (0, 'Available models\nnot a model\n')),
                              ('boundary refused', core.CursorBoundaryError('no OS boundary'))):
            with self.subTest(label):
                cache, _ = self.refresh_cursor(result, previous)
                self.assertEqual(cache['discovered'], previous)
                self.assertIn('cursor', cache['errors'])
        cache, metadata = self.refresh_cursor(lambda *a, **k: (0, CURSOR_MODELS), None)
        self.assertNotEqual(cache['discovered']['cursor'], previous['cursor'])
        self.assertEqual(cache['discovered']['grok'], previous['grok'])
        unready = dict(self.available, cursor=dict(status='sandbox_unavailable', compatible=False),
                       grok=dict(status='not_installed'), antigravity=dict(status='not_installed'))
        with patch.object(core, 'cursor_metadata') as metadata:
            r.refresh(core, unready)
            metadata.assert_not_called()  # an unready Cursor is not even listed

    # -- setup, models, aliases ----------------------------------------------------------------
    def setup_args(self, **changes):
        return argparse.Namespace(**dict(dict(non_interactive=True, skip_live_test=True, billing=[]), **changes))

    def run_setup(self, **changes):
        self.quiet()
        with patch.object(r, 'inventory', return_value=self.available):
            return r.setup(core, self.setup_args(**changes))

    def cursor_state(self):
        return {p['id']: p['enabled'] for p in r.load()['profiles'] if p['adapter'] == 'cursor'}

    def test_setup_leaves_cursor_disabled_until_explicitly_enabled(self):
        self.run_setup()
        self.assertEqual(set(self.cursor_state().values()), {False})
        self.run_setup(refresh_defaults=True)
        self.assertEqual(set(self.cursor_state().values()), {False})
        self.run_setup(enable_cursor=True)
        self.assertEqual(self.cursor_state(), {pid: True for pid in self.SHIPPED})
        before = r.load()
        self.run_setup(enable_cursor=True)
        self.assertEqual(r.load(), before)  # idempotent
        self.assertTrue(all(p['enabled'] for p in before['profiles'] if p['adapter'] == 'cursor'))
        r.save(r.root() / 'routing.json', r.starter(core))  # the same opt-in through the real command line
        self.assertEqual(set(self.cursor_state().values()), {False})
        with patch.object(r, 'inventory', return_value=self.available):
            self.assertEqual(core.main(['setup', '--non-interactive', '--skip-live-test']), 0)
            self.assertEqual(set(self.cursor_state().values()), {False})
            self.assertEqual(core.main(['setup', '--non-interactive', '--skip-live-test', '--enable-cursor']), 0)
        self.assertEqual(self.cursor_state(), {pid: True for pid in self.SHIPPED})

    def test_enable_cursor_adds_missing_profiles_and_preserves_everything_else(self):
        old = [p for p in self.config['profiles'] if p['adapter'] != 'cursor']
        old[0].update(model='gpt-custom', billing_mode='subscription', enabled=False, cost_rank=17)
        custom = dict(self.profile('cursor-large-composer-2-5'), id='mine', model='composer-3', enabled=False, cost_rank=9)
        self.config['profiles'] = old + [custom]
        r.save(r.root() / 'routing.json', self.config)
        self.run_setup(enable_cursor=True)
        got = {p['id']: p for p in r.load()['profiles']}
        self.assertEqual({pid for pid, p in got.items() if p['adapter'] == 'cursor' and p['enabled']}, set(self.SHIPPED))
        self.assertFalse(got['mine']['enabled'])  # only the shipped profiles are switched on
        self.assertEqual(got['mine'], custom)
        self.assertEqual(got[old[0]['id']], old[0])  # non-Cursor profiles, billing and models untouched
        self.assertEqual([p['id'] for p in r.load()['profiles']][:len(old)], [p['id'] for p in old])

    def test_enable_cursor_enables_only_shipped_profiles_not_lookalikes(self):
        lookalike = dict(self.profile('cursor-large-composer-2-5'), id='my-composer', enabled=False, cost_rank=9)
        collide = dict(self.profile('cursor-large-claude-opus-5-5'), model='claude-opus-5-5-low', enabled=False, cost_rank=8)
        shipped = dict(self.profile('cursor-large-gpt-5-6-sol'), enabled=False)
        self.config['profiles'] = ([p for p in self.config['profiles'] if p['adapter'] != 'cursor']
                                   + [lookalike, collide, shipped])
        # `my-composer` shares a shipped model but is the user's own; `cursor-large-claude-opus-5-5`
        # is a shipped ID with a different model, so it is not the shipped profile either.
        r.save(r.root() / 'routing.json', self.config)
        self.run_setup(enable_cursor=True)
        got = {p['id']: p for p in r.load()['profiles']}
        self.assertEqual(got['my-composer'], lookalike)
        self.assertEqual(got['cursor-large-claude-opus-5-5'], collide)
        self.assertTrue(got['cursor-large-gpt-5-6-sol']['enabled'])  # the exact shipped profile
        # The user's own composer-2.5 profile already covers that model, so no shipped duplicate is added;
        # no profile covers claude-opus-5-5-high, so the shipped one is added (its ID is taken) and enabled.
        self.assertNotIn('cursor-large-composer-2-5', got)
        self.assertTrue(got['cursor-large-claude-opus-5-5-2']['enabled'])
        self.assertEqual(got['cursor-large-claude-opus-5-5-2']['model'], 'claude-opus-5-5-high')
        for pid in ('cursor-medium-gemini-3-8-flash', 'cursor-large-grok-4-7'):
            self.assertTrue(got[pid]['enabled'])
        self.assertEqual({pid for pid, p in got.items() if p['adapter'] == 'cursor' and not p['enabled']},
                         {'my-composer', 'cursor-large-claude-opus-5-5'})
        before = r.load()
        self.run_setup(enable_cursor=True)
        self.assertEqual(r.load(), before)  # still idempotent

    def test_refresh_defaults_adds_cursor_disabled_and_keeps_enabled_state_pins_and_billing(self):
        mine = self.profile('cursor-large-composer-2-5')
        mine.update(enabled=True, billing_mode='metered', cost_rank=11, model='composer-2.5')
        self.config['profiles'] = [p for p in self.config['profiles'] if p['adapter'] != 'cursor' or p is mine]
        r.save(r.root() / 'routing.json', self.config)
        with patch.dict(os.environ, {'ALLOY_CURSOR_AGENT_MODEL': 'composer-2.5'}):
            self.run_setup(refresh_defaults=True)
        got = {p['id']: p for p in r.load()['profiles'] if p['adapter'] == 'cursor'}
        self.assertEqual(got['cursor-large-composer-2-5'], mine)  # enabled, metered, rank untouched
        self.assertEqual({pid for pid, p in got.items() if p['enabled']}, {'cursor-large-composer-2-5'})
        self.assertEqual(set(got), set(self.SHIPPED))

    def test_reset_defaults_keeps_a_cursor_billing_choice(self):
        for p in self.config['profiles']:
            if p['adapter'] == 'cursor':
                p.update(billing_mode='metered', enabled=True)
        r.save(r.root() / 'routing.json', self.config)
        self.run_setup(reset_defaults=True)
        cursor = [p for p in r.load()['profiles'] if p['adapter'] == 'cursor']
        self.assertEqual({p['billing_mode'] for p in cursor}, {'metered'})
        self.assertEqual({p['enabled'] for p in cursor}, {False})  # shipped defaults come back disabled

    def test_guided_setup_asks_about_cursor_and_defaults_to_no(self):
        asked = []
        def answer(reply):
            def fake(prompt=''):
                asked.append(prompt)
                return reply if 'Cursor' in prompt else ''
            return fake
        for reply, expected in (('', False), ('n', False), ('y', True), ('YES', True)):
            r.save(r.root() / 'routing.json', r.starter(core))
            asked.clear()
            with self.subTest(reply=reply), patch.object(r, 'inventory', return_value=self.available), \
                 patch.object(r.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=answer(reply)), \
                 patch.object(r.getpass, 'getpass'):
                self.quiet()
                r.setup(core, self.setup_args(non_interactive=False, keyless=True))
                self.assertEqual(len([q for q in asked if 'Cursor' in q]), 1)
                self.assertEqual(set(self.cursor_state().values()), {expected})
        # Not detected (or unusable) means no question and nothing enabled.
        for status in ('not_installed', 'sandbox_unavailable', 'probe_failed'):
            r.save(r.root() / 'routing.json', r.starter(core))
            asked.clear()
            unready = dict(self.available, cursor=dict(status=status, compatible=False))
            with self.subTest(status=status), patch.object(r, 'inventory', return_value=unready), \
                 patch.object(r.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=answer('y')), \
                 patch.object(r.getpass, 'getpass'):
                self.quiet()
                r.setup(core, self.setup_args(non_interactive=False, keyless=True))
                self.assertFalse([q for q in asked if 'Cursor' in q])
                self.assertEqual(set(self.cursor_state().values()), {False})

    def test_models_enable_disable_is_the_granular_alternative(self):
        self.quiet()
        self.assertEqual(core.main(['models', 'enable', '--id', 'cursor-large-composer-2-5']), 0)
        self.assertEqual({k for k, v in self.cursor_state().items() if v}, {'cursor-large-composer-2-5'})
        self.assertEqual(core.main(['models', 'disable', '--id', 'cursor-large-composer-2-5']), 0)
        self.assertEqual(set(self.cursor_state().values()), {False})

    def test_models_add_takes_cursor_fast_and_the_legacy_adapter_name(self):
        self.quiet()
        add = ['models', 'add', '--id', 'cf', '--model', 'gpt-5.6-sol-high', '--family', 'openai', '--tier', 'large']
        self.assertEqual(core.main(add + ['--cli', 'cursor']), 0)
        self.assertNotIn('cursor_fast', next(p for p in r.load()['profiles'] if p['id'] == 'cf'))  # default: off
        self.assertEqual(core.main(add + ['--cli', 'cursor', '--cursor-fast']), 0)
        fast = lambda: next(p for p in r.load()['profiles'] if p['id'] == 'cf').get('cursor_fast')
        self.assertIs(fast(), True)
        self.assertEqual(core.main(['models', 'add', '--id', 'cf', '--cost-rank', '3']), 0)
        self.assertIs(fast(), True)  # an unrelated update keeps the opt-in
        self.assertEqual(core.main(['models', 'add', '--id', 'cf', '--no-cursor-fast']), 0)
        self.assertIs(fast(), False)
        # The legacy adapter name is accepted and persisted canonically.
        self.assertEqual(core.main(['models', 'add', '--id', 'legacy', '--cli', 'cursor-agent', '--model', 'composer-2.5',
                                    '--family', 'cursor', '--tier', 'large']), 0)
        self.assertEqual(next(p for p in r.load()['profiles'] if p['id'] == 'legacy')['adapter'], 'cursor')
        self.assertNotIn('cursor-agent', (r.root() / 'routing.json').read_text())
        # ... including when models_command is called directly with the alias (no argparse in between).
        direct = argparse.Namespace(action='add', id='direct', cli='cursor-agent', model='composer-2.5', family='cursor',
                                    tier='large')
        self.assertEqual(r.models_command(core, direct), 0)
        self.assertEqual(next(p for p in r.load()['profiles'] if p['id'] == 'direct')['adapter'], 'cursor')
        # Rejections: fast without a Cursor profile, `auto`, and a family that does not match.
        self.assertEqual(core.main(['models', 'add', '--id', 'nf', '--cli', 'codex', '--model', 'gpt-5.6-sol',
                                    '--family', 'openai', '--tier', 'large', '--cursor-fast']), 2)
        self.assertEqual(core.main(['models', 'add', '--id', 'auto1', '--cli', 'cursor', '--model', 'auto',
                                    '--family', 'openai', '--tier', 'large']), 2)
        self.assertEqual(core.main(['models', 'add', '--id', 'wrong', '--cli', 'cursor', '--model', 'gpt-5.6-sol-high',
                                    '--family', 'anthropic', '--tier', 'large']), 2)
        self.assertEqual(core.main(['models', 'add', '--id', 'lie', '--cli', 'codex', '--model', 'gpt-5.6-sol',
                                    '--family', 'cursor', '--tier', 'large']), 2)
        self.assertEqual({p['id'] for p in r.load()['profiles']} & {'nf', 'auto1', 'wrong', 'lie'}, set())

    def test_alias_is_normalized_at_the_boundaries_and_validate_stays_pure(self):
        self.profile('cursor-large-composer-2-5')['adapter'] = 'cursor-agent'
        aliased = copy.deepcopy(self.config)
        with self.assertRaisesRegex(r.RoutingError, 'unknown adapter'):
            r.validate(aliased)  # validate() neither accepts the alias nor rewrites it
        self.assertEqual(next(p for p in aliased['profiles'] if p['id'] == 'cursor-large-composer-2-5')['adapter'], 'cursor-agent')
        r.save(r.root() / 'routing.json', self.config)
        loaded = r.load()  # load() normalizes before validating
        self.assertEqual(next(p for p in loaded['profiles'] if p['id'] == 'cursor-large-composer-2-5')['adapter'], 'cursor')
        self.assertEqual(r.normalize_adapter(' cursor-agent '), 'cursor')
        self.assertEqual(r.normalize_adapter('codex'), 'codex')
        self.assertIsNone(r.normalize_adapter(None))
        self.assertIs(r.normalize({'profiles': 'not a list'})['profiles'], 'not a list')
        self.run_setup()  # the next explicit save persists the canonical name and no alias anywhere
        self.assertNotIn('cursor-agent', (r.root() / 'routing.json').read_text())
        self.assertNotIn('cursor-agent', json.dumps(r.starter(core)))
        with patch.object(r, 'inventory', return_value=self.available), contextlib.redirect_stderr(io.StringIO()):
            r.setup(core, self.setup_args(billing=['cursor-agent=metered']))
        self.assertEqual({p['billing_mode'] for p in r.load()['profiles'] if p['adapter'] == 'cursor'}, {'metered'})
        self.assertNotIn('cursor-agent', (r.root() / 'routing.json').read_text())

    def test_panelists_alias_selects_the_one_canonical_adapter(self):
        self.only('cursor-large-composer-2-5', 'codex-large')
        for value in ('cursor-agent', 'cursor', ' cursor-agent , cursor ', 'cursor-agent,cursor-agent'):
            with self.subTest(panelists=value):
                decision = self.resolve(panelists=value)
                self.assertEqual((decision['cli'], decision['profile']), ('cursor', 'cursor-large-composer-2-5'))
                self.assertEqual(self.reasons(decision)['codex-large'], 'outside explicit panelists')
        with patch.dict(os.environ, {'ALLOY_PANELISTS': 'cursor-agent'}):
            self.assertEqual(self.resolve()['cli'], 'cursor')
        self.assertEqual(self.resolve(panelists='codex')['cli'], 'codex')

    def test_unnormalized_alias_profiles_dispatch_only_under_the_canonical_name(self):
        # Even an in-memory profile that still says cursor-agent yields the canonical name in decisions.
        self.profile('cursor-large-composer-2-5')['adapter'] = 'cursor-agent'
        self.only('cursor-large-composer-2-5')
        decision = self.resolve()
        self.assertEqual(decision['cli'], 'cursor')
        self.assertEqual([c['profile'] for c in self.cards()], ['cursor-large-composer-2-5'])

    # -- pacing --------------------------------------------------------------------------------
    def paced(self, pid, host):
        self.only(pid)
        self.config['policy']['quota_pacing'] = True
        snap = self.live(cursor=(.3, .05))  # a fresh Cursor window: 30% left, 5% of the window still to run
        answers = core.execution.host_assessment(argparse.Namespace(task_tier='large'))
        args = copy.copy(self.args)
        args.host_family = host
        return r.resolve(core, self.config, answers, self.available, args, snap)

    def test_quota_pacing_uses_the_effective_family_of_cursor_profiles(self):
        snap = self.live(cursor=(.3, .05))
        self.assertIsNotNone(r.usage.pacing(self.profile('cursor-large-claude-opus-5-5'), snap))  # the window is usable ...
        self.assertIsNone(r.usage.pacing(self.profile('cursor-large-claude-opus-5-5'), {}))       # ... unknown usage is not
        discounted = lambda d: d['effective_cost_rank'] < d['cost_rank']
        pressure = (.05 / .3)
        # Cursor-to-Claude IS the host's Anthropic family: the conservative rule, no outside-family discount.
        d = self.paced('cursor-large-claude-opus-5-5', 'anthropic')
        self.assertFalse(discounted(d))
        self.assertAlmostEqual(d['effective_cost_rank'], 3 / .3)
        d = self.paced('cursor-large-claude-opus-5-5', 'openai')
        self.assertAlmostEqual(d['effective_cost_rank'], 3 * pressure, places=4)
        # Cursor-to-GPT follows the same rule against an OpenAI host, and Composer against a Cursor host.
        self.assertFalse(discounted(self.paced('cursor-large-gpt-5-6-sol', 'openai')))
        self.assertTrue(discounted(self.paced('cursor-large-gpt-5-6-sol', 'anthropic')))
        self.assertFalse(discounted(self.paced('cursor-large-composer-2-5', 'cursor')))
        self.assertTrue(discounted(self.paced('cursor-large-composer-2-5', 'anthropic')))
        self.assertTrue(discounted(self.paced('cursor-large-composer-2-5', None)))


class InstallerTests(unittest.TestCase):
    def test_install_repeat_uninstall_and_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, SKILLS_DIR=tmp + '/skills', ALLOY_INSTALL_BIN_DIR=tmp + '/bin')
            def run(*args):
                return subprocess.run(['bash', str(REPO/'install.sh'), '--skip-doctor'] + list(args), env=env, capture_output=True, text=True)
            self.assertEqual(run().returncode, 0)
            self.assertEqual(run().returncode, 0)
            executable = Path(tmp) / 'bin/alloy'
            self.assertTrue(executable.is_symlink())
            proc = subprocess.run([str(executable), 'route', '--help'], env=env, capture_output=True)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(run('--uninstall').returncode, 0)
            self.assertFalse(executable.exists())
            executable.write_text('keep me')
            self.assertNotEqual(run().returncode, 0)
            self.assertEqual(executable.read_text(), 'keep me')
