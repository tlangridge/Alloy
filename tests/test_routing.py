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
import subprocess
import sys
import tempfile
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


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'ALLOY_ROUTING_HOME': self.tmp.name, 'ALLOY_CONFIG': '/dev/null', 'ALLOY_USAGE': 'off'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.settings = patch.object(core, '_CONFIG', {})
        self.settings.start(); self.addCleanup(self.settings.stop)
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

    def test_grok_47_default_preserves_pins_and_separates_fast_evidence(self):
        with patch.dict(os.environ, {'ALLOY_GROK_MODEL': ''}):
            profiles = r.starter(core)['profiles']
            self.assertEqual(next(p['model'] for p in profiles if p['adapter'] == 'grok'), 'grok-4.7')
        with patch.dict(os.environ, {'ALLOY_GROK_MODEL': 'grok-4.6'}):
            self.assertEqual(next(p['model'] for p in r.starter(core)['profiles'] if p['adapter'] == 'grok'), 'grok-4.6')
        data = r.evidence.catalog()
        data['status'] = 'current'
        profile = dict(model='grok-4.7', family='xai', effort='high')
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
