# Changelog

All notable changes to Alloy are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.1.10] - 2026-08-12

### Changed
- **Default agy model is `gemini-3.6-flash-high`** — the latest Gemini family
  seat, so the panel gets that family's current perspective rather than the
  older 3.1 Pro. `ALLOY_ANTIGRAVITY_MODEL=gemini-3.1-pro-high` restores the
  previous default; `gemini-3.6-flash-low` remains the cheap/fast option.

## [0.1.9] - 2026-08-12

### Changed
- **Grok's documented default is `grok-4.6`.** xAI shipped Grok 4.6 (500k
  context, agent/coding flagship) and the Grok CLI (1.0.3) made it the default.
  Alloy still leaves `ALLOY_GROK_MODEL` unset so a panel already picks up the
  CLI default — this release just corrects the stale docs/comments that still
  named `grok-4.5`. `grok-4.5` remains available as the previous generation via
  `ALLOY_GROK_MODEL`. `grok-composer-2.5-fast` is gone from `grok models`.
- **Host-agnostic judge.** The skill no longer assumes the host is Claude.
  Judge + synthesizer is whoever invoked `/alloy` (Claude Code, Grok, Codex, …).
  Self-preference is now "do not favor your own family": a Grok host must not
  treat the `grok` seat as confirmation of itself, a Claude host must not treat
  the `claude` seat that way. Zero-panelist fallback is "host-only", not
  "Claude-only". This was a real correctness bug when the skill ran under Grok.
- **Model catalog refresh.** Codex example is `gpt-5.6-sol` (the old
  `gpt-5.2-codex` example is sunset). Claude aliases now mention `fable` /
  `opus` / `sonnet`. agy still defaults to `gemini-3.1-pro-high` (strongest
  Gemini; Claude 4.6 / GPT-OSS on agy would duplicate other panelists) and
  documents `gemini-3.6-flash-*` as the cheap/fast seat.
- **`install.sh` also links into `~/.grok/skills/alloy`** when `~/.grok` exists,
  so Grok Build finds the skill without relying on the Claude skills directory.
  `SKILLS_DIR=/path ./install.sh` still installs only to that path.

### Tests
- Grok leaves `-m` off unless `ALLOY_GROK_MODEL` is set; override pins
  `grok-4.5`. Zero-panelist fallback note must say `host-only`.

## [0.1.8] - 2026-07-25

### Added
- **Antigravity (`agy`) is a first-class, read-only panelist on agy >= 1.1.0** —
  Gemini 3.x joins the default panel with no opt-in. agy 1.1 changed its headless
  permission model: print mode can no longer prompt, so any tool **outside**
  `permissions.allow` is **auto-denied** instead of auto-executed. Verified live
  against agy 1.1.7 — asked to write a file, the run fails closed with
  `write_file` denied; asked to run a shell command, `command` denied; reads still
  work. Alloy turns that into enforcement with three layers:
  1. a generated `settings.json` allow-listing **read tools only**
     (`read_file`, `grep_search`, `list_dir`, …) and explicitly denying the write
     and shell tools;
  2. an **alloy-owned HOME** (`$XDG_STATE_HOME/alloy/agy-home`) so those settings
     are ours and never the user's, and agy's scratch dir, conversations and
     caches stay out of `~/.gemini`. Auth is **symlinked**, never copied, so no
     token is duplicated to disk. `ALLOY_ANTIGRAVITY_HOME=run` gives a throwaway
     HOME per run instead (costs ~13MB and ~6s of re-unpacking each time);
  3. repo access granted explicitly with `--add-dir <repo>` plus
     `allowNonWorkspaceAccess: false`, because agy ignores the process cwd.
  `--dangerously-skip-permissions` is never passed — it would disable layer 1.
- **`ALLOY_ANTIGRAVITY_EFFORT`** (`low`/`medium`/`high`) and
  **`ALLOY_ANTIGRAVITY_HOME`** (`run`, or a path).
- **Adapters can supply child-process env overrides** (`Adapter.prepare_env`) and
  receive run context in `build_args` (`repo`, `pdir`, `cwd`, `timeout_s`).

### Changed
- **Default agy model is `gemini-3.1-pro-high`** — the strongest model agy exposes,
  and fast in practice (~6-14s per panel answer against ~30-120s for the others).
  `agy models` lists the alternatives; `ALLOY_ANTIGRAVITY_MODEL=gemini-3.6-flash-low`
  for a cheap/fast panel seat.
- **agy's prompt is staged as a FILE**, not stdin: agy 1.1.7 ignores stdin in print
  mode, so the prompt is copied to `<run>/antigravity/prompt_in/prompt.md`, that
  directory alone is granted with `--add-dir`, and only a pointer to it reaches
  argv. The "no prompt on argv" invariant (ARG_MAX, `ps` leakage, quoting) holds.
- Alloy passes its own per-panelist deadline through as `--print-timeout`, so agy's
  hidden 5-minute default can't cut a longer run short.

### Security
- **An OLD agy (< 1.1.0) is still refused.** On those releases print mode
  auto-executes every tool; the adapter reports `read_only = False` +
  `experimental` and the engine skips it unless `ALLOY_ALLOW_UNSANDBOXED=1`, exactly
  as before. `read_only` is now derived from the **installed CLI version**, not
  assumed.
- Do **not** set `toolPermission: "strict"` in agy's settings: it overrides the
  allow-list and denies the read tools too, producing a panelist that can never
  answer. Documented in the adapter so it is not "fixed" later.
- With `ALLOY_WEB=0`, agy's web tools are added to the deny list.

## [0.1.7] - 2026-07-09

### Changed
- **Grok now dispatches `grok-4.5` by default.** xAI shipped `grok-4.5`, their
  opus-class flagship, and the Grok CLI made it the default model. Alloy uses each
  CLI's own default, so a panel already picks up `grok-4.5` with no config — this
  release just corrects the stale docs/comments that still named the old default
  (`grok-composer-2.5-fast`) and a `grok-build` model that no longer exists.
  `grok-composer-2.5-fast` remains available as a cheaper option via
  `ALLOY_GROK_MODEL`; run `grok models` to see what your account can reach.
- **Antigravity (`agy`) print mode carries a best-effort `--mode plan` hint.**
  agy 1.0.16 adds a headless `--mode plan`; alloy now passes it to steer the model
  toward analysis over edits (what a consult panel wants).

### Security
- **Antigravity stays `read_only = False`, experimental, and refused by default.**
  Re-verified against agy 1.0.16: `agy -p --mode plan` is **not** an enforced
  read-only mode — asked to write a file it still called `write_to_file` and
  created it on disk, in agy's own scratch dir (`~/.gemini/antigravity-cli/scratch`),
  ignoring the process cwd. So `--mode plan` is an intent hint only; the adapter
  still runs only under `ALLOY_ALLOW_UNSANDBOXED=1`. Prefer a real read-only
  panelist (codex / grok / claude).

### Tests
- `test_antigravity_runs_unsandboxed_print_mode` now asserts the `--mode plan`
  hint is present (and the bypass flag still absent).

## [0.1.6] - 2026-06-26

### Changed
- **The panel now READS your repository by default.** This is a deliberate change
  to the safety posture: a read-only panel that can't see your code gives weak
  coding answers. Read-only adapters (codex, grok, claude) now run with their cwd
  set to your **real working tree** (live, including uncommitted edits), so they
  can ground answers in the actual code. Their CLI read-only flag
  (`codex -s read-only`, grok/claude `--permission-mode plan`) is what prevents
  writes — **best-effort, not a hard sandbox**. Repo auto-detects the git root of
  the invoking directory.

### Added
- **`--repo PATH` / `ALLOY_REPO`** to pin the readable directory; **`--no-repo` /
  `ALLOY_REPO=none`** restores the old zero-access throwaway cwd (use it for pure
  web research or maximum caution).
- **Write-capable adapters never touch your tree.** The opt-in non-read-only
  adapters (antigravity, cursor-agent, opencode) get a **disposable copy** of the
  repo (`.git` and heavy/regenerable dirs excluded) instead of the real one, so
  their writes land off your working tree.
- **Tamper tripwire.** alloy fingerprints the working tree (`git status` + HEAD)
  before and after the run; if a "read-only" panelist somehow modified it, the
  manifest (`summary.repo_tamper`) and the matrix scream about it. Per-panelist
  `repo_access` (`real`/`copy`/`none`) and `cwd` are recorded in the manifest.

### Tests
- +4 cases: real-repo access for read-only adapters, `--no-repo` isolation,
  disposable copy (with `.git` excluded) for write-capable adapters, git-root
  auto-detection. 52 pass.

## [0.1.5] - 2026-06-25

### Fixed
- **A transient panelist auth-refresh race no longer surfaces as a silent empty
  voice.** When a CLI's OAuth access token expired exactly at dispatch, it could
  fail that one call (`worker quit … Auth(AuthorizationRequired)`) yet still exit
  0 with empty stdout — so the panel silently dropped from 3 voices to 2 with no
  signal, even though the very next call would have succeeded (the failed call
  refreshes the token as a side effect). Observed with `grok` 0.2.54; the cause
  is generic to any OAuth-token CLI.

### Added
- **`auth` status + legible empties.** The classifier now scans stderr on an
  empty result: an auth marker (`AuthorizationRequired`, `Unauthorized`, `401`,
  `invalid api key/token/credentials`, …) is classified `auth` with the reason in
  `error`; a genuine blank is still `empty` but records the stderr tail in `error`
  instead of going silent. Scoped to stderr so a model *discussing* auth is never
  misclassified.
- **Single self-healing retry (`ALLOY_RETRY`).** A panelist whose first attempt
  hit a retryable status is re-dispatched exactly **once** (never a loop); the
  token refresh has almost always landed by then, so the retry runs on a fresh
  token. Default `auth`; set `ALLOY_RETRY="auth,empty"` to also re-ask blank
  answers, or `ALLOY_RETRY=0` to disable. The retry result carries `retried: true`
  and `first_attempt_status`; first-attempt artifacts are kept under
  `<panelist>/_retry`'s parent for debugging.

### Tests
- +5 cases: auth classification, stderr-tail surfacing on empty, retry recovers a
  transient auth failure, blanks aren't retried by default, retry disable. 48 pass.

## [0.1.4] - 2026-06-19

### Changed
- **Swapped the Gemini CLI for Google's Antigravity CLI (`agy`).** The
  `gemini` adapter is removed and replaced by an `antigravity` adapter that
  drives the `agy` binary headlessly (`agy -p`, prompt on stdin).
- **`antigravity` ships as a non-read-only, opt-in adapter** (`read_only = False`,
  experimental — same bucket as `cursor-agent`). It is **refused by default** and
  runs only when `ALLOY_ALLOW_UNSANDBOXED=1`. Reason: `agy` has **no enforceable
  headless read-only mode** — its only non-interactive entry point, print mode,
  auto-executes file-writes *and* arbitrary shell regardless of `--sandbox`,
  `toolPermission: strict`, or `permissions.deny` (all three verified ignored in
  print mode against `agy` 1.0.10). Model override via **`ALLOY_ANTIGRAVITY_MODEL`**.
- **Default panel no longer includes a Google model.** With `ALLOY_PANELISTS`
  unset, the panel is the verified read-only set that is installed + authed
  (codex, grok, claude). Add `antigravity` explicitly (plus
  `ALLOY_ALLOW_UNSANDBOXED=1`) to include it.

### Tests
- Harness default panel pinned to `codex,claude`; mock impersonates codex +
  claude; added `antigravity` adapter cases (refused-by-default, opt-in `-p`
  dispatch with no bypass flag, model override). 43 pass.

## [0.1.3] - 2026-06-17

### Added
- **`claude` panelist — the host's own model in the panel.** A fresh, independent
  `claude` (Claude Code) instance now runs as a read-only panelist
  (`-p --permission-mode plan`; `-p` skips the workspace-trust dialog), with model
  selection via **`ALLOY_CLAUDE_MODEL`**. This is deliberate "self-fusion" (in
  OpenRouter's data a model fused with itself still gains lift) and makes the panel
  a complete set of available models.

### Changed
- **Default panel is now the complete set of available models.** With
  `ALLOY_PANELISTS` unset, the panel is every verified, read-only, non-experimental
  adapter that is installed + authenticated (codex, gemini, grok, claude) — it
  auto-includes new adapters instead of a fixed `codex,gemini` list. Set
  `ALLOY_PANELISTS` to pin a narrower / cheaper panel.
- **Judge guidance hardened** for the case where Claude is *both* a panelist and
  the judge: treat the `claude` panelist as one anonymized voice, never
  self-prefer, and count agreement with it as self-agreement (not consensus).

### Tests
- Test harness now pins `ALLOY_PANELISTS=codex,gemini` so the "all available"
  default can't spawn real CLIs installed on a contributor's machine; +2 `claude`
  adapter cases. 40 pass.

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
