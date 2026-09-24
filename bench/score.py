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
                usd=sum(cost) / len(cost) if cost else None,
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
        pts = sorted(((stat(r)['usd'] or 0, stat(r)['q'], p) for p, r in profs.items()), key=lambda x: (x[0], -x[1]))
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


def replay(core, config, tasks, data, hosts):
    bench = h.bench_profiles()
    by_key = {profile_key(p['cli'], p['model'], p.get('effort')): pid for pid, p in bench.items()}
    available = {n: dict(status='ready', compatible=True) for n in core.routing.FAMILIES}
    # Checker cost for execute = that profile's mean cost on review tasks of the same tier.
    review_cost = {}
    for (task, profile), rows in data.items():
        t = tasks.get(task)
        if t and t['type'] == 'review':
            review_cost.setdefault((profile, t['tier']), []).extend(r['api_usd'] for r in rows if r.get('api_usd') is not None)
    per_task, unmeasured = [], []
    for host in hosts:
        for t in tasks.values():
            answers = core.execution.host_assessment(_ap.Namespace(task_kind=t['kind'], task_tier=t['tier'],
                                                                   task_risk=False, task_ambiguous=False))
            mode = dict(make='make', review='review', consult='consult')[t['type']]
            args = _ap.Namespace(mode=mode, profile=None, panelists=None, host_family=host,
                                 exclude_family=host if mode == 'review' else '', prior_failures=0,
                                 failed_profile=[], max_estimated_usd=None)
            try:
                d = core.routing.resolve(core, config, answers, available, args, {})
            except core.routing.RoutingError as exc:
                per_task.append(dict(task=t['id'], host=host, error=str(exc), q=0.0, usd=0.0))
                continue
            pid = by_key.get(profile_key(d['cli'], d['model'], d.get('effort')))
            rows = data.get((t['id'], pid)) if pid else None
            if not rows:
                unmeasured.append((t['id'], d['profile'], host))
                continue
            s = stat(rows)
            usd = s['usd'] or 0.0
            checker = None
            if mode == 'make':
                cargs = _ap.Namespace(**dict(vars(args), mode='review', exclude_family=host + ',' + d['family']))
                c = core.routing.resolve(core, config, answers, available, cargs, {})
                checker = by_key.get(profile_key(c['cli'], c['model'], c.get('effort')))
                costs = review_cost.get((checker, t['tier'])) or []
                usd += sum(costs) / len(costs) if costs else 0.0
            per_task.append(dict(task=t['id'], type=t['type'], tier=t['tier'], host=host,
                                 profile=pid, checker=checker, q=s['q'], usd=usd))
    return per_task, unmeasured


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
                usd = sum(stat(data[(i, pid)])['usd'] or 0 for i in ids) / len(ids)
                if best is None or (q, -usd) > (best[1], -best[2]):
                    best = (pid, q, usd)
        solvable = sum(any(stat(r)['q'] for (i2, _p), r in data.items() if i2 == i) for i in ids) / len(ids)
        refs[typ] = dict(profile=best[0] if best else None, q=best[1] if best else None,
                         usd=best[2] if best else None, n=len(ids), ceiling=solvable)
    return refs


def summarize(per_task, refs):
    out = {}
    for typ in h.TYPES:
        rows = [r for r in per_task if r.get('type') == typ or (r.get('error') and typ == 'make')]
        rows = [r for r in per_task if r.get('type') == typ]
        if not rows:
            continue
        q = sum(r['q'] for r in rows) / len(rows)
        usd = sum(r['usd'] for r in rows) / len(rows)
        ref = refs.get(typ, {})
        tol = 1.0 / ref['n'] if ref.get('n') else 0
        out[typ] = dict(q=q, usd=usd, cps=usd / q if q else math.inf, n=len(rows),
                        ref_q=ref.get('q'), ref_profile=ref.get('profile'), ref_usd=ref.get('usd'),
                        ceiling=ref.get('ceiling'),
                        gate=ref.get('q') is None or q >= ref['q'] - tol - 1e-9)
    total_usd = sum(v['usd'] * v['n'] for v in out.values())
    total_q = sum(v['q'] * v['n'] for v in out.values())
    out['overall'] = dict(cps=total_usd / total_q if total_q else math.inf,
                          gate=all(v['gate'] for v in out.values()),
                          q=total_q / sum(v['n'] for v in out.values() if 'n' in v) if out else None)
    return out


def cmd_replay(args):
    h.configure(Path(args.state))
    core = h.load_core()
    config = json.loads(Path(args.config).read_text())
    core.routing.validate(config)
    tasks = {t['id']: t for t in h.load_tasks(split=args.split)}
    data = cells(args.tags, args.split)
    per_task, unmeasured = replay(core, config, tasks, data, args.hosts.split(','))
    refs = references(tasks, data)
    s = summarize(per_task, refs)
    if args.json:
        print(json.dumps(dict(summary=s, unmeasured=unmeasured, per_task=per_task), indent=2, default=str))
        return 0
    rows = [[typ, v['n'], fmt(v['q'], '%.3f'), fmt(v['ref_q'], '%.3f') + ' (' + str(v['ref_profile']) + ')',
             fmt(v['ceiling'], '%.2f'), fmt(v['usd'], '$%.4f'), fmt(v['cps'], '$%.4f'), 'PASS' if v['gate'] else 'FAIL']
            for typ, v in s.items() if typ != 'overall']
    print(table(rows, ['type', 'n', 'routed_q', 'quality_ref', 'ceiling', 'usd/task', 'usd/solve', 'gate']))
    o = s['overall']
    print('\nOVERALL  cost_per_solve=$%.4f  q=%.3f  gate=%s' % (o['cps'], o['q'] or 0, 'PASS' if o['gate'] else 'FAIL'))
    if unmeasured:
        print('\nUNMEASURED routed choices (%d): measure these profiles before trusting the score:' % len(unmeasured))
        for u in sorted(set((b, c) for _a, b, c in unmeasured)):
            print('  ', u)
    if args.verbose:
        for r in per_task:
            print(r)
    return 0


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
    args = ap.parse_args()
    return dict(profiles=cmd_profiles, frontier=cmd_frontier, replay=cmd_replay)[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
