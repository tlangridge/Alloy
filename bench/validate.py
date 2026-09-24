#!/usr/bin/env python3
"""Validate bench tasks offline (no model calls): structure, fairness preconditions,
reference solutions and determinism. Usage: python3 bench/validate.py [task-id ...]"""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402

COMMON = ('id', 'type', 'tier', 'kind', 'split', 'title')
KINDS = ('implementation', 'debugging', 'testing', 'refactoring', 'review', 'research', 'architecture')
LIMIT_S = 30


def check_make(t, errors):
    d = Path(t['dir'])
    for k in ('allow_paths', 'visible_test', 'hidden_test', 'hidden_checks'):
        if not t.get(k):
            errors.append('missing ' + k)
    for sub in ('repo', 'hidden', 'solution'):
        if not (d / sub).is_dir():
            errors.append('missing %s/' % sub)
    if not (d / 'spec.md').is_file():
        errors.append('missing spec.md')
    if errors:
        return
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / 'initial'
        h.materialize(t, wt)
        g = h.grade_make(t, wt, LIMIT_S)
        if g['passed']:
            errors.append('initial repo already passes hidden tests')
        for i in range(3):
            wt = Path(tmp) / ('ref%d' % i)
            h.materialize(t, wt, overlays=('solution',))
            code, out, secs = h.run_cmd(t['visible_test'], wt, LIMIT_S)
            if code:
                errors.append('reference fails visible_test (run %d): %s' % (i, out[-600:]))
                break
            g = h.grade_make(t, wt, LIMIT_S)
            if not g['passed']:
                errors.append('reference fails hidden_test (run %d): %s' % (i, g['hidden_tail'][-600:]))
                break
            if secs > LIMIT_S or g['hidden_s'] > LIMIT_S:
                errors.append('tests too slow')
            if g['hidden_total'] == 0:
                errors.append('hidden test count not parseable (unittest summary or BENCH_SCORE)')
                break


def check_review(t, errors):
    d = Path(t['dir'])
    for k in ('claimed_change', 'visible_test'):
        if not t.get(k):
            errors.append('missing ' + k)
    if not isinstance(t.get('bug'), bool):
        errors.append('bug must be true/false')
    for sub in ('repo', 'change'):
        if not (d / sub).is_dir():
            errors.append('missing %s/' % sub)
    if t.get('bug'):
        gt = t.get('ground_truth') or {}
        if not gt.get('path') or not gt.get('keywords') or not gt.get('description'):
            errors.append('bug task needs ground_truth.path/keywords/description')
        if not (d / 'hidden').is_dir():
            errors.append('bug task needs hidden/ demonstrating the bug')
    if errors:
        return
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / 'rev'
        h.materialize(t, wt)
        h.commit_overlay(t, wt, 'change', 'change')
        if not (Path(wt) / t['ground_truth']['path']).exists() if t.get('bug') else False:
            errors.append('ground_truth.path does not exist in the reviewed revision')
        code, out, _ = h.run_cmd(t['visible_test'], wt, LIMIT_S)
        if code:
            errors.append('visible tests fail on reviewed revision: ' + out[-600:])
        if t.get('bug'):
            probe = dict(t, hidden_test=t.get('hidden_test', 'python3 -m unittest discover -s %s -v' % h.HIDDEN_DIR))
            g = h.grade_make(probe, wt, LIMIT_S)
            if g['passed']:
                errors.append('hidden bug demonstration passes on the reviewed revision')
            if (Path(t['dir']) / 'fixed').is_dir():
                wt2 = Path(tmp) / 'fixed'
                h.materialize(t, wt2)
                h.commit_overlay(t, wt2, 'change', 'change')
                h.commit_overlay(t, wt2, 'fixed', 'fix')
                if not h.grade_make(probe, wt2, LIMIT_S)['passed']:
                    errors.append('fixed/ overlay does not pass the hidden bug demonstration')


def check_consult(t, errors):
    if not t.get('prompt') or not t.get('answers'):
        errors.append('missing prompt/answers')
    if t.get('match') not in ('exact', 'number', 'regex'):
        errors.append('match must be exact|number|regex')
    if errors:
        return
    if t.get('verify'):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / 'repo'
            if (Path(t['dir']) / 'repo').exists():
                h.materialize(t, wt)
            else:
                wt.mkdir()
            code, out, _ = h.run_cmd(t['verify'], wt, LIMIT_S)
            lines = [ln for ln in out.strip().splitlines() if ln.strip()]
            got = h.grade_consult(t, 'ANSWER: ' + (lines[-1] if lines else ''))
            if code or not got['passed']:
                errors.append('verify command does not reproduce the answer: %r' % (lines[-1:] if lines else out[-300:]))


def validate(t):
    errors = [('missing ' + k) for k in COMMON if not t.get(k)]
    if t.get('type') not in h.TYPES:
        errors.append('bad type')
    if t.get('tier') not in h.TIERS:
        errors.append('bad tier')
    if t.get('kind') not in KINDS:
        errors.append('bad kind')
    if t.get('split') not in ('dev', 'holdout'):
        errors.append('bad split')
    if t.get('id') != Path(t['dir']).name:
        errors.append('id does not match directory')
    if not errors:
        dict(make=check_make, review=check_review, consult=check_consult)[t['type']](t, errors)
    return errors


def main():
    ids = sys.argv[1:]
    tasks = h.load_tasks(ids=ids or None)
    if ids and len(tasks) != len(set(ids)):
        print('unknown task id(s):', sorted(set(ids) - {t['id'] for t in tasks}))
        return 2
    bad = 0
    for t in tasks:
        errors = validate(t)
        bad += bool(errors)
        print(('FAIL ' if errors else 'ok   ') + t['id'] + ('' if not errors else '\n  - ' + '\n  - '.join(errors)))
    counts = {}
    for t in tasks:
        counts[(t['type'], t['split'])] = counts.get((t['type'], t['split']), 0) + 1
    print('\n%d task(s), %d invalid; ' % (len(tasks), bad) + ', '.join('%s/%s=%d' % (a, b, n) for (a, b), n in sorted(counts.items())))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
