"""Quality, capabilities and migration behavior with fake transport only."""
import argparse
import copy
import json
import os
import time
from unittest.mock import patch

from test_routing import RoutingCase, response, core, r


class QualityRoutingTests(RoutingCase):
    def setUp(self):
        super().setUp()
        self.config['policy']['objective'] = 'quality_first'

    def profile(self, identity, adapter, model, preferences, cost=1, tier='large'):
        return dict(id=identity, adapter=adapter, model=model, family=r.FAMILIES[adapter],
                    effort='high', tier=tier, enabled=True, billing_mode='unknown',
                    cost_rank=cost, task_preferences=preferences)

    def select(self, kind='debugging', tier='large', snapshot=None):
        answers = response(tier)['answers']
        answers['kind']['choice'] = kind
        return r.resolve(core, self.config, answers, self.available, self.args, snapshot)

    def test_quality_beats_price_outside_old_premium(self):
        self.config['profiles'] = [self.profile('cheap', 'grok', 'grok-4.7', [], .01),
                                   self.profile('specialist', 'claude', 'claude-opus-5-5', ['debugging'], 9)]
        picked = self.select()
        self.assertEqual(picked['profile'], 'specialist')
        self.assertFalse(picked['recommendations'][0]['within_cost_tolerance'])
        self.assertIsNone(picked['quality']['measured_success_rate'])

    def test_spare_quota_cannot_overrule_quality(self):
        self.config['profiles'] = [self.profile('idle', 'grok', 'grok-4.7', [], .01),
                                   self.profile('busy', 'claude', 'claude-opus-5-5', ['debugging'], 9)]
        self.assertEqual(self.select(snapshot=self.live(grok=(.99, .7), claude=(.12, .8)))['profile'], 'busy')

    def test_equal_quality_can_use_spare_capacity(self):
        self.config['profiles'] = [self.profile('idle', 'grok', 'grok-4.7', ['debugging']),
                                   self.profile('busy', 'claude', 'claude-opus-5-5', ['debugging'])]
        self.assertEqual(self.select(snapshot=self.live(grok=(.9, .7), claude=(.2, .8)))['profile'], 'idle')

    def test_tier_promotion_does_not_certify_large_checker(self):
        p = next(p for p in self.config['profiles'] if p['id'] == 'codex-small')
        self.config['profiles'] = [p]
        self.args.mode = 'review'
        with self.assertRaisesRegex(r.RoutingError, 'below required tier'):
            self.select(kind='review')

    def test_ambiguity_stops_maker_before_work(self):
        self.args.mode, self.args.host_family = 'make', 'openai'
        with self.assertRaisesRegex(r.RoutingError, 'needs_clarification'):
            r.resolve(core, self.config, response('large', ambiguous=1)['answers'], self.available, self.args)

    def test_expired_evidence_cannot_restore_small_checker_promotion(self):
        p = next(p for p in self.config['profiles'] if p['id'] == 'codex-small')
        self.config['profiles'] = [p]
        self.args.mode = 'review'
        with patch.object(r.evidence, 'catalog', return_value={'status': 'expired', 'models': []}):
            with self.assertRaisesRegex(r.RoutingError, 'below required tier'):
                self.select(kind='review')

    def test_authoritative_listing_requires_matching_version_and_freshness(self):
        cache = {'discovered': {'claude': dict(models=[], authoritative=True, cli_version='test', observed_at=time.time())}}
        r.apply_discovery(self.available, cache)
        self.assertIs(self.available['claude']['authoritative'], True)
        for version, age in (('different', 1), ('test', 90000)):
            current = copy.deepcopy(self.available)
            current['claude'].pop('authoritative'); current['claude'].pop('models')
            cache['discovered']['claude'].update(cli_version=version, observed_at=time.time() - age)
            r.apply_discovery(current, cache)
            self.assertNotIn('authoritative', current['claude'])

    def test_review_tool_requirements_are_shared_and_respect_kind_confidence(self):
        args = argparse.Namespace(require_capability=['image_generation', 'web'], artifact=['page.png'])
        self.assertEqual(r.quality.requirements(args, 'image_generation', 'review'), ['image_input', 'web'])
        self.config['profiles'] = [self.profile('vision', 'muse', 'muse-wonder-full-1.0', ['review'])]
        self.available['muse']['image_flag'] = '--image'
        self.args.mode = 'review'
        self.assertEqual(self.select(kind='image_understanding')['profile'], 'vision')
        self.args.require_capability = ['web']
        self.args.artifact = ['page.png']
        with self.assertRaisesRegex(r.RoutingError, 'web'):
            self.select(kind='image_generation')
        self.args.require_capability = None; self.args.artifact = None
        self.available['muse'].pop('image_flag')
        answers = response('large')['answers']
        answers['kind'] = dict(choice='image_understanding', confidence=.4)
        with self.assertRaisesRegex(r.RoutingError, 'image_input'):
            r.resolve(core, self.config, answers, self.available, self.args)
        self.available['muse']['image_flag'] = '--image'
        self.assertEqual(r.resolve(core, self.config, answers, self.available, self.args)['profile'], 'vision')

    def test_native_aliases_cannot_be_relabelled_as_an_independent_family(self):
        p = self.profile('alias', 'claude', 'sonnet', ['review'])
        p['family'] = 'openai'
        self.assertIn('family', r.profile_problem(p))
        with self.assertRaisesRegex(core.execution.ExecutionError, 'family'):
            core.execution.check_decision(core, dict(cli='claude', model='sonnet', family='openai'))
        p.update(model='gpt-6.1-sol')  # An explicit cross-provider identity remains supported.
        self.assertIsNone(r.profile_problem(p))
        p.update(adapter='antigravity', model='opaque-alias', family='google')
        self.assertIn('known family', r.profile_problem(p))

    def test_refresh_adds_distinct_efforts_and_preserves_disabled_choices(self):
        config = r.starter(core)
        config['profiles'] = [p for p in config['profiles'] if p['id'] != 'claude-opus-5-5-xhigh']
        before = copy.deepcopy(config['profiles'])
        r.refresh_defaults(core, config)
        added = next(p for p in config['profiles'] if p['id'] == 'claude-opus-5-5-xhigh')
        self.assertEqual(added['effort'], 'xhigh')
        self.assertEqual(config['profiles'][:len(before)], before)
        current = copy.deepcopy(config)
        r.refresh_defaults(core, config)
        self.assertEqual(config, current)
        config['profiles'] = [p for p in before]
        for p in config['profiles']:
            if p['model'] == 'claude-opus-5-5':
                p['enabled'] = False
        r.refresh_defaults(core, config)
        self.assertFalse(next(p for p in config['profiles'] if p['id'] == 'claude-opus-5-5-xhigh')['enabled'])

    def test_custom_preferences_keep_model_modality_and_tier_evidence(self):
        p = self.profile('vision', 'muse', 'muse-wonder-full-1.0', ['review'])
        self.available['muse']['image_flag'] = '--image'
        assessed = r.evidence.assessment(p, r.evidence.catalog())
        self.assertEqual(assessed['status'], 'user-configured')
        self.assertIn('image', assessed['input_modalities'])
        self.assertEqual(assessed['suggested_tier'], 'large')
        self.assertEqual(r.quality.capabilities(core, p, self.available)['image_input'], 'verified')

    def test_legacy_maker_cannot_reserve_an_unavailable_checker(self):
        self.config['policy']['objective'] = 'cost_first'
        self.config['profiles'] = [self.profile('m', 'claude', 'claude-opus-5-5', ['implementation']),
                                   self.profile('c', 'antigravity', 'gemini-4-argon-high', ['review'])]
        self.args.mode, self.args.host_family = 'make', 'openai'
        self.available['antigravity'].update(models=[], authoritative=True)
        with self.assertRaisesRegex(r.RoutingError, 'independent.*Checker'):
            self.select(kind='implementation')

    def test_raster_generation_needs_an_actual_tool(self):
        with self.assertRaisesRegex(r.RoutingError, 'image_generation'):
            self.select(kind='image_generation')

    def test_capability_attestation_is_exact_and_expires(self):
        p = self.profile('vision', 'claude', 'claude-opus-5-5', ['debugging'])
        now = time.time()
        p['capabilities'] = {'image_input': dict(status='verified', source='fake CLI probe',
            observed_at=now - 1, expires_at=now + 60,
            identity=dict(model=p['model'], effort='high', cli_version='test'))}
        self.config['profiles'] = [p]
        self.args.require_capability = ['image_input']
        self.assertEqual(self.select()['profile'], 'vision')
        self.available['claude']['version'] = 'different'
        with self.assertRaisesRegex(r.RoutingError, 'image_input'):
            self.select()
        self.available['claude']['version'] = 'test'
        p['capabilities']['image_input']['expires_at'] = now - .5
        with self.assertRaisesRegex(r.RoutingError, 'image_input'):
            self.select()

    def test_declared_write_tool_cannot_grant_an_unsupported_maker(self):
        self.config['profiles'] = [self.profile('meta', 'muse', 'muse-wonder-full-1.0', ['implementation'])]
        self.args.mode, self.args.host_family = 'make', 'openai'
        with self.assertRaisesRegex(r.RoutingError, 'managed write adapter'):
            self.select(kind='implementation')

    def test_joint_pair_preserves_the_strong_checker_family(self):
        self.config['profiles'] = [
            self.profile('cheap-maker', 'claude', 'claude-opus-5-5', ['implementation'], .01),
            self.profile('other-maker', 'antigravity', 'gemini-4-argon-high', ['implementation'], 2),
            self.profile('strong-checker', 'claude', 'claude-opus-5-5', ['review'], 3),
            self.profile('weak-checker', 'grok', 'grok-4.7', [], .01)]
        args = argparse.Namespace(mode='make', host_family='openai', profile=None, panelists=None,
                                  exclude_family='', max_estimated_usd=None)
        m, c = r.resolve_pair(core, self.config, response('large')['answers'], self.available, args)
        self.assertEqual((m['profile'], c['profile']), ('other-maker', 'strong-checker'))
        self.assertEqual(len({'openai', m['family'], c['family']}), 3)

    def test_joint_pair_honors_explicit_profiles_and_quota_reserve(self):
        self.config['profiles'] = [self.profile('m', 'claude', 'claude-opus-5-5', ['implementation']),
                                   self.profile('c', 'antigravity', 'gemini-4-argon-high', ['review'])]
        args = argparse.Namespace(mode='make', host_family='openai', profile=None, maker_profile='m',
                                  checker_profile='c', panelists=None, exclude_family='', max_estimated_usd=None)
        m, c = r.resolve_pair(core, self.config, response('large')['answers'], self.available, args)
        self.assertEqual((m['profile'], c['profile']), ('m', 'c'))
        self.config['profiles'][1]['quota_pool'] = 'antigravity:gemini'
        self.config['quota_pools'] = {'antigravity:gemini': {'remaining_fraction': .01, 'reserve_fraction': .1}}
        self.config['profiles'][1]['billing_mode'] = 'subscription'
        with self.assertRaises(r.RoutingError):
            r.resolve_pair(core, self.config, response('large')['answers'], self.available, args,
                           {})

    def test_model_effort_and_family_are_not_interchangeable(self):
        p = self.profile('argon', 'antigravity', 'gemini-4-argon-high', ['implementation'])
        p['effort'] = 'xhigh'
        self.config['profiles'] = [p]
        with self.assertRaisesRegex(r.RoutingError, 'suffix|supports'):
            r.validate(self.config)
        p['effort'] = 'high'; p['family'] = 'anthropic'
        with self.assertRaisesRegex(r.RoutingError, 'family'):
            r.validate(self.config)

    def test_explicit_model_pin_is_not_replaced_by_quality(self):
        self.config['profiles'] = [self.profile('pinned', 'claude', 'claude-opus-5-5', [], 9),
                                   self.profile('other', 'claude', 'claude-sonnet-5-5', ['debugging'], .1)]
        with patch.dict(os.environ, ALLOY_CLAUDE_MODEL='claude-opus-5-5'):
            self.assertEqual(self.select()['profile'], 'pinned')

    def test_authoritative_absence_blocks_but_advisory_absence_does_not(self):
        self.config['profiles'] = [self.profile('p', 'claude', 'claude-opus-5-5', ['debugging'])]
        self.available['claude'].update(models=[], authoritative=False)
        self.assertEqual(self.select()['profile'], 'p')
        self.available['claude']['authoritative'] = True
        with self.assertRaisesRegex(r.RoutingError, 'authoritative'):
            self.select()

    def test_migration_preserves_all_account_and_profile_choices(self):
        original = copy.deepcopy(self.config)
        original['schema'] = 1; original['policy']['objective'] = 'cost_first'
        original['profiles'][0].update(enabled=False, billing_mode='metered', input_per_million=7)
        original['quota_pools'] = {'private': {'reserve_fraction': .2}}
        converted = r.quality.migrate(r.normalize(copy.deepcopy(original)))
        self.assertEqual(converted['profiles'], original['profiles'])
        self.assertEqual(converted['quota_pools'], original['quota_pools'])
        self.assertEqual(converted['policy']['objective'], 'quality_first')
        self.assertEqual(original['schema'], 1)
        self.assertEqual(original['policy']['objective'], 'cost_first')

    def test_new_defaults_are_quality_first_and_frontier_cards_match(self):
        config = r.starter(core)
        self.assertEqual(config['policy']['objective'], 'quality_first')
        models = {p['model']: p for p in config['profiles']}
        for name in ('gpt-6.1-sol', 'claude-sonnet-5-5', 'gemini-4-argon-high', 'muse-wonder-full-1.0'):
            self.assertEqual(r.evidence.assessment(models[name], r.evidence.catalog())['status'], 'matched')

    def test_outcomes_do_not_confuse_review_with_correctness(self):
        task = dict(id='fake-quality', state='ready', maker=dict(model='frontier', task_kind='implementation'),
                    checker=dict(model='independent'), implementation_rounds=1, active_seconds=3,
                    rounds=[dict(gates=[dict(exit_code=0)], review=dict(verdict='pass'),
                                 maker=dict(status='ok'), checker_attempts=[dict(status='timeout'), dict(status='ok')])])
        core.execution.record_outcome(core, task)
        row = json.loads((r.root() / 'outcomes/fake-quality.json').read_text())
        self.assertTrue(row['first_pass_gates'])
        self.assertEqual(row['first_pass_review'], 'pass')
        self.assertIsNone(row['independently_verified_correctness'])
        self.assertIsNone(row['user_accepted'])
        self.assertEqual(len(row['dispatches']), 3)
        self.assertNotIn('prompt', row)
