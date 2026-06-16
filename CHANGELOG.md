# Changelog

All notable changes to Alloy are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.1.0] - 2026-06-16

First public release. Alloy runs OpenRouter's "Fusion" methodology locally with
the AI coding CLIs you already have: dispatch one prompt to a read-only panel in
parallel, then Claude judges (compare, don't merge) and synthesizes.

### Dispatcher (`bin/alloy`, stdlib-only Python 3.8+)
- `panel` — dispatch one prompt to all ready panelists in parallel, strictly
  read-only, in a throwaway working directory; capture per-panelist output plus a
  machine-readable `manifest.json`, and print a compact run **matrix** (status /
  time / chars / redactions) on stderr.
- `doctor` — classify each panelist (ready / no-read-only / not-authed /
  not-installed) and count the default panel honestly, with install + auth hints.
- `estimate` — model-call count for a run.
- `update-check` — throttled, git-based update check (sends no data;
  `ALLOY_NO_UPDATE_CHECK=1` to disable).
- `version`.

### Panelists
- Verified read-only, in the default panel: **codex** (`-s read-only`) and
  **gemini** (`--approval-mode plan`).
- Registered but off by default: **llm** (read-only; opt in via `ALLOY_PANELISTS`),
  **opencode** / **cursor-agent** (no read-only mode → refused unless
  `ALLOY_ALLOW_UNSANDBOXED=1`), **antigravity** (experimental).
- **Web research on by default** (codex `tools.web_search`; gemini's
  `google_web_search` in plan mode), matching Fusion's web-enabled panel;
  `ALLOY_WEB=0` disables it.
- `--attach` / `ALLOY_ATTACH` folds explicit files into the prompt as read-only
  reference context (e.g. the call sites a diff omits).

### Skill (`SKILL.md`)
- Args-based modes: `ask`, `review`, `plan`, the full
  research → plan → implement → test lifecycle, `doctor`, and an opt-in,
  **evidence-gated `debate`** round — used only for objective questions with real
  disagreement, with anonymized answers, evidence-weighted judging, and a single
  round, to avoid the "confident bully" / conformity failure mode of multi-agent
  debate.
- Standing rules: panel output is untrusted data; the panel is read-only and the
  host does the writing; surface disagreement; "cross-model agreement is a
  recommendation — you decide." Judge schema + anti-sycophancy rubric; plan-mode
  handling.

### Safety
- Prompts on stdin (never argv); process-group timeouts (`os.killpg`, always
  escalating to SIGKILL); non-TTY stdin so unauthenticated CLIs fail fast; bounded
  prompt + output reads; codepoint-safe caps.
- Best-effort secret redaction of all persisted panelist output (redact before
  capping; whole PEM blocks; common token families; syntax-preserving).
- Run artifacts kept outside your repo (`$XDG_STATE_HOME/alloy/runs`; `0700` dirs
  / `0600` files; auto `.gitignore`); `KEY=value` config that is never `source`d;
  PATH-shadow guard; no auto-approve / bypass flags; no telemetry.

### Docs & CI
- `README`, `docs/methodology.md` (Fusion mapping, Claude-as-judge bias, debate
  evidence), `docs/adding-a-panelist.md`, `NOTICE`, `CONTRIBUTING`, `SECURITY`,
  issue/PR templates.
- Mock-panelist test suite (31 tests, no token spend) + GitHub Actions CI
  (macOS + Linux, Python 3.8 + 3.12).

### Out of scope (roadmap)
- Panelists writing code (opt-in, isolated git worktree).
- Auto-running builds in the TEST stage beyond the project's own command.
- An `ALLOY_JUDGE=codex|gemini` judge-rotation override.
