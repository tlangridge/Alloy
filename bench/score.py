#!/usr/bin/env python3
"""Score alloy-bench results. Offline: no model calls.

  python3 bench/score.py profiles --tags baseline            # per-profile quality/cost
  python3 bench/score.py frontier --tags baseline            # cost/quality Pareto per type+tier
  python3 bench/score.py replay --tags baseline [--config data/routing-defaults.json]
                                                             # route every task with PRODUCTION
                                                             # resolve() and score the choices

THE METRIC (see program.md): a configuration's routed quality Q (mean solve
probability) must stay within one task of the quality reference -- the best
single measured profile per task type -- and among configurations that pass
that gate, lower cost per solved task (CPS, API-list-price USD) is better.
"""
import argparse
import argparse as _ap
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402

RUNS = h.RESULTS / 'runs.jsonl'
MODEL_ALIASES = {'sonnet': 'claude-sonnet-5', 'opus': 'claude-opus-5-5'}


def cells(tags, split=None):
    """(task, profile) -> list of finished runs (harness errors and skips excluded)."""
    out = {}
    for r in h.read_runs(RUNS):
        if r.get('tag') not in tags or r.get('outcome') != 'done':
            continue
        if split and r.get('split') != split:
            continue
        out.setdefault((r['task'], r['profile']), []).append(r)
    return out


def stat(rows):
    n = len(rows)
    cost = [r['api_usd'] for r in rows if r.get('api_usd') is not None]
    return dict(n=n, q=sum(bool(r['passed']) for r in rows) / n if n else None,
                usd=sum(cost) / n if n and len(cost) == n else None,
                wall=sum(r.get('wall_s') or 0 for r in rows) / n if n else None,
                score=sum(r.get('score') or 0 for r in rows) / n if n else None)


def fmt(x, spec='%.3f'):
    return '-' if x is None else spec % x


def table(rows, headers):
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    line = lambda r: '  '.join(str(v).ljust(w) for v, w in zip(r, widths))
    return '\n'.join([line(headers), line(['-' * w for w in widths])] + [line(r) for r in rows])


def cmd_profiles(args):
    data = cells(args.tags, args.split)
    tasks = {t['id']: t for t in h.load_tasks()}
    groups = {}
    for (task, profile), rows in data.items():
        t = tasks.get(task)
        if not t:
            continue
        for key in ((profile, t['type'], 'all'), (profile, t['type'], t['tier'])):
            groups.setdefault(key, []).extend(rows)
    out = []
    for (profile, typ, tier), rows in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][2] != 'all', kv[0][2], kv[0][0])):
        s = stat(rows)
        cps = s['usd'] / s['q'] if s['q'] and s['usd'] is not None else None
        out.append([typ, tier, profile, s['n'], fmt(s['q'], '%.2f'), fmt(s['score'], '%.2f'),
                    fmt(s['usd'], '$%.4f'), fmt(cps, '$%.4f'), fmt(s['wall'], '%.0fs')])
    print(table(out, ['type', 'tier', 'profile', 'n', 'solve', 'partial', 'usd/task', 'usd/solve', 'wall']))


def cmd_frontier(args):
    data = cells(args.tags, args.split)
    tasks = {t['id']: t for t in h.load_tasks()}
    groups = {}
    for (task, profile), rows in data.items():
        t = tasks.get(task)
        if t:
            groups.setdefault((t['type'], t['tier']), {}).setdefault(profile, []).extend(rows)
    for (typ, tier), profs in sorted(groups.items(), key=lambda kv: (kv[0][0], h.TIERS.index(kv[0][1]))):
        pts = sorted(((stat(r)['usd'], stat(r)['q'], p) for p, r in profs.items()
                      if stat(r)['usd'] is not None), key=lambda x: (x[0], -x[1]))
        best_q = -1
        print('\n%s / %s' % (typ, tier))
        for usd, q, p in pts:
            pareto = q > best_q
            best_q = max(best_q, q)
            print('  %s %-22s solve %.2f  $%.4f' % ('*' if pareto else ' ', p, q, usd))


# --------------------------------------------------------------------------- #
# replay: production routing decisions against measured outcomes
# --------------------------------------------------------------------------- #
def profile_key(cli, model, effort):
    return (cli, MODEL_ALIASES.get(model, model), effort or None)


def replay_fits(core, config, entry, classifier_only=False):
    """Use the original ordered cards; fit_N has no identity without them."""
    if classifier_only or not config['policy'].get('use_model_evidence', True):
        return {}
    cards = entry.get('model_context')
    if not isinstance(cards, list) or not cards:
        raise ValueError('Jev replay needs the original model_context cards; '
                         'use --classifier-only for an explicitly limited historical replay')
    profiles = {p['id']: p for p in config['profiles']}
    seen = set()
    for card in cards:
        profile = profiles.get(card.get('profile'))
        if (not profile or card['profile'] in seen or
            profile['model'] != card.get('model') or
            profile.get('effort') != card.get('effort')):
            raise ValueError('Jev model_context does not match the replay profiles; recapture answers')
        seen.add(card['profile'])
    expected = {'fit_' + str(i) for i in range(len(cards))}
    actual = {key for key in entry['answers'] if key.startswith('fit_')}
    if actual != expected:
        raise ValueError('Jev replay needs one model-fit answer per original card')
    return core.routing.model_fits(entry, cards)


def replay(core, config, tasks, data, hosts, answers_by_task=None, classifier_only=False):
    bench = h.bench_profiles()
    by_key = {profile_key(p['cli'], p['model'], p.get('effort')): pid for pid, p in bench.items()}
    available = {n: dict(status='ready', compatible=True) for n in core.routing.FAMILIES}
    # A component proxy, NOT an observed execute run. Use correctness and cost
    # from same-tier reviews; do not substitute formatting validity or other tiers.
    reviews = {}
    for (task, profile), rows in data.items():
        t = tasks.get(task)
        if t and t['type'] == 'review':
            reviews.setdefault((profile, t['tier']), []).extend(rows)
    per_task, unmeasured = [], []
    for host in hosts:
        for t in tasks.values():
            fits = {}
            if answers_by_task is not None:
                entry = answers_by_task[t['id']]
                answers = entry['answers']
                fits = replay_fits(core, config, entry, classifier_only)
            else:
                answers = core.execution.host_assessment(_ap.Namespace(task_kind=t['kind'], task_tier=t['tier'],
                                                                       task_risk=False, task_ambiguous=False))
            mode = dict(make='make', review='review', consult='consult')[t['type']]
            args = _ap.Namespace(mode=mode, profile=None, panelists=None, host_family=host,
                                 exclude_family=host if mode == 'review' else '', prior_failures=0,
                                 failed_profile=[], max_estimated_usd=None)
            row = dict(task=t['id'], type=t['type'], tier=t['tier'], host=host,
                       profile=None, checker=None, q=None, usd=None)
            per_task.append(row)
            try:
                d = core.routing.resolve(core, config, answers, available, args, {}, fits)
            except core.routing.RoutingError as exc:
                row.update(error=str(exc), q=0.0, usd=0.0)
                continue
            pid = by_key.get(profile_key(d['cli'], d['model'], d.get('effort')))
            row['profile'] = pid
            rows = data.get((t['id'], pid)) if pid else None
            if not rows:
                unmeasured.append((t['id'], d['profile'], host))
                continue
            result = stat(rows)
            row.update(q=result['q'], usd=result['usd'])
            if result['usd'] is None:
                unmeasured.append((t['id'], 'cost:' + d['profile'], host))
            if mode == 'make':
                cargs = _ap.Namespace(**dict(vars(args), mode='review', exclude_family=host + ',' + d['family']))
                try:
                    c = core.routing.resolve(core, config, answers, available, cargs, {}, fits)
                except core.routing.RoutingError as exc:
                    row.update(error=str(exc), q=0.0)
                    continue
                checker = by_key.get(profile_key(c['cli'], c['model'], c.get('effort')))
                row['checker'] = checker
                checks = reviews.get((checker, t['tier']))
                if not checks:
                    row.update(q=None, usd=None)
                    unmeasured.append((t['id'], 'checker:' + c['profile'], host))
                    continue
                review = stat(checks)
                row['q'] *= review['q']
                row['usd'] = (row['usd'] + review['usd']
                              if row['usd'] is not None and review['usd'] is not None else None)
                if review['usd'] is None:
                    unmeasured.append((t['id'], 'checker-cost:' + c['profile'], host))
    return per_task, unmeasured


def mean_known(values):
    return sum(values) / len(values) if values and all(v is not None for v in values) else None


def references(tasks, data):
    """Quality reference per type: the best single profile measured on EVERY task of the type."""
    refs = {}
    bench = h.bench_profiles()
    for typ in h.TYPES:
        ids = [i for i, t in tasks.items() if t['type'] == typ]
        if not ids:
            continue
        best = None
        for pid in bench:
            if all((i, pid) in data for i in ids):
                q = sum(stat(data[(i, pid)])['q'] for i in ids) / len(ids)
                usd = mean_known([stat(data[(i, pid)])['usd'] for i in ids])
                if usd is None:
                    continue
                if best is None or (q, -usd) > (best[1], -best[2]):
                    best = (pid, q, usd)
        solvable = sum(any(stat(r)['q'] for (i2, _p), r in data.items() if i2 == i) for i in ids) / len(ids)
        refs[typ] = dict(profile=best[0] if best else None, q=best[1] if best else None,
                         usd=best[2] if best else None, n=len(ids), ceiling=solvable)
    return refs


def summarize(per_task, refs):
    out = {}
    for typ in h.TYPES:
        rows = [r for r in per_task if r['type'] == typ]
        if not rows:
            continue
        q = mean_known([r['q'] for r in rows])
        usd = mean_known([r['usd'] for r in rows])
        complete = q is not None and usd is not None
        ref = refs.get(typ, {})
        tol = 1.0 / ref['n'] if ref.get('n') else 0
        out[typ] = dict(q=q, usd=usd, cps=usd / q if complete and q else None,
                        n=len(rows), complete=complete,
                        ref_q=ref.get('q'), ref_profile=ref.get('profile'), ref_usd=ref.get('usd'),
                        ceiling=ref.get('ceiling'),
                        gate=complete and ref.get('q') is not None and q >= ref['q'] - tol - 1e-9)
    q = mean_known([r['q'] for r in per_task])
    usd = mean_known([r['usd'] for r in per_task])
    complete = q is not None and usd is not None
    out['overall'] = dict(cps=usd / q if complete and q else None,
                          gate=bool(out) and all(v['gate'] for v in out.values()),
                          q=q, complete=complete, n=len(per_task))
    return out


def bootstrap(per_task, refs, n=2000, seed=7):
    """90% intervals for routed q and cost/solve, resampling tasks (both hosts together)."""
    import random
    rng = random.Random(seed)
    by_task = {}
    for r in per_task:
        if 'type' in r:
            by_task.setdefault(r['task'], []).append(r)
    ids = sorted(by_task)
    out = {}
    for typ in list(h.TYPES) + ['overall']:
        pool = [i for i in ids if typ == 'overall' or by_task[i][0]['type'] == typ]
        if not pool or any(r['q'] is None or r['usd'] is None for i in pool for r in by_task[i]):
            continue
        qs, cps = [], []
        for _ in range(n):
            rows = [r for i in (rng.choice(pool) for _ in pool) for r in by_task[i]]
            q = sum(r['q'] for r in rows) / len(rows)
            usd = sum(r['usd'] for r in rows) / len(rows)
            qs.append(q)
            cps.append(usd / q if q else math.inf)
        qs.sort(), cps.sort()
        out[typ] = dict(q=(qs[int(.05 * n)], qs[int(.95 * n)]), cps=(cps[int(.05 * n)], cps[int(.95 * n)]))
    return out


def baselines(tasks, data):
    """Single-profile baselines with full coverage of a type: best (quality, then cost) and cheapest."""
    out = {}
    for typ in h.TYPES:
        ids = [i for i, t in tasks.items() if t['type'] == typ]
        rows = []
        for pid in h.bench_profiles():
            if ids and all((i, pid) in data for i in ids):
                q = sum(stat(data[(i, pid)])['q'] for i in ids) / len(ids)
                usd = mean_known([stat(data[(i, pid)])['usd'] for i in ids])
                if usd is None:
                    continue
                rows.append((pid, q, usd))
        if rows:
            out[typ] = dict(best=max(rows, key=lambda x: (x[1], -x[2])), cheapest=min(rows, key=lambda x: (x[2], -x[1])))
    return out


def cmd_replay(args):
    h.configure(Path(args.state))
    core = h.load_core()
    config = json.loads(Path(args.config).read_text())
    for item in args.policy or []:  # quick policy experiments without editing the config file
        k, _, v = item.partition('=')
        config['policy'][k] = json.loads(v)
    core.routing.validate(config)
    tasks = {t['id']: t for t in h.load_tasks(split=args.split)}
    data = cells(args.tags, args.split)
    answers = json.loads(Path(args.answers).read_text()) if args.answers else None
    try:
        per_task, unmeasured = replay(core, config, tasks, data, args.hosts.split(','), answers, args.classifier_only)
    except (ValueError, KeyError, core.routing.RoutingError) as exc:
        print('Replay input error: %s' % exc, file=sys.stderr)
        return 2
    refs = references(tasks, data)
    s = summarize(per_task, refs)
    ci = bootstrap(per_task, refs)
    base = baselines(tasks, data)
    if args.json:
        print(json.dumps(dict(measurement='component_proxy',
                              assessment='classifier_only' if args.classifier_only else ('jev_model_fit' if answers is not None and config['policy'].get('use_model_evidence', True) else 'task_labels_or_priors'),
                              summary=s, ci=ci, baselines=base, unmeasured=unmeasured, per_task=per_task), indent=2, default=str))
        return 0 if s['overall']['gate'] else 1
    rows = [[typ, v['n'], fmt(v['q'], '%.3f'), fmt(v['ref_q'], '%.3f') + ' (' + str(v['ref_profile']) + ')',
             fmt(v['ceiling'], '%.2f'), fmt(v['usd'], '$%.4f'), fmt(v['cps'], '$%.4f'), 'PASS' if v['gate'] else 'FAIL']
            for typ, v in s.items() if typ != 'overall']
    for row in rows:
        c = ci.get(row[0])
        row.insert(3, '[%.2f, %.2f]' % c['q'] if c else '-')
        row.append('[$%.3f, $%.3f]' % c['cps'] if c else '-')
    print(table(rows, ['type', 'n', 'routed_q', 'q 90% CI', 'quality_ref', 'ceiling', 'usd/task', 'usd/solve', 'gate', 'usd/solve 90% CI']))
    o = s['overall']
    print('\nCOMPONENT PROXY (not end-to-end execute; %s) cost_per_solve=%s  q=%s  gate=%s' % (
        'classifier-only' if args.classifier_only else 'model-fit or task-label routing',
        fmt(o['cps'], '$%.4f'), fmt(o['q'], '%.3f'), 'PASS' if o['gate'] else 'FAIL/INCOMPLETE'))
    print('\nBASELINES (single profile on every task of the type):')
    for typ, b in base.items():
        for label in ('best', 'cheapest'):
            pid, q, usd = b[label]
            print('  %-8s %-9s %-20s q=%.3f  usd/task=$%.4f  usd/solve=%s' % (typ, label, pid, q, usd, '$%.4f' % (usd / q) if q else '-'))
    if unmeasured:
        print('\nUNMEASURED routed choices (%d): measure these profiles before trusting the score:' % len(unmeasured))
        for u in sorted(set((b, c) for _a, b, c in unmeasured)):
            print('  ', u)
    if args.verbose:
        for r in per_task:
            print(r)
    return 0 if s['overall']['gate'] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('profiles', 'frontier', 'replay'):
        p = sub.add_parser(name)
        p.add_argument('--tags', type=lambda s: s.split(','), required=True)
        p.add_argument('--split', choices=('dev', 'holdout'), default='dev')
        if name == 'replay':
            p.add_argument('--config', default=str(h.ROOT / 'data' / 'routing-defaults.json'))
            p.add_argument('--hosts', default='anthropic,openai')
            p.add_argument('--state', default=str(Path.home() / '.local' / 'state' / 'alloy-bench' / 'replay'))
            p.add_argument('--json', action='store_true')
            p.add_argument('--verbose', action='store_true')
            p.add_argument('--classifier-only', action='store_true', help='explicit historical replay without Jev model-fit evidence')
            p.add_argument('--answers', help='per-task classifier answers (JSON from a Jev run) instead of task labels')
            p.add_argument('--policy', action='append', help='policy override, e.g. confidence_floor=0.5 (repeatable)')
    args = ap.parse_args()
    return dict(profiles=cmd_profiles, frontier=cmd_frontier, replay=cmd_replay)[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
