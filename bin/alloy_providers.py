"""Provider contracts and model identities shared by routing and dispatch.

These facts never grant permissions: each adapter still builds and validates its
own invocation, and managed execution still probes the actual boundary.
"""
import re


def failure_kind(reason):
    text = (reason or '').lower()
    if re.search(r'quota|rate.?limit|credit balance|usage limit|resource_exhausted', text):
        return 'quota'
    if re.search(r'unknown model|model[^\n]*(?:not found|not available|unavailable|does not exist)', text):
        return 'model_unavailable'
    if 'permission' in text and ('denied' in text or 'auto-denied' in text):
        return 'permission_denied'
    return 'provider_error'

ALIASES = {'cursor-agent': 'cursor'}
FAMILIES = {'codex': 'openai', 'claude': 'anthropic', 'grok': 'xai',
            'antigravity': 'google', 'cursor': 'cursor', 'muse': 'meta'}
CURSOR_EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
CONTRACTS = {
    'codex': dict(probe=('--sandbox', '--model'), effort='codex', writer=True),
    'claude': dict(probe=('--permission-mode', '--model', '--output-format', '--tools'),
                   effort='--effort', writer=True, native_session=True),
    'grok': dict(probe=('--permission-mode', '--model', '--prompt-file'),
                 effort='--effort', writer=True, native_session=True),
    'antigravity': dict(probe=('--model', '--mode', '--print', '--add-dir'),
                       effort='--effort', writer=True),
    'cursor': dict(probe=('--print', '--output-format', '--mode', '--model', '--list-models'),
                   effort='model', writer=True),
    'muse': dict(probe=('--model', '--reasoning-effort', '--prompt-file', '--disable-write', '--disable-shell'),
                 effort='--reasoning-effort', writer=False),
}
WRITE_PROBE_FLAGS = {
    'codex': ('workspace-write',),
    'claude': ('acceptEdits', '--allowedTools', '--disallowedTools', '--tools'),
    'grok': ('acceptEdits', '--allow', '--tools'),
    'antigravity': ('accept-edits', '--sandbox'),
}
AGY_EFFORTS = {
    'gemini-4-carbon': ('low', 'medium', 'high'),
    'gemini-4-argon': ('low', 'medium', 'high'),
    'gemini-4-hydrogen': ('low', 'medium', 'high', 'xhigh'),
}
AGY_WORKFLOWS = ('gemini-pro-orchestrator', 'gemini-pro-orchestrator-argon')


def normalize(name):
    name = (name or '').strip()
    return ALIASES.get(name, name)


def cursor_split(model):
    match = re.fullmatch(r'([^\[\]]*)(?:\[([^\[\]]*)\])?', model or '')
    if not match:
        return None
    fields = {}
    for part in match.group(2).split(',') if match.group(2) else ():
        key, sep, value = part.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not key or not value or key in fields:
            return None
        fields[key] = value
    return match.group(1).strip(), fields


def cursor_family(model):
    parts = cursor_split(model) if isinstance(model, str) else None
    if parts is None:
        return None
    base = parts[0]
    if base.endswith('-fast'):
        base = base[:-5]
    if not base or base == 'auto' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', base):
        return None
    for prefixes, family in ((('claude-',), 'anthropic'), (('gpt-', 'codex-'), 'openai'),
                             (('gemini-',), 'google'), (('grok-', 'cursor-grok-'), 'xai'),
                             (('composer-',), 'cursor')):
        if base.startswith(prefixes):
            return family
    return 'openai' if base == 'codex' else None


def agy_model_problem(model, effort):
    if not isinstance(model, str) or not model:
        return 'model identity must be a nonempty string'
    if model in AGY_WORKFLOWS:
        return 'Orchestrator has a fixed mixed-model configuration; effort must be unset' if effort is not None else None
    if not model.startswith('gemini-'):
        return None
    suffix = model.rsplit('-', 1)[-1]
    if suffix in ('low', 'medium', 'high', 'xhigh') and effort is not None and effort != suffix:
        return 'Gemini model suffix conflicts with effort'
    for base, levels in AGY_EFFORTS.items():
        if model == base or model in tuple(base + '-' + level for level in CURSOR_EFFORTS):
            if effort is not None and effort not in levels:
                return base + ' supports ' + ', '.join(levels) + ' effort'
            if model != base and suffix not in levels:
                return 'Unsupported effort suffix for ' + base
    return None


def effort_args(name, effort):
    if not effort:
        return []
    style = CONTRACTS.get(name, {}).get('effort')
    if style == 'codex':
        return ['-c', 'model_reasoning_effort=' + effort]
    if style and style != 'model':
        return [style, effort]
    raise ValueError('No effort mapping for adapter ' + str(name))
