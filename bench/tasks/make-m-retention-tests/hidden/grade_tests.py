#!/usr/bin/env python3
"""Mutation grader for make-m-retention-tests.

Runs the Maker's suite (`python3 -m unittest discover -s tests`) on a copy of
the worktree: once unmodified (must pass, at least one test), then once per
directory in mutants/ overlaid onto the copy (must fail). Prints
`BENCH_SCORE: killed/total`; exits 0 only if the original passes and every
mutant is killed.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MUTANTS = sorted(p for p in (HERE / 'mutants').iterdir() if p.is_dir())
CMD = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests']
IGNORE = shutil.ignore_patterns(HERE.name, '.git', '__pycache__', '*.pyc')


def run_suite(tree):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    try:
        cp = subprocess.run(CMD, cwd=str(tree), capture_output=True, text=True, timeout=30, env=env,
                            stdin=subprocess.DEVNULL)
        return cp.returncode, cp.stdout + cp.stderr
    except subprocess.TimeoutExpired:
        return 124, 'TIMEOUT'


def overlay(src, dest):
    for path in sorted(src.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            target = dest / path.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(path), str(target))


def main():
    total = len(MUTANTS)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / 'original'
        shutil.copytree(str(ROOT), str(base), ignore=IGNORE)
        code, out = run_suite(base)
        ran = re.findall(r'^Ran (\d+) tests? in', out, re.M)
        if code != 0 or not ran or int(ran[-1]) == 0:
            print(out[-3000:])
            print('ORIGINAL: suite must pass on the unmodified implementation (exit %d)' % code)
            print('BENCH_SCORE: 0/%d' % total)
            return 1
        print('ORIGINAL: pass (%s tests)' % ran[-1])
        killed = 0
        for mutant in MUTANTS:
            tree = Path(tmp) / mutant.name
            shutil.copytree(str(ROOT), str(tree), ignore=IGNORE)
            overlay(mutant, tree)
            code, _ = run_suite(tree)
            status = 'killed' if code != 0 else 'SURVIVED'
            killed += code != 0
            print('%-32s %s' % (mutant.name, status))
    print('BENCH_SCORE: %d/%d' % (killed, total))
    return 0 if killed == total else 1


if __name__ == '__main__':
    sys.exit(main())
