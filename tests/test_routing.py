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
        r.save(r.root() / 'routing.json', self.config)
        self.available = {n: dict(status='ready', compatible=True, version='test') for n in r.FAMILIES}
        r.save(r.root() / 'models-cache.json', dict(refreshed_at=r.time.time(), adapters=self.available))
        self.args = argparse.Namespace(mode='consult', exclude_family='', host_family=None,
            panelists=None, profile=None, max_estimated_usd=None)

    def decide(self, answer=None):
        return r.route(core, 'Change the README title to Alloy.', self.args,
            transport=lambda payload: (answer or response(), 5), available=self.available)

    def test_small_and_large_choose_different_profiles(self):
        self.assertEqual(self.decide()['profile'], 'codex-small')
        self.assertEqual(self.decide(response('large'))['required_tier'], 'large')
        self.assertNotEqual(self.decide(response('large'))['profile'], 'codex-small')

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
        with patch.object(r.subprocess, 'run', side_effect=output):
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

    def test_http_retry_bounded_and_error_body_not_exposed(self):
        error = lambda: urllib.error.HTTPError('url', 429, 'secret-body', {'Retry-After': '0'}, None)
        opener = Mock(); opener.open.side_effect = [error(), error(), error()]
        with patch.object(r, 'key', return_value='secret'), patch.object(r.urllib.request, 'build_opener', return_value=opener), patch.object(r.time, 'sleep'):
            with self.assertRaisesRegex(r.RoutingError, 'HTTP 429'): r.request({})
        self.assertEqual(opener.open.call_count, 3)

    def test_http_401_does_not_retry_or_reveal_body(self):
        opener = Mock(); opener.open.side_effect = urllib.error.HTTPError('url', 401, 'secret', {}, None)
        with patch.object(r, 'key', return_value='secret'), patch.object(r.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(r.RoutingError, 'HTTP 401'): r.request({})
        self.assertEqual(opener.open.call_count, 1)

    def test_route_adapter_does_not_mutate_default(self):
        before = core.ADAPTERS['codex'].model()
        decision = self.decide()
        ad = r.routed_adapter(core, decision)
        argv = ad.build_args('p', 'out', 'consult')
        self.assertIn(decision['model'], argv)
        self.assertIn('model_reasoning_effort=medium', argv)
        self.assertEqual(core.ADAPTERS['codex'].model(), before)

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
        executable.write_text('#!/usr/bin/env python3\nimport os,sys,json\nprint(json.dumps({"argv":sys.argv[1:],"key_present":"TYPESAFE_API_KEY" in os.environ}))\n')
        executable.chmod(0o755)
        task = Path(self.tmp.name) / 'task'; task.write_text('Rename README heading')
        output = io.StringIO()
        with patch.dict(os.environ, {'ALLOY_BIN_CODEX': str(executable), 'CODEX_API_KEY': 'test', 'TYPESAFE_API_KEY': 'private', 'ALLOY_REPO': 'none'}), patch.object(r, 'inventory', return_value=self.available), patch.object(r, 'request', return_value=(response(), 1)), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = core.main(['panel', '--route', '--prompt-file', str(task), '--no-repo', '--run-dir', str(Path(self.tmp.name) / 'runs')])
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
