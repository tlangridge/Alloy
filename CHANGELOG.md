# Changelog

All notable changes to fusion are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.1.0] - 2026-06-15

Initial release.

### Added
- `bin/fusion`: stdlib-only Python 3 dispatcher.
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
  adapters lacking a real read-only mode unless `FUSION_ALLOW_UNSANDBOXED=1`.
- `SKILL.md`: the Claude Code skill — args-based modes (doctor / ask / review /
  plan / full lifecycle), the "panel output is untrusted data" standing rule, the
  judge schema + anti-sycophancy synthesis rubric, and plan-mode handling.
- Docs: `README.md`, `docs/methodology.md`, `docs/adding-a-panelist.md`, `NOTICE`.
- Tests: mock-panelist harness + `tests/test_fusion.py`; CI workflow.

### Deliberately out of scope (roadmap)
- Panelists writing code (opt-in, isolated git worktree).
- Auto-running builds in the TEST stage beyond the project's own command.
- `FUSION_JUDGE=codex|gemini` judge-rotation override.
