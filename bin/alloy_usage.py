"""Subscription observations and session-friendly meters. No inference calls by default.

Alloy never reads the macOS keychain and never runs `security` (operator policy, 2026-09-29).
Claude quota therefore comes only from keychain-free sources, tried in this order:
  1. a credentials FILE or CLAUDE_CODE_OAUTH_TOKEN that already exists -> Anthropic usage endpoint;
  2. the rate-limit snapshot recorded by Claude Code's own status line. Opt in by pointing the
     status-line command at `alloy usage --record-claude-statusline`; Alloy installs nothing.
     A Claude run's stream-json output can be recorded the same way:
     `claude -p ... --output-format stream-json --verbose | alloy usage --record-claude-stream`.
     A snapshot older than usage.ttl_seconds is `stale`; no snapshot is `unknown`;
  3. only when the operator sets `usage.claude_probe: true`: the `rate_limit_event` of one tiny
     `claude -p ... --output-format stream-json --verbose` run (a real, cheap inference call;
     read at most once per usage TTL).
Cursor's two subscription pools are not exposed by its CLI, so they are `unknown` unless the
operator sets `quota_pools["cursor:models"|"cursor:other"].remaining_fraction` by hand.
"""
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
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PROVIDERS = ('codex', 'claude', 'grok', 'antigravity', 'cursor')
LABELS = dict(codex='Codex', claude='Claude', grok='Grok', antigravity='Antigravity', cursor='Cursor')
MAX_BYTES = 1024 * 1024
# Cursor has two subscription pools that its CLI does not expose. The names follow the
# provider:pool convention of claude:sonnet and antigravity:gemini.
CURSOR_POOLS = {'cursor:models': 'Cursor Models', 'cursor:other': 'Other Models'}
# Never a usage-child environment value: router keys and Cursor credential/endpoint overrides.
SCRUBBED = ('TYPESAFE_API_KEY', 'OPENROUTER_API_KEY', 'CURSOR_API_KEY', 'CURSOR_API_ENDPOINT')
CLAUDE_WINDOWS = (('five_hour', '5h'), ('seven_day', '7d'))
CLAUDE_SNAPSHOT = 'claude-rate-limits.json'
SNAPSHOT_BYTES = 64 * 1024
# The tiny fresh-reading probe. --no-session-persistence and --strict-mcp-config keep it from
# writing a session or starting MCP servers (both flags exist in Claude Code 2.1.284 --help).
CLAUDE_PROBE_ARGV = ('-p', 'OK', '--model', 'haiku', '--output-format', 'stream-json', '--verbose',
                     '--no-session-persistence', '--strict-mcp-config')


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
    # Newer responses expose model buckets in limits, not seven_day_<model>.
    limits = data.get('limits') or []
    if not isinstance(limits, list):
        raise UsageError('Unrecognized Claude scoped limits')
    for lane in limits:
        if not isinstance(lane, dict) or lane.get('kind') != 'weekly_scoped':
            continue
        scope = lane.get('scope')
        if not isinstance(scope, dict) or scope.get('surface') is not None:
            continue
        model = scope.get('model')
        if not isinstance(model, dict):
            continue
        names = ' '.join(str(model.get(k) or '') for k in ('id', 'display_name')).lower()
        matches = [name for name in ('fable', 'sonnet', 'opus', 'haiku')
                   if re.search(r'\b' + name + r'\b', names)]
        if len(matches) != 1:
            continue
        used = lane.get('percent')
        if not finite(used, 0, 100):
            raise UsageError('Invalid Claude scoped quota percentage')
        pool = 'claude:' + matches[0]
        # Prefer the explicit scoped entry over a duplicate legacy bucket.
        windows = [w for w in windows if w['pool'] != pool]
        windows.append(window(pool, '7d', 1 - used / 100, lane.get('resets_at')))
    if not windows:
        raise UsageError('Claude did not report subscription windows')
    return windows


def claude_windows(lanes):
    """Alloy windows from Claude Code's own rate-limit fields, no OAuth token involved.
    Two shapes, both verified against Claude Code 2.1.284 and both reporting USED capacity:
      stream-json rate_limit_event: rate_limit_info.unifiedWindows.<window> =
          {utilization: used FRACTION 0-1, resetsAt: epoch seconds}
      status-line JSON: rate_limits.<window> =
          {used_percentage: used PERCENT 0-100, resets_at: epoch seconds}
    Only five_hour and seven_day are mapped. remaining = 1 - used. Up to double the range means
    the limit was exceeded, which is exhausted (remaining 0), never unknown; beyond that the
    field is not what it claims to be and is invalid."""
    if not isinstance(lanes, dict):
        raise UsageError('Unrecognized Claude rate-limit fields')
    windows = []
    for key, label in CLAUDE_WINDOWS:
        lane = lanes.get(key)
        if not isinstance(lane, dict):
            continue
        if lane.get('utilization') is not None:
            used, scale = lane['utilization'], 1
        elif lane.get('used_percentage') is not None:
            used, scale = lane['used_percentage'], 100
        else:
            continue
        if not finite(used, 0, scale * 2):
            raise UsageError('Invalid Claude quota utilization')
        windows.append(window('claude', label, 1 - min(used, scale) / scale,
                              lane.get('resetsAt', lane.get('resets_at'))))
    if not windows:
        raise UsageError('Claude did not report subscription windows')
    return windows


def claude_stream_lanes(text):
    """The latest rate_limit_event's unifiedWindows entry for each window in
    `claude -p --output-format stream-json --verbose` output. Other lines are ignored."""
    lanes = {}
    for line in text.splitlines():
        if 'rate_limit_event' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        info = event.get('rate_limit_info') if isinstance(event, dict) and event.get('type') == 'rate_limit_event' else None
        unified = info.get('unifiedWindows') if isinstance(info, dict) else None
        if isinstance(unified, dict):
            lanes.update({key: unified[key] for key, _ in CLAUDE_WINDOWS if isinstance(unified.get(key), dict)})
    return lanes


def parse_claude_stream(text):
    return claude_windows(claude_stream_lanes(text))


def claude_snapshot_path(core):
    return core.routing.root() / CLAUDE_SNAPSHOT


def read_claude_snapshot(core):
    """(windows, observed_at) from the status-line snapshot, or None when there is no file.
    The observation time is the older of the recorded time and the file's mtime, so neither a
    copied file nor an edited timestamp can make old data look fresh."""
    try:
        with claude_snapshot_path(core).open('rb') as stream:
            info = os.fstat(stream.fileno())
            raw = stream.read(SNAPSHOT_BYTES + 1)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or len(raw) > SNAPSHOT_BYTES:
        raise UsageError('Claude rate-limit snapshot is not a small regular file')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise UsageError('Unrecognized Claude rate-limit snapshot')
    lanes = data.get('rate_limits') if isinstance(data.get('rate_limits'), dict) else data.get('unifiedWindows')
    windows = claude_windows(lanes)
    recorded = timestamp(data.get('observed_at'))
    observed = min(info.st_mtime, recorded if recorded is not None else info.st_mtime)
    now = time.time()
    if observed > now + 60:
        raise UsageError('Claude rate-limit snapshot is dated in the future')
    return windows, min(observed, now)


def meter_line(windows):
    return 'Claude ' + ' | '.join('%s %.0f%% left' % (w['window'], w['remaining_fraction'] * 100) for w in windows)


def record_claude_statusline(core, stream):
    """`alloy usage --record-claude-statusline`: the opt-in Claude Code status-line command.
    Claude Code sends its status JSON on stdin; keep only rate_limits.five_hour/seven_day,
    write the snapshot atomically and privately, and print a one-line meter. It must never fail
    a status line, so an absent or unusable rate_limits (API-key login, before the first
    response) is a silent no-op. Alloy does not install it."""
    try:
        raw = stream.read(MAX_BYTES + 1)
        data = json.loads(raw) if len(raw) <= MAX_BYTES else None
        lanes = data.get('rate_limits') if isinstance(data, dict) else None
        if not isinstance(lanes, dict):
            return 0
        kept = {key: {'used_percentage': lanes[key].get('used_percentage'),
                      'resets_at': timestamp(lanes[key].get('resets_at'))}
                for key, _ in CLAUDE_WINDOWS if isinstance(lanes.get(key), dict)}
        windows = claude_windows(kept)
        core.routing.save(claude_snapshot_path(core), dict(schema=1, observed_at=time.time(), rate_limits=kept))
    except (UsageError, OSError, ValueError, core.routing.RoutingError):
        return 0
    print(meter_line(windows))
    return 0


def record_claude_stream(core, stream):
    """`claude -p ... --output-format stream-json --verbose | alloy usage --record-claude-stream`:
    record the rate_limit_event of a Claude run that was made anyway (an operator's, or a
    dispatch Alloy makes in stream-json mode) instead of spending a probe. Only the latest
    event's five_hour/seven_day windows are kept, in the same snapshot the status-line command
    writes, so the usage TTL, staleness and reserve rules are identical. The stream is read line
    by line without holding it; like the status-line command it never fails its caller."""
    try:
        lines = []
        while True:
            line = stream.readline(MAX_BYTES + 1)
            if not line:
                break
            if 'rate_limit_event' in line and len(line) <= MAX_BYTES:
                lines = (lines + [line])[-50:]
        kept = {key: {'utilization': lane.get('utilization'), 'resetsAt': timestamp(lane.get('resetsAt', lane.get('resets_at')))}
                for key, lane in claude_stream_lanes(''.join(lines)).items()}
        windows = claude_windows(kept)
        core.routing.save(claude_snapshot_path(core), dict(schema=1, observed_at=time.time(), unifiedWindows=kept))
    except (UsageError, OSError, ValueError, core.routing.RoutingError):
        return 0
    print(meter_line(windows))
    return 0


def parse_grok(data):
    config = data.get('config') if isinstance(data, dict) else None
    if not isinstance(config, dict):
        raise UsageError('Unrecognized Grok billing response')
    used = config.get('creditUsagePercent')
    # Only included credits are subscription capacity. Never use on-demand caps.
    if used is None:
        consumed, limit = config.get('used'), config.get('monthlyLimit')
        if isinstance(consumed, dict) and isinstance(limit, dict):
            consumed, limit = consumed.get('val'), limit.get('val')
            if finite(consumed, 0, 1e18) and finite(limit, 1e-12, 1e18):
                used = consumed / limit * 100
    if not finite(used, 0, 100):
        raise UsageError('Grok did not report valid included-credit usage')
    period = config.get('currentPeriod')
    period = period if isinstance(period, dict) else {}
    end = timestamp(period.get('end'))
    start = timestamp(period.get('start'))
    if end is None:
        end = timestamp(config.get('billingPeriodEnd'))
        start = timestamp(config.get('billingPeriodStart'))
    if end is None or (start is not None and (start >= end or start > time.time())):
        raise UsageError('Grok did not report a valid billing period')
    duration = end - start if start is not None else None
    label = 'weekly' if duration and 6*86400 <= duration <= 8*86400 else 'monthly' if duration and 27*86400 <= duration <= 32*86400 else 'credits'
    return [window('grok', label, 1 - used / 100, end)]


def grok_auth_path(core):
    return Path(core.setting('GROK_HOME') or Path.home() / '.grok').expanduser() / 'auth.json'


def fetch_grok(core):
    if core.setting('XAI_API_KEY') or core.setting('GROK_API_KEY'):
        raise UsageError('API-key override present; subscription applicability is unknown')
    with grok_auth_path(core).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise UsageError('Grok credential file too large')
    credentials = json.loads(raw)
    candidates = [(scope, entry) for scope, entry in credentials.items()
        if isinstance(entry, dict) and isinstance(entry.get('key'), str) and entry['key']
        and (scope.startswith('https://auth.x.ai::') or scope == 'https://accounts.x.ai/sign-in')]
    preferred = [entry for scope, entry in candidates if scope.startswith('https://auth.x.ai::')]
    entries = preferred or [entry for _, entry in candidates]
    if len(entries) != 1:
        raise UsageError('Grok login missing or ambiguous; run grok login')
    entry = entries[0]
    expires = timestamp(entry.get('expires_at'))
    if expires is None or expires <= time.time():
        raise UsageError('Grok login expired or expiry unknown; run grok login')
    if str(entry.get('principal_type', '')).lower() == 'team':
        raise UsageError('Grok team subscription quota is unavailable')
    request = urllib.request.Request('https://cli-chat-proxy.grok.com/v1/billing?format=credits',
        headers={'Authorization': 'Bearer ' + entry['key'],
                 'x-xai-token-auth': 'xai-grok-cli', 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(core.routing.NoRedirect).open(request, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise UsageError('Grok billing response too large')
        return 'grok-cli-billing', parse_grok(json.loads(raw))
    except urllib.error.HTTPError as exc:
        code = exc.code; exc.close()
        raise UsageError('Grok billing HTTP %s; keep the CLI responsible for login/token refresh' % code) from None


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
    scrubbed = set(SCRUBBED) | set(getattr(core.routing, 'SCRUBBED_ENV', ()))
    for name, value in core._CONFIG.items():
        if name not in scrubbed:
            env.setdefault(name, value)
    for name in scrubbed:
        env.pop(name, None)
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


def cursor_state_path():
    return Path.home() / '.cursor' / 'agent-cli-state.json'


def binding(core, provider):
    """Invalidate cached observations when a known credential source changes."""
    if provider not in PROVIDERS:
        raise UsageError('Unknown usage provider: %s' % str(provider)[:64])
    paths = {
        'codex': [Path(core.setting('CODEX_HOME') or Path.home() / '.codex') / 'auth.json'],
        'claude': [Path(core.setting('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))) / '.credentials.json'],
        'antigravity': [Path.home() / '.gemini' / 'oauth_creds.json',
                       Path.home() / '.gemini/antigravity-cli/antigravity-oauth-token'],
        'grok': [grok_auth_path(core)],
        # Path, mtime and size only; the account file's contents are never read or hashed.
        'cursor': [cursor_state_path()]}[provider]
    parts = [str(p) for p in paths]
    for path in paths:
        try:
            st = path.stat(); parts.append('%s:%s' % (st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append('missing')
    # Cursor binds no environment value: CURSOR_API_KEY and CURSOR_API_ENDPOINT are never
    # part of a cache key, a child environment or a persisted observation.
    names = {'codex': ('CODEX_API_KEY', 'OPENAI_API_KEY'),
             'claude': ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_BASE_URL'),
             'antigravity': ('ANTIGRAVITY_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'), 'grok': ('XAI_API_KEY', 'GROK_API_KEY'),
             'cursor': ()}[provider]
    # Persist only a digest, never tokens, identities or their source contents.
    parts.extend(core.setting(n, '') for n in names)
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def fetch(core, provider, options):
    if provider == 'grok':
        return fetch_grok(core)
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
    if provider == 'cursor':
        # The Cursor CLI has no usage command or subscription quota API. Operator-set
        # quota_pools are applied in get(), never fetched. Per-call token usage is not quota.
        raise UsageError('Cursor CLI exposes no subscription usage source')
    if provider == 'claude':
        return fetch_claude(core, options)
    # Never fall through to another provider's credentials, a keychain or the network.
    raise UsageError('Unknown usage provider: %s' % str(provider)[:64])


def claude_oauth(core, token):
    """Anthropic's OAuth usage endpoint with a token that ALREADY exists in the environment
    or a credentials file. Alloy never reads a keychain and never refreshes credentials."""
    request = urllib.request.Request('https://api.anthropic.com/api/oauth/usage',
        headers={'Authorization': 'Bearer ' + token, 'anthropic-beta': 'oauth-2025-04-20'})
    opener = urllib.request.build_opener(core.routing.NoRedirect)
    try:
        with opener.open(request, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise UsageError('Claude usage response too large')
        return parse_claude(json.loads(raw))
    except urllib.error.HTTPError as exc:
        code = exc.code; exc.close()
        raise UsageError('Claude usage HTTP %s; keep the CLI responsible for login/token refresh' % code) from None


def claude_probe(core):
    """One tiny real `claude -p` run whose stream-json output carries a rate_limit_event.
    Opt-in (usage.claude_probe); spends a very small amount of quota; cached for the usage TTL.
    Runs through command(), which starts the child with stdin=DEVNULL (`< /dev/null`), so the
    run can never wait on, or read, the caller's terminal or pipe."""
    return parse_claude_stream(command([binary_for(core, 'claude'), *CLAUDE_PROBE_ARGV], core, timeout=30))


def fetch_claude(core, options):
    """Claude quota with no keychain access. Sources, in order: an existing OAuth credential
    (env or file), the status-line snapshot, the opt-in probe, then a stale snapshot. Returns
    (source, windows, observed_at) so an old snapshot is reported stale, not fresh."""
    if core.setting('ANTHROPIC_API_KEY') or core.setting('ANTHROPIC_BASE_URL'):
        raise UsageError('API/proxy override present; subscription applicability is unknown')
    ttl = options.get('ttl_seconds', 120)
    ttl = ttl if finite(ttl, 5, 3600) else 120
    failure = None
    token = core.setting('CLAUDE_CODE_OAUTH_TOKEN')
    if not token:
        home = Path(core.setting('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
        try:
            token = json.loads((home / '.credentials.json').read_text()).get('claudeAiOauth', {}).get('accessToken')
        except (OSError, ValueError, AttributeError):
            token = None
    if token:
        try:
            return 'claude-oauth', claude_oauth(core, token), time.time()
        except UsageError as exc:
            failure = exc
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            failure = UsageError('Claude OAuth usage source unavailable or response format changed')
    snapshot = None
    try:
        snapshot = read_claude_snapshot(core)
    except UsageError as exc:
        failure = failure or exc
    except (OSError, ValueError):
        failure = failure or UsageError('Claude rate-limit snapshot unreadable')
    if snapshot and time.time() - snapshot[1] < ttl:
        return 'claude-rate-limit-snapshot', snapshot[0], snapshot[1]
    if options.get('claude_probe') is True:
        try:
            return 'claude-cli-probe', claude_probe(core), time.time()
        except (UsageError, OSError, ValueError, subprocess.SubprocessError) as exc:
            failure = failure or (exc if isinstance(exc, UsageError) else UsageError('Claude usage probe failed'))
    if snapshot:
        return 'claude-rate-limit-snapshot', snapshot[0], snapshot[1]  # get() reports it stale
    raise failure or UsageError('Claude usage unavailable: keychain access disabled by policy '
        '(no credentials file and no rate-limit snapshot; see alloy usage --record-claude-statusline)')


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
    if 'claude_probe' in options and type(options['claude_probe']) is not bool:
        raise r.RoutingError('usage.claude_probe must be true or false')
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
        if provider == 'cursor':
            # Operator-set pools are configuration, not a provider read: never cached, so an edit
            # (or its removal) takes effect on the next read, including --cached.
            manual = cursor_manual_windows(config.get('quota_pools'))
            if manual:
                return provider, dict(status='fresh', source='operator-config', windows=manual,
                    observed_at=time.time(), checked_at=time.time(), binding=current_binding)
            if previous.get('source') == 'operator-config':
                previous = {}
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
            fetched = fetch(core, provider, options)
            source, windows = fetched[0], fetched[1]
            # A source may report when it observed the data (a recorded snapshot); otherwise now.
            observed = fetched[2] if len(fetched) > 2 else time.time()
            status = ('stale' if any(w.get('resets_at') is not None and w['resets_at'] <= time.time() for w in windows)
                      or time.time() - observed >= ttl else 'fresh')
            # A fresh recorded snapshot stops being cache-valid when the observation stops being
            # fresh (it can be older than this read). A stale one is the last resort after a
            # failed probe or OAuth attempt: cache that failure for the TTL like any other provider.
            checked = observed if source == 'claude-rate-limit-snapshot' and status == 'fresh' else time.time()
            return provider, dict(status=status, source=source, windows=windows,
                observed_at=observed, checked_at=checked, binding=current_binding)
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

    with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as executor:
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


def cursor_pool(model):
    """'Cursor Models' (composer-*, cursor-grok-*) or 'Other Models' (every other model served
    through Cursor). Bracket controls such as [context=1m] are not part of the model ID."""
    base = str(model).strip().lower().partition('[')[0]
    return 'cursor:models' if base.startswith(('composer-', 'cursor-grok-')) else 'cursor:other'


def cursor_manual_windows(quota_pools):
    """One window per Cursor pool the operator described by hand in routing `quota_pools`.
    The CLI exposes no quota, so a pool without a valid remaining_fraction stays unknown.
    The pool's own reserve_fraction (default 0.1, as for every manual pool) is honoured by
    headroom() in addition to the global usage.reserve_fraction that routing applies."""
    windows = []
    for pool in CURSOR_POOLS:
        entry = quota_pools.get(pool) if isinstance(quota_pools, dict) else None
        if not isinstance(entry, dict) or not finite(entry.get('remaining_fraction')):
            continue
        row = window(pool, 'manual', entry['remaining_fraction'])
        reserve = entry.get('reserve_fraction', .1)
        row['reserve_fraction'] = reserve if finite(reserve) else .1
        windows.append(row)
    return windows


def applicable(profile):
    provider = profile['adapter']
    model = profile['model'].lower()
    pools = []
    if provider == 'cursor':
        # Before any family or model logic: a Cursor model's vendor never selects a native
        # provider's pool. Every Cursor model shares the account-wide `cursor` pool (a window
        # named `cursor`, when a source reports one) and draws on one of Cursor's two billing
        # pools. Like claude + claude:<model>, the most constrained applicable window wins.
        pools = ['cursor', cursor_pool(model)]
    elif provider == 'antigravity':
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
    # A pool that carries its own reserve (manual Cursor pools) at or under it is exhausted
    # for routing; routing separately applies the global usage.reserve_fraction to this value.
    if any(finite(w.get('reserve_fraction')) and w['remaining_fraction'] <= w['reserve_fraction'] for w in selected):
        return 0.0
    return min(w['remaining_fraction'] for w in selected)


_WINDOW_UNITS = {'h': 3600, 'd': 86400, 'w': 7 * 86400}
_WINDOW_NAMES = {'hourly': 3600, 'daily': 86400, 'weekly': 7 * 86400, 'monthly': 30 * 86400}


def window_seconds(name):
    """Length of a quota window from its label ('5h', '7d', 'weekly'); None if unknown."""
    name = str(name).strip().lower()
    if name in _WINDOW_NAMES:
        return _WINDOW_NAMES[name]
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([hdw])', name)
    return float(m.group(1)) * _WINDOW_UNITS[m.group(2)] if m else None


def pacing(profile, snapshot):
    """Quota pressure: (share of the window still to run) / (share of quota left),
    worst window wins. Below 1, capacity will reset unused at the current pace;
    above 1, it is running short. None when any window is unknown or unparseable."""
    if headroom(profile, snapshot) is None:
        return None
    now = time.time()
    row = snapshot['providers'][profile['adapter']]
    pools = applicable(profile)
    pressure = []
    for w in row.get('windows', []):
        if w.get('pool') not in pools:
            continue
        length = window_seconds(w.get('window'))
        if not length or w.get('resets_at') is None:
            return None
        left = min(1.0, max(0.0, (w['resets_at'] - now) / length))
        pressure.append(left / max(w['remaining_fraction'], .05))
    return max(pressure) if pressure else None


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
            if provider == 'claude':
                pool = {'fable': 'Fable', 'sonnet': 'Sonnet', 'opus': 'Opus', 'haiku': 'Haiku'}.get(pool, pool)
            if provider == 'antigravity':
                pool = {'gemini': 'Gemini', '3p': 'Claude/GPT'}.get(pool, pool)
            if provider == 'cursor':
                pool = CURSOR_POOLS.get(w['pool'], pool)
            if not pool and w['pool'] != provider:
                pool = w['pool']
            label = LABELS[provider] + (' / ' + pool if pool else '')
            # All provider text is escaped before entering Markdown.
            label = label.replace('|', '\\|').replace('\n', ' ')
            status = row.get('status', 'unknown')
            observed = row.get('observed_at')
            if row.get('source') == 'operator-config':
                status, observed = 'manual (operator-set)', None
            if observed is not None:
                status += ' · %ds old' % max(0, now - observed)
            lines.append('| %s | %s | `%s` %.0f%% | %s | %s |' %
                (label, str(w['window']).replace('|', '\\|').replace('\n', ' '),
                 bar, n * 100, reset_text(w.get('resets_at'), now), status))
    lines += ['', 'Stale/unknown readings are excluded from quota calculations.']
    return '\n'.join(lines) + '\n'


def emit(core, args):
    if getattr(args, 'record_claude_statusline', False):
        return record_claude_statusline(core, sys.stdin)
    if getattr(args, 'record_claude_stream', False):
        return record_claude_stream(core, sys.stdin)
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
    summary = ('subscription meters for session context; no inference calls unless the opt-in '
               'usage.claude_probe is set, which makes one small Claude call per usage TTL')
    parser = sub.add_parser('usage', help=summary, description=summary)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--refresh', action='store_true', help='force bounded provider reads')
    group.add_argument('--cached', action='store_true', help='read cache only; no provider access')
    group.add_argument('--record-claude-statusline', action='store_true',
        help='opt-in Claude Code status-line command: read its JSON on stdin, record the Claude '
             'rate-limit snapshot for keychain-free quota, print a one-line meter (Alloy installs nothing)')
    group.add_argument('--record-claude-stream', action='store_true',
        help='read `claude -p --output-format stream-json --verbose` output on stdin and record its '
             'rate_limit_event as the same snapshot (no extra Claude call)')
    parser.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    parser.add_argument('--if-changed', action='store_true', help='emit only on first use, 5%% change, reset or status change')
    parser.add_argument('--session', help='stable session identifier for change suppression')
    parser.set_defaults(func=lambda args: emit(core, args))
