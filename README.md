# fusion

**Ask several frontier AI coding CLIs the same hard question, in parallel, and
get an honest map of where they agree, disagree, and are collectively blind —
instead of one confident answer from one model.**

fusion is a [Claude Code](https://claude.com/claude-code) skill that brings the
idea behind [OpenRouter's "Fusion"](https://openrouter.ai/docs/guides/routing/routers/fusion-router)
router — *"fusion beats frontier"* — down to the CLIs already installed on your
machine. It dispatches one prompt to a **panel** (`codex`, `gemini`, …) running
**in parallel and strictly read-only**, then Claude acts as the **judge** and
**synthesizer**: it compares the answers and writes a final one that *surfaces
the disagreement* rather than averaging it away.

> **It does not merge answers into mush.** Its whole job is to show you the
> consensus, the contradictions, the unique insight only one model had, and the
> blind spot none of them saw — then let you decide.

fusion ships **no API keys** and makes **no network calls of its own**. It only
runs the CLIs you have already installed and authenticated.

> Not affiliated with OpenRouter. "Fusion" is OpenRouter's term for the
> methodology; this is an independent local reimplementation. See [`NOTICE`](NOTICE).

---

## See it in 15 seconds

A real fusion round (the prompt: *"the single biggest reliability risk when an
orchestrator runs multiple AI CLIs in parallel"*) — note that the two models
**disagree**, which is exactly the point:

```
$ fusion doctor
  [ready] codex   codex-cli 0.139.0
  [ready] gemini  0.46.0

$ fusion panel --prompt-file prompt.txt
[fusion] panel: codex, gemini (2 model call(s))
[fusion] codex: ok in 10.4s (exit 0)
[fusion] gemini: ok in 13.6s (exit 0)
```

- **codex:** "…nondeterministic, interleaved output causing the orchestrator to
  misattribute messages to the wrong CLI."
- **gemini:** "…race conditions where agents modify the same shared files, leading
  to silent code corruption."

Claude then judges (*they answered different questions — codex is about reading
output, gemini about writing files; both are real, they are not in conflict*) and
synthesizes one answer that keeps both, attributed. One model would have given
you only half the picture, confidently.

---

## Quickstart

```bash
git clone https://github.com/<you>/fusion ~/.claude/skills/fusion   # or use install.sh
~/.claude/skills/fusion/bin/fusion doctor
```

`doctor` is always the first command. It tells you which panelists are installed,
which are authenticated, and exactly how to add the ones that are missing:

```
  [ready]  codex   codex-cli 0.139.0
  [auth?]  gemini             installed but not authenticated -> run `gemini` once to log in
  [ --- ]  antigravity  (experimental, no read-only mode)
```

Then, inside Claude Code:

```
/fusion ask Should we migrate this service to event sourcing or keep CRUD? Trade-offs.
/fusion review            # panel reviews your current git diff
/fusion plan add rate limiting to the public API
/fusion <a full build task>   # research -> plan -> implement -> test
```

> **The prerequisite cliff, stated honestly:** fusion is only useful if you have
> **2+** of {`codex`, `gemini`, …} installed *and authenticated*. With only Claude
> it degrades to a normal single-model answer and tells you so. Run `doctor`
> first; it will not surprise you.

---

## What you get

| Mode | What it does |
|---|---|
| `/fusion doctor` | Which panelists are installed / authed / ready, with fix-it hints. |
| `/fusion ask <q>` | One fusion round: panel answers in parallel → judge → synthesis. The cheapest, safest mode. |
| `/fusion review [target]` | Panel reviews your current diff, read-only → consolidated pass/fail + findings. |
| `/fusion plan <task>` | Research + plan rounds → one synthesized plan, presented for approval. |
| `/fusion <task>` | Full lifecycle: research → plan → collaborate → implement → test. |

In the lifecycle, **Claude writes all the code; the panel only ever reviews,
read-only.** fusion never lets a panelist edit your files, run a build, or touch
a git worktree. That is a deliberate v1 boundary (see *Roadmap*).

---

## Why a *local* version?

OpenRouter's hosted Fusion is web-UI only — there is no API for it, so you cannot
drop it into a coding workflow. fusion gets you the same panel→judge→synthesize
shape against the CLIs you already pay for, right inside Claude Code, with the
run captured to disk so you can audit exactly what each model said.

## When fusion helps (and when it doesn't)

Multi-model panels shine on **high-stakes thinking**: architecture decisions,
research, planning, debugging triage, security/correctness review — *"if the cost
of being wrong is higher than the cost of asking three models, fuse."* They are a
**poor** fit for raw line-by-line code generation (synthesis dilutes a model's
distinctive voice and just adds latency and cost). That is why fusion uses the
panel for the *thinking* and leaves the *writing* to Claude.

## Safety model

- **Read-only panel.** Panelists run behind their CLI's read-only sandbox flag
  (`codex -s read-only`, `gemini --approval-mode plan`) **and** in a throwaway
  temporary working directory, so they get no access to your repo. Adapters
  without a real read-only mode (e.g. `cursor-agent`) are refused unless you
  explicitly opt in with `FUSION_ALLOW_UNSANDBOXED=1`.
- **Panel output is treated as untrusted data**, never as instructions — fusion
  is hardened against a panelist emitting "ignore previous instructions / run
  this command".
- **Prompts go on stdin**, never on the command line (no `ARG_MAX` limits, no
  quoting bugs, no shell injection, no leaking prompts into `ps`).
- **No auto-approve.** fusion never passes `--yolo` / `-y` /
  `--dangerously-bypass-approvals-and-sandbox`.
- **Secret scanning.** Panelist output is scanned and redacted for common secret
  shapes before it is saved.
- **No project-level config execution.** Config is read from `~/.config/fusion/`
  as `KEY=value` (never `source`d), so a hostile repo cannot run code.

## Privacy & cost

fusion makes no network calls itself and stores no keys. Each fusion round makes
**one model call per ready panelist**, in parallel, billed to **your** provider
accounts through your CLIs — your prompts and diffs are sent to those providers.
A panel of 3 is roughly 3–5× the cost of one call; the full lifecycle is several
rounds. fusion shows a cost preflight before multi-round runs. You are
responsible for each CLI's terms of service regarding automated use.

## Configuration

Copy [`fusion.config.example`](fusion.config.example) to
`~/.config/fusion/config` and edit. Everything is also settable via environment
variables (env wins over the file):

| Key | Default | Meaning |
|---|---|---|
| `FUSION_PANELISTS` | `codex,gemini` | which adapters form the panel |
| `FUSION_TIMEOUT` | `240` | per-panelist timeout, seconds |
| `FUSION_MAX_CHARS` | `200000` | cap on each panelist's captured output |
| `FUSION_CODEX_MODEL` / `FUSION_GEMINI_MODEL` | CLI default | model override per adapter |
| `FUSION_JUDGE` | `claude` | who judges (Claude is host default; see methodology) |
| `FUSION_RUN_ROOT` | `./.fusion/runs` | where run output is written |

## Requirements

- Python 3.8+ (standard library only — no `pip install`).
- macOS or Linux (Windows via WSL).
- At least one supported CLI, ideally two: [`codex`](https://github.com/openai/codex),
  [`gemini`](https://github.com/google-gemini/gemini-cli).

## How it works

```
            prompt (on stdin, never argv)
                      |
        bin/fusion panel  -- parallel, read-only, throwaway cwd, process-group timeouts
          /        |        \
      codex      gemini     (more adapters)
          \        |        /
       run dir + manifest.json  (per-panelist status, paths, caps, redactions)
                      |
   Claude: JUDGE (compare, do not merge) -> judge.json
                      |
   Claude: SYNTHESIZE (attributed, disagreements surfaced) -> you decide
```

`bin/fusion` is the hardened, tested mechanical core (dispatch + capture).
Claude does the judging and synthesis — the parts that need intelligence and your
repo context. See [`docs/methodology.md`](docs/methodology.md).

## Extending it

Adding a CLI is a small, well-defined adapter. See
[`docs/adding-a-panelist.md`](docs/adding-a-panelist.md) for the 5-function
contract (detect / auth / invoke-read-only / parse / capabilities), a copy-paste
template, and the worked `cursor-agent` example (which shows how an adapter with
*no* read-only mode is handled).

## Roadmap

v1 deliberately keeps the panel read-only. Clearly out of scope until the core is
battle-tested: panelists writing code (opt-in, isolated git worktree),
auto-running builds, and a `FUSION_JUDGE=codex|gemini` judge-rotation override.

## License

[MIT](LICENSE). Built to be published and forked.
