"""Quota normalization, freshness, rendering and routing. No live provider calls."""
import argparse
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import stat
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
            self.assertEqual(mock.call_count, len(u.PROVIDERS))  # one read per provider, cached on the second call
            u.get(core, force=True)
            self.assertEqual(mock.call_count, 2 * len(u.PROVIDERS))

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


REPO = Path(__file__).resolve().parents[1]


class Lane4Tests(unittest.TestCase):
    """Lane 4: the Cursor usage provider and its two manual pools, fail-closed provider
    dispatch, and Claude quota with no keychain access. Fixtures and mocks only: no live
    provider, no network, no keychain, and HOME is never set (Path.home is patched)."""
    setUp = UsageTests.setUp
    row = UsageTests.row

    CLAUDE_ENV = ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CONFIG_DIR')

    def home(self):
        home = Path(self.tmp.name) / 'home'
        home.mkdir(exist_ok=True)
        return home

    @contextlib.contextmanager
    def claude_env(self, **extra):
        """No Claude credential anywhere, on macOS, in a private fake home."""
        env = {k: v for k, v in os.environ.items() if k not in self.CLAUDE_ENV}
        env.update(extra)
        with patch.dict(os.environ, env, clear=True), \
             patch.object(u.Path, 'home', return_value=self.home()), \
             patch.object(sys, 'platform', 'darwin'):
            yield

    @contextlib.contextmanager
    def sealed(self):
        """Any subprocess, keychain helper or network call fails the test."""
        def deny(name):
            def raiser(*args, **kwargs):
                raise AssertionError('%s called with %r' % (name, args[:1]))
            return raiser
        with patch.object(u, 'command', side_effect=deny('command')), \
             patch.object(u.subprocess, 'Popen', side_effect=deny('Popen')), \
             patch.object(u.urllib.request, 'build_opener', side_effect=deny('build_opener')), \
             patch.object(u.urllib.request, 'urlopen', side_effect=deny('urlopen')):
            yield

    def only(self, provider):
        """u.fetch reaches the real source of ONE provider; every other provider is refused, so
        a test can never start a live codex, grok or agy read."""
        real = u.fetch
        def route(_core, name, options):
            if name == provider:
                return real(_core, name, options)
            raise u.UsageError('not under test')
        return patch.object(u, 'fetch', side_effect=route)

    def get_claude(self, config, forget=False, **kwargs):
        """One snapshot; forget=True first drops the cached readings, since a failed refresh
        deliberately keeps the last reading of the same account visible as stale."""
        if forget:
            with contextlib.suppress(FileNotFoundError):
                (r.root() / 'usage-cache.json').unlink()
        with self.only('claude'):
            return u.get(core, config, **kwargs)

    def stream(self, five=.06, seven=.55, extra=None):
        """`claude -p ... --output-format stream-json --verbose` output (field names verified
        against Claude Code 2.1.284): an init line, a rate_limit_event, a result line."""
        now = int(time.time())
        info = {'status': 'allowed', 'resetsAt': now + 3600, 'rateLimitType': 'five_hour',
                'overageStatus': 'rejected', 'isUsingOverage': False,
                'unifiedWindows': {'five_hour': {'utilization': five, 'resetsAt': now + 3600},
                                   'seven_day': {'utilization': seven, 'resetsAt': now + 86400}}}
        info.update(extra or {})
        return '\n'.join([json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's', 'tools': ['Bash'] * 50}),
                          json.dumps({'type': 'rate_limit_event', 'rate_limit_info': info, 'session_id': 's'}),
                          json.dumps({'type': 'result', 'subtype': 'success', 'result': 'OK'})]) + '\n'

    def statusline(self, five=6, seven=55, **extra):
        """Claude Code's status-line JSON (schema read from the installed 2.1.284 binary)."""
        now = int(time.time())
        return dict({'session_id': 's', 'cwd': '/private/project', 'transcript_path': '/private/t.jsonl',
                     'model': {'id': 'claude-x'}, 'rate_limits': {
                         'five_hour': {'used_percentage': five, 'resets_at': now + 3600},
                         'seven_day': {'used_percentage': seven, 'resets_at': now + 86400}}}, **extra)

    def snapshot_file(self, age=0, recorded=None, **kwargs):
        path = u.claude_snapshot_path(core)
        r.save(path, dict(schema=1, observed_at=time.time() - age if recorded is None else recorded,
                          rate_limits=self.statusline(**kwargs)['rate_limits']))
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def enable(self, *ids):
        for p in self.config['profiles']:
            p['enabled'] = p['id'] in ids
        return self.config

    def resolve(self, snapshot):
        return r.resolve(core, self.config, response()['answers'], self.available, self.args, snapshot)

    def reasons(self, result):
        return {x['profile']: x['reason'] for x in result['rejected']}

    # ---- Cursor: one provider, two pools, unknown unless the operator says otherwise ---- #

    def test_cursor_is_one_canonical_provider_with_a_label(self):
        self.assertEqual(u.PROVIDERS.count('cursor'), 1)
        self.assertEqual(len(u.PROVIDERS), len(set(u.PROVIDERS)))
        self.assertEqual(u.LABELS['cursor'], 'Cursor')
        self.assertNotIn('cursor-agent', u.PROVIDERS)  # the alias is normalised at config boundaries
        with patch.object(u, 'fetch', side_effect=u.UsageError('unavailable')):
            snapshot = u.get(core)
        self.assertEqual(list(snapshot['providers']).count('cursor'), 1)
        self.assertEqual(len(snapshot['providers']), len(u.PROVIDERS))

    def test_cursor_models_use_cursor_pools_never_a_native_providers(self):
        table = {'composer-2.5': 'cursor:models', 'composer-2.5-fast': 'cursor:models',
                 'composer-2.5[fast=true]': 'cursor:models', 'Composer-2.5': 'cursor:models',
                 'cursor-grok-4.7': 'cursor:models', 'cursor-grok-4.7-high': 'cursor:models',
                 'gpt-5.6-sol-high': 'cursor:other', 'claude-opus-5-5-high': 'cursor:other',
                 'claude-opus-4-8[context=1m,effort=high]': 'cursor:other',
                 'gemini-3.8-flash-high': 'cursor:other', 'grok-4.7-high': 'cursor:other',
                 'codex-5.6': 'cursor:other', 'sonnet-5-5': 'cursor:other', 'something-new': 'cursor:other'}
        for model, pool in table.items():
            with self.subTest(model=model):
                # The shared `cursor` pool applies to every Cursor model, plus its billing pool.
                self.assertEqual(u.applicable(dict(adapter='cursor', model=model)), ['cursor', pool])
        # An explicit user pool is still added, after the Cursor pools.
        self.assertEqual(u.applicable(dict(adapter='cursor', model='composer-2.5', usage_pool='mine')),
                         ['cursor', 'cursor:models', 'mine'])
        # A Cursor profile of an Anthropic model never inherits Claude's pools.
        pools = u.applicable(dict(adapter='cursor', model='claude-sonnet-5-5-high'))
        self.assertFalse({'claude', 'claude:sonnet', 'codex', 'grok'} & set(pools))
        # Native providers are unchanged.
        self.assertEqual(u.applicable(dict(adapter='claude', model='claude-sonnet-5-5')), ['claude', 'claude:sonnet'])
        self.assertEqual(u.applicable(dict(adapter='grok', model='cursor-grok-4.7')), ['grok'])

    def test_the_shared_cursor_pool_applies_to_every_cursor_model_alongside_its_billing_pool(self):
        composer = dict(adapter='cursor', model='composer-2.5', billing_mode='subscription')
        gpt = dict(composer, model='gpt-5.6-sol-high')
        row = self.row('cursor', .3, pool='cursor')
        snapshot = dict(enabled=True, ttl_seconds=120, providers={'cursor': row})
        self.assertEqual((u.headroom(composer, snapshot), u.headroom(gpt, snapshot)), (.3, .3))
        self.assertIsNotNone(u.pacing(gpt, snapshot))  # a real dated window paces ...
        row['windows'].append(u.window('cursor:models', 'manual', .2))
        self.assertEqual((u.headroom(composer, snapshot), u.headroom(gpt, snapshot)), (.2, .3))
        row['windows'].append(u.window('cursor:other', 'manual', .9))
        self.assertEqual((u.headroom(composer, snapshot), u.headroom(gpt, snapshot)), (.2, .3))  # never above the shared pool
        self.assertIsNone(u.pacing(gpt, snapshot))  # ... a manual, undated one does not (pacing needs every window's reset)

    def test_cursor_has_no_usage_source_so_quota_is_unknown_and_never_blocks(self):
        with self.sealed(), self.assertRaisesRegex(u.UsageError, '^Cursor CLI exposes no subscription usage source$'):
            u.fetch(core, 'cursor', {})
        with self.sealed(), self.only('cursor'):
            snapshot = u.get(core)
        row = snapshot['providers']['cursor']
        self.assertEqual((row['status'], row['windows']), ('unknown', []))
        self.assertEqual(row['error'], 'Cursor CLI exposes no subscription usage source')
        composer = dict(adapter='cursor', model='composer-2.5', billing_mode='subscription')
        self.assertIsNone(u.headroom(composer, snapshot))
        # Routing: enabled Cursor profiles stay eligible; a drained Claude subscription does
        # not spill onto a Cursor Claude-model profile because their pools are separate.
        self.enable('cursor-large-composer-2-5', 'cursor-large-claude-opus-5-5')
        snapshot['providers']['claude'] = self.row('claude', 0)
        result = self.resolve(snapshot)
        self.assertEqual(result['cli'], 'cursor')
        self.assertFalse({v for k, v in self.reasons(result).items() if k.startswith('cursor')} &
                         {'live subscription quota reserve reached'})
        self.assertIsNone(result['live_remaining_fraction'])
        self.assertNotIn('cursor-large-claude-opus-5-5', self.reasons(result))
        self.assertNotIn('cursor-large-composer-2-5', self.reasons(result))

    def test_cursor_api_overrides_are_never_a_binding_value(self):
        state = Path(self.tmp.name) / 'agent-cli-state.json'
        state.write_text('{"account": "person@example.invalid"}')
        state.chmod(0)  # metadata only: the contents are never read
        self.addCleanup(state.chmod, 0o600)
        with patch.object(u, 'cursor_state_path', return_value=state):
            base = u.binding(core, 'cursor')
            with patch.dict(os.environ, {'CURSOR_API_KEY': 'test-key-1', 'CURSOR_API_ENDPOINT': 'https://one.invalid'}):
                self.assertEqual(u.binding(core, 'cursor'), base)
                with patch.object(core, '_CONFIG', {'CURSOR_API_KEY': 'test-key-2', 'CURSOR_API_ENDPOINT': 'https://two.invalid'}):
                    self.assertEqual(u.binding(core, 'cursor'), base)
            self.assertEqual(len(base), 64)
            state.chmod(0o600)
            state.write_text('{"account": "another@example.invalid", "more": 1}')
            self.assertNotEqual(u.binding(core, 'cursor'), base)  # mtime/size changed
        state.chmod(0o600)
        with patch.object(u, 'cursor_state_path', return_value=Path(self.tmp.name) / 'missing.json'):
            self.assertEqual(len(u.binding(core, 'cursor')), 64)  # a missing file is a valid binding

    def test_usage_child_env_never_carries_a_cursor_override(self):
        # Neither from the process environment nor from the Alloy config file.
        secrets = {'CURSOR_API_KEY': 'test-key-3', 'CURSOR_API_ENDPOINT': 'https://three.invalid'}
        with patch.dict(os.environ, secrets), patch.object(core, '_CONFIG', dict(secrets, KEEP_ME='yes')):
            env = u.provider_env(core)
            self.assertFalse(set(secrets) & set(env))
            self.assertEqual(env.get('KEEP_ME'), 'yes')
            out = u.command([sys.executable, '-c', 'import os;print(os.environ.get("CURSOR_API_KEY","-"),'
                             'os.environ.get("CURSOR_API_ENDPOINT","-"),os.environ.get("KEEP_ME","-"))'], core)
            self.assertEqual(out.split(), ['-', '-', 'yes'])

    def test_unknown_provider_cannot_fall_through_to_claude_keychain_or_network(self):
        for name in ('nonesuch', 'cursor-agent', 'CLAUDE', '', None):
            with self.subTest(provider=name), self.claude_env(), self.sealed():
                self.home().joinpath('.claude').mkdir(exist_ok=True)  # a credential a fall-through could use
                self.home().joinpath('.claude/.credentials.json').write_text('{"claudeAiOauth":{"accessToken":"test-token"}}')
                with self.assertRaisesRegex(u.UsageError, '^Unknown usage provider'):
                    u.fetch(core, name, {})
                with self.assertRaisesRegex(u.UsageError, '^Unknown usage provider'):
                    u.binding(core, name)
        with self.claude_env(), self.sealed():
            with self.assertRaises(u.UsageError):
                u.fetch(core, 'cursor', {})  # Cursor itself reads no credential and makes no call

    # ---- Cursor: operator-set pools and the reserve rule ---- #

    def pools(self, **pools):
        self.config['quota_pools'] = pools
        r.save(r.root() / 'routing.json', self.config)

    def get_with(self, config, **kwargs):
        with patch.object(u, 'fetch', side_effect=u.UsageError('unavailable')):
            return u.get(core, config, **kwargs)

    def test_manual_cursor_pools_become_windows_and_unset_pools_stay_unknown(self):
        self.pools(**{'cursor:models': dict(remaining_fraction=.6), 'cursor:other': dict(remaining_fraction=.4)})
        snapshot = self.get_with(self.config)
        row = snapshot['providers']['cursor']
        self.assertEqual((row['status'], row['source']), ('fresh', 'operator-config'))
        self.assertEqual({w['pool']: w['remaining_fraction'] for w in row['windows']},
                         {'cursor:models': .6, 'cursor:other': .4})
        composer = dict(adapter='cursor', model='composer-2.5', billing_mode='subscription')
        gpt = dict(composer, model='gpt-5.6-sol-high')
        self.assertEqual(u.headroom(composer, snapshot), .6)
        self.assertEqual(u.headroom(gpt, snapshot), .4)
        self.assertIsNone(u.headroom(dict(gpt, billing_mode='metered'), snapshot))
        # Only one pool described: the other stays unknown, never borrowed from it.
        self.pools(**{'cursor:other': dict(remaining_fraction=.4)})
        snapshot = self.get_with(self.config)
        self.assertIsNone(u.headroom(composer, snapshot))
        self.assertEqual(u.headroom(gpt, snapshot), .4)
        # Nothing valid: unknown, and an invalid value is never capacity.
        for bad in (None, -.1, 1.1, True, 'half', float('nan'), {}):
            with self.subTest(value=bad):
                self.config['quota_pools'] = {'cursor:models': dict(remaining_fraction=bad), 'other-pool': dict(remaining_fraction=.5)}
                row = self.get_with(self.config)['providers']['cursor']
                self.assertEqual((row['status'], row['windows']), ('unknown', []))

    def test_manual_cursor_pools_are_configuration_never_cached(self):
        self.pools(**{'cursor:models': dict(remaining_fraction=.6)})
        self.get_with(self.config)                       # persists the operator's reading
        self.config['quota_pools']['cursor:models']['remaining_fraction'] = .2
        row = self.get_with(self.config)['providers']['cursor']  # an edit applies at once, not after the TTL
        self.assertEqual(row['windows'][0]['remaining_fraction'], .2)
        row = self.get_with(self.config, cached=True)['providers']['cursor']
        self.assertEqual(row['windows'][0]['remaining_fraction'], .2)
        self.config['quota_pools'] = {}                  # removing it makes Cursor unknown again
        for kwargs in ({}, {'cached': True}, {'force': True}):
            row = self.get_with(self.config, **kwargs)['providers']['cursor']
            self.assertEqual((row['status'], row['windows']), ('unknown', []), kwargs)

    def test_reserve_rule_applies_to_each_manual_cursor_pool(self):
        self.enable('cursor-large-composer-2-5', 'cursor-large-claude-opus-5-5', 'codex-large')
        self.pools(**{'cursor:models': dict(remaining_fraction=.05), 'cursor:other': dict(remaining_fraction=.5)})
        result = self.resolve(self.get_with(self.config))
        reasons = self.reasons(result)
        self.assertEqual(reasons['cursor-large-composer-2-5'], 'live subscription quota reserve reached')
        self.assertNotIn('cursor-large-claude-opus-5-5', reasons)  # the other pool has capacity
        self.pools(**{'cursor:models': dict(remaining_fraction=.5), 'cursor:other': dict(remaining_fraction=.05)})
        reasons = self.reasons(self.resolve(self.get_with(self.config)))
        self.assertEqual(reasons['cursor-large-claude-opus-5-5'], 'live subscription quota reserve reached')
        self.assertNotIn('cursor-large-composer-2-5', reasons)
        # The global usage.reserve_fraction applies to a pool with plenty above its own reserve.
        self.pools(**{'cursor:models': dict(remaining_fraction=.25), 'cursor:other': dict(remaining_fraction=.25)})
        self.assertNotIn('cursor-large-composer-2-5', self.reasons(self.resolve(self.get_with(self.config))))
        self.config['usage'] = dict(self.config.get('usage', {}), reserve_fraction=.3)
        reasons = self.reasons(self.resolve(self.get_with(self.config)))
        self.assertEqual({reasons['cursor-large-composer-2-5'], reasons['cursor-large-claude-opus-5-5']},
                         {'live subscription quota reserve reached'})
        # A Maker's independent Checker honours it too. Two Cursor profiles only: composer needs
        # the Claude-model profile as its Checker, which the drained "Other Models" pool removes.
        self.enable('cursor-large-composer-2-5', 'cursor-large-claude-opus-5-5')
        self.config['usage']['reserve_fraction'] = .1
        self.args.mode, self.args.host_family = 'make', 'openai'
        self.pools(**{'cursor:models': dict(remaining_fraction=.5), 'cursor:other': dict(remaining_fraction=.5)})
        self.assertEqual(self.resolve(self.get_with(self.config))['profile'], 'cursor-large-composer-2-5')
        self.pools(**{'cursor:models': dict(remaining_fraction=.5), 'cursor:other': dict(remaining_fraction=.05)})
        with self.assertRaisesRegex(r.RoutingError, 'No eligible profile'):
            self.resolve(self.get_with(self.config))

    def test_manual_cursor_pool_reserve_fraction_is_honoured(self):
        composer = dict(adapter='cursor', model='composer-2.5', billing_mode='subscription')
        for remaining, reserve, expected in ((.25, None, .25), (.25, .3, 0.0), (.25, .2, .25), (.1, None, 0.0), (.11, None, .11)):
            with self.subTest(remaining=remaining, reserve=reserve):
                pool = dict(remaining_fraction=remaining) if reserve is None else dict(remaining_fraction=remaining, reserve_fraction=reserve)
                self.pools(**{'cursor:models': pool})
                self.assertEqual(u.headroom(composer, self.get_with(self.config)), expected)

    def test_render_names_the_cursor_pools_and_marks_them_manual(self):
        self.pools(**{'cursor:models': dict(remaining_fraction=.6), 'cursor:other': dict(remaining_fraction=.3)})
        text = u.render(self.get_with(self.config))
        self.assertIn('| Cursor / Cursor Models | manual |', text)
        self.assertIn('| Cursor / Other Models | manual |', text)
        self.assertIn('60%', text); self.assertIn('30%', text)
        self.assertIn('manual (operator-set)', text)
        self.assertNotIn('operator-config', text.replace('manual (operator-set)', ''))
        empty = u.render(self.get_with(dict(self.config, quota_pools={})))
        self.assertIn('| Cursor | — | unknown | — | unavailable |', empty)

    # ---- Claude: never the keychain ---- #

    def test_module_source_never_touches_the_macos_keychain(self):
        tree = ast.parse(Path(u.__file__).read_text())
        strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for banned in ('/usr/bin/security', 'find-generic-password', 'add-generic-password',
                       'delete-generic-password', 'dump-keychain', 'Claude Code-credentials', 'login.keychain'):
            self.assertFalse([s for s in strings if banned in s], banned)
        self.assertNotIn('security', strings)  # an exact argv element
        imported = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(imported & {'keyring', 'ctypes', 'objc', 'Security', 'Foundation'})

    def test_claude_without_a_credential_file_is_unknown_with_the_policy_reason_and_runs_nothing(self):
        for options in ({}, {'keychain': True}, {'keychain': False}, {'claude_probe': False}):
            with self.subTest(options=options), self.claude_env(), self.sealed():
                with self.assertRaisesRegex(u.UsageError, 'keychain access disabled by policy'):
                    u.fetch(core, 'claude', options)
        config = dict(self.config, usage=dict(self.config.get('usage', {}), keychain=True))
        with self.claude_env(), self.sealed():
            snapshot = self.get_claude(config, force=True)
        row = snapshot['providers']['claude']
        self.assertEqual((row['status'], row['windows']), ('unknown', []))
        self.assertIn('keychain access disabled by policy', row['error'])
        # Unknown Claude quota never blocks routing.
        self.enable('claude-large')
        self.assertEqual(self.resolve(snapshot)['cli'], 'claude')

    def test_claude_config_dir_and_default_home_are_only_read_as_existing_files(self):
        payload = json.dumps(dict(five_hour=dict(utilization=20, resets_at=time.time() + 3600),
                                  seven_day=dict(utilization=30, resets_at=time.time() + 86400)))
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(side_effect=lambda: io.BytesIO(payload.encode()))
        opener.open.return_value.__exit__ = Mock(return_value=False)
        for label, extra, where in (('default home', {}, self.home() / '.claude'),
                                    ('CLAUDE_CONFIG_DIR', {'CLAUDE_CONFIG_DIR': str(Path(self.tmp.name) / 'profile')},
                                     Path(self.tmp.name) / 'profile')):
            with self.subTest(source=label), self.claude_env(**extra):
                where.mkdir(exist_ok=True)
                (where / '.credentials.json').write_text('{"claudeAiOauth":{"accessToken":"test-token"}}')
                with patch.object(u, 'command', side_effect=AssertionError('no subprocess')), \
                     patch.object(u.urllib.request, 'build_opener', return_value=opener):
                    source, windows, observed = u.fetch(core, 'claude', {})
                self.assertEqual(source, 'claude-oauth')
                self.assertEqual({w['window'] for w in windows}, {'5h', '7d'})
                self.assertAlmostEqual(windows[0]['remaining_fraction'], .8)
                self.assertEqual(opener.open.call_args[0][0].get_header('Authorization'), 'Bearer test-token')
        with self.claude_env(CLAUDE_CODE_OAUTH_TOKEN='env-test-token'), \
             patch.object(u, 'command', side_effect=AssertionError('no subprocess')), \
             patch.object(u.urllib.request, 'build_opener', return_value=opener):
            u.fetch(core, 'claude', {})
        self.assertEqual(opener.open.call_args[0][0].get_header('Authorization'), 'Bearer env-test-token')

    def test_claude_oauth_failure_falls_back_to_the_snapshot_and_api_overrides_read_nothing(self):
        self.snapshot_file(age=5)
        opener = Mock()
        opener.open.side_effect = u.urllib.error.HTTPError('url', 401, 'secret-body', {}, io.BytesIO(b'secret'))
        with self.claude_env(CLAUDE_CODE_OAUTH_TOKEN='test-token'), patch.object(u.urllib.request, 'build_opener', return_value=opener), \
             patch.object(u, 'command', side_effect=AssertionError('no subprocess')):
            source, windows, _ = u.fetch(core, 'claude', {})
        self.assertEqual(source, 'claude-rate-limit-snapshot')
        self.assertEqual(opener.open.call_count, 1)
        u.claude_snapshot_path(core).unlink()
        with self.claude_env(CLAUDE_CODE_OAUTH_TOKEN='test-token'), patch.object(u.urllib.request, 'build_opener', return_value=opener), \
             patch.object(u, 'command', side_effect=AssertionError('no subprocess')):
            with self.assertRaisesRegex(u.UsageError, 'HTTP 401') as caught:
                u.fetch(core, 'claude', {})
            self.assertNotIn('secret', str(caught.exception))
        self.snapshot_file()
        for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL'):
            with self.subTest(override=name), self.claude_env(**{name: 'test-value'}), self.sealed():
                with self.assertRaisesRegex(u.UsageError, 'API/proxy override present'):
                    u.fetch(core, 'claude', {'claude_probe': True})

    # ---- Claude: rate_limit_event, status-line and snapshot sources ---- #

    def test_rate_limit_event_fixture_maps_used_fraction_to_remaining_windows(self):
        windows = u.parse_claude_stream(self.stream())
        self.assertEqual([(w['pool'], w['window']) for w in windows], [('claude', '5h'), ('claude', '7d')])
        self.assertAlmostEqual(windows[0]['remaining_fraction'], .94)  # utilization is USED
        self.assertAlmostEqual(windows[1]['remaining_fraction'], .45)
        self.assertTrue(all(w['resets_at'] > time.time() for w in windows))
        # Fields other than the two windows are not capacity: the top-level utilization,
        # rateLimitType, overage state and the per-model overage-included bucket.
        text = self.stream(extra=dict(utilization=.99))
        self.assertEqual(len(u.parse_claude_stream(text)), 2)
        event = json.loads(text.splitlines()[1])
        event['rate_limit_info']['unifiedWindows']['seven_day_overage_included'] = dict(utilization=1, resetsAt=int(time.time()) + 5)
        self.assertEqual([w['window'] for w in u.parse_claude_stream(json.dumps(event))], ['5h', '7d'])
        # The latest event wins; unparseable lines and events without windows are ignored.
        later = self.stream(five=.5, seven=.6)
        combined = self.stream() + 'not json rate_limit_event\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n' + later
        got = u.parse_claude_stream(combined)
        self.assertAlmostEqual(got[0]['remaining_fraction'], .5)
        self.assertAlmostEqual(got[1]['remaining_fraction'], .4)
        for none in ('', '{"type":"result"}\n', '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n'):
            with self.assertRaises(u.UsageError):
                u.parse_claude_stream(none)

    def test_claude_windows_reject_invalid_values_and_treat_exceeded_as_exhausted(self):
        for bad in (float('nan'), -.01, True, '0.5', float('inf'), 2.5, 55):
            with self.subTest(utilization=bad), self.assertRaises(u.UsageError):
                u.claude_windows({'five_hour': {'utilization': bad}})
        for bad in (float('nan'), -1, False, '5', 250):
            with self.subTest(used_percentage=bad), self.assertRaises(u.UsageError):
                u.claude_windows({'five_hour': {'used_percentage': bad}})
        self.assertEqual(u.claude_windows({'five_hour': {'utilization': 1.3}})[0]['remaining_fraction'], 0)
        self.assertEqual(u.claude_windows({'seven_day': {'used_percentage': 130}})[0]['remaining_fraction'], 0)
        self.assertEqual(u.claude_windows({'five_hour': {'utilization': 2}})[0]['remaining_fraction'], 0)  # the edge
        self.assertEqual(u.claude_windows({'five_hour': {'utilization': 0}})[0]['remaining_fraction'], 1)
        # A window that is absent or null is simply not reported; nothing reported is an error.
        self.assertEqual([w['window'] for w in u.claude_windows({'seven_day': {'utilization': .5}, 'five_hour': None})], ['7d'])
        for none in ({}, {'five_hour': {}}, {'spend_limit': {'used_percentage': 1}}, None, []):
            with self.assertRaises(u.UsageError):
                u.claude_windows(none)

    def test_statusline_and_stream_shapes_use_different_units(self):
        stream = u.claude_windows(json.loads(self.stream(five=.55, seven=.55).splitlines()[1])['rate_limit_info']['unifiedWindows'])
        line = u.claude_windows(self.statusline(five=55, seven=55)['rate_limits'])
        for a, b in zip(stream, line):
            self.assertAlmostEqual(a['remaining_fraction'], .45)
            self.assertAlmostEqual(b['remaining_fraction'], .45)
        # 0.5 in used_percentage is half a percent, not half the quota.
        self.assertAlmostEqual(u.claude_windows({'five_hour': {'used_percentage': .5}})[0]['remaining_fraction'], .995)

    def test_claude_windows_from_rate_limits_apply_the_reserve_to_claude_profiles(self):
        self.enable('claude-large', 'codex-large')
        for used, reserve, rejected in ((.88, .15, True), (.88, .10, False), (.80, .15, False)):
            with self.subTest(used=used, reserve=reserve):
                row = self.row('claude'); row['windows'] = u.parse_claude_stream(self.stream(five=used, seven=.1))
                self.snapshot['providers']['claude'] = row
                self.config['usage'] = dict(self.config.get('usage', {}), reserve_fraction=reserve)
                reasons = self.reasons(self.resolve(self.snapshot))
                self.assertEqual(reasons.get('claude-large') == 'live subscription quota reserve reached', rejected)
        claude = dict(adapter='claude', model='claude-opus-5-5', billing_mode='subscription')
        self.assertAlmostEqual(u.headroom(claude, self.snapshot), .2)
        self.assertIn('| Claude | 5h |', u.render(self.snapshot))

    def test_snapshot_is_fresh_within_the_ttl_stale_after_and_unknown_when_missing(self):
        with self.claude_env(), self.sealed():
            snapshot = self.get_claude(self.config, force=True)
            self.assertEqual(snapshot['providers']['claude']['status'], 'unknown')  # no file
            self.snapshot_file(age=10, five=20, seven=30)
            row = self.get_claude(self.config, force=True)['providers']['claude']
            self.assertEqual((row['status'], row['source']), ('fresh', 'claude-rate-limit-snapshot'))
            self.assertAlmostEqual(row['windows'][0]['remaining_fraction'], .8)
            self.assertAlmostEqual(time.time() - row['observed_at'], 10, delta=3)  # the recording time, not now
            claude = dict(adapter='claude', model='claude-opus-5-5', billing_mode='subscription')
            self.assertAlmostEqual(u.headroom(claude, dict(enabled=True, ttl_seconds=120, providers={'claude': row})), .7)
            self.snapshot_file(age=300, five=20, seven=30)
            row = self.get_claude(self.config, force=True)['providers']['claude']
            self.assertEqual(row['status'], 'stale')
            self.assertAlmostEqual(time.time() - row['observed_at'], 300, delta=3)
            self.assertEqual(len(row['windows']), 2)  # kept for display, excluded from routing
            self.assertIsNone(u.headroom(claude, dict(enabled=True, ttl_seconds=120, providers={'claude': row})))
            self.assertIn('stale · 30', u.render(dict(enabled=True, providers={'claude': row})))
            # The TTL is the configured one.
            config = dict(self.config, usage=dict(self.config.get('usage', {}), ttl_seconds=600))
            self.assertEqual(self.get_claude(config, force=True)['providers']['claude']['status'], 'fresh')
            # A fresh snapshot is cache-valid only while it is fresh, not for a whole TTL after
            # it was read: a recording 100s old is re-read before its 120s are up.
            self.snapshot_file(age=100, five=20, seven=30)
            self.assertEqual(self.get_claude(self.config, forget=True)['providers']['claude']['status'], 'fresh')
            self.snapshot_file(age=0, five=50, seven=30)
            with patch.object(u.time, 'time', return_value=time.time() + 30):  # 130s after the first recording
                row = self.get_claude(self.config)['providers']['claude']
            self.assertAlmostEqual(row['windows'][0]['remaining_fraction'], .5)
            # A reading whose reset has passed is stale however new it is.
            self.snapshot_file(age=1)
            path = u.claude_snapshot_path(core)
            data = json.loads(path.read_text()); data['rate_limits']['five_hour']['resets_at'] = time.time() - 5
            path.write_text(json.dumps(data))
            self.assertEqual(self.get_claude(self.config, force=True)['providers']['claude']['status'], 'stale')

    def test_snapshot_age_cannot_be_forged_by_content_or_mtime_and_bad_files_are_unknown(self):
        with self.claude_env(), self.sealed():
            self.snapshot_file(age=300, recorded=time.time())  # new claim inside an old file
            self.assertEqual(self.get_claude(self.config, force=True)['providers']['claude']['status'], 'stale')
            path = self.snapshot_file(age=0, recorded=time.time() - 300)  # old claim inside a new file
            self.assertEqual(self.get_claude(self.config, force=True)['providers']['claude']['status'], 'stale')
            self.snapshot_file(age=0, recorded=time.time() + 3600)       # dated in the future
            os.utime(path, (time.time() + 3600, time.time() + 3600))
            row = self.get_claude(self.config, forget=True, force=True)['providers']['claude']
            self.assertEqual((row['status'], row['windows']), ('unknown', []))
            for content in ('not json', '[]', '{}', '{"rate_limits": {"five_hour": {"used_percentage": 500000}}}',
                            '{"rate_limits": {"five_hour": {"used_percentage": "6"}}}', 'x' * (u.SNAPSHOT_BYTES + 1)):
                with self.subTest(content=content[:30]):
                    path.write_text(content)
                    row = self.get_claude(self.config, forget=True, force=True)['providers']['claude']
                    self.assertEqual((row['status'], row['windows']), ('unknown', []))
            path.unlink(); path.mkdir()  # not a regular file
            self.assertEqual(self.get_claude(self.config, forget=True, force=True)['providers']['claude']['status'], 'unknown')

    def test_statusline_command_records_only_rate_limits_privately(self):
        stdout = io.StringIO()
        payload = self.statusline(five=6, seven=55)
        payload['rate_limits']['spend_limit'] = dict(used_percentage=99, resets_at=1)
        with contextlib.redirect_stdout(stdout):
            code = u.record_claude_statusline(core, io.StringIO(json.dumps(payload)))
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().strip(), 'Claude 5h 94% left | 7d 45% left')
        path = u.claude_snapshot_path(core)
        text = path.read_text()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        for private in ('/private', 'claude-x', 'session_id', 'transcript', 'spend_limit', 'cwd'):
            self.assertNotIn(private, text)
        data = json.loads(text)
        self.assertEqual(set(data), {'schema', 'observed_at', 'rate_limits'})
        self.assertEqual(set(data['rate_limits']), {'five_hour', 'seven_day'})
        self.assertEqual(set(data['rate_limits']['five_hour']), {'used_percentage', 'resets_at'})
        junk = self.statusline(five=6, seven=55)
        junk['rate_limits']['five_hour']['resets_at'] = {'nested': ['junk']}
        with contextlib.redirect_stdout(io.StringIO()):
            u.record_claude_statusline(core, io.StringIO(json.dumps(junk)))
        self.assertIsNone(json.loads(path.read_text())['rate_limits']['five_hour']['resets_at'])
        with contextlib.redirect_stdout(io.StringIO()):
            u.record_claude_statusline(core, io.StringIO(json.dumps(payload)))
        with self.claude_env(), self.sealed():
            source, windows, observed = u.fetch(core, 'claude', {})
        self.assertEqual(source, 'claude-rate-limit-snapshot')
        self.assertAlmostEqual(windows[0]['remaining_fraction'], .94)
        self.assertAlmostEqual(windows[1]['remaining_fraction'], .45)
        self.assertAlmostEqual(observed, time.time(), delta=5)

    def test_statusline_command_never_fails_and_never_writes_on_unusable_input(self):
        path = u.claude_snapshot_path(core)
        huge = json.dumps(self.statusline(pad='x' * (u.MAX_BYTES + 10)))
        for label, raw in (('empty', ''), ('not json', '{{{'), ('array', '[]'), ('no limits', json.dumps({'model': {}})),
                           ('limits not an object', '{"rate_limits": 5}'), ('no windows', '{"rate_limits": {"spend_limit": {}}}'),
                           ('invalid used', json.dumps(self.statusline(five=float('nan')))),
                           ('negative', json.dumps(self.statusline(five=-4))), ('oversized', huge)):
            with self.subTest(case=label):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(u.record_claude_statusline(core, io.StringIO(raw)), 0)
                self.assertEqual(stdout.getvalue(), '')
                self.assertFalse(path.exists())
        with patch.object(r, 'save', side_effect=OSError('read-only')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(u.record_claude_statusline(core, io.StringIO(json.dumps(self.statusline()))), 0)

    def test_alloy_usage_flag_is_a_working_statusline_command_and_touches_no_provider(self):
        parser = argparse.ArgumentParser()
        u.register(parser.add_subparsers(), core)
        args = parser.parse_args(['usage', '--record-claude-statusline'])
        self.assertTrue(args.record_claude_statusline)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(['usage', '--record-claude-statusline', '--refresh'])
        with self.sealed(), patch.object(u, 'get', side_effect=AssertionError('no provider read')), \
             patch.object(sys, 'stdin', io.StringIO(json.dumps(self.statusline()))), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(args.func(args), 0)
        self.assertIn('Claude 5h', out.getvalue())
        self.assertTrue(u.claude_snapshot_path(core).exists())
        # The real entry point, as Claude Code would run it: a status-line command with the
        # JSON on stdin. No HOME is set for the child and no provider is reached.
        u.claude_snapshot_path(core).unlink()
        env = {'PATH': os.environ.get('PATH', ''), 'ALLOY_ROUTING_HOME': self.tmp.name, 'ALLOY_CONFIG': '/dev/null'}
        done = subprocess.run([sys.executable, str(REPO / 'bin/alloy'), 'usage', '--record-claude-statusline'],
                              input=json.dumps(self.statusline(five=6, seven=55)), env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, 'Claude 5h 94% left | 7d 45% left'), done.stderr)
        self.assertTrue(u.claude_snapshot_path(core).exists())

    def test_probe_is_opt_in_and_reads_the_rate_limit_event_once_per_ttl(self):
        calls = []
        def fake(argv, _core, timeout=15):
            calls.append(list(argv))
            return self.stream(five=.06, seven=.55)
        with self.claude_env(), patch.object(u, 'binary_for', return_value='/fake/claude'), patch.object(u, 'command', side_effect=fake):
            for options in ({}, {'claude_probe': False}):
                with self.assertRaisesRegex(u.UsageError, 'keychain access disabled by policy'):
                    u.fetch(core, 'claude', options)
            self.assertEqual(calls, [])  # a usage read is never an inference call unless the operator opts in
            config = dict(self.config, usage=dict(self.config.get('usage', {}), claude_probe=True))
            row = self.get_claude(config, force=True)['providers']['claude']
            self.assertEqual((row['status'], row['source']), ('fresh', 'claude-cli-probe'))
            self.assertAlmostEqual(row['windows'][0]['remaining_fraction'], .94)
            self.assertEqual(len(calls), 1)
            argv = calls[0]
            self.assertEqual(argv[:8], ['/fake/claude', '-p', 'OK', '--model', 'haiku', '--output-format', 'stream-json', '--verbose'])
            self.assertIn('--no-session-persistence', argv)
            self.assertNotIn('security', [os.path.basename(a) for a in argv])
            self.get_claude(config)                     # inside the TTL: cached, no second call
            self.assertEqual(len(calls), 1)
            self.get_claude(config, force=True)
            self.assertEqual(len(calls), 2)
            for bad in ('yes', 1, None):
                with self.assertRaisesRegex(r.RoutingError, 'claude_probe must be true or false'):
                    self.get_claude(dict(self.config, usage=dict(config['usage'], claude_probe=bad)), force=True)

    def fake_claude(self, body):
        """A local stand-in for the claude executable (never the real one)."""
        path = Path(self.tmp.name) / 'fake-claude'
        path.write_text('#!%s\nimport json, os, sys, time\nnow = int(time.time())\n%s\n' % (sys.executable, body))
        path.chmod(0o755)
        return str(path)

    def test_probe_runs_with_stdin_closed(self):
        # The child must see /dev/null on fd 0 (`< /dev/null`), never the caller's terminal or pipe.
        stdin_is_devnull = ('if not os.path.samestat(os.fstat(0), os.stat(os.devnull)):\n'
                            '    sys.exit(3)\n'
                            'print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", '
                            '"unifiedWindows": {"five_hour": {"utilization": 0.25, "resetsAt": now + 3600}, '
                            '"seven_day": {"utilization": 0.5, "resetsAt": now + 86400}}}}))')
        launched = []
        real = subprocess.Popen
        def spy(argv, *args, **kwargs):
            launched.append(dict(kwargs, argv=list(argv)))
            return real(argv, *args, **kwargs)
        with self.claude_env(), patch.object(u, 'binary_for', return_value=self.fake_claude(stdin_is_devnull)), \
             patch.object(u.subprocess, 'Popen', side_effect=spy):
            windows = u.claude_probe(core)
            self.assertAlmostEqual(windows[0]['remaining_fraction'], .75)
            self.assertAlmostEqual(windows[1]['remaining_fraction'], .5)
            self.assertEqual(len(launched), 1)
            self.assertIs(launched[0]['stdin'], subprocess.DEVNULL)
            self.assertEqual(launched[0]['argv'][1:4], ['-p', 'OK', '--model'])
            # And through the whole opt-in read path.
            source, windows, _ = u.fetch(core, 'claude', {'claude_probe': True})
            self.assertEqual(source, 'claude-cli-probe')
        # Not closed: the fake exits 3, the probe fails, and no reading is invented.
        with self.claude_env(), patch.object(u, 'binary_for', return_value=self.fake_claude('sys.exit(3)')):
            with self.assertRaises(u.UsageError):
                u.claude_probe(core)

    def test_usage_help_says_when_inference_can_happen(self):
        parser = argparse.ArgumentParser(prog='alloy')
        u.register(parser.add_subparsers(), core)
        listing = ' '.join(parser.format_help().split())
        self.assertIn('usage.claude_probe', listing)
        self.assertNotIn('(no inference calls)', listing)
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            parser.parse_args(['usage', '--help'])
        text = ' '.join(out.getvalue().split())
        self.assertRegex(text, r'no inference calls unless the opt-in usage\.claude_probe is set, which makes one small Claude call')
        self.assertIn('--record-claude-stream', text)

    def test_stream_json_output_of_a_claude_run_is_recorded_without_a_probe(self):
        noise = ['{"type":"system","subtype":"init","session_id":"secret-session","cwd":"/private/project"}',
                 '{"type":"assistant","message":{"content":"private answer"}}',
                 'plain text, not json but mentions rate_limit_event',
                 '{"type":"result","result":"OK"}']
        first = self.stream(five=.5, seven=.5).splitlines()[1]
        latest = self.stream(five=.06, seven=.55).splitlines()[1]
        text = '\n'.join(noise[:2] + [first] + noise[2:3] + [latest] + noise[3:]) + '\n'
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(u.record_claude_stream(core, io.StringIO(text)), 0)
        self.assertEqual(out.getvalue().strip(), 'Claude 5h 94% left | 7d 45% left')  # the latest event wins
        path = u.claude_snapshot_path(core)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        saved = path.read_text()
        for private in ('secret-session', '/private', 'private answer', 'session_id', 'overageStatus', 'rateLimitType'):
            self.assertNotIn(private, saved)
        self.assertEqual(set(json.loads(saved)), {'schema', 'observed_at', 'unifiedWindows'})
        with self.claude_env(), self.sealed():  # read back as a fresh snapshot: no probe, no subprocess, no network
            source, windows, observed = u.fetch(core, 'claude', {})
            row = self.get_claude(self.config, force=True)['providers']['claude']
        self.assertEqual(source, 'claude-rate-limit-snapshot')
        self.assertAlmostEqual(windows[0]['remaining_fraction'], .94)
        self.assertAlmostEqual(windows[1]['remaining_fraction'], .45)
        self.assertEqual(row['status'], 'fresh')
        # It feeds the same reserve rule as every other Claude reading.
        self.enable('claude-large', 'codex-large')
        self.snapshot['providers']['claude'] = row
        self.assertNotIn('claude-large', self.reasons(self.resolve(self.snapshot)))
        path.write_text(json.dumps(dict(schema=1, observed_at=time.time(), unifiedWindows={
            'five_hour': {'utilization': .95, 'resetsAt': time.time() + 3600}})))
        with self.claude_env(), self.sealed():
            self.snapshot['providers']['claude'] = self.get_claude(self.config, force=True, forget=True)['providers']['claude']
        self.assertEqual(self.reasons(self.resolve(self.snapshot))['claude-large'], 'live subscription quota reserve reached')

    def test_stream_recording_never_fails_its_caller_and_writes_nothing_unusable(self):
        path = u.claude_snapshot_path(core)
        big = 'x' * (u.MAX_BYTES + 10)
        for label, raw in (('empty', ''), ('no event', '{"type":"result"}\n'),
                           ('event without windows', '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed"}}\n'),
                           ('invalid utilization', json.dumps({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
                               "five_hour": {"utilization": float("nan"), "resetsAt": 1}}}}) + '\n'),
                           ('negative', json.dumps({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
                               "five_hour": {"utilization": -1, "resetsAt": 1}}}}) + '\n'),
                           ('oversized line', 'rate_limit_event ' + big + '\n')):
            with self.subTest(case=label):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(u.record_claude_stream(core, io.StringIO(raw)), 0)
                self.assertEqual(out.getvalue(), '')
                self.assertFalse(path.exists())
        # A long line before the event does not hide it, and is not held in memory.
        text = big + '\n' + self.stream().splitlines()[1] + '\n'
        with contextlib.redirect_stdout(io.StringIO()):
            u.record_claude_stream(core, io.StringIO(text))
        self.assertTrue(path.exists())
        with patch.object(r, 'save', side_effect=OSError('read-only')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(u.record_claude_stream(core, io.StringIO(self.stream())), 0)

    def test_record_claude_stream_flag_is_a_working_command_and_touches_no_provider(self):
        parser = argparse.ArgumentParser()
        u.register(parser.add_subparsers(), core)
        args = parser.parse_args(['usage', '--record-claude-stream'])
        self.assertTrue(args.record_claude_stream)
        for other in ('--refresh', '--cached', '--record-claude-statusline'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(['usage', '--record-claude-stream', other])
        with self.sealed(), patch.object(u, 'get', side_effect=AssertionError('no provider read')), \
             patch.object(sys, 'stdin', io.StringIO(self.stream())), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(args.func(args), 0)
        self.assertIn('Claude 5h 94% left', out.getvalue())
        # The real entry point, fed by a stand-in claude run through a pipe. No HOME is set for the children.
        u.claude_snapshot_path(core).unlink()
        run = self.fake_claude('print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": '
                               '{"five_hour": {"utilization": 0.25, "resetsAt": now + 3600}}}}))')
        env = {'PATH': os.environ.get('PATH', ''), 'ALLOY_ROUTING_HOME': self.tmp.name, 'ALLOY_CONFIG': '/dev/null'}
        stream = subprocess.run([run], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, env=env)
        done = subprocess.run([sys.executable, str(REPO / 'bin/alloy'), 'usage', '--record-claude-stream'],
                              input=stream.stdout, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, 'Claude 5h 75% left'), done.stderr)
        self.assertTrue(u.claude_snapshot_path(core).exists())

    def test_probe_failure_keeps_a_stale_snapshot_and_never_raises_past_get(self):
        config = dict(self.config, usage=dict(self.config.get('usage', {}), claude_probe=True))
        self.snapshot_file(age=300)
        for failure in (u.UsageError('Usage command failed; recheck provider login'), OSError('exec failed'),
                        subprocess.TimeoutExpired('claude', 30)):
            with self.subTest(failure=type(failure).__name__), self.claude_env(), \
                 patch.object(u, 'binary_for', return_value='/fake/claude'), patch.object(u, 'command', side_effect=failure):
                row = self.get_claude(config, force=True)['providers']['claude']
                self.assertEqual((row['status'], row['source']), ('stale', 'claude-rate-limit-snapshot'))
        u.claude_snapshot_path(core).unlink()
        with self.claude_env(), patch.object(u, 'binary_for', return_value='/fake/claude'), \
             patch.object(u, 'command', return_value='{"type":"result"}\n'):
            row = self.get_claude(config, forget=True, force=True)['providers']['claude']
            self.assertEqual((row['status'], row['windows']), ('unknown', []))
        with self.claude_env(), patch.object(u, 'binary_for', side_effect=u.UsageError('Claude CLI not installed')):
            self.assertEqual(self.get_claude(config, forget=True, force=True)['providers']['claude']['error'], 'Claude CLI not installed')

    def test_a_failed_degraded_read_is_cached_for_the_ttl_not_retried_on_every_get(self):
        """Stale snapshot as the last resort after a failed probe or OAuth attempt: the failure
        is remembered for the TTL, so usage reads do not spawn claude or call the network each time."""
        self.snapshot_file(age=300)
        calls = []
        def failing(argv, _core, timeout=15):
            calls.append(argv)
            raise u.UsageError('Usage command failed; recheck provider login')
        config = dict(self.config, usage=dict(self.config.get('usage', {}), claude_probe=True))
        with self.claude_env(), patch.object(u, 'binary_for', return_value='/fake/claude'), patch.object(u, 'command', side_effect=failing):
            for _ in range(3):
                self.assertEqual(self.get_claude(config)['providers']['claude']['status'], 'stale')
            self.assertEqual(len(calls), 1)
            self.get_claude(config, force=True)
            self.assertEqual(len(calls), 2)
        opener = Mock()
        opener.open.side_effect = u.urllib.error.HTTPError('url', 401, 'x', {}, io.BytesIO(b''))
        with self.claude_env(CLAUDE_CODE_OAUTH_TOKEN='test-token'), \
             patch.object(u.urllib.request, 'build_opener', return_value=opener), patch.object(u, 'command', side_effect=AssertionError('no probe')):
            self.assertEqual(self.get_claude(self.config, forget=True)['providers']['claude']['status'], 'stale')
            for _ in range(2):
                self.assertEqual(self.get_claude(self.config)['providers']['claude']['status'], 'stale')
            self.assertEqual(opener.open.call_count, 1)

    def test_fetch_may_report_when_it_observed_and_two_tuples_still_work(self):
        old = time.time() - 500
        def fetch(_core, name, _opts):
            return ('recorded', [u.window(name, '7d', .8, time.time() + 3600)], old) if name == 'codex' \
                else ('fake', [u.window(name, '7d', .8, time.time() + 3600)])
        with patch.object(u, 'fetch', side_effect=fetch):
            snapshot = u.get(core, force=True)
        self.assertEqual((snapshot['providers']['codex']['status'], snapshot['providers']['codex']['observed_at']), ('stale', old))
        self.assertEqual(snapshot['providers']['grok']['status'], 'fresh')
