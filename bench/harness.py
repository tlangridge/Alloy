"""Alloy bench: the FIXED evaluator for Alloy's autoresearch loop.

This module is to Alloy what `prepare.py` is to Karpathy's autoresearch: task
loading, workspaces, grading, token pricing and scoring. The loop NEVER edits
it (or `tasks/`, `pricing.json`, `profiles.json`). The system under test is the
Alloy checkout that contains this directory (`bin/`, `data/`).

Live runs reuse production code paths so the measurement is of Alloy itself:
  * make    -- execution.maker_prompt/dispatch/gate/scope (the execute Maker loop
               without the Checker), graded by hidden tests;
  * review  -- execution.review_packet/checker_prompt/dispatch/review_json (the
               execute Checker), graded against a seeded-bug ground truth;
  * consult -- routing.routed_adapter + run_panelist (one read-only panelist),
               graded against an answer key;
  * execute -- execution.run() end to end (Maker + Checker + corrections).
Standard library only.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
TASKS = BENCH / 'tasks'
RESULTS = BENCH / 'results'
HIDDEN_DIR = '_hidden_tests'
TYPES = ('make', 'review', 'consult')
TIERS = ('small', 'medium', 'large')
GIT_ENV = dict(GIT_AUTHOR_NAME='bench', GIT_AUTHOR_EMAIL='bench@localhost',
               GIT_COMMITTER_NAME='bench', GIT_COMMITTER_EMAIL='bench@localhost',
               GIT_AUTHOR_DATE='2026-01-01T00:00:00Z', GIT_COMMITTER_DATE='2026-01-01T00:00:00Z')
_WRITE_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# tasks and workspaces
# --------------------------------------------------------------------------- #
def load_task(task_id):
    d = TASKS / task_id
    t = json.loads((d / 'task.json').read_text())
    t['dir'] = str(d)
    return t


def load_tasks(ids=None, types=None, split=None, tiers=None):
    out = []
    for d in sorted(TASKS.iterdir()) if TASKS.exists() else []:
        if not (d / 'task.json').exists():
            continue
        t = load_task(d.name)
        if ((ids and t['id'] not in ids) or (types and t['type'] not in types)
                or (split and t['split'] != split) or (tiers and t['tier'] not in tiers)):
            continue
        out.append(t)
    return out


def git(cwd, *args):
    env = dict(os.environ, **GIT_ENV)
    cp = subprocess.run(['git', '-C', str(cwd), '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', *args],
                        capture_output=True, text=True, env=env, timeout=60)
    if cp.returncode:
        raise RuntimeError('git %s failed: %s' % (' '.join(args), cp.stderr[-500:]))
    return cp.stdout.strip()


def overlay(src, dest):
    for path in sorted(Path(src).rglob('*')):
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        target = Path(dest) / path.relative_to(src)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def materialize(task, dest, overlays=()):
    """A fresh git repository holding repo/ (plus overlays), committed as base."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    overlay(Path(task['dir']) / 'repo', dest)
    for name in overlays:
        overlay(Path(task['dir']) / name, dest)
    (dest / '.gitignore').write_text('__pycache__/\n*.pyc\n' + HIDDEN_DIR + '/\n')
    git(dest, 'init', '-q', '-b', 'main')
    git(dest, 'add', '-A')
    git(dest, 'commit', '-qm', 'base')
    return git(dest, 'rev-parse', 'HEAD')


def commit_overlay(task, repo, name, message):
    overlay(Path(task['dir']) / name, repo)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', message)
    return git(repo, 'rev-parse', 'HEAD')


def run_cmd(cmd, cwd, timeout=120):
    started = time.monotonic()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ALLOY_', 'MOCK_'))}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        cp = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
                            timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        code, out = cp.returncode, cp.stdout + cp.stderr
    except subprocess.TimeoutExpired as exc:
        code, out = 124, ((exc.stdout or b'') if isinstance(exc.stdout, bytes) else (exc.stdout or '').encode()).decode(errors='replace') + '\nTIMEOUT'
    return code, out, round(time.monotonic() - started, 2)


_RAN = re.compile(r'^Ran (\d+) tests? in', re.M)
_FAILED = re.compile(r'^FAILED \(([^)]*)\)', re.M)
_SCORE = re.compile(r'BENCH_SCORE:\s*(\d+)\s*/\s*(\d+)')


def test_counts(text):
    """(passed, total) from a BENCH_SCORE line or unittest's summary."""
    m = _SCORE.findall(text)
    if m:
        a, b = m[-1]
        return int(a), int(b)
    ran = _RAN.findall(text)
    if not ran:
        return 0, 0
    total = int(ran[-1])
    bad = 0
    f = _FAILED.findall(text)
    if f:
        for part in f[-1].split(','):
            k, _, v = part.strip().partition('=')
            if k in ('failures', 'errors') and v.isdigit():
                bad += int(v)
    return max(0, total - bad), total


# --------------------------------------------------------------------------- #
# grading (deterministic; no model judges)
# --------------------------------------------------------------------------- #
def grade_make(task, worktree, timeout=120):
    wt = Path(worktree)
    hidden = wt / HIDDEN_DIR
    if hidden.exists():
        shutil.rmtree(hidden)
    overlay(Path(task['dir']) / 'hidden', hidden)
    code, out, secs = run_cmd(task['hidden_test'], wt, timeout)
    shutil.rmtree(hidden, ignore_errors=True)
    passed, total = test_counts(out)
    return dict(passed=code == 0, score=(passed / total) if total else float(code == 0),
                hidden_passed=passed, hidden_total=total, hidden_exit=code, hidden_s=secs,
                hidden_tail=out[-1500:])


_LOCATION = re.compile(r'(?:[:#]L?\d+(?:[-:]L?\d+)*|\s*\(line[^)]*\))$', re.I)


def finding_matches(finding, truth):
    # Reviewers often append a location: "pkg/x.py:84", "pkg/x.py#L84-L90", "x.py (line 84)".
    path = _LOCATION.sub('', str(finding.get('path', '')).strip().strip('`')).lstrip('./')
    want = truth['path'].lstrip('./')
    if not (path.endswith(want) or want.endswith(path) and path):
        return False
    text = (str(finding.get('evidence', '')) + ' ' + str(finding.get('fix', ''))).lower()
    return any(k.lower() in text for k in truth['keywords'])


def grade_review(task, verdict, error=None):
    """verdict: the production-validated Checker JSON, or None when it failed closed."""
    if verdict is None:
        return dict(passed=False, score=0.0, verdict=None, malformed=True, error=error)
    findings = verdict.get('findings', [])
    if task['bug']:
        hit = verdict['verdict'] == 'fail' and any(finding_matches(f, task['ground_truth']) for f in findings)
        return dict(passed=hit, score=float(hit), verdict=verdict['verdict'], findings=len(findings),
                    detected=hit, malformed=False)
    ok = verdict['verdict'] == 'pass'
    return dict(passed=ok, score=float(ok), verdict=verdict['verdict'], findings=len(findings),
                false_positive=not ok, malformed=False)


_ANSWER = re.compile(r'^\W*ANSWER\W*:\s*(.+?)\s*$', re.M | re.I)


_MARKUP = ' \t`*_"\''


def normalize(text):
    """Trim whitespace, markdown emphasis/code marks, quotes and a trailing period."""
    return re.sub(r'\s+', ' ', text.strip(_MARKUP).rstrip('.').strip(_MARKUP)).lower()


def grade_consult(task, text):
    found = _ANSWER.findall(text or '')
    if not found:
        return dict(passed=False, score=0.0, answer=None)
    got = found[-1]
    ok = False
    for want in task['answers']:
        if task['match'] == 'number':
            try:
                ok = abs(float(normalize(got).replace(',', '')) - float(want)) < 1e-9
            except ValueError:
                ok = False
        elif task['match'] == 'regex':
            ok = re.fullmatch(want, normalize(got), re.I) is not None
        else:
            ok = normalize(got) == normalize(want)
        if ok:
            break
    return dict(passed=ok, score=float(ok), answer=got[:200])


# --------------------------------------------------------------------------- #
# cost: provider-reported tokens x fixed list prices (pricing.json)
# --------------------------------------------------------------------------- #
def prices():
    return json.loads((BENCH / 'pricing.json').read_text())['models']


def api_usd(model, usage, table=None):
    """API-list-price equivalent of one dispatch. Anthropic cache writes use the
    1-hour rate (2x input) that Claude Code requests; others bill writes as input.
    Returns (computed_usd or None, priced_model_key)."""
    if not usage:
        return None, None
    table = table or prices()
    key = model if model in table else next((k for k, v in table.items() if model in v.get('aliases', [])), None)
    if key is None:
        return None, None
    p = table[key]
    write_rate = p.get('cache_write', p['input'])
    usd = (usage['input_tokens'] * p['input'] + usage['cache_read_tokens'] * p.get('cached_input', p['input'])
           + usage['cache_write_tokens'] * write_rate + usage['output_tokens'] * p['output']) / 1e6
    return round(usd, 6), key


def add_usage(a, b):
    if not b:
        return a
    a = dict(a or {})
    for k in ('input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens'):
        a[k] = a.get(k, 0) + (b.get(k) or 0)
    if b.get('reported_cost_usd') is not None:
        a['reported_cost_usd'] = round((a.get('reported_cost_usd') or 0) + b['reported_cost_usd'], 6)
    a['dispatches'] = a.get('dispatches', 0) + 1
    return a


def cost_of(model, usage):
    """Prefer the CLI's own list-price figure (it covers helper models); else compute."""
    computed, key = api_usd(model, usage)
    reported = (usage or {}).get('reported_cost_usd')
    return dict(api_usd=reported if reported is not None else computed, computed_usd=computed,
                reported_usd=reported, priced_as=key)


# --------------------------------------------------------------------------- #
# the system under test
# --------------------------------------------------------------------------- #
def configure(state):
    """Isolate every Alloy setting from the user's own config before import."""
    state = Path(state).resolve()
    for sub in ('routing', 'runs', 'work'):
        (state / sub).mkdir(parents=True, exist_ok=True)
    (state / 'config').write_text('# alloy-bench: no pins, no overrides\n')
    for k in list(os.environ):
        if k.startswith('ALLOY_') or k.startswith('MOCK_'):
            del os.environ[k]
    os.environ.update(ALLOY_CONFIG=str(state / 'config'), ALLOY_ROUTING_HOME=str(state / 'routing'),
                      ALLOY_RUN_ROOT=str(state / 'runs'), ALLOY_CAPTURE_USAGE='1',
                      ALLOY_NO_UPDATE_CHECK='1', ALLOY_REPO='')
    profiles = json.loads((BENCH / 'profiles.json').read_text())['profiles']
    defaults = json.loads((ROOT / 'data' / 'routing-defaults.json').read_text())
    config = dict(schema=1, jev_model=defaults.get('jev_model'), quota_pools={}, policy=defaults['policy'],
                  profiles=[dict(id=p['id'], adapter=p['cli'], model=p['model'], tier='small', family=p['family'],
                                 effort=p.get('effort'), cost_rank=1, enabled=True, billing_mode='subscription',
                                 quota_pool=p['cli'], evidence='alloy-bench measured profile') for p in profiles])
    (state / 'routing' / 'routing.json').write_text(json.dumps(config, indent=2))
    return state


def load_core():
    sys.path.insert(0, str(ROOT / 'bin'))
    loader = importlib.machinery.SourceFileLoader('alloy_bench_core', str(ROOT / 'bin' / 'alloy'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    core = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = core
    loader.exec_module(core)
    return core


def bench_profiles():
    return {p['id']: p for p in json.loads((BENCH / 'profiles.json').read_text())['profiles']}


def decide(core, profile_id, mode, kind='implementation', exclude=''):
    """The production resolver's decision for one explicit profile. The bench
    measures every profile on every task, so the tier gate is not applied."""
    r = core.routing
    config = r.load()
    answers = core.execution.host_assessment(argparse.Namespace(task_kind=kind, task_tier='small',
                                                                task_risk=False, task_ambiguous=False))
    args = argparse.Namespace(mode=mode, profile=profile_id, panelists=None, host_family='bench',
                              exclude_family=exclude, prior_failures=0, failed_profile=[], max_estimated_usd=None)
    d = r.resolve(core, config, answers, r.inventory(core), args, r.usage.get(core, config))
    d['answers'] = answers
    return d


def _record(task, profile, **extra):
    p = bench_profiles()[profile]
    return dict(task=task['id'], type=task['type'], tier=task['tier'], kind=task['kind'], split=task['split'],
                profile=profile, cli=p['cli'], model=p['model'], effort=p.get('effort'), family=p['family'], **extra)


def _dispatch_summary(result):
    return dict(status=result.get('status'), error=(result.get('error') or '')[:300] or None,
                duration_s=round(result.get('duration_ms', 0) / 1000, 1), usage=result.get('usage'),
                session_mode=result.get('session_mode'))


def _new_task(core, worktree, base, allow_paths, tests, timeout):
    tid = uuid.uuid4().hex[:16]
    return dict(schema=1, id=tid, worktree=str(worktree), base=base, host_family='bench',
                allow_paths=allow_paths, tests=tests, timeout=timeout, test_timeout=120,
                max_fix_rounds=2, max_estimated_usd=None, rounds=[], sessions={}, feedback='')


def run_make(core, task, profile, work, timeout=1200, max_rounds=3):
    """The execute Maker loop without a Checker: Maker -> gates -> fix rounds."""
    ex = core.execution
    wt = Path(work) / 'wt'
    base = materialize(task, wt)
    rec = _new_task(core, wt, base, task['allow_paths'], [task['visible_test']], timeout)
    rec['maker'] = decide(core, profile, 'make', task['kind'])
    spec = (Path(task['dir']) / 'spec.md').read_text()
    folder = ex.taskdir(core, rec['id'])
    usage, rounds, failure, gates_ok = None, [], None, False
    started = time.monotonic()
    for index in range(max_rounds):
        prompt = ex.maker_prompt(rec, spec, rec['feedback'])
        result = ex.dispatch(core, rec, 'maker', prompt, folder / ('round-%d' % index) / 'maker')
        usage = add_usage(usage, result.get('usage'))
        rounds.append(_dispatch_summary(result))
        if result.get('status') != 'ok':
            failure = 'maker_' + str(result.get('status'))
            break
        try:
            ex.scope(rec)
        except ex.ExecutionError as exc:
            failure = 'scope: ' + str(exc)[:200]
            break
        gates = [ex.gate(core, rec, cmd, folder / ('round-%d' % index) / ('gate-%d.log' % i))
                 for i, cmd in enumerate(rec['tests'])]
        rounds[-1]['gates'] = [g['exit_code'] for g in gates]
        if not any(g['exit_code'] for g in gates):
            gates_ok = True
            break
        rec['feedback'] = '\n'.join('GATE FAILURE ' + g['command'] + '\n' + Path(g['log']).read_text()[-12000:]
                                    for g in gates if g['exit_code'])
    grade = grade_make(task, wt)
    if failure:
        grade['passed'] = False
    return _record(task, profile, passed=grade['passed'], score=grade['score'], gates_ok=gates_ok,
                   failure=failure, rounds=len(rounds), dispatches=rounds, usage=usage,
                   wall_s=round(time.monotonic() - started, 1), grade=grade, **cost_of(rec['maker']['model'], usage))


def run_review(core, task, profile, work, timeout=900):
    ex = core.execution
    wt = Path(work) / 'wt'
    base = materialize(task, wt)
    tip = commit_overlay(task, wt, 'change', 'change under review')
    rec = _new_task(core, wt, base, ['.'], [task['visible_test']], timeout)
    rec['maker'] = dict(family='none', answers=None)
    rec['checker'] = decide(core, profile, 'review', 'review', exclude='bench,none')
    rec['maker']['answers'] = rec['checker']['answers']
    folder = ex.taskdir(core, rec['id'])
    folder.mkdir(parents=True, exist_ok=True)
    record = dict(index=0, gates=[ex.gate(core, rec, task['visible_test'], folder / 'gate-0.log')])
    diff = ex.git(wt, 'diff', '--binary', '--no-ext-diff', '--no-textconv', base, tip)
    packet, packet_id = ex.review_packet(core, rec, record, tip, diff, task['claimed_change'])
    started = time.monotonic()
    result = ex.dispatch(core, rec, 'checker', ex.checker_prompt(packet, packet_id, tip), folder / 'checker')
    tampered = git(wt, 'status', '--porcelain') != '' or git(wt, 'rev-parse', 'HEAD') != tip
    verdict, error = None, None
    if result.get('status') == 'ok':
        try:
            verdict = ex.review_json(Path(result['result_path']).read_text(), record['packet'])
        except ex.ExecutionError as exc:
            error = str(exc)
    else:
        error = 'checker_' + str(result.get('status'))
    grade = grade_review(task, verdict, error)
    if tampered:
        grade.update(passed=False, score=0.0, tampered=True)
    return _record(task, profile, passed=grade['passed'], score=grade['score'], failure=error,
                   rounds=1, dispatches=[_dispatch_summary(result)], usage=result.get('usage'),
                   wall_s=round(time.monotonic() - started, 1), grade=grade,
                   raw=(Path(result['result_path']).read_text()[:4000] if result.get('result_path') and Path(result['result_path']).exists() else None),
                   **cost_of(rec['checker']['model'], result.get('usage')))


CONSULT_SUFFIX = '\n\nEnd your reply with one final line: `ANSWER: <answer>`.'


def run_consult(core, task, profile, work, timeout=600):
    work = Path(work)
    repo = None
    if (Path(task['dir']) / 'repo').exists():
        repo = work / 'wt'
        materialize(task, repo)
    decision = decide(core, profile, 'consult', task['kind'])
    ad = core.routing.routed_adapter(core, decision)
    prompt_path = work / 'prompt.md'
    prompt_path.write_text(task['prompt'] + CONSULT_SUFFIX)
    started = time.monotonic()
    result = core.run_panelist(ad, str(prompt_path), str(work / 'panelist'), timeout, 200000, 'consult',
                               repo=str(repo) if repo else None)
    text = Path(result['result_path']).read_text() if result.get('status') == 'ok' else ''
    grade = grade_consult(task, text)
    return _record(task, profile, passed=grade['passed'], score=grade['score'],
                   failure=None if result.get('status') == 'ok' else 'panelist_' + str(result.get('status')),
                   rounds=1, dispatches=[_dispatch_summary(result)], usage=result.get('usage'),
                   wall_s=round(time.monotonic() - started, 1), grade=grade,
                   **cost_of(decision['model'], result.get('usage')))


RUNNERS = dict(make=run_make, review=run_review, consult=run_consult)


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
def sut_revision():
    try:
        sha = git(ROOT, 'rev-parse', '--short', 'HEAD')
        dirty = git(ROOT, 'status', '--porcelain', '--', 'bin', 'data') != ''
        return sha + ('+dirty' if dirty else '')
    except RuntimeError:
        return 'unknown'


def append(path, row):
    """Append one JSON line; safe across threads and concurrent runner processes."""
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK, path.open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(row, sort_keys=True) + '\n')
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


# Provider-side failures that say nothing about the model's ability; the runner
# records these as infra errors and a resumed matrix retries them.
INFRA = re.compile(r'no capacity|UNAVAILABLE|\b503\b|\b529\b|overloaded|rate.?limit|RESOURCE_EXHAUSTED|quota', re.I)


def infra_failure(row):
    return any(d.get('status') != 'ok' and INFRA.search(d.get('error') or '') for d in row.get('dispatches') or [])


def read_runs(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
