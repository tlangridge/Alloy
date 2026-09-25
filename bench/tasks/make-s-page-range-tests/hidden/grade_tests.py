#!/usr/bin/env python3
"""Mutation grader for make-s-page-range-tests.

Runs the Maker's test suite (``python3 -m unittest discover -s tests``) in a
scratch copy of the worktree: once with the original ``printq/pages.py`` (must
pass and run at least one test) and once per mutant in ``mutants/`` (must
fail). Prints ``BENCH_SCORE: killed/total``; exits 0 only if the suite passes
on the original and kills every mutant.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = Path.cwd()
TARGET = Path('printq') / 'pages.py'
TIMEOUT_S = 10
_IGNORE = shutil.ignore_patterns('.git', '_hidden_tests', '__pycache__', '*.pyc')


def run_suite(module_path, scratch):
    tree = Path(scratch) / 'wt'
    if tree.exists():
        shutil.rmtree(str(tree))
    shutil.copytree(str(WORKTREE), str(tree), ignore=_IGNORE)
    shutil.copyfile(str(module_path), str(tree / TARGET))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    try:
        cp = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                            cwd=str(tree), capture_output=True, text=True, timeout=TIMEOUT_S,
                            env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, 'TIMEOUT'
    return cp.returncode, cp.stdout + cp.stderr


def main():
    mutants = sorted((HERE / 'mutants').glob('m*.py'))
    total = len(mutants)
    with tempfile.TemporaryDirectory() as scratch:
        code, out = run_suite(HERE / 'original' / 'pages.py', scratch)
        ran = re.findall(r'^Ran (\d+) tests? in', out, re.M)
        if code != 0 or not ran or int(ran[-1]) == 0:
            print('ORIGINAL: test suite must pass on the unmodified implementation and run >= 1 test')
            print(out[-3000:])
            print('BENCH_SCORE: 0/%d' % total)
            return 1
        print('ORIGINAL: pass (%s tests)' % ran[-1])
        killed = 0
        for mutant in mutants:
            code, _ = run_suite(mutant, scratch)
            status = 'killed' if code != 0 else 'SURVIVED'
            killed += code != 0
            print('%-40s %s' % (mutant.stem, status))
    print('BENCH_SCORE: %d/%d' % (killed, total))
    return 0 if killed == total else 1


if __name__ == '__main__':
    sys.exit(main())
