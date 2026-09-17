"""Quota normalization, freshness, rendering and routing. No live provider calls."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from test_routing import core, response

r = core.routing
u = r.usage


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'ALLOY_ROUTING_HOME': self.tmp.name, 'ALLOY_USAGE': 'on'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.cfg = patch.object(core, '_CONFIG', {})
        self.cfg.start(); self.addCleanup(self.cfg.stop)
        self.config = r.starter(core)
        r.save(r.root() / 'routing.json', self.config)
        self.snapshot = dict(enabled=True, ttl_seconds=120, providers={})
        self.available = {n: dict(status='ready', compatible=True) for n in u.PROVIDERS}
        self.args = argparse.Namespace(mode='consult', exclude_family='', host_family=None,
            panelists=None, profile=None, max_estimated_usd=None)

    def row(self, provider='codex', remaining=.5, age=0, pool=None, status='fresh'):
        return dict(status=status, observed_at=time.time()-age, checked_at=time.time(),
            binding=u.binding(core, provider), source='test', windows=[
            u.window(pool or provider, '5h', remaining, time.time()+3600)])

    def test_grok_percentage_period_and_zero(self):
        now = time.time()
        for used in (0, 49, 100):
            windows = u.parse_grok({'config': {'creditUsagePercent': used,
                'currentPeriod': {'start': now-100, 'end': now-100+7*86400}}})
            self.assertEqual(windows[0]['window'], 'weekly')
            self.assertAlmostEqual(windows[0]['remaining_fraction'], 1-used/100)
        result = u.parse_grok({'config': {'used': {'val': 25}, 'monthlyLimit': {'val': 100},
            'billingPeriodStart': now-100, 'billingPeriodEnd': now-100+30*86400}})
        self.assertEqual(result[0]['window'], 'monthly')
        self.assertEqual(result[0]['remaining_fraction'], .75)

    def test_grok_missing_invalid_and_ondemand_are_not_capacity(self):
        base = {'billingPeriodEnd': time.time()+1000}
        for extra in ({}, {'creditUsagePercent': None}, {'creditUsagePercent': -1},
                      {'creditUsagePercent': 101}, {'creditUsagePercent': float('nan')},
                      {'creditUsagePercent': True}, {'creditUsagePercent': '49'},
                      {'onDemandUsed': {'val': 0}, 'onDemandCap': {'val': 100}},
                      {'used': {'val': 0}, 'monthlyLimit': {'val': 0}}):
            with self.subTest(extra=extra), self.assertRaises(u.UsageError):
                u.parse_grok({'config': dict(base, **extra)})
        with self.assertRaises(u.UsageError):
            u.parse_grok({'config': {'creditUsagePercent': 0}})

    def test_grok_fetch_is_bounded_private_and_auth_bound(self):
        auth = Path(self.tmp.name)/'auth.json'
        entry = {'key': 'test-secret', 'expires_at': time.time()+1000}
        auth.write_text(json.dumps({'https://auth.x.ai::test': entry}))
        payload = {'config': {'creditUsagePercent': 49, 'billingPeriodEnd': time.time()+1000}}
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=io.BytesIO(json.dumps(payload).encode()))
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.dict(os.environ, {'GROK_HOME': self.tmp.name, 'XAI_API_KEY': '', 'GROK_API_KEY': ''}), \
             patch.object(u.urllib.request, 'build_opener', return_value=opener):
            before = u.binding(core, 'grok')
            source, windows = u.fetch_grok(core)
            self.assertEqual(source, 'grok-cli-billing')
            self.assertEqual(windows[0]['remaining_fraction'], .51)
            request = opener.open.call_args[0][0]
            self.assertEqual(request.full_url, 'https://cli-chat-proxy.grok.com/v1/billing?format=credits')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
            self.assertEqual(opener.open.call_args[1]['timeout'], 8)
            self.assertNotIn('test-secret', json.dumps(windows))
            for changes in ({'expires_at': 1}, {'principal_type': 'team'}):
                auth.write_text(json.dumps({'https://auth.x.ai::test': dict(entry, **changes)}))
                with self.assertRaises(u.UsageError): u.fetch_grok(core)
            self.assertNotEqual(before, u.binding(core, 'grok'))
            self.assertEqual(opener.open.call_count, 1)

    def test_grok_http_error_never_exposes_response(self):
        auth = Path(self.tmp.name)/'auth.json'
        auth.write_text(json.dumps({'https://auth.x.ai::test':
            {'key': 'test-secret', 'expires_at': time.time()+1000}}))
        opener = Mock()
        opener.open.side_effect = u.urllib.error.HTTPError('url', 401, 'secret-body', {}, io.BytesIO(b'secret'))
        with patch.dict(os.environ, {'GROK_HOME': self.tmp.name, 'XAI_API_KEY': '', 'GROK_API_KEY': ''}), \
             patch.object(u.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(u.UsageError, 'HTTP 401') as caught: u.fetch_grok(core)
            self.assertNotIn('secret', str(caught.exception))
            self.assertEqual(opener.open.call_count, 1)

    def test_codex_duration_and_zero_are_not_missing(self):
        data = dict(rateLimitsByLimitId={'codex': dict(primary=dict(usedPercent=100,
            windowDurationMins=10080, resetsAt=time.time()+100), secondary=None)})
        windows = u.parse_codex(data)
        self.assertEqual(windows[0]['window'], '7d')
        self.assertEqual(windows[0]['remaining_fraction'], 0)
        data['rateLimitsByLimitId']['codex']['primary']['usedPercent'] = None
        with self.assertRaises(u.UsageError): u.parse_codex(data)

    def test_codex_named_buckets_kept_separate(self):
        data = dict(rateLimitsByLimitId={n: dict(primary=dict(usedPercent=i,
            windowDurationMins=300)) for n,i in [('codex',20),('codex-special',90)]})
        self.assertEqual({w['pool'] for w in u.parse_codex(data)}, {'codex','codex-special'})

    def test_claude_model_specific_windows(self):
        data = dict(five_hour=dict(utilization=20), seven_day=dict(utilization=30),
            seven_day_sonnet=dict(utilization=100), seven_day_opus=None)
        row = self.row('claude'); row['windows'] = u.parse_claude(data)
        self.snapshot['providers']['claude'] = row
        sonnet = dict(adapter='claude', model='sonnet', billing_mode='subscription')
        opus = dict(sonnet, model='opus')
        self.assertEqual(u.headroom(sonnet, self.snapshot), 0)
        self.assertAlmostEqual(u.headroom(opus, self.snapshot), .7)

    def test_claude_fable_scoped_limit_display_and_routing(self):
        lane = dict(kind='weekly_scoped', percent=16, is_active=False,
            resets_at=time.time()+3600, scope=dict(model=dict(id=None, display_name='Fable'), surface=None))
        data = dict(seven_day=dict(utilization=30), limits=[lane])
        row = self.row('claude'); row['windows'] = u.parse_claude(data)
        self.snapshot['providers']['claude'] = row
        self.assertIn('Claude / Fable', u.render(self.snapshot))
        self.assertIn('84%', u.render(self.snapshot))
        fable = dict(adapter='claude', model='claude-fable-5.1', billing_mode='subscription')
        self.assertAlmostEqual(u.headroom(fable, self.snapshot), .7)
        lane['percent'] = 95
        row['windows'] = u.parse_claude(data)
        self.assertAlmostEqual(u.headroom(fable, self.snapshot), .05)
        self.assertAlmostEqual(u.headroom(dict(fable, model='sonnet'), self.snapshot), .7)
        data['seven_day_fable'] = dict(utilization=10)
        self.assertEqual(len(u.parse_claude(data)), 2)
        lane['percent'] = None
        with self.assertRaises(u.UsageError): u.parse_claude(data)

    def test_claude_scoped_unknown_or_surface_not_shared(self):
        for model, surface in [('Future', None), ('Fable', 'cowork')]:
            data = dict(seven_day=dict(utilization=30), limits=[dict(kind='weekly_scoped',
                percent=100, scope=dict(model=dict(display_name=model), surface=surface))])
            self.assertEqual(len(u.parse_claude(data)), 1)

    def test_agy_builtin_contract_and_separate_pools(self):
        data = dict(status='SUCCESS', command=dict(name='usage', data=dict(groups=[dict(buckets=[
            dict(id='gemini-5h', window='5h', remaining_fraction=.9),
            dict(id='3p-5h', window='5h', remaining_fraction=.05)])])))
        row = self.row('antigravity'); row['windows'] = u.parse_agy(data)
        self.snapshot['providers']['antigravity'] = row
        p = dict(adapter='antigravity', model='gemini-next', billing_mode='unknown')
        self.assertEqual(u.headroom(p, self.snapshot), .9)
        self.assertEqual(u.headroom(dict(p, model='claude-next'), self.snapshot), .05)
        self.assertIsNone(u.headroom(dict(p, model='unclassified-model'), self.snapshot))
        data['command']['name'] = 'chat'
        with self.assertRaises(u.UsageError): u.parse_agy(data)

    def test_specialized_pool_does_not_bypass_common_limit(self):
        p = dict(self.config['profiles'][0], usage_pool='codex-special')
        row = self.row(remaining=0)
        row['windows'].append(u.window('codex-special', '5h', 1))
        self.snapshot['providers']['codex'] = row
        self.assertEqual(u.headroom(p, self.snapshot), 0)

    def test_make_requires_checker_with_capacity(self):
        self.args.mode = 'make'; self.args.host_family = 'openai'
        self.snapshot['providers']['claude'] = self.row('claude', 0)
        self.snapshot['providers']['grok'] = self.row('grok', 0)
        self.snapshot['providers']['antigravity'] = self.row('antigravity', .9, pool='antigravity:gemini')
        with self.assertRaises(r.RoutingError):
            r.resolve(core, self.config, response()['answers'], self.available, self.args, self.snapshot)

    def test_invalid_percentages_are_errors(self):
        for number in (float('nan'), -1, 101, True):
            with self.assertRaises(u.UsageError):
                u.parse_claude({'five_hour': {'utilization': number}})

    def test_stale_expired_reset_and_metered_never_gate(self):
        p = self.config['profiles'][0]
        for row in (self.row(age=200), self.row(status='stale')):
            self.snapshot['providers']['codex'] = row
            self.assertIsNone(u.headroom(p, self.snapshot))
        row = self.row(); row['windows'][0]['resets_at'] = time.time()-1
        self.snapshot['providers']['codex'] = row
        self.assertIsNone(u.headroom(p, self.snapshot))
        self.snapshot['providers']['codex'] = self.row(remaining=0)
        self.assertIsNone(u.headroom(dict(p, billing_mode='metered'), self.snapshot))

    def test_cached_read_never_fetches_and_marks_stale(self):
        r.save(r.root() / 'usage-cache.json', dict(providers={'codex': self.row(age=200)}))
        with patch.object(u, 'fetch', side_effect=AssertionError('network')):
            s = u.get(core, cached=True)
        self.assertEqual(s['providers']['codex']['status'], 'stale')
        self.assertEqual(s['providers']['claude']['status'], 'unknown')

    def test_cache_reuses_reads_and_force_refreshes(self):
        def fetch(_core, name, _opts): return 'fake', [u.window(name, '7d', .8)]
        with patch.object(u, 'fetch', side_effect=fetch) as mock:
            u.get(core); u.get(core)
            self.assertEqual(mock.call_count, 4)
            u.get(core, force=True)
            self.assertEqual(mock.call_count, 8)

    def test_failed_refresh_retains_age_but_not_routing_authority(self):
        original = self.row(age=70)
        r.save(r.root() / 'usage-cache.json', dict(providers={'codex': original}))
        with patch.object(u, 'fetch', side_effect=u.UsageError('unavailable')):
            snapshot = u.get(core, force=True)
        self.assertEqual(snapshot['providers']['codex']['status'], 'stale')
        self.assertEqual(snapshot['providers']['codex']['observed_at'], original['observed_at'])
        self.assertIsNone(u.headroom(self.config['profiles'][0], snapshot))

    def test_changed_credential_binding_drops_old_account(self):
        original = self.row(); original['binding'] = 'previous-account'
        r.save(r.root() / 'usage-cache.json', dict(providers={'codex': original}))
        with patch.object(u, 'fetch', side_effect=u.UsageError('not logged in')):
            snapshot = u.get(core, force=True)
        self.assertEqual(snapshot['providers']['codex']['windows'], [])
        self.assertEqual(snapshot['providers']['codex']['status'], 'unknown')

    def test_reset_boundary_refreshes_before_ttl(self):
        original = self.row(); original['windows'][0]['resets_at'] = time.time()-1
        r.save(r.root() / 'usage-cache.json', dict(providers={'codex': original}))
        with patch.object(u, 'fetch', return_value=('fake', [u.window('codex','5h',1)])) as mock:
            snapshot = u.get(core)
        self.assertTrue(mock.called)
        self.assertEqual(snapshot['providers']['codex']['windows'][0]['remaining_fraction'], 1)

    def test_quota_reserve_excludes_otherwise_cheap_profile(self):
        self.snapshot['providers']['codex'] = self.row(remaining=.05)
        result = r.resolve(core, self.config, response()['answers'], self.available, self.args, self.snapshot)
        self.assertNotEqual(result['cli'], 'codex')
        self.assertTrue(any(x['reason'] == 'live subscription quota reserve reached' for x in result['rejected']))

    def test_capacity_pressure_breaks_cost_tie(self):
        self.snapshot['providers']['codex'] = self.row(remaining=.3)
        self.snapshot['providers']['antigravity'] = self.row('antigravity', .9, pool='antigravity:gemini')
        result = r.resolve(core, self.config, response()['answers'], self.available, self.args, self.snapshot)
        self.assertEqual(result['cli'], 'antigravity')
        self.assertEqual(result['live_remaining_fraction'], .9)

    def test_unknown_not_fabricated_as_full_and_no_identity_in_public(self):
        self.snapshot['providers']['codex'] = self.row(remaining=.57)
        rendered = u.render(self.snapshot)
        self.assertIn('57%', rendered)
        self.assertIn('| Grok | — | unknown', rendered)
        self.assertNotIn('binding', json.dumps(u.public(self.snapshot)))

    def test_if_changed_suppresses_age_only_but_emits_capacity_change(self):
        self.snapshot['providers']['codex'] = self.row(remaining=.57)
        args = argparse.Namespace(refresh=False, cached=False, if_changed=True, session='test-session', format='markdown')
        with patch.object(u, 'get', return_value=self.snapshot):
            first = io.StringIO()
            with contextlib.redirect_stdout(first): u.emit(core, args)
            second = io.StringIO()
            with contextlib.redirect_stdout(second): u.emit(core, args)
            self.assertTrue(first.getvalue()); self.assertFalse(second.getvalue())
            self.snapshot['providers']['codex']['windows'][0]['remaining_fraction'] = .49
            third = io.StringIO()
            with contextlib.redirect_stdout(third): u.emit(core, args)
            self.assertTrue(third.getvalue())

    def test_rpc_handshake_and_cleanup_with_fake_server(self):
        executable = Path(self.tmp.name) / 'codex'
        executable.write_text('''#!/usr/bin/env python3
import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if m.get('method')=='initialize': print(json.dumps({'id':m['id'],'result':{}}),flush=True)
 if m.get('method')=='account/rateLimits/read': print(json.dumps({'id':m['id'],'result':{'rateLimits':{'primary':{'usedPercent':20,'windowDurationMins':300}}}}),flush=True)
''')
        executable.chmod(0o755)
        data = u.codex_rpc(core, str(executable))
        self.assertAlmostEqual(u.parse_codex(data)[0]['remaining_fraction'], .8)

    def test_command_deadline_terminates_child(self):
        start = time.monotonic()
        with self.assertRaises(u.UsageError):
            u.command([sys.executable, '-c', 'import time; time.sleep(60)'], core, timeout=.1)
        self.assertLess(time.monotonic()-start, 3)

    def test_disabled_usage_has_no_provider_reads(self):
        with patch.dict(os.environ, {'ALLOY_USAGE':'off'}), patch.object(u, 'fetch', side_effect=AssertionError('network')):
            self.assertFalse(u.get(core)['enabled'])

