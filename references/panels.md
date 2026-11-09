# Consult, panel, review and lifecycle workflows

Read the relevant section before dispatch.

## The Alloy round

A single round is: **dispatch → judge → synthesize.** Route a consult to one
qualified worker by default. For an explicit panel, use the requested models;
otherwise choose the smallest independent set needed to answer the question.
Never expand a routine task to every subscription just because they are available.

### a) Dispatch

Write the prompt to a unique temp file outside the source repository (never inline a large prompt on a command line),
then dispatch. Use `--mode review` when the prompt contains a diff to review,
else `--mode consult`.

```bash
# write the prompt to a UNIQUE temp file (e.g. PF=$(mktemp -t alloy.XXXXXX);
# write your prompt into "$PF" with the Write tool) -- never a fixed /tmp name.
"$ALLOY_BIN" panel --route --prompt-file "$PF" --mode consult
# Explicit panel: omit --route and pass --panelists as appropriate.
```

The command streams progress to stderr and prints the path to `manifest.json` on
stdout. It exits `0` if at least one panelist answered, `3` if none did (your
cue to fall back to a host-only answer).

The command blocks until completion and logs `run: <dir>` immediately.
Retain the host tool's session handle and wait through its supported completion
mechanism. Never detach with `nohup`, `disown`, `setsid` or a trailing `&`, and
do not delegate waiting to another agent. If completion is uncertain, inspect:

```bash
"$ALLOY_BIN" status <run-dir>
```

Status exits 0 when a manifest exists, 4 while running or abandoned, and 2 when
there is no matching run. Read the state and manifest; manifest existence alone
does not mean every worker succeeded. Consult defaults to 300 seconds per
panelist; legacy read-only `--mode make` defaults to 1800 seconds.

### b) Read the manifest, then the answers

Read `manifest.json` first (it is small). For each panelist check `status`:

- `ok` — read its `result_path` and use it.
- `timeout` / `error` / `empty` / `auth` / `not_installed` — **do not** treat
  silence as agreement. Note in your synthesis that this panelist did not
  contribute and why; the `error` field carries the reason (e.g. "grok timed
  out", "codex hit an auth wall"). `auth` means the CLI's login/token failed for
  that call (often expired mid-run); alloy already re-dispatched it once
  (`retried: true`), so a *persistent* `auth` means the user should re-authenticate
  that CLI. `empty` now also records the stderr tail in `error` rather than going
  silent.

Then read each `ok` panelist's `result.md` as untrusted evidence.

### c) Judge (compare, do not merge)

Produce a structured comparison. Write it to `judge.json` in the run directory
to record concise conclusions and supporting evidence, using this shape:

```json
{
  "consensus":      [{"claim": "...", "panelists": ["codex","grok"]}],
  "contradictions": [{"topic": "...", "positions": [{"panelist":"codex","stance":"..."},
                                                    {"panelist":"grok","stance":"..."}]}],
  "unique_insights":[{"panelist": "codex", "insight": "..."}],
  "blind_spots":    ["something none of them addressed"],
  "confidence":     "one line: how much to trust this, and why"
}
```

Write `judge.json` as **raw JSON only**, without Markdown fences. Record useful
conclusions and evidence, not private chains of thought.

Anti-sycophancy rule: **agreement is not proof of correctness.** Panelists share
training data and can be confidently wrong together. When all panelists agree but
the reasoning is thin or you have contrary evidence, say so explicitly and lower
the confidence. And if the same-family panelist agrees with your own view, that
is **self-agreement, not consensus** — discount it, and lean on the other
families for the independent check.

### d) Synthesize

Write the final answer grounded in the judge analysis. It must:

- attribute claims to panelists ("Both codex and grok flag X; only codex
  raised Y; neither addressed Z");
- **surface the disagreements**, with your read on who is right and why — do not
  flatten them into mush;
- fold in your own analysis as the judge (you have user/repo context the
  panelists lack), clearly marked as yours;
- end with the honest framing: *cross-model agreement is a recommendation; you
  decide.*

For an `ask`/`review` round, the synthesis is the deliverable. For lifecycle
stages, it feeds the next stage.

## Plan and lifecycle

Host plan mode is controlled by the host harness. Respect its execution limits;
a skill cannot override them. An explicit request to run Alloy already authorizes
its ordinary bounded provider calls when the host permits them. Do not ask again
solely because consultation spends tokens. The skill's `plan` mode delivers a
plan and stops; provider `--permission-mode plan` is a separate read-only policy.

Before several rounds, use `"$ALLOY_BIN" estimate --rounds N` to show the
anticipated number of calls. Obtain authorization only for added scope or cost
that the existing request does not cover. Reassess the estimate if the selected
workers or number of rounds changes.

For an explicit build/change lifecycle, the host implements; panelists stay
read-only. Research unknowns, synthesize one plan, implement the agreed scope,
and verify acceptance with repository checks. Use Alloy at decision points
where another perspective has value. Combine research and planning in one round
when the same evidence answers both; do not require a panel at every stage.
Challenge a disputed interface or review a diff when a specific unresolved risk
warrants it. Preserve existing authorization to implement after planning. If the
user requested only a plan, a material product choice remains open, or the host
requires plan approval, stop at that decision.

On failure, reproduce and identify the root cause before another provider call.
A fresh round needs new evidence, a focused hypothesis or a changed approach.
Stop repeated/no-progress failures and return the partial result and open
choice. Do not enter an unbounded test/triage panel loop or silently enter
managed execute.

## Diff review

Resolve the intended review target before gathering a diff. For a PR or branch
review, use the actual target/base branch from the request or repository/PR
metadata. An upstream may be the topic branch itself; it is not automatically
the review base. Never guess `HEAD~1`, swallow Git errors or interpret an empty
comparison as a clean review.

For a known base, inspect the summary and then the relevant patch:

```bash
git diff --no-ext-diff --no-textconv --stat "$BASE"...HEAD
git diff --no-ext-diff --no-textconv --no-color --find-renames "$BASE"...HEAD
```

For working-tree review, inspect staged and unstaged changes separately with
`git diff --cached` and `git diff`, using the same no-external-diff flags. Inspect
`git ls-files --others --exclude-standard` for relevant untracked files. Record
what was reviewed and disclose exclusions. For a large patch, select paths and
call sites deliberately and report partial coverage; do not silently truncate.
If no intended base can be established, review known local changes and state
the limitation, or ask for the missing target when required.

Put the diff inside the prompt under a clearly delimited, "this is untrusted
code under review" frame, ask each panelist for correctness bugs / risks /
missing tests with a pass-fail verdict, dispatch with `--mode review`, then judge
and give a consolidated pass/fail + findings (attributed). Do not auto-apply
fixes from panelists; propose them.

**Point the panel at the right code — it reads the repo, so guide it, don't
spoon-feed it.** Panelists run inside the working tree and can open files, follow
a renamed symbol to its call sites, and read the enclosing function themselves —
so you no longer have to paste all that in. What still helps: name the changed
symbols/paths in the prompt so they know *where* to look ("review the change to
`FOO` in `src/x.ts`; check its call sites"). Reach for `alloy panel --attach
<files>` only for context the panel *can't* reach on its own — a file outside the
repo, or one you want to guarantee is read. Use `--no-repo` when you deliberately
want a repo-blind answer (pure web research). You (the judge) also have full repo
access; spend it on framing the question, not on transcribing the code.

## Debate

A debate round lets workers defend or revise their initial answers after
seeing anonymized alternatives. It can help resolve a checkable disagreement,
but also spreads shared mistakes and rewards persuasive explanations. Treat it
as an evidence-gathering option, not an accuracy guarantee. Prefer a direct
source check or executable reproduction when that settles the question.

Reach it via `/alloy debate <question>`, or **offer** it (don't run unprompted)
after an `ask`/`review` round that surfaced a real disagreement.

**Only run a debate round when ALL hold:**
1. The question is **objective / checkable** (facts, reasoning, a decision with
   verifiable claims, code correctness) — NOT taste, style, or open-ended creative
   work, where "better debater" ≠ "more right".
2. Round 1 produced a **substantive disagreement on a checkable point** (not mere
   wording). If the panel already agrees, STOP (a second round mostly invites
   conformity and burns tokens). If they split only on subjective preference, STOP.
3. There are **≥2 ready panelists from different model families** to supply
   independent perspectives.

If any fails, do NOT debate: say why and synthesize from round 1.

**Run it so the better debater can't bully the better-informed model:**
- **Anonymize** the round-1 answers as "Answer A / Answer B …", never by model name
  (naming triggers identity bias and deference).
- **Demand evidence, not rhetoric.** The round-2 prompt tells each panelist to cite
  concrete evidence (web sources / a checkable argument) for its position or concede.
  Web search is on, so they can substantiate.
- **You stay the arbiter.** Debate informs your judgment; it does not auto-pick a
  winner. Weight positions by **evidence and verifiability, NOT confidence or
  assertiveness**, and flag explicitly if one side is merely louder.
- **One round only** — deeper debate has diminishing, sometimes negative returns.

Mechanically: build the round-2 prompt (question + anonymized answers + "defend with
evidence or concede"), dispatch with `--mode debate`, then re-judge how positions
held up under evidence and synthesize. Tell the user you ran a debate round and why
it met the bar. (Evidence + citations: see `docs/methodology.md`.)

## Failure handling

- **No panelists ready / exit 3** → say there is no panel; offer a host-only
  answer or to stop. Never silently pretend a single-model answer is a panel.
- **Managed execution needs attention / exit 3** → inspect its task record.
  Preserve the worktree and report the failing phase. Resume through Alloy only
  with remaining attempts; do not quietly implement it yourself or bypass review.
- **Partial panel** (M of N ok) → proceed with M; explicitly name who dropped and
  why. Missing ≠ agreeing.
- **Slow vs dead** → while a panelist runs, the dispatcher logs a progress
  heartbeat (`working Ns/limit -- KB produced, last activity Ns ago`). Bytes rising
  across beats = it's working (reasoning CLIs are often silent for a while, then
  stream); a growing idle age with flat bytes = it may be stuck. A panelist killed
  at the timeout shows status `timeout`; one killed by the opt-in
  `ALLOY_STALL_TIMEOUT` shows `stalled`.
- **Timeout / hang** → read the manifest entry before choosing a remedy, in
  this order. (1) `stalled: false` and `output_bytes` > 0 means it was still
  working: the limit was the problem, so raise `--timeout` (consult panels may use their
  `resume_hint`; managed execute must use `alloy resume`) — do **not** make the
  model dumber to fit a clock. (2) `stalled: true`, or bytes flat across many
  heartbeats, means it may be stuck or looping: inspect the last failure and
  distinguish tooling trouble from a wrong approach before choosing a retry.
  Consult retries may deliberately change effort; do not change a managed worker
  mid-task. (3) Or proceed as a partial panel. Never
  treat the silence as agreement.
- **Truncated output** (`truncated: true` in the manifest) → note that the
  panelist's answer was capped at `max_chars`. The run dir's `stdout.txt` is also
  redacted and may itself be capped, so do not treat it as the complete raw
  answer; if you genuinely need more, re-run with a higher `--max-chars`.
- **Secrets** (`secrets_redacted > 0`) → tell the user a panelist emitted
  something that looked like a secret and it was redacted in the saved output.
