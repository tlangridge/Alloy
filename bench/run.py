#!/usr/bin/env python3
"""Run alloy-bench live against real provider CLIs (spends subscription quota).

  python3 bench/run.py matrix --tag baseline --types make --split dev \
      --profiles codex-luna-medium,agy-flash-low --repeats 1
  python3 bench/run.py one --task make-s-foo --profile claude-sonnet
  python3 bench/run.py quota            # live headroom vs the bench floors

Results append to bench/results/runs.jsonl (untracked). A matrix is resumable:
finished (tag, task, profile, repeat) cells are skipped. Before every dispatch
the runner reads live quota and skips a provider whose tightest window is below
its floor, so a long run cannot drain a subscription.
"""
import argparse
import concurrent.futures as cf
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402

RUNS = h.RESULTS / 'runs.jsonl'
# Minimum remaining fraction of the tightest live window per provider. Claude is
# higher because the host session shares that subscription.
FLOORS = dict(codex=0.12, claude=0.35, grok=0.25, antigravity=0.15)


def state_dir():
    return Path(os.environ.get('ALLOY_BENCH_STATE') or Path.home() / '.local' / 'state' / 'alloy-bench')


def quota_view(core, profiles, force=False):
    snap = core.routing.usage.get(core, core.routing.load(), force=force)
    out = {}
    for pid, p in profiles.items():
        prof = dict(adapter=p['cli'], model=p['model'], quota_pool=p['cli'], billing_mode='subscription')
        out[pid] = core.routing.usage.headroom(prof, snap)
    return out


class Guard:
    """Serializes quota reads (cached ~2 min by Alloy) and tracks exhausted providers."""
    def __init__(self, core, profiles, floors):
        self.core, self.profiles, self.floors = core, profiles, floors
        self.lock = threading.Lock()
        self.blocked = {}

    def allow(self, profile):
        cli = self.profiles[profile]['cli']
        with self.lock:
            if cli in self.blocked:
                return False, self.blocked[cli]
            try:
                room = quota_view(self.core, {profile: self.profiles[profile]})[profile]
            except Exception as exc:  # unknown quota never blocks, but is logged
                return True, 'quota unknown: %s' % exc
            if room is not None and room < self.floors.get(cli, 0):
                self.blocked[cli] = 'quota floor: %.0f%% left < %.0f%%' % (room * 100, self.floors[cli] * 100)
                return False, self.blocked[cli]
            return True, None if room is None else '%.0f%% left' % (room * 100)


def cmd_matrix(args, core):
    profiles = h.bench_profiles()
    chosen = args.profiles.split(',') if args.profiles else list(profiles)
    unknown = [p for p in chosen if p not in profiles]
    if unknown:
        sys.exit('unknown profile(s): %s' % unknown)
    tasks = h.load_tasks(ids=args.tasks.split(',') if args.tasks else None,
                         types=args.types.split(',') if args.types else None,
                         split=args.split, tiers=args.tiers.split(',') if args.tiers else None)
    done = {(r['tag'], r['task'], r['profile'], r['repeat']) for r in h.read_runs(RUNS)
            if r.get('outcome') == 'done'}
    jobs = [(t, p, rep) for rep in range(args.repeats) for t in tasks for p in chosen
            if (args.tag, t['id'], p, rep) not in done]
    # Interleave providers so every CLI's slots stay busy.
    jobs.sort(key=lambda j: (j[2], h.TIERS.index(j[0]['tier']), j[0]['id'], profiles[j[1]]['cli']))
    print('%d job(s) pending for tag %r (%d task(s) x %d profile(s) x %d repeat(s))'
          % (len(jobs), args.tag, len(tasks), len(chosen), args.repeats), file=sys.stderr)
    if args.dry_run:
        for t, p, rep in jobs:
            print(args.tag, t['id'], p, rep)
        return 0
    floors = dict(FLOORS, **json.loads(args.floors or '{}'))
    guard = Guard(core, profiles, floors)
    slots = {cli: threading.Semaphore(args.per_cli) for cli in {p['cli'] for p in profiles.values()}}
    revision = h.sut_revision()
    work_root = state_dir() / 'work' / args.tag

    def one(job):
        task, profile, rep = job
        cli = profiles[profile]['cli']
        with slots[cli]:
            ok, note = guard.allow(profile)
            base = dict(tag=args.tag, repeat=rep, sut=revision, started_at=time.time(), note=note)
            if not ok:
                row = dict(h._record(task, profile), outcome='skipped', reason=note, **base)
                h.append(RUNS, row)
                return row
            work = work_root / task['id'] / profile / ('%d-%s' % (rep, uuid.uuid4().hex[:6]))
            work.mkdir(parents=True)
            try:
                row = h.RUNNERS[task['type']](core, task, profile, work)
                row.update(outcome='done', work=str(work), **base)
            except Exception as exc:
                row = dict(h._record(task, profile), outcome='harness_error', error=repr(exc)[:500],
                           trace=traceback.format_exc()[-2000:], work=str(work), **base)
            row['finished_at'] = time.time()
            h.append(RUNS, row)
            usd = row.get('api_usd')
            print('[bench] %-8s %-28s %-20s %s  $%s  %ss' % (
                row['outcome'], task['id'], profile,
                'PASS' if row.get('passed') else 'fail', '%.4f' % usd if usd is not None else '?',
                row.get('wall_s', '?')), file=sys.stderr, flush=True)
            return row

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(one, jobs))
    return 0


def cmd_one(args, core):
    task = h.load_task(args.task)
    work = state_dir() / 'work' / 'adhoc' / ('%s-%s-%s' % (args.task, args.profile, uuid.uuid4().hex[:6]))
    work.mkdir(parents=True)
    row = h.RUNNERS[task['type']](core, task, args.profile, work)
    row.update(tag=args.tag, repeat=0, outcome='done', sut=h.sut_revision(), work=str(work))
    if args.tag != 'adhoc':
        h.append(RUNS, row)
    print(json.dumps({k: v for k, v in row.items() if k not in ('dispatches', 'raw')}, indent=2, default=str))
    return 0


def cmd_quota(args, core):
    profiles = h.bench_profiles()
    view = quota_view(core, profiles, force=True)
    for pid, room in sorted(view.items()):
        cli = profiles[pid]['cli']
        print('%-22s %-12s %s (floor %.0f%%)' % (pid, cli, 'unknown' if room is None else '%.0f%%' % (room * 100),
                                                  FLOORS.get(cli, 0) * 100))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('matrix')
    m.add_argument('--tag', required=True)
    m.add_argument('--profiles')
    m.add_argument('--tasks')
    m.add_argument('--types')
    m.add_argument('--tiers')
    m.add_argument('--split', choices=('dev', 'holdout'))
    m.add_argument('--repeats', type=int, default=1)
    m.add_argument('--per-cli', type=int, default=2)
    m.add_argument('--workers', type=int, default=8)
    m.add_argument('--floors', help='JSON overrides, e.g. {"codex": 0.2}')
    m.add_argument('--dry-run', action='store_true')
    o = sub.add_parser('one')
    o.add_argument('--task', required=True)
    o.add_argument('--profile', required=True)
    o.add_argument('--tag', default='adhoc')
    sub.add_parser('quota')
    args = ap.parse_args()
    h.configure(state_dir())
    core = h.load_core()
    core._install_signal_handlers()
    return dict(matrix=cmd_matrix, one=cmd_one, quota=cmd_quota)[args.cmd](args, core)


if __name__ == '__main__':
    sys.exit(main())
