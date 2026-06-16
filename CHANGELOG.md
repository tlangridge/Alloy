# Changelog

All notable changes to Alloy are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.1.2] - 2026-06-16

### Added
- **Grok CLI adapter** (`grok`, xAI). Verified read-only via `--permission-mode
  plan`; headless, web-search-aware (`--disable-web-search` when `ALLOY_WEB=0`),
  with model selection via `ALLOY_GROK_MODEL` (`grok-build` /
  `grok-composer-2.5-fast`). Registered and opt-in — add `grok` to
  `ALLOY_PANELISTS` to include it in the panel.

### Changed
- Adapter `build_args` now receive the prompt-file path, so a CLI that reads its
  prompt from a file (like Grok's `--prompt-file`, which doesn't accept stdin) is
  supported alongside the stdin-based panelists.

## [0.1.1] - 2026-06-16

### Fixed
- **Codex timeouts from an inherited `xhigh` reasoning effort.** A panel run used
  to inherit the global `model_reasoning_effort` from `~/.codex/config.toml`; an
  `xhigh` default routinely exceeded the 240 s timeout on heavy prompts. The codex
  adapter now pins effort to `high` by default (`-c model_reasoning_effort=high`),
  configurable via **`ALLOY_CODEX_EFFORT`** (`medium` / `high` / `xhigh`, or
  `inherit` to use your codex config).
- **Partial output on timeout is no longer discarded** — codex streams its preamble
  to stderr, so `parse()` now falls back to stderr when the final message and
  stdout are both empty.
- **Misleading `(exit 0)` on a timed-out panelist** — the log now reads
  `timeout after Ns (killed)` instead of showing a 0 exit code.

### Added
- **Progress-aware heartbeat:** a long-running panelist logs `working Ns/limit --
  KB produced, last activity Ns ago` (every `ALLOY_HEARTBEAT`, default 30 s), so
  rising bytes mean it's working and a growing idle age means it may be stuck.
- **Opt-in stall kill** (`ALLOY_STALL_TIMEOUT`, off by default): kill a panelist
  that produces no new output for N seconds — off by default because reasoning
  CLIs are legitimately silent while thinking, so silence is not a reliable
  "dead" signal. A stall-killed panelist gets the distinct status `stalled`.
- Default per-panelist timeout raised 240 → **300 s** (a panel runs in parallel,
  so it's the max, not the sum), and `output_bytes` is recorded per panelist.

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
