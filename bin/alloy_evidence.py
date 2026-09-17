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


def match(profile, data):
    if data['status'] != 'current':
        return None
    return next((row for row in data['models'] if profile['model'] in row['models']
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
        basis=row['basis'], suggested_tier=row['suggested_tier'])


def advise(core, config, data, cache):
    profiles = []
    for profile in config['profiles']:
        p = dict(profile)
        name = p['adapter']
        p['family'] = core.routing.family(p)
        override = core.setting(core.routing.EFFORT_KEYS[name])
        if override:
            p['effort'] = None if override in ('inherit', 'default') else override
        pin = core.setting(core.routing.MODEL_KEYS[name])
        profiles.append(dict(profile=p['id'], model=p['model'], evidence=assessment(p, data),
            model_pin=pin or None, blocked_by_pin=bool(pin and pin != p['model']),
            billing_mode=p['billing_mode'], configured_tier=p['tier']))
    configured = {p['model'] for p in config['profiles']}
    discovered = {model for entry in cache.get('discovered', {}).values() for model in entry.get('models', [])}
    return dict(evidence_revision=data.get('revision'), evidence_status=data['status'],
        profiles=profiles, candidates=[dict(row, discovered=bool(set(row['models']) & discovered))
            for row in data['models'] if not set(row['models']) & configured],
        note='Read-only advice. Exact model IDs and effort matter; candidate availability must be verified. Prices and subscription cost ranks are not interchangeable. No pins, billing or profiles changed.')
