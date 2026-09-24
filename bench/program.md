# Alloy autoresearch

An autonomous experiment loop, after Karpathy's
[autoresearch](https://github.com/karpathy/autoresearch), that optimizes Alloy
for **the best quality at the lowest cost across the user's subscription
providers** (Codex, Claude, Grok, Antigravity).

| autoresearch | Alloy |
| --- | --- |
| `prepare.py` — fixed data, eval, constants | `bench/` — tasks with hidden tests, grading, pricing, profiles, scorer. **Never edited by the loop.** |
| `train.py` — the one thing the agent edits | Alloy's routing configuration, adapter invocation and worker prompts (below) |
| `val_bpb` — one number, lower is better | **cost per solved task** (USD at API list price), subject to a **quality gate** |
| 5-minute fixed budget | fixed task set, fixed timeouts, fixed prices; paired comparisons |
| `results.tsv` | `bench/results.tsv` (untracked during the loop) |

## Setup

1. Agree on a run tag (e.g. `sep24`); work on branch `autoresearch/<tag>` in a
   **separate git worktree** — the user's installed skill may point at the main
   checkout.
2. Read: `README.md`, `SKILL.md`, `bench/TASK_FORMAT.md`, `bench/harness.py`,
   `bench/score.py`, `bin/alloy_routing.py` (`resolve`), `bin/alloy_execution.py`
   (`maker_prompt`, `checker_prompt`, `worker_adapter`, `run`), the adapters in
   `bin/alloy`, `data/routing-defaults.json`, `data/model-evidence.json`.
3. `python3 bench/validate.py` — every task must print `ok`.
4. `python3 -m unittest discover -s tests` and `python3 tests/validate_skill.py` pass.
5. `python3 bench/run.py quota` — check live headroom against the floors.
6. Create `bench/results.tsv` with the header row (tab-separated):
   `commit	kind	q	cost_per_solve	gate	status	description`

## The metric

`python3 bench/score.py replay --tags <measurement tags> --answers
bench/results/jev-answers.json` routes every **dev** task through PRODUCTION
`resolve()` using the classifier's real judgments of each task (for two hosts:
an Anthropic host and an OpenAI host) and scores the choices against measured
outcomes. Run it without `--answers` too: true-label routing isolates policy
from classifier error. Regenerate the answers when the Jev model or rubric
changes (48 calls, about one cent). The literature is clear that difficulty
prediction is the weak link of pre-generation routers, so the realistic score
is the primary one. The report includes 90% bootstrap intervals and single-
profile baselines (best, cheapest); a change inside the noise is not a win.

- **q** — routed mean solve probability per task type (`make`, `review`, `consult`).
  `make` counts only hidden-test success; `review` counts a correct verdict
  that also names the seeded defect; `consult` counts the exact answer.
- **quality gate** — per type, q must be at least the *quality reference* (the
  best single measured profile on that type) minus one task. Quality is never
  traded for cost beyond noise.
- **cost_per_solve** — routed USD / routed solves. `make` adds the routed
  Checker's measured review cost (execute always runs one).
- The run log shows `UNMEASURED` when the router picks a profile with no data;
  measure it (or treat the score as untrusted).

Lower `cost_per_solve` with `gate=PASS` wins. The quality reference moves only
when new measurements arrive, never because a change was made.

## Lessons so far (read before proposing routing changes)

- Execute cascades (cheap Maker, escalate on gate failure) lost to tier routing:
  the visible gate caught only 54% of failures and cheap models fail slowly and
  expensively on hard tasks. Revisit only with a stronger verifier.
- Lowering `confidence_floor` below .75 made routing worse: over-escalating to
  large-tier Gemini is cheap; under-escalating to weak models is not.
- Same-family agreement is not independent evidence: Gemini variants made the
  same mistakes on consult questions.
- Quota exchange rates differ by >10x across pools (Gemini via Antigravity is
  the cheapest capacity; agy's Claude/GPT pool the most expensive) and are
  plan-specific: calibrate a user's private config, not shipped defaults.

## What you CAN change (the mutable surface)

1. **Routing configuration** — `data/routing-defaults.json`: profile `tier`,
   `cost_rank`, `effort`, `enabled`; `policy` knobs (`confidence_floor`,
   `risk_threshold`, `task_fit_cost_slack`, `use_model_evidence`). Adding a
   profile is allowed only for a (cli, model, effort) the bench has measured.
2. **Task evidence** — `data/model-evidence.json` `preferred_tasks`, citing the
   bench measurement (tag + date) as the source.
3. **Invocation** — adapter flags in `bin/alloy` that change what a CLI loads or
   how hard it thinks (context trimming, effort defaults), and the Maker/Checker
   prompt text in `bin/alloy_execution.py`.

## What you CANNOT change

- Anything under `bench/` except `results.tsv` — tasks, hidden tests, grading,
  prices, profiles and the scorer are the ground truth. Fix a genuinely broken
  task only in a separate, announced commit that re-runs every affected cell.
- Safety invariants: consult/review panels stay read-only; Maker, Checker and
  host are three model families; no sandbox-bypass flags; at most two fix
  rounds; cleanup requires merge proof; user model pins and billing settings
  win over defaults; unknown quota is never treated as free.
- No task-specific rules. Routing may use only what the router sees at run time
  (tier, kind, risk, ambiguity, mode, host family, quota).
- The unit tests and skill validator must pass after every kept change.

## The experiment loop

LOOP (until the user interrupts or every provider is at its quota floor):

1. Look at `results.tsv`, the per-profile table (`score.py profiles`) and the
   frontier (`score.py frontier`). Pick ONE idea with a clear hypothesis.
2. Edit the mutable surface. `git commit`.
3. Evaluate:
   - **Routing/evidence change → offline.** `python3 bench/score.py replay
     --tags <all current measurement tags>`. Free, instant, run as many as you like.
   - **Invocation/prompt change → live, paired.** Run the affected profiles on
     the dev tasks under a new tag: `python3 bench/run.py matrix --tag
     exp-<n> --profiles <affected> --split dev`, then compare against the same
     cells of the current baseline with `score.py profiles --tags <tag>`.
     Keep only if solves do not drop (allow one-task noise only when the lost
     task also fails in a baseline repeat) AND cost falls ≥ 10%, or solves rise
     at ≤ cost. Promote a kept tag to the measurement set for replay.
4. Record a row in `results.tsv` (do not commit it).
5. Keep → leave the commit. Discard → `git reset --hard HEAD~1`.
6. Run the unit tests after every kept code change.

**Simplicity criterion.** All else equal, simpler wins. A tiny cost gain that
adds special cases is not worth it; deleting configuration or code at equal
quality is a win.

**Noise.** Agentic runs are stochastic. Prefer paired comparisons on identical
tasks; repeat a cell before concluding that one flip matters; never promote a
change on a single task.

**Budget.** Live runs spend real subscription quota. `bench/run.py` refuses to
dispatch to a provider whose tightest live window is below its floor (Claude's
floor is highest because the host session shares it). Prefer offline
experiments; use the holdout split only once, at the end.

## Finishing

1. Freeze the configuration. Run the **holdout** split for the final routed
   profiles and replay with `--split holdout`; report both splits.
2. Run a few end-to-end `alloy execute` tasks with the final routing to confirm
   the component measurements compose (Maker + Checker + corrections).
3. Write up: what changed, measured quality/cost before and after, what did not
   work, and what to re-measure when models change.
