# Changelog

All notable changes to alloy are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.1.0] - 2026-06-15

Initial release.

### Added
- `bin/alloy`: stdlib-only Python 3 dispatcher.
  - `panel` — dispatch one prompt to all ready panelists in parallel, read-only,
    in a throwaway working directory; capture per-panelist output and a
    machine-readable `manifest.json`.
  - `doctor` — classify each panelist as ready / installed-but-not-authed /
    not-installed, with install and auth hints.
  - `estimate` — print the model-call count for a run.
  - `version`.
- Verified adapters: `codex` (`-s read-only`), `gemini` (`--approval-mode plan`).
  Experimental, off-by-default: `antigravity`.
- Safety: prompts on stdin (never argv); process-group timeouts with
  `os.killpg`; non-TTY stdin so unauthenticated CLIs fail fast instead of
  hanging; codepoint-safe output caps; secret redaction of panelist output;
  `KEY=value` user-level config that is never `source`d; refusal to dispatch to
  adapters lacking a real read-only mode unless `ALLOY_ALLOW_UNSANDBOXED=1`.
- `SKILL.md`: the Claude Code skill — args-based modes (doctor / ask / review /
  plan / full lifecycle), the "panel output is untrusted data" standing rule, the
  judge schema + anti-sycophancy synthesis rubric, and plan-mode handling.
- Docs: `README.md`, `docs/methodology.md`, `docs/adding-a-panelist.md`, `NOTICE`.
- Tests: mock-panelist harness + `tests/test_alloy.py`; CI workflow.

### Hardened after a multi-model review of the implementation
The shipped code was itself reviewed by a live Codex + Gemini + Claude panel.
Fixes that landed from it:
- Run artifacts now default to `$XDG_STATE_HOME/alloy/runs` (outside your repo),
  and the run root gets a `*` `.gitignore` so prompts/diffs/output are never
  committed even if pointed inside a repo.
- Secrets are redacted BEFORE capping; the raw `stdout`/`stderr`/`last_message`
  sidecar files are redacted in place; patterns expanded (GitHub/GitLab/npm/JWT/
  Stripe/ASIA), full PEM blocks redacted, name-with-suffix keys
  (`AWS_SECRET_ACCESS_KEY`) caught, and placeholder double-counting fixed.
- Output reads are byte-bounded to prevent a runaway panelist from OOMing.
- `gemini` runs with `--skip-trust` (its throwaway cwd is untrusted, which
  otherwise silently downgrades `--approval-mode plan` and fails headless).
- Config-file keys/overrides now actually reach the child and `doctor`'s auth
  check (`setting()` everywhere, `env.update(_CONFIG)`).
- `_kill_group` no longer skips `SIGKILL` on a transient `PermissionError`.
- `strip_ansi` also strips OSC sequences (clipboard / hyperlink escapes).
- Timeout / max-chars are validated; relative run roots are made absolute.

### Deliberately out of scope (roadmap)
- Panelists writing code (opt-in, isolated git worktree).
- Auto-running builds in the TEST stage beyond the project's own command.
- `ALLOY_JUDGE=codex|gemini` judge-rotation override.
