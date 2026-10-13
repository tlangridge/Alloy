#!/usr/bin/env python3
"""Opt-in complete execute evaluation. No model calls without --live.

Runs production selection, Maker, gates, independent Checker and corrections.
Hidden tests run only after workers stop. Results and retained worktrees live
outside the checkout. This measures fixture correctness, never user acceptance.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h


def summarize(core, fixture, task, grade, elapsed):
    dispatches = []
    costs = []
    for round_ in task['rounds']:
        calls = ([('maker', round_['maker'])] if 'maker' in round_ else []) + [
            ('checker', call) for call in round_.get('checker_attempts',
                [round_['checker']] if 'checker' in round_ else [])]
        for role, call in calls:
            dispatches.append(dict(role=role, round=round_['index'], **h._dispatch_summary(call)))
            costs.append(h.cost_of(task[role]['model'], call.get('usage')).get('api_usd'))
    first = task['rounds'][0] if task['rounds'] else {}
    gates = first.get('gates', [])
    worker_usd = sum(costs) if costs and all(c is not None for c in costs) else None
    routed = 'jev_usage' in task['maker'] or bool(task['maker'].get('jev_model'))
    return dict(schema=1, type='execute', task=fixture['id'], tier=fixture['tier'], kind=fixture['kind'],
        split=fixture['split'], sut=h.sut_revision(), task_id=task['id'], state=task['state'],
        revision=task.get('tip'),
        workers={role: {key: task[role].get(key) for key in ('profile', 'cli', 'cli_version', 'model', 'family',
                                                         'effort', 'cursor_fast', 'billing_mode', 'quota_pool', 'objective')}
                 for role in ('maker', 'checker')},
        process_ready=task['state'] == 'ready', hidden_correct=grade['passed'],
        passed=task['state'] == 'ready' and grade['passed'],
        first_pass_gates=all(g['exit_code'] == 0 for g in gates) if gates else None,
        first_pass_review=first.get('review', {}).get('verdict'),
        first_pass_hidden_correctness=None, user_accepted=None,
        correction_rounds=max(0, task.get('implementation_rounds', len(task['rounds'])) - 1),
        dispatches=dispatches, wall_s=round(elapsed, 2), active_s=task.get('active_seconds'),
        worker_api_usd=worker_usd, api_usd=None if routed else worker_usd,
        router=dict(used=routed, model=task['maker'].get('jev_model'), usage=task['maker'].get('jev_usage'),
                    latency_ms=task['maker'].get('jev_latency_ms'), api_usd=None if routed else 0),
        pricing_basis='Worker API list-price equivalent; total unknown when router is unpriced; not subscription consumption',
        hidden_grade={k: grade[k] for k in ('passed', 'score', 'hidden_passed', 'hidden_total', 'hidden_exit')},
        retained_worktree=task['worktree'], outcome='done')


def run_execute(core, fixture, work, args):
    if fixture['type'] != 'make':
        raise ValueError('Complete execute evaluation needs a make fixture')
    work = Path(work)
    repo = work / 'source'
    h.materialize(fixture, repo)
    spec = work / 'spec.txt'
    spec.write_text((Path(fixture['dir']) / 'spec.md').read_text())
    argv = ['execute', '--repo', str(repo), '--prompt-file', str(spec), '--host-family', args.host_family,
            '--task-tier', fixture['tier'], '--task-kind', fixture['kind'],
            '--budget-minutes', str(args.budget_minutes), '--timeout', str(args.timeout),
            '--max-fix-rounds', str(args.max_fix_rounds), '--logical-task-id', 'bench-' + uuid.uuid4().hex]
    for path in fixture['allow_paths']:
        argv += ['--allow-path', path]
    argv += ['--test', fixture['visible_test']]
    if args.route:
        argv.append('--route')
    if args.maker_profile:
        argv += ['--maker-profile', args.maker_profile]
    if args.checker_profile:
        argv += ['--checker-profile', args.checker_profile]
    parsed = core.build_parser().parse_args(argv)
    started = time.monotonic()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        core.execution.create(core, parsed)
    report = json.loads(buffer.getvalue())
    task = json.loads(Path(report['record']).read_text())
    # Ground truth is never staged for either role. It cannot influence their
    # decision, correction prompt, tests or context receipt.
    grade = h.grade_make(fixture, task['worktree'])
    return summarize(core, fixture, task, grade, time.monotonic() - started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True)
    parser.add_argument('--host-family', required=True, choices=('openai', 'anthropic', 'google', 'meta', 'xai', 'cursor'))
    parser.add_argument('--maker-profile')
    parser.add_argument('--checker-profile')
    parser.add_argument('--route', action='store_true')
    parser.add_argument('--live', action='store_true', help='authorize real CLI calls and optional Jev routing')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--budget-minutes', type=float, default=45)
    parser.add_argument('--max-fix-rounds', type=int, default=1)
    parser.add_argument('--state', help='private output directory outside this checkout')
    args = parser.parse_args()
    fixture = h.load_task(args.task)
    if fixture['type'] != 'make':
        parser.error('Choose a make fixture')
    if not args.route and not (args.maker_profile and args.checker_profile):
        parser.error('Supply --route or both worker profiles')
    if not args.live:
        print(json.dumps(dict(task=args.task, live=False, host=args.host_family,
                              maker=args.maker_profile, checker=args.checker_profile, route=args.route), indent=2))
        return 0
    state = Path(args.state or Path.home() / '.local/state/alloy-bench/execute').resolve()
    if state == h.ROOT or h.ROOT in state.parents:
        parser.error('Evaluation state must be outside the checkout')
    core = h.load_core()
    # Snapshot configuration before moving evaluation state. Pins and billing
    # remain binding; the fixed component benchmark's tier bypass is not used.
    config = core.routing.load()
    session = state / uuid.uuid4().hex
    session.mkdir(parents=True, mode=0o700)
    os.environ['ALLOY_RUN_ROOT'] = str(session / 'panels')
    os.environ['ALLOY_ROUTING_HOME'] = str(session / 'routing')
    core.routing.save(core.routing.root() / 'routing.json', config)
    core._install_signal_handlers()
    try:
        row = run_execute(core, fixture, session, args)
    except (core.execution.ExecutionError, core.routing.RoutingError, OSError, ValueError) as exc:
        row = dict(type='execute', task=args.task, outcome='infra_error', passed=False,
                   error=str(exc), state=str(session))
    h.append(state / 'results.jsonl', row)
    print(json.dumps(row, indent=2))
    return 0 if row.get('passed') else 3


if __name__ == '__main__':
    sys.exit(main())
