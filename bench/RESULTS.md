# Alloy autoresearch — results (September 24–25, 2026)

Branch `autoresearch/sep24`. Method: [program.md](program.md), after Karpathy's
autoresearch: a frozen evaluator (`bench/`), one change at a time, keep only
changes that hold quality and cut cost, log every experiment
(`results.tsv`, untracked). Routing is scored by replaying production
`resolve()` against measured outcomes, using the real Jev classifier's answers.

## Headline

| | Before (master) | After (this branch) |
| --- | --- | --- |
| Routed `alloy execute` for a Claude host | Maker = agy, which could not run its tests on agy 1.2 (fails every task); large Checker = `gpt-6-sol`, rejected for ChatGPT-account Codex | Holdout coding tasks **12/12** (Gemini Maker, Luna Checker; the Codex-host Claude Checker is unmeasured) |
| Grok as panelist | 1/12 dev reviews/consults answered (turn cancelled mid-answer) | 11/12 |
| Claude as panelist/worker | $5.99 list-price for 10 dev tasks | $1.98 (−67%), quality within noise |
| Claude Checker verdicts accepted | 8/12 correct reviews | 12/12 |
| Routed consult accuracy (Jev) | 0.67 | 0.83 |
| Overall cost per solved task (replay, dev, Jev) | $0.377 with a working Checker | **$0.251** at equal quality (0.917) |
| **Holdout (24 unseen tasks)** | — | **q 0.917, $0.183/solve [0.128, 0.244]; every gate passes** |

## Kept changes

| Round | Change | Evidence |
| --- | --- | --- |
| smoke | agy ≥1.2 managed Maker: grant `command(*)` in the new permission grammar | Maker returned empty (auto-denied); fixed → passes |
| smoke | Grok Maker: explicit `Edit`/`Write` allow rules | turn cancelled at first edit, 3 wasted rounds; fixed → passes in 1 |
| r1 | Claude lean context (`--strict-mcp-config --disable-slash-commands --setting-sources project,local`; `ALLOY_CLAUDE_LEAN=0` opts out) | paired 10 tasks: cost −67%, wall −24%; flips explained (format bug both ways; 1/4 consult miss) |
| r2 | Accept exactly one verdict object wrapped in prose; receipt still required | offline regrade 4/6 → 6/6; live 6 reviews old 4/6 → new 6/6; conflicting/absent verdicts still fail closed |
| r3 | Grok read-only panels: read-only tool whitelist + pre-approved `WebFetch` | cancelled turns 11/12 → 1/12; solved 1/12 → 11/12 |
| r4 | `policy.min_tier_by_mode = {consult: medium}` | Jev tier accuracy 40%; repo questions under-rated; consult q 0.67 → 0.83, cost/solve $0.105 → $0.062 |
| r5 | Ship `gpt-6-sol` disabled; `tier_by_mode {review: large}` for Luna and Gemini Flash Low | gpt-6-sol: "not supported when using Codex with a ChatGPT account"; reviewers Luna 5/6 $0.01, Flash Low 6/6 $0.03 vs Sol 5/6 $0.38; overall cost/solve −33% |
| — | Opt-in `policy.quota_pacing` (price quota by reset time; host CLI exempt) | unmeasurable by the bench; off by default |
| — | `ALLOY_CAPTURE_USAGE=1` provider-reported token usage | prerequisite for every cost number here |

## Tested and rejected

- **Execute cascade** (cheap Maker, escalate on gate failure): costlier at equal quality.
  The visible gate caught only 15/28 failures (13 of 69 "green" results failed hidden
  tests), and cheap models fail slowly and expensively on hard tasks.
- **Lower `confidence_floor`** (.6/.5/.3): quality down and cost up at every setting.
- **Large-tier consult floor**: same quality as medium, higher cost.
- **Grok ranked cheap** (q 0.56), **Luna as a large Maker** (gate fail),
  **Sol preferred as large Maker via a lower rank** (one task better on dev; not justified
  by its quota cost).

## Measured profiles (dev split, list-price USD per task)

| Profile | Make (12) | Review (6) | Consult (6) | Make $/task | Notes |
| --- | --- | --- | --- | --- | --- |
| Codex gpt-5.6-sol high | **12/12** (+12/12 holdout) | 5/6 | 5/6 | 0.57 | only perfect coder |
| Codex gpt-5.6-luna medium | 10/12 | 5/6 | 0.75 | **0.02** | cheapest by far; ~$10 list per Codex weekly point |
| Gemini 3.8 Flash high (agy) | 11/12 (+12/12 holdout) | 6/6 | 5/6 | 0.42 | default large Maker |
| Gemini 3.8 Flash low (agy) | 10/12 | **6/6 at $0.03** | 3/6 | 0.40 | small tasks 4/4 at $0.06; flails on large |
| Gemini 3.6 Flash high (agy) | medium 3/4 | 1/2 | 0.75 | 0.19 | default medium Maker |
| Gemini 3.1 Pro high (agy) | 8/12 | 5/6 | **6/6** | 0.29 | |
| Claude Sonnet 5 (lean) | 4/4 measured | 8/9 | 0.83 | 0.24 | Claude quota not spent further |
| Grok 4.7 (after fix) | 5/12, slow (20-min timeouts) | 6/6 | 5/6 | 0.37 | heavy reasoning at default effort |
| Opus 4.6 via agy | 10/12 | 3/6 | 3/6 | 0.49 | Checker returns before its subagent; agy 3p pool is small |
| GPT-OSS 120B via agy | 2/12 | 1/6 | 0/6 | 0.05 | unreliable |

Quota exchange (list-price USD absorbed per weekly point, rough, 1% meter
resolution): Gemini via Antigravity ≈ 14, Codex ≈ 10, Claude ≈ 9.5, Grok ≈ 1.5,
Antigravity Claude/GPT pool ≈ 0.7. Plan-specific: tune a private config, not the
shipped defaults.

## Also found

- A `gpt-6-sol` model pin breaks the Codex panelist for ChatGPT-account users
  (this machine's pin was moved to `gpt-5.6-sol`; backup kept).
- Grok panelists still cancel when the model reaches for a tool from the user's own
  grok MCP servers; grok has no per-call switch to drop them.
- Jev rates code-comprehension questions by their text; their difficulty lives in the
  repository (see the "scouting" literature). A repo-aware assessment is future work.

## Open items

1. Measure Claude Opus as the large Checker for Codex hosts (the one unmeasured
   routed choice; skipped to preserve Claude quota).
2. Lower-effort Grok and `gpt-5.6-sol`/`xhigh` profiles; Codex/Grok context trimming
   (≈19k / 44k tokens of per-call overhead).
3. Record real execute outcomes to learn per-(kind, tier) success online.
4. Re-run when models change: `python3 bench/validate.py`, the matrix for new
   profiles, then `score.py replay --answers bench/results/jev-answers.json`.

## Reproduce

```sh
python3 bench/validate.py                         # 48 tasks, offline
python3 bench/run.py quota                        # live headroom vs floors
python3 bench/run.py matrix --tag X --profiles P --split dev
python3 bench/score.py replay --tags <tags> --answers bench/results/jev-answers.json
```
