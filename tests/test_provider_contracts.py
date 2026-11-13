"""Provider identity, billing and failure regressions; mock CLIs only."""
import copy
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import threading
from unittest.mock import patch

from test_routing import RoutingCase, core, r, response
from test_frontier_adapters import FrontierCase


FAKE = r'''#!%(python)s
import json, os, sys
if '--version' in sys.argv:
    print('2.1.321'); sys.exit(0)
sys.stdin.buffer.read()
if os.environ.get('FAKE_PROTOCOL') == 'agy':
    print(json.dumps({'event':'init', 'init':{'model':'gemini-4-carbon-high',
                      'permission_mode':os.environ.get('FAKE_MODE', 'request-review')}}))
print(os.environ['FAKE_RECEIPT'])
sys.stderr.write(os.environ.get('FAKE_REASON', ''))
sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
'''


class ProviderIdentityTests(RoutingCase):
    def test_bulk_setup_does_not_acknowledge_new_fable_and_enable_is_explicit(self):
        args = argparse.Namespace(non_interactive=True, billing=['claude=subscription'], skip_live_test=True)
        with patch.object(r, 'inventory', return_value=self.available), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            r.setup(core, args)
            config = r.load()
            p = next(p for p in config['profiles'] if p['id'] == 'claude-fable-5-2')
            self.assertEqual(p['billing_mode'], 'unknown')
            self.assertFalse(p.get('usage_credits_acknowledged', False))
            r.models_command(core, argparse.Namespace(action='enable', id=p['id'], acknowledge_usage_credits=True))
        p = next(p for p in r.load()['profiles'] if p['id'] == 'claude-fable-5-2')
        self.assertTrue(p['enabled'])
        self.assertTrue(p['usage_credits_acknowledged'])

    def test_catalog_clock_isolated_from_calendar_and_expiry_is_visible(self):
        with patch('time.time', return_value=1900000000):
            self.assertEqual(r.evidence.catalog()['status'], 'current')
        with patch.object(r.evidence.time, 'time', return_value=1900000000):
            data = r.evidence.catalog()
        self.assertEqual(data['status'], 'stale')
        self.assertIn('stale', r.evidence.warning(data))
        self.assertIn('expires', r.evidence.warning(dict(status='current', days_remaining=4)))

    def test_gemini_suffixes_and_fixed_workflow_are_consistent_at_dispatch(self):
        for model, effort in (('gemini-4-carbon-high', 'xhigh'),
                              ('gemini-4-hydrogen-xhigh', 'high'),
                              ('gemini-4-hydrogen-high', 'max'),
                              ('gemini-pro-orchestrator', 'high'),
                              ('gemini-pro-orchestrator-argon', 'medium')):
            with self.subTest(model=model, effort=effort):
                p = dict(adapter='antigravity', model=model, effort=effort, family='google')
                self.assertIsNotNone(r.profile_problem(p))
                with self.assertRaises(r.RoutingError):
                    r.routed_adapter(core, dict(cli='antigravity', model=model, effort=effort))
        for model, effort in (('gemini-4-hydrogen-xhigh', 'xhigh'), ('gemini-pro-orchestrator', None)):
            self.assertIsNone(r.profile_problem(dict(adapter='antigravity', model=model, effort=effort, family='google')))

    def test_new_catalog_gates_do_not_inherit_account_or_billing_authority(self):
        config = r.starter(core)
        carbon = next(p for p in config['profiles'] if p['id'] == 'antigravity-carbon-high')
        listing = dict(version='1.5.8', authoritative=True, models=[carbon['model']])
        self.assertIsNone(r.profile_gate(carbon, listing))
        self.assertIn('listing', r.profile_gate(carbon, dict(listing, authoritative=False)))
        self.assertIn('CLI', r.profile_gate(carbon, dict(listing, version='1.5.0')))
        fable = next(p for p in config['profiles'] if p['id'] == 'claude-fable-5-2')
        self.assertFalse(fable['enabled'])
        self.assertIn('billing', r.profile_gate(fable, dict(version='2.1.321')))
        fable['usage_credits_acknowledged'] = True
        self.assertIsNone(r.profile_gate(fable, dict(version='2.1.321')))
        self.assertIn('CLI', r.profile_gate(fable, dict(version='2.1.320')))

    def test_bulk_refresh_and_reset_leave_new_fable_billing_unknown(self):
        config = copy.deepcopy(self.config)
        config['profiles'] = [p for p in config['profiles'] if p['adapter'] == 'claude' and not p.get('billing_ack_required')]
        for p in config['profiles']:
            p['billing_mode'] = 'subscription'
        before = copy.deepcopy(config['profiles'])
        r.refresh_defaults(core, config)
        self.assertEqual(config['profiles'][:len(before)], before)
        for result in (config, r.reset_defaults(core, config)):
            profiles = [p for p in result['profiles'] if p.get('billing_ack_required')]
            self.assertTrue(profiles)
            self.assertTrue(all(p['billing_mode'] == 'unknown' and not p['enabled'] for p in profiles))

    def test_current_inventory_listing_routes_new_profiles_without_relaxing_gates(self):
        config = r.starter(core)
        for p in config['profiles']:
            if not p.get('billing_ack_required'):
                p['billing_mode'] = 'subscription'
        available = copy.deepcopy(self.available)
        available['antigravity']['version'] = '1.5.8'
        listing = dict(discovered={'antigravity':dict(authoritative=True, observed_at=r.time.time(),
            cli_version='1.5.8', models=['gemini-4-carbon-high', 'gemini-4-hydrogen-xhigh'])})
        with patch.object(r, 'probe', side_effect=lambda _core, name: available[name]), patch.object(r, 'read_json', return_value=listing):
            inventory = r.inventory(core)
        for profile, expected in (('antigravity-carbon-high', 'gemini-4-carbon-high'),
                                  ('antigravity-hydrogen-xhigh', 'gemini-4-hydrogen-xhigh')):
            args = copy.copy(self.args)
            args.profile = profile
            answer = response(tier='medium')['answers']
            decision = r.resolve(core, config, answer, inventory, args, {})
            self.assertEqual(decision['model'], expected)
            self.assertEqual(decision['cli_version'], '1.5.8')

    def test_orchestrator_is_not_a_managed_writer_or_single_model_evidence(self):
        p = next(p for p in r.starter(core)['profiles'] if p['id'] == 'antigravity-orchestrator-carbon')
        caps = r.quality.capabilities(core, p, self.available, 'make')
        self.assertNotEqual(caps['managed_write'], 'verified')
        assessed = r.evidence.assessment(p, r.evidence.catalog())
        self.assertIn('Mixed-model', assessed['strengths'])
        with self.assertRaisesRegex(core.execution.ExecutionError, 'Orchestrator'):
            core.execution.probe(core, dict(cli='antigravity', model=p['model']), True)

    def test_discarded_fit_answers_are_not_requested(self):
        cards = [dict(evidence_status='unmatched', preferred_tasks=[]),
                 dict(evidence_status='matched', preferred_tasks=['review']),
                 dict(evidence_status='effort-unverified', preferred_tasks=[])]
        questions = r.fit_questions(cards)
        self.assertEqual(set(questions), {'fit_1'})
        self.assertIn('models[1]', questions['fit_1']['instructions'])

    def test_claude_read_tools_cannot_enable_shell_agents_or_mcp(self):
        ad = core.ClaudeAdapter()
        for mode in ('consult', 'review'):
            with patch.dict(os.environ, ALLOY_WEB='0', ALLOY_CLAUDE_LEAN='0'):
                args = ad.build_args('prompt', 'last', mode)
            self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk')
            self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
            self.assertIn('--strict-mcp-config', args)
            self.assertIn('--disable-slash-commands', args)
        maker = core.execution.worker_adapter(core, dict(cli='claude', model='claude-opus-5-5', effort='high'), True)
        args = maker.build_args('prompt', 'last', 'make')
        self.assertEqual(args.count('--tools'), 1)
        self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep,Edit,Write,Bash')
        self.assertIn('acceptEdits', args)
        self.assertIn('--disallowedTools', args)

    def test_fable_cli_version_is_checked_before_dispatch(self):
        ad = core.ClaudeAdapter()
        with patch.dict(os.environ, ALLOY_CLAUDE_MODEL='claude-fable-5-2'), patch.object(ad, 'cli_version', return_value='2.1.320'):
            with self.assertRaisesRegex(core.AdapterError, '2.1.321'):
                ad.build_args('prompt', 'last', 'consult')

    def test_effort_only_override_selects_known_agy_seat_but_keeps_model_pins(self):
        p = next(p for p in self.config['profiles'] if p['adapter'] == 'antigravity' and p['model'] == 'gemini-4-argon-high')
        with patch.dict(os.environ, ALLOY_ANTIGRAVITY_MODEL='', ALLOY_ANTIGRAVITY_EFFORT='Low'):
            effective = r.effective_profile(core, p, 'review')
            self.assertEqual((effective['model'], effective['effort']), ('gemini-4-argon-low', 'low'))
            ad = core.AntigravityAdapter()
            with patch.object(ad, '_agy_version', return_value=(1, 5, 8)):
                self.assertEqual(ad.model(), 'gemini-4-argon-low')
        with patch.dict(os.environ, ALLOY_ANTIGRAVITY_MODEL=p['model'], ALLOY_ANTIGRAVITY_EFFORT='low'):
            with self.assertRaises(r.RoutingError):
                r.effective_profile(core, p, 'review')
        self.assertIsNone(core.providers.agy_model_problem('gemini-4-carbon-preview-20261113', 'high'))

    def test_version_change_precedes_listing_and_minimum_version_gates(self):
        for cli, old, new in (('antigravity', '1.5.7', '1.5.8'), ('claude', '2.1.321', '2.1.320')):
            decision = dict(cli=cli, cli_version=old, profile='gated-profile')
            task = dict(maker=decision, host_family='openai')
            with patch.object(r, 'load', return_value=self.config), patch.object(r, 'inventory', return_value={cli:dict(version=new)}), patch.object(r, 'resolve') as resolve:
                with self.assertRaisesRegex(core.execution.ExecutionError, old + ' -> ' + new):
                    core.execution.revalidate(core, task, 'maker')
                resolve.assert_not_called()


class ProviderReceiptTests(FrontierCase):
    def setUp(self):
        super().setUp()
        os.environ['ALLOY_BIN_CLAUDE'] = self.fake('claude', FAKE)
        os.environ['ALLOY_BIN_ANTIGRAVITY'] = self.fake('agy', FAKE)
        os.environ['ALLOY_BIN_CODEX'] = self.fake('codex', FAKE)

    def test_exit_zero_structured_failure_is_not_an_answer(self):
        receipt = dict(type='result', subtype='error_max_turns', is_error=True,
                       result='Credit balance is too low sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123')
        st = self.dispatch(self.f.ClaudeAdapter(), FAKE_RECEIPT=json.dumps(receipt))
        self.assertEqual((st['status'], st['failure_kind']), ('error', 'quota'))
        self.assertIn('Credit balance', st['error'])
        self.assertNotIn('sk-proj-', st['error'])
        self.assertNotIn('sk-proj-', self.read(st, 'stdout_path'))

    def test_nonzero_auth_is_classified_and_non_auth_retains_diagnostics(self):
        for reason, status in [('Invalid API key', 'auth'), ('provider crashed', 'error')]:
            st = self.dispatch(self.f.ClaudeAdapter(), FAKE_RECEIPT='', FAKE_EXIT='1', FAKE_REASON=reason)
            self.assertEqual(st['status'], status)
            self.assertIn(reason, st['error'])

    def test_answer_auth_words_never_trigger_retry_and_early_stderr_auth_is_seen(self):
        receipt = dict(type='result', subtype='error_max_turns', is_error=True,
                       result='Stopped reviewing HTTP 401 Unauthorized handling')
        st = self.dispatch(self.f.ClaudeAdapter(), FAKE_RECEIPT=json.dumps(receipt))
        self.assertEqual((st['status'], st['failure_kind']), ('error', 'provider_error'))

        receipt.update(subtype='success', is_error=False)
        st = self.dispatch(self.f.ClaudeAdapter(), FAKE_RECEIPT=json.dumps(receipt), FAKE_EXIT='1')
        self.assertEqual(st['status'], 'error')
        st = self.dispatch(self.f.ClaudeAdapter(), FAKE_RECEIPT='',
                           FAKE_REASON='AuthorizationRequired\n' + 'diagnostic noise\n' * 15)
        self.assertEqual(st['status'], 'auth')
        self.assertIn('AuthorizationRequired', st['error'])
        st = self.dispatch(self.f.CodexAdapter(), FAKE_RECEIPT='', FAKE_EXIT='1',
                           FAKE_REASON='Review the HTTP 401 Unauthorized handler')
        self.assertEqual((st['status'], st['failure_kind']), ('error', 'provider_error'))

    def test_codex_json_preamble_cannot_turn_stderr_prose_into_auth_retry(self):
        st = self.dispatch(self.f.CodexAdapter(), ALLOY_CAPTURE_USAGE='1', FAKE_EXIT='1',
                           FAKE_RECEIPT=json.dumps(dict(type='thread.started', thread_id='fixture')),
                           FAKE_REASON='Review the HTTP 401 Unauthorized handler')
        self.assertEqual(st['status'], 'error')
        self.assertNotEqual(st['failure_kind'], 'auth')

    def test_served_models_are_retained_separately_from_requested_model(self):
        receipt = dict(type='result', subtype='success', is_error=False, result='Review done',
                       modelUsage={'claude-fable-5-2': {}, 'claude-haiku-5-5': {}})
        st = self.dispatch(self.f.ClaudeAdapter(), FAKE_RECEIPT=json.dumps(receipt), ALLOY_CLAUDE_MODEL='claude-fable-5-2')
        self.assertEqual(st['status'], 'ok')
        self.assertEqual(st['model'], 'claude-fable-5-2')
        self.assertEqual(st['served_models'], ['claude-fable-5-2', 'claude-haiku-5-5'])

    def test_agy_reported_write_mode_fails_read_only_call(self):
        receipt = dict(event='result', result=dict(status='SUCCESS', response='Done', error=''))
        st = self.dispatch(self.f.AntigravityAdapter(), FAKE_RECEIPT=json.dumps(receipt), FAKE_PROTOCOL='agy', FAKE_MODE='auto')
        self.assertEqual(st['status'], 'error')
        self.assertEqual(st['provider_init']['permission_mode'], 'auto')

    def test_agy_nested_receipt_preserves_model_and_flat_receipts_still_work(self):
        receipt = dict(event='result', result=dict(status='SUCCESS', response='Done', error=''))
        ad = self.f.AntigravityAdapter()
        st = self.dispatch(ad, FAKE_RECEIPT=json.dumps(receipt), FAKE_PROTOCOL='agy')
        self.assertEqual(st['status'], 'ok')
        self.assertEqual(st['provider_init'], dict(model='gemini-4-carbon-high', permission_mode='request-review'))
        flat = dict(event='init', model='legacy', permission_mode='plan')
        self.assertEqual(ad.provider_meta(json.dumps(flat))['provider_init']['model'], 'legacy')

    def test_custom_agy_account_survives_direct_and_managed_dispatch_homes(self):
        real, pinned = Path(self.tmp) / 'real', Path(self.tmp) / 'account'
        preferences = bytes.fromhex('62706c6973743030d101025e4163636f756e74466978747572655864697374696e6374080b1a0000000000000101000000000000000300000000000000000000000000000023')
        for root, account in ((real, 'default'), (pinned, 'distinct')):
            (root / '.gemini').mkdir(parents=True)
            (root / '.gemini/oauth_creds.json').write_text(json.dumps(dict(account=account)))
            (root / 'Library/Preferences').mkdir(parents=True)
            (root / 'Library/Preferences/com.apple.security.plist').write_bytes(preferences)
        ad = self.f.AntigravityAdapter()
        with patch.dict(os.environ, HOME=str(real), ALLOY_ANTIGRAVITY_HOME=str(pinned)):
            direct = ad._home(dict(pdir=self.tmp))
            self.assertEqual(direct, str(pinned))
            self.assertFalse((pinned / '.gemini/oauth_creds.json').is_symlink())
            self.assertEqual((pinned / 'Library/Preferences/com.apple.security.plist').read_bytes(), preferences)
            with patch.object(ad, '_agy_version', return_value=(1, 2, 12)):
                self.assertEqual(ad._home(dict(pdir=self.tmp)), str(pinned))
                lease = ad.open_scope(self.tmp, self.repo, False)
                try:
                    with self.assertRaises(self.f.AdapterBusyError):
                        ad.open_scope(self.tmp, self.repo, False)
                finally:
                    lease.close()
            private = Path(ad._home(dict(pdir=self.tmp, managed_worktree=True)))
            self.assertNotEqual(private, pinned)
            self.assertEqual(json.loads((private / '.gemini/oauth_creds.json').read_text())['account'], 'distinct')
            if self.f.sys.platform == 'darwin':
                self.assertEqual((private / 'Library/Preferences/com.apple.security.plist').read_bytes(), preferences)
            ad.execution_permissions = {}
            checker = Path(ad._home(dict(pdir=str(Path(self.tmp) / 'checker'))))
            self.assertEqual(checker.name, 'agy_home')

    def test_home_lock_errors_are_recorded_and_contention_is_retryable(self):
        pinned = Path(self.tmp) / 'pinned'
        pinned.mkdir()
        (pinned / '.alloy-home.lock').symlink_to(Path(self.tmp) / 'elsewhere')
        with patch.dict(os.environ, ALLOY_ANTIGRAVITY_HOME=str(pinned)):
            st = self.dispatch(self.f.AntigravityAdapter(), FAKE_RECEIPT='')
            self.assertEqual(st['failure_kind'], 'refused')
            (pinned / '.alloy-home.lock').unlink()
            ad = self.f.AntigravityAdapter()
            lease = ad.open_scope(self.tmp, self.repo, False)
            try:
                st = self.dispatch(ad, FAKE_RECEIPT='')
                self.assertEqual(st['failure_kind'], 'busy')
                self.assertTrue(st['error'].startswith('busy:'))
            finally:
                lease.close()

    def test_agy_grant_sets_never_overwrite_each_other(self):
        ad = self.f.AntigravityAdapter()
        repos = [str(Path(self.tmp) / name) for name in ('one', 'two')]
        for repo in repos:
            Path(repo).mkdir()
        barrier = threading.Barrier(2)
        observed = {}
        def read(index):
            ctx = {'agy_add_dirs': [repos[index]]}
            home = ad._home(ctx)
            barrier.wait(timeout=5)
            settings = json.loads((Path(home) / '.gemini/antigravity-cli/settings.json').read_text())
            observed[index] = (home, settings['permissions']['allow'])
        workers = [threading.Thread(target=read, args=(i,)) for i in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(10)
        self.assertEqual(len(observed), 2)
        self.assertNotEqual(observed[0][0], observed[1][0])
        for index in range(2):
            self.assertEqual([g for g in observed[index][1] if g.startswith('read_file(')], ['read_file(%s)' % repos[index]])

    def test_pinned_agy_home_has_one_lease_and_preserves_its_path(self):
        home = str(Path(self.tmp) / 'pinned')
        ad = self.f.AntigravityAdapter()
        with patch.dict(os.environ, ALLOY_ANTIGRAVITY_HOME=home):
            lease = ad.open_scope(self.tmp, self.repo, False)
            try:
                with self.assertRaisesRegex(self.f.AdapterError, 'in use'):
                    ad.open_scope(self.tmp, self.repo, False)
                self.assertEqual(ad._home({}), home)
            finally:
                lease.close()
            ad.open_scope(self.tmp, self.repo, False).close()
