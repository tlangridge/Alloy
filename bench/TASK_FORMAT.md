# Alloy bench task format

Every task lives in `bench/tasks/<id>/` and is **frozen** once the baseline is
recorded: the autoresearch loop may never edit tasks, hidden tests, grading or
pricing (see `program.md`). Run `python3 bench/validate.py <id>` after authoring.

All task code is Python 3.8+ standard library only. Every test command must
finish in under 30 seconds and be deterministic (no network, no wall-clock or
random dependence without a fixed seed, no sleeps longer than 0.2 s).

## Common `task.json` fields

| Field | Meaning |
| --- | --- |
| `id` | Directory name; `make-*`, `review-*` or `consult-*` |
| `type` | `make`, `review` or `consult` |
| `tier` | `small`, `medium` or `large` — the capability a careful router should require |
| `kind` | Router task kind: `implementation`, `debugging`, `testing`, `refactoring`, `review`, `research`, `architecture` |
| `split` | `dev` (the loop may look at results) or `holdout` (only scored at the end) |
| `title` | One line |

## `make` — the execute-mode Maker

```
task.json   + allow_paths, visible_test, hidden_test, hidden_checks
spec.md     the SPEC the Maker receives (goal, current behavior, desired behavior,
            allowed paths, non-goals, acceptance criteria, test commands, handoff)
repo/       the initial repository (the harness git-inits and commits it)
hidden/     grading files, copied to <worktree>/_hidden_tests/ ONLY after the Maker finishes
solution/   overlay onto repo/ forming a reference solution (validation only; never shown)
```

- `visible_test` runs in the worktree root; it is the gate the Maker is told to run.
- `hidden_test` runs in the worktree root after `hidden/` is copied to
  `_hidden_tests/`. Exit 0 means solved. Use `python3 -m unittest discover -s
  _hidden_tests -v` (put `__init__.py` in `hidden/`; `python3 -m` puts the
  worktree root on `sys.path`). Testing-kind tasks run a grader script instead.
- **Fairness rule:** every hidden assertion must trace to an explicit sentence
  in `spec.md` or to behavior the existing code/visible tests already establish.
  `hidden_checks` lists each hidden test with the spec sentence it enforces.
  Never test naming, formatting or structure the spec does not require.
- Validation requires: the initial repo FAILS `hidden_test`; the repo plus
  `solution/` PASSES both `visible_test` and `hidden_test` three times in a row.
- Testing-kind tasks (the Maker writes tests): `hidden/` holds `grade_tests.py`
  and `mutants/`. The grader runs the Maker's tests against the original
  implementation (must pass) and against each mutant (must fail). It exits 0 if
  at least the threshold stated in `spec.md` of mutants are killed and prints
  `BENCH_SCORE: killed/total`. Mutants must each violate a spec'd behavior.

## `review` — the independent Checker

```
task.json   + bug (bool), claimed_change, visible_test, ground_truth (bug tasks)
repo/       base revision
change/     overlay forming the reviewed revision (what a Maker produced; visible tests pass)
hidden/     bug tasks: a unittest that FAILS on the reviewed revision, proving the bug
```

- `claimed_change` is the goal the change claims to implement (the review packet's `goal`).
- `ground_truth`: `{"path": "pkg/x.py", "keywords": ["off-by-one", "<= len", ...],
  "description": "..."}`. A finding matches when its `path` ends with the
  ground-truth path and its evidence/fix text contains any keyword
  (case-insensitive). List many phrasings a competent reviewer might use.
- Clean tasks (`bug: false`) are genuinely correct changes; any finding is a
  false positive. They should look plausible to nitpick but contain no defect.
- Validation requires: visible tests pass on the reviewed revision; for bug
  tasks the hidden test fails there.

## `consult` — read-only panel questions

```
task.json   + prompt, answers, match ("exact" | "number" | "regex")
repo/       optional repository the panelist may read (read-only)
```

The harness appends: *End your reply with one final line: `ANSWER: <answer>`.*
Grading reads the last `ANSWER:` line. `exact` compares case-insensitively
after trimming spaces, backticks and a trailing period; `number` compares
numerically; `regex` uses `re.fullmatch` (case-insensitive). Questions must
have one objectively correct answer that can be verified by running code or
reading the repo — no opinion questions.
