"""Quality policy: ordinal task priors, never invented success probabilities."""
import copy
import time

CAPABILITIES = ('repo_read', 'managed_write', 'run_tests', 'web', 'image_input',
                'image_generation', 'browser', 'session_resume')
BANDS = ('unknown', 'bounded', 'capable', 'specialist')


def objective(config):
    # Old installations retain their policy until an explicit migration.
    return config.get('policy', {}).get('objective', 'cost_first')


def role_tier(profile, mode, assessment):
    declared = profile.get('tier_by_mode', {}).get(mode, profile['tier'])
    if mode == 'review':
        # A six-case proxy cannot erase a documented difficult-work limitation.
        tiers = ('small', 'medium', 'large')
        floor = assessment.get('suggested_tier', profile['tier'])
        return tiers[min(tiers.index(declared), tiers.index(profile['tier']), tiers.index(floor))]
    return declared


def requirements(args, kind, mode):
    required = set(getattr(args, 'require_capability', None) or [])
    if mode == 'review':
        if 'image_generation' in required:
            required.remove('image_generation')
            required.add('image_input')
        if getattr(args, 'artifact', None):
            required.add('image_input')
    if kind == 'image_generation':
        required.add('image_input' if mode == 'review' else 'image_generation')
    if kind == 'image_understanding':
        required.add('image_input')
    if mode == 'make':
        required.update(('managed_write', 'run_tests'))
    return sorted(required)


def capabilities(core, profile, available, mode='consult'):
    """Known adapter contracts plus explicit, dated operator attestations.

    A model card's input modalities never certify a tool in a CLI harness.
    These records cannot grant permissions; execution still probes its boundary.
    """
    name = profile['adapter']
    ready = available.get(name, {}).get('compatible') is True
    ad = core.ADAPTERS.get(name)
    result = {key: 'unverified' for key in CAPABILITIES}
    if ready and ad is not None:
        result['repo_read'] = 'verified' if ad.read_only else 'unverified'
        if mode == 'make' and name in core.execution.MANAGED_WRITERS:
            result.update(managed_write='verified', run_tests='verified')
        if available.get(name, {}).get('image_flag') == '--image':
            assessed = core.routing.evidence.assessment(core.routing.evidence_view(profile), core.routing.evidence.catalog())
            if 'image' in assessed.get('input_modalities', []):
                result['image_input'] = 'verified'
    for key, record in profile.get('capabilities', {}).items():
        if key in ('managed_write', 'run_tests', 'image_generation') and mode != 'make':
            continue
        if key in ('managed_write', 'run_tests') and name not in core.execution.MANAGED_WRITERS:
            continue
        if isinstance(record, dict) and record.get('status') == 'verified':
            # Require the identity the attestation actually covered. A changed
            # CLI version or effort invalidates it instead of borrowing evidence.
            identity = record.get('identity', {})
            if (identity.get('model') == profile['model']
                    and identity.get('effort') == profile.get('effort')
                    and identity.get('cli_version') == available.get(name, {}).get('version')
                    and isinstance(record.get('observed_at'), (int, float))
                    and isinstance(record.get('expires_at'), (int, float))
                    and record['observed_at'] <= time.time() < record['expires_at']):
                result[key] = 'verified'
        elif record in ('unavailable', 'unverified'):
            result[key] = record
    return result


def grade(profile, assessment, kind, fit, enabled=True):
    """An editorial suitability band, not a prediction of downstream correctness."""
    supported = enabled and assessment.get('status') in ('matched', 'user-configured')
    preferred = kind in assessment.get('preferred_tasks', []) if supported else False
    band = 'capable' if supported else 'unknown'
    declared = assessment.get('task_bands', {}).get(kind) if supported else None
    if declared in BANDS:
        band = declared
    elif preferred:
        band = 'specialist'
    if supported and fit is not None:
        # Noul measures a suitability condition, not a task-success rate. Use it
        # as a narrow categorical adjustment; retain the raw judgment in output.
        if fit <= .25:
            band = 'bounded'
        elif fit >= .75 and preferred:
            band = 'specialist'
    return dict(band=band, rank=BANDS.index(band), preferred=preferred,
                basis=assessment.get('basis', 'unmeasured exact identity'),
                measured_success_rate=None)


def ordering(decision):
    """Quality first. Capacity and spend only compare equally suitable choices."""
    return (-decision['quality']['rank'], decision['selection_cost'], decision['profile'])


def pair_order(maker, checker):
    # Each role matters: the weaker qualification is the first comparison.
    mq, cq = maker['quality']['rank'], checker['quality']['rank']
    comparable = maker['cost_basis'] == checker['cost_basis'] == 'estimated_usd'
    cost = (maker['selection_cost'] + checker['selection_cost'] if comparable else
            maker['effective_cost_rank'] + checker['effective_cost_rank'])
    return (-min(mq, cq), -mq, -cq, cost,
            maker['profile'], checker['profile'])


def migrate(config):
    result = copy.deepcopy(config)
    result.setdefault('policy', {})['objective'] = 'quality_first'
    return result
