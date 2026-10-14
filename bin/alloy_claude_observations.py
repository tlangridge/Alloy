"""Bounded, profile-bound Claude quota observations. No provider or credential reads."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

try:
    import fcntl
except ImportError:  # Writers are supported on Unix, including WSL.
    fcntl = None

SCHEMA = 2
MAX_BYTES = 65536
MAX_PRODUCERS = 128
MAX_FRONTIER = 16
BASES = ('response-counter', 'dispatch-start-bound', 'probe-start-bound', 'oauth-fetch')


def number(value, low=0, high=1e15):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def profile_dir(core):
    configured = core.setting('CLAUDE_CONFIG_DIR') or str(Path.home() / '.claude')
    return core.routing.root() / 'claude-observations' / digest(str(Path(configured).expanduser().resolve()))


def context(core, binding):
    return dict(profile=profile_dir(core).name, binding=binding)


def epoch_path(core):
    return profile_dir(core) / 'epoch.json'


def path(core, ctx):
    return profile_dir(core) / (ctx['binding'] + '.json')


def read(location):
    fd = os.open(str(location), os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Not a regular observation')
        raw = stream.read(MAX_BYTES + 1)
    if not stat.S_ISREG(info.st_mode) or len(raw) > MAX_BYTES:
        raise ValueError('Not a bounded regular observation')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Invalid observation')
    return data, info.st_mtime


@contextmanager
def locked(location):
    if fcntl is None:
        raise OSError('Observation writer requires a file lock')
    location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(location) + '.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        deadline = time.monotonic() + .25
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OSError('Observation writer busy')
                time.sleep(.01)
        yield
    finally:
        os.close(fd)


def classify(window, now, ttl):
    result = {k: window.get(k) for k in ('pool', 'window', 'remaining_fraction', 'resets_at',
              'source', 'observed_at', 'received_at', 'freshness_basis',
              'coverage_incomplete', 'coverage_until')}
    if not number(result['observed_at']):
        result['observed_at'] = None
    if not number(result['received_at']):
        result['received_at'] = 0
    observed = result.get('observed_at')
    verified = result.get('freshness_basis') in BASES and number(observed, 0, now)
    reset = result.get('resets_at')
    result['status'] = ('unverified' if not verified else
                        'stale' if now - observed >= ttl or reset is not None and reset <= now else 'fresh')
    return result


def usable(window):
    return (isinstance(window, dict) and isinstance(window.get('pool'), str)
            and (window['pool'] == 'claude' or window['pool'].startswith('claude:'))
            and window.get('window') in ('5h', '7d') and number(window.get('remaining_fraction'), 0, 1)
            and (window.get('resets_at') is None or number(window['resets_at'])))


def select(windows, now, ttl):
    groups = {}
    for window in _retain([], windows):
        candidate = classify(window, now, ttl)
        groups.setdefault((candidate['pool'], candidate['window']), []).append(candidate)
    selected = []
    for candidates in groups.values():
        fresh = [w for w in candidates if w['status'] == 'fresh']
        # Overlapping response intervals cannot establish which reading is later.
        # Respect the tightest fresh constraint, including ambiguous reset periods.
        if fresh:
            chosen = min(fresh, key=lambda w: (w['remaining_fraction'],
                         w.get('source') != 'claude-oauth', -(w.get('observed_at') or 0)))
        else:
            chosen = max(candidates, key=lambda w: (w['status'] != 'unverified',
                         w.get('observed_at') or 0, w.get('received_at') or 0,
                         w.get('source') == 'claude-oauth'))
        chosen = dict(chosen)
        if any(w.get('coverage_incomplete') for w in candidates):
            chosen['coverage_incomplete'] = True
            chosen['coverage_until'] = max(_upper(w) for w in candidates)
        selected.append(chosen)
    return sorted(selected, key=lambda w: (w['pool'], w['window']))


def observed(windows, source, at, basis, received=None):
    return [dict(w, source=source, observed_at=at, received_at=received if received is not None else time.time(),
                 freshness_basis=basis) for w in windows]


def _previous(location, ctx):
    try:
        data, _ = read(location)
        if (data.get('schema') == SCHEMA and data.get('context') == ctx
                and isinstance(data.get('windows', []), list) and isinstance(data.get('producers', {}), dict)):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _upper(window):
    return max(v for v in (window.get('observed_at'), window.get('received_at'),
                          window.get('coverage_until')) if number(v))


def _retain(windows, incoming):
    # Keep the nondominated interval frontier, not a pairwise winner: overlap
    # preference is not transitive. A lower bound must pass an upper bound to
    # establish that another response has superseded it.
    groups = {}
    for window in windows + incoming:
        if not usable(window):
            continue
        window = classify(window, time.time(), 120)
        window.pop('status', None)
        verified = window.get('freshness_basis') in BASES and number(window.get('observed_at'), 0, time.time())
        groups.setdefault((window['pool'], window['window'], verified), []).append(window)
    retained = []
    for (_pool, _window, verified), candidates in sorted(groups.items()):
        if not verified:
            retained.append(max(candidates, key=lambda w: w.get('received_at') or 0))
            continue
        lower = max(w['observed_at'] for w in candidates)
        frontier = [w for w in candidates if _upper(w) >= lower]
        # Identical normalized observations are replay-safe, without widening the
        # original receipt bound when a cache is merged into the store again.
        unique = {json.dumps(w, sort_keys=True): w for w in frontier}
        frontier = list(unique.values())
        if len(frontier) > MAX_FRONTIER:
            chosen = dict(min(frontier, key=lambda w: (w['remaining_fraction'],
                          w.get('source') != 'claude-oauth', -w['observed_at'])))
            chosen.update(coverage_incomplete=True, coverage_until=max(_upper(w) for w in frontier))
            frontier = [chosen]
        retained.extend(frontier)
    return retained


def candidates(windows):
    """Retain normalized evidence for subsequent merges, independent of display."""
    return _retain([], windows)


def _prune(location):
    # Credential refreshes start a new baseline. Keep recent generations and all
    # potentially fresh data; never unlink lock files used by concurrent writers.
    try:
        entries = []
        for item in location.parent.iterdir():
            if item.suffix != '.json' or len(item.stem) != 64 or any(c not in '0123456789abcdef' for c in item.stem):
                continue
            info = item.lstat()
            if stat.S_ISREG(info.st_mode):
                entries.append((info.st_mtime, item))
        entries.sort(key=lambda pair: pair[0], reverse=True)
        for modified, item in entries[4:]:
            if item != location and modified < time.time() - 3600:
                item.unlink()
    except OSError:
        pass


def _save(core, location, data):
    if len(json.dumps(data).encode()) > MAX_BYTES:
        raise ValueError('Observation storage limit exceeded')
    core.routing.save(location, data)
    _prune(location)


def record_statusline(core, ctx, payload, windows, current_context):
    now = time.time()
    ident = payload.get('session_id')
    identified = isinstance(ident, str) and bool(ident) and len(ident) <= 1024
    producer = digest(ident) if identified else 'unidentified'
    cache = payload.get('prompt_cache')
    counter = cache.get('requests') if isinstance(cache, dict) else None
    if type(counter) is not int or not number(counter):
        counter = None
    cost = payload.get('cost')
    startup_zero = isinstance(cost, dict) and type(cost.get('total_api_duration_ms')) in (int, float) and cost['total_api_duration_ms'] == 0
    location = path(core, ctx)
    with locked(location):
        if current_context() != ctx:
            return []
        data = _previous(location, ctx)
        producers = data.get('producers', {})
        previous = producers.get(producer, {})
        if not isinstance(previous, dict):
            previous = {}
        last, anchor = previous.get('counter'), previous.get('counter_anchor_at')
        progressed = (identified and counter is not None and type(last) is int and counter > last
                      and number(anchor, 0, now))
        # Only a valid unchanged/increased counter can establish a response bound.
        incoming = observed(windows, 'claude-statusline', anchor if progressed else None,
                            'response-counter' if progressed else 'unverified', now)
        if counter is None and startup_zero and not previous:
            counter = 0
        high_water = max(last, counter) if type(last) is int and counter is not None else last if counter is None else counter
        producers[producer] = dict(counter=high_water if identified else None, received_at=now,
                                  counter_anchor_at=now if counter is not None and (type(last) is not int or counter >= last) else anchor,
                                  counter_reset=counter is not None and type(last) is int and counter < last)
        producers = {k: v for k, v in producers.items() if isinstance(v, dict) and number(v.get('received_at'))}
        producers = dict(sorted(producers.items(), key=lambda p: p[1]['received_at'], reverse=True)[:MAX_PRODUCERS])
        data = dict(schema=SCHEMA, context=ctx, producers=producers,
                    windows=_retain(data.get('windows', []), incoming))
        _save(core, location, data)
        return select(data['windows'], now, 120)


def record_windows(core, ctx, windows, bound, current_context, source='claude-stream'):
    now = time.time()
    trusted = number(bound, 0, now)
    incoming = observed(windows, source, bound if trusted else None,
                        'oauth-fetch' if trusted and source == 'claude-oauth' else
                        'probe-start-bound' if trusted and source == 'claude-cli-probe' else
                        'dispatch-start-bound' if trusted else 'unverified', now)
    location = path(core, ctx)
    with locked(location):
        if current_context() != ctx:
            return []
        data = _previous(location, ctx)
        data.update(schema=SCHEMA, context=ctx, windows=_retain(data.get('windows', []), incoming))
        _save(core, location, data)
        return incoming


def local(core, ctx, now, ttl):
    try:
        data, modified = read(path(core, ctx))
        if data.get('schema') != SCHEMA or data.get('context') != ctx:
            return [], ['native_profile_changed']
        windows = []
        for item in data.get('windows', []):
            if not usable(item):
                continue
            item = dict(item)
            if number(item.get('observed_at')):
                item['observed_at'] = min(item['observed_at'], modified)
            windows.append(item)
        result = [classify(w, now, ttl) for w in candidates(windows)]
        notes = ['waiting_for_native_response'] if not result or any(w['status'] == 'unverified' for w in result) else []
        if any(w.get('coverage_incomplete') for w in result):
            notes.append('native_observation_overflow')
        if any(p.get('counter_reset') for p in data.get('producers', {}).values()):
            notes.append('native_counter_reset')
        return result, notes
    except FileNotFoundError:
        return [], ['waiting_for_native_response']
    except (OSError, ValueError, TypeError, AttributeError):
        return [], ['native_observation_invalid']
