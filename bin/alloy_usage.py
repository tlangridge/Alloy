"""Subscription observations and session-friendly meters. No inference calls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PROVIDERS = ('codex', 'claude', 'grok', 'antigravity')
LABELS = dict(codex='Codex', claude='Claude', grok='Grok', antigravity='Antigravity')
MAX_BYTES = 1024 * 1024


class UsageError(Exception):
    pass


def finite(value, low=0, high=1):
    return type(value) in (float, int) and math.isfinite(value) and low <= value <= high


def timestamp(value):
    if value is None:
        return None
    if finite(value, 0, 1e12):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                return None
            return parsed.timestamp()
        except ValueError:
            pass
    return None


def window(pool, name, remaining, reset=None):
    if not finite(remaining):
        raise UsageError('Invalid or missing quota percentage')
    return dict(pool=pool, window=name, remaining_fraction=remaining, resets_at=timestamp(reset))


def parse_codex(data):
    if not isinstance(data, dict):
        raise UsageError('Unrecognized Codex usage response')
    windows = []
    limits = data.get('rateLimitsByLimitId')
    if not isinstance(limits, dict) or not limits:
        limits = {'codex': data.get('rateLimits')}
    for key, limit in limits.items():
        if not isinstance(limit, dict):
            continue
        for part in ('primary', 'secondary'):
            lane = limit.get(part)
            if not isinstance(lane, dict) or lane.get('usedPercent') is None:
                continue
            used = lane['usedPercent']
            if not finite(used, 0, 100):
                raise UsageError('Invalid Codex quota percentage')
            minutes = lane.get('windowDurationMins')
            name = ('%gd' % (minutes / 1440) if minutes >= 1440 else '%gh' % (minutes / 60)) if finite(minutes, 1, 1e9) else part
            windows.append(window(str(key), name, 1 - used / 100, lane.get('resetsAt')))
    if not windows:
        raise UsageError('Codex did not report subscription windows')
    return windows


def parse_claude(data):
    if not isinstance(data, dict):
        raise UsageError('Unrecognized Claude usage response')
    windows = []
    for field, lane in data.items():
        if field not in ('five_hour', 'seven_day') and not field.startswith('seven_day_'):
            continue
        if not isinstance(lane, dict) or lane.get('utilization') is None:
            continue
        used = lane['utilization']
        if not finite(used, 0, 100):
            raise UsageError('Invalid Claude quota percentage')
        scope = field[len('seven_day_'):] if field.startswith('seven_day_') else None
        pool = 'claude:' + scope if scope else 'claude'
        windows.append(window(pool, '5h' if field == 'five_hour' else '7d', 1 - used / 100, lane.get('resets_at')))
    if not windows:
        raise UsageError('Claude did not report subscription windows')
    return windows


def parse_agy(data):
    if (not isinstance(data, dict) or data.get('status') != 'SUCCESS'
        or data.get('command', {}).get('name') != 'usage'):
        raise UsageError('Antigravity did not return a built-in usage report')
    windows = []
    groups = data.get('command', {}).get('data', {}).get('groups', [])
    if not isinstance(groups, list):
        raise UsageError('Unrecognized Antigravity quota groups')
    for group in groups:
        for bucket in group.get('buckets', []):
            if bucket.get('enabled') is False:
                continue
            ident = bucket.get('id', '')
            pool = 'antigravity:gemini' if ident.startswith('gemini-') else 'antigravity:3p' if ident.startswith('3p-') else None
            if pool is None:
                continue  # An unknown bucket's capacity is not automatically shared.
            windows.append(window(pool, str(bucket.get('window', 'unknown')),
                bucket.get('remaining_fraction'), bucket.get('reset_time')))
    if not windows:
        raise UsageError('Antigravity did not report known quota groups')
    return windows


def stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)


def provider_env(core):
    env = core.routing.clean_env()
    for name, value in core._CONFIG.items():
        if name != 'TYPESAFE_API_KEY':
            env.setdefault(name, value)
    return env


def binary_for(core, provider):
    binary = core.ADAPTERS[provider].resolved_bin()
    if not binary:
        raise UsageError(LABELS[provider] + ' CLI not installed')
    override = core.setting('ALLOY_BIN_' + provider.upper())
    if not override and core._is_within(binary, os.path.abspath(os.getcwd())):
        raise UsageError('Usage binary resolves inside working directory; configure a trusted binary explicitly')
    return binary


def command(argv, core, timeout=15):
    """Bound output in memory, deadline and child lifetime; no repo context."""
    with tempfile.TemporaryDirectory(prefix='alloy-usage-') as cwd:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=cwd, env=provider_env(core), start_new_session=True)
        chunks, size = [], 0
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        end = time.monotonic() + timeout
        try:
            while time.monotonic() < end:
                if not selector.select(min(.2, max(0, end - time.monotonic()))):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    if process.wait(timeout=1):
                        raise UsageError('Usage command failed; recheck provider login')
                    return b''.join(chunks).decode('utf-8')
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UsageError('Usage command exceeded output limit')
                chunks.append(chunk)
            raise UsageError('Usage command timed out')
        finally:
            stop(process)
            process.stdout.close()
            selector.close()


def codex_rpc(core, binary):
    with tempfile.TemporaryDirectory(prefix='alloy-usage-') as cwd:
        process = subprocess.Popen([binary, 'app-server'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=cwd,
            env=provider_env(core), start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        buffer = b''
        total = 0
        end = time.monotonic() + 12

        def send(message):
            process.stdin.write((json.dumps(message) + '\n').encode())
            process.stdin.flush()

        def rpc(ident, method, params=None):
            nonlocal buffer, total
            message = dict(id=ident, method=method)
            if params is not None:
                message['params'] = params
            send(message)
            while time.monotonic() < end:
                if b'\n' in buffer:
                    raw, buffer = buffer.split(b'\n', 1)
                    parsed = json.loads(raw)
                    if parsed.get('id') == ident:
                        if 'error' in parsed:
                            raise UsageError('Codex usage RPC unavailable; recheck login')
                        return parsed.get('result', {})
                elif selector.select(.2):
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise UsageError('Codex RPC exceeded output limit')
                    buffer += chunk
            raise UsageError('Codex usage RPC timed out')
        try:
            rpc(1, 'initialize', {'clientInfo': {'name': 'alloy_usage', 'version': '1'}})
            send({'method': 'initialized'})
            return rpc(2, 'account/rateLimits/read')
        finally:
            stop(process)
            process.stdin.close()
            process.stdout.close()
            selector.close()


def binding(core, provider):
    """Invalidate cached observations when a known credential source changes."""
    paths = {
        'codex': [Path(core.setting('CODEX_HOME') or Path.home() / '.codex') / 'auth.json'],
        'claude': [Path(core.setting('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))) / '.credentials.json'],
        'antigravity': [Path.home() / '.gemini' / 'oauth_creds.json',
                       Path.home() / '.gemini/antigravity-cli/antigravity-oauth-token'],
        'grok': []}[provider]
    parts = [str(p) for p in paths]
    for path in paths:
        try:
            st = path.stat(); parts.append('%s:%s' % (st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append('missing')
    names = {'codex': ('CODEX_API_KEY', 'OPENAI_API_KEY'),
             'claude': ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_BASE_URL'),
             'antigravity': ('ANTIGRAVITY_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'), 'grok': ('XAI_API_KEY',)}[provider]
    # Persist only a digest, never tokens, identities or their source contents.
    parts.extend(core.setting(n, '') for n in names)
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def fetch(core, provider, options):
    if provider == 'grok':
        raise UsageError('No supported Grok subscription-limit source; token totals are not remaining quota')
    if provider == 'codex':
        if core.setting('CODEX_API_KEY') or core.setting('OPENAI_API_KEY'):
            raise UsageError('API-key override present; subscription applicability is unknown')
        binary = binary_for(core, 'codex')
        if not binary:
            raise UsageError('Codex CLI not installed')
        return 'codex-cli-rpc', parse_codex(codex_rpc(core, binary))
    if provider == 'antigravity':
        if any(core.setting(k) for k in ('ANTIGRAVITY_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY')):
            raise UsageError('API-key override present; subscription applicability is unknown')
        binary = binary_for(core, 'antigravity')
        if not binary:
            raise UsageError('Antigravity CLI not installed')
        version = command([binary, '--version'], core, timeout=3)
        match = re.search(r'(\d+)\.(\d+)\.(\d+)', version)
        if not match or tuple(map(int, match.groups())) < (1, 1, 11):
            raise UsageError('Antigravity 1.1.11+ required for built-in non-inference usage command')
        return 'agy-usage', parse_agy(json.loads(command([binary, '-p', '/usage', '--output-format', 'json'], core)))
    if core.setting('ANTHROPIC_API_KEY') or core.setting('ANTHROPIC_BASE_URL'):
        raise UsageError('API/proxy override present; subscription applicability is unknown')
    token = core.setting('CLAUDE_CODE_OAUTH_TOKEN')
    home = Path(core.setting('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
    if not token:
        try:
            credentials = json.loads((home / '.credentials.json').read_text())
            token = credentials.get('claudeAiOauth', {}).get('accessToken')
        except (OSError, ValueError):
            pass
    if not token and sys.platform == 'darwin' and options.get('keychain', True) and not core.setting('CLAUDE_CONFIG_DIR'):
        try:
            credentials = json.loads(command(['/usr/bin/security', 'find-generic-password',
                '-s', 'Claude Code-credentials', '-w'], core, timeout=4))
            token = credentials.get('claudeAiOauth', {}).get('accessToken')
        except (UsageError, ValueError):
            pass
    if not token:
        raise UsageError('Claude usage OAuth credential unavailable; recheck Claude login/Keychain access')
    request = urllib.request.Request('https://api.anthropic.com/api/oauth/usage',
        headers={'Authorization': 'Bearer ' + token, 'anthropic-beta': 'oauth-2025-04-20'})
    opener = urllib.request.build_opener(core.routing.NoRedirect)
    try:
        with opener.open(request, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise UsageError('Claude usage response too large')
        return 'claude-oauth', parse_claude(json.loads(raw))
    except urllib.error.HTTPError as exc:
        code = exc.code; exc.close()
        raise UsageError('Claude usage HTTP %s; keep the CLI responsible for login/token refresh' % code) from None


def get(core, config=None, force=False, cached=False):
    r = core.routing
    if config is None:
        config = r.load() if (r.root() / 'routing.json').exists() else {}
    options = config.get('usage', {})
    if core.setting('ALLOY_USAGE', '').lower() in ('off', '0', 'false') or options.get('enabled') is False:
        return dict(schema=1, enabled=False, providers={})
    now = time.time()
    ttl = options.get('ttl_seconds', 120)
    if not finite(ttl, 5, 3600):
        raise r.RoutingError('usage.ttl_seconds must be 5–3600 seconds')
    path = r.root() / 'usage-cache.json'
    try:
        saved = r.read_json(path, {})
        old = saved.get('providers', {}) if isinstance(saved, dict) else {}
    except r.RoutingError:
        old = {}
    snapshot = dict(schema=1, enabled=True, generated_at=now, ttl_seconds=ttl, providers={})

    def one(provider):
        previous = old.get(provider, {})
        current_binding = binding(core, provider)
        checked = previous.get('checked_at', 0)
        reuse = (finite(checked, 0, now) and now - checked < ttl
                 and previous.get('binding') == current_binding)
        if previous.get('status') == 'fresh' and any(w.get('resets_at') is not None and w['resets_at'] <= now for w in previous.get('windows', [])):
            reuse = False
        if (reuse and not force) or cached:
            result = dict(previous) if previous.get('binding') == current_binding else {}
            result.setdefault('windows', [])
            result.setdefault('status', 'unknown')
            observed = result.get('observed_at', 0)
            if (result['status'] == 'fresh' and
                (not finite(observed, 0, now) or now - observed >= ttl)):
                result['status'] = 'stale'
            # A reset passing is not proof that capacity is replenished.
            if result['status'] == 'fresh' and any(w.get('resets_at') is not None and w['resets_at'] <= now for w in result['windows']):
                result['status'] = 'stale'
            return provider, result
        try:
            source, windows = fetch(core, provider, options)
            status = 'stale' if any(w.get('resets_at') is not None and w['resets_at'] <= time.time() for w in windows) else 'fresh'
            return provider, dict(status=status, source=source, windows=windows,
                observed_at=time.time(), checked_at=time.time(), binding=current_binding)
        except (UsageError, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired):
            # Catch below separately to avoid serializing provider raw response bodies.
            info = sys.exc_info()[1]
            error = str(info) if isinstance(info, UsageError) else 'Usage source unavailable or response format changed'
            same = previous.get('binding') == current_binding
            windows = previous.get('windows', []) if same else []
            return provider, dict(status='stale' if windows else 'unknown',
                source=previous.get('source') if same else None, windows=windows,
                observed_at=previous.get('observed_at') if same else None,
                checked_at=time.time(), binding=current_binding, error=error)

    with ThreadPoolExecutor(max_workers=4) as executor:
        snapshot['providers'] = dict(executor.map(one, PROVIDERS))
    if not cached:
        r.save(path, snapshot)
    return snapshot


def public(snapshot):
    """Only selected quota data enters prompts/manifests, never auth metadata."""
    out = dict(snapshot)
    out['providers'] = {n: {k: v for k, v in row.items() if k != 'binding'}
                        for n, row in snapshot.get('providers', {}).items()}
    return out


def applicable(profile):
    provider = profile['adapter']
    model = profile['model'].lower()
    pools = []
    if provider == 'antigravity':
        if model.startswith('gemini-'):
            pools = ['antigravity:gemini']
        elif model.startswith(('claude-', 'gpt-')):
            pools = ['antigravity:3p']
    elif provider == 'claude':
        pools = ['claude']
        for name in ('sonnet', 'opus', 'fable', 'haiku'):
            if name in model:
                pools.append('claude:' + name)
    else:
        pools = [provider]
    if profile.get('usage_pool'):
        pools.append(profile['usage_pool'])
    return list(dict.fromkeys(pools))


def headroom(profile, snapshot):
    if profile.get('billing_mode') == 'metered':
        return None
    row = snapshot.get('providers', {}).get(profile['adapter'], {})
    if row.get('status') != 'fresh':
        return None
    now = time.time()
    observed = row.get('observed_at')
    if not finite(observed, 0, now) or now - observed >= snapshot.get('ttl_seconds', 120):
        return None
    pools = applicable(profile)
    selected = [w for w in row.get('windows', []) if w.get('pool') in pools]
    if not selected or any(w.get('resets_at') is not None and w['resets_at'] <= now for w in selected):
        return None
    if any(not finite(w.get('remaining_fraction')) for w in selected):
        return None
    return min(w['remaining_fraction'] for w in selected)


def reset_text(value, now):
    if value is None:
        return 'unknown'
    seconds = value - now
    if seconds <= 0:
        return 'reset passed; refresh needed'
    if seconds >= 86400:
        return '%dd %dh' % (seconds // 86400, seconds % 86400 // 3600)
    if seconds >= 3600:
        return '%dh %dm' % (seconds // 3600, seconds % 3600 // 60)
    return '%dm' % max(1, seconds // 60)


def render(snapshot):
    if not snapshot.get('enabled'):
        return 'Alloy usage tracking is disabled.\n'
    lines = ['**Subscription capacity remaining**', '',
             '| Provider / pool | Window | Available | Resets in | Status |',
             '| --- | --- | --- | --- | --- |']
    now = time.time()
    for provider in PROVIDERS:
        row = snapshot.get('providers', {}).get(provider, {})
        windows = row.get('windows', [])
        if not windows:
            lines.append('| %s | — | unknown | — | unavailable |' % LABELS[provider])
        for w in windows:
            n = w['remaining_fraction']
            bar = '█' * round(n * 10) + '░' * (10 - round(n * 10))
            pool = w['pool'].partition(':')[2]
            if provider == 'antigravity':
                pool = {'gemini': 'Gemini', '3p': 'Claude/GPT'}.get(pool, pool)
            if not pool and w['pool'] != provider:
                pool = w['pool']
            label = LABELS[provider] + (' / ' + pool if pool else '')
            # All provider text is escaped before entering Markdown.
            label = label.replace('|', '\\|').replace('\n', ' ')
            status = row.get('status', 'unknown')
            observed = row.get('observed_at')
            if observed is not None:
                status += ' · %ds old' % max(0, now - observed)
            lines.append('| %s | %s | `%s` %.0f%% | %s | %s |' %
                (label, str(w['window']).replace('|', '\\|').replace('\n', ' '),
                 bar, n * 100, reset_text(w.get('resets_at'), now), status))
    lines += ['', 'Stale/unknown readings are excluded from quota calculations. Grok quota reporting is not supported yet.']
    return '\n'.join(lines) + '\n'


def emit(core, args):
    snapshot = get(core, force=args.refresh, cached=args.cached)
    if args.if_changed:
        state = {n: dict(status=p.get('status'), windows=[
            dict(pool=w['pool'], window=w['window'], band=int(w['remaining_fraction'] * 20), resets_at=w.get('resets_at'))
            for w in p.get('windows', [])]) for n, p in snapshot.get('providers', {}).items()}
        digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
        session = args.session or os.environ.get('CODEX_THREAD_ID') or os.environ.get('ALLOY_SESSION_ID') or os.getcwd()
        name = hashlib.sha256(session.encode()).hexdigest()[:24]
        path = core.routing.root() / 'usage-displays' / (name + '.json')
        previous = core.routing.read_json(path, {})
        if previous.get('digest') == digest:
            return 0
        core.routing.save(path, dict(digest=digest))
    print(json.dumps(public(snapshot), indent=2) if args.format == 'json' else render(snapshot), end='\n')
    return 0


def register(sub, core):
    parser = sub.add_parser('usage', help='subscription meters for session context (no inference calls)')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--refresh', action='store_true', help='force bounded provider reads')
    group.add_argument('--cached', action='store_true', help='read cache only; no provider access')
    parser.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    parser.add_argument('--if-changed', action='store_true', help='emit only on first use, 5%% change, reset or status change')
    parser.add_argument('--session', help='stable session identifier for change suppression')
    parser.set_defaults(func=lambda args: emit(core, args))
