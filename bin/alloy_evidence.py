"""Offline, dated model evidence. Preferences are priors, never permissions."""
import hashlib
import json
from pathlib import Path
import time
from datetime import datetime, timezone

PATH = Path(__file__).resolve().parent.parent / 'data/model-evidence.json'
KINDS = ('implementation', 'debugging', 'review', 'research', 'architecture',
         'frontend', 'testing', 'documentation', 'other')


def catalog():
    try:
        raw = PATH.read_bytes()
        data = json.loads(raw)
        expires = datetime.strptime(data['expires_at'], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()
        reviewed = datetime.strptime(data['reviewed_at'], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()
        valid = data.get('schema') == 1 and reviewed <= time.time() < expires
        return dict(data, status='current' if valid else 'stale',
                    sha256=hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, KeyError, TypeError):
        return dict(status='unavailable', models=[], revision=None, sha256=None)


def adapters(row):
    """The adapters whose harness/provider a row's evidence covers; a row that does not
    declare a list of adapter names covers none, so it can never be borrowed."""
    value = row.get('adapters')
    return [a for a in value if isinstance(a, str)] if isinstance(value, list) else []


def match(profile, data):
    """The row covering this profile's exact identity, or None. Identity is the canonical
    adapter, the exact normalized model ID, the family and the fast state (a row must state
    all of them); effort is judged afterwards by assessment(). Evidence for a model on one
    provider is never borrowed by the same model text on another adapter."""
    if data['status'] != 'current':
        return None
    adapter = profile.get('adapter')
    fast = bool(profile.get('fast', False))
    return next((row for row in data['models']
                 if isinstance(adapter, str) and adapter in adapters(row)
                 and type(row.get('fast')) is bool and row['fast'] == fast
                 and profile['model'] in row['models']
                 and profile.get('family') == row['family']), None)


def assessment(profile, data):
    row = match(profile, data)
    if 'task_preferences' in profile:
        return dict(status='user-configured', preferred_tasks=profile['task_preferences'], sources=[])
    if row is None:
        return dict(status=data['status'] if data['status'] != 'current' else 'unmatched',
                    preferred_tasks=[], sources=[])
    effort = profile.get('effort')
    # API benchmark evidence cannot certify arbitrary reasoning-effort overrides.
    supported = effort in row['applicable_efforts']
    return dict(status='matched' if supported else 'effort-unverified',
        preferred_tasks=row['preferred_tasks'] if supported else [],
        strengths=row['strengths'], limitations=row['limitations'], sources=row['sources'],
        basis=row['basis'], suggested_tier=row['suggested_tier'],
        api_pricing=row.get('api_pricing'), effort_guidance=row.get('effort_guidance'))


def advise(core, config, data, cache):
    routing = core.routing
    profiles = []
    for profile in config['profiles']:
        name = routing.normalize_adapter(profile['adapter'])
        pin = routing.setting_for(core, name, 'model')
        try:
            # The same identity routing uses: configured effort plus any effort pin, and for
            # a Cursor profile its derived family and effective effort/fast state.
            p = routing.effective_profile(core, profile, None)
            assessed = assessment(routing.evidence_view(p), data)
        except routing.RoutingError as exc:
            assessed = dict(status='unroutable', preferred_tasks=[], sources=[], reason=str(exc))
        profiles.append(dict(profile=profile['id'], model=profile['model'], evidence=assessed,
            model_pin=pin or None, blocked_by_pin=bool(pin and pin != profile['model']),
            billing_mode=profile['billing_mode'], configured_tier=profile['tier']))
    # A model counts as configured or discovered only on an adapter its evidence covers.
    configured = {(routing.normalize_adapter(p['adapter']), p['model']) for p in config['profiles']}
    discovered = {(name, model) for name, entry in cache.get('discovered', {}).items()
                  for model in entry.get('models', [])}
    covered = lambda row, pairs: any((a, m) in pairs for a in adapters(row) for m in row['models'])
    return dict(evidence_revision=data.get('revision'), evidence_status=data['status'],
        profiles=profiles, candidates=[dict(row, discovered=covered(row, discovered))
            for row in data['models'] if not covered(row, configured)],
        note='Read-only advice. Exact model IDs and effort matter; candidate availability must be verified. Prices and subscription cost ranks are not interchangeable. No pins, billing or profiles changed.')
