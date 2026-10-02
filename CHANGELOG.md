# Changelog

All notable changes to Alloy are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.13.0] - 2026-10-02

- Add optional `alloy search` through Jevgrep, preserving upstream search defaults
  and native agent context packets. The skill reuses relevant source evidence in
  Maker handoffs without replacing independent Checker review.
- Add inference-free local readiness checks and explicit TypeSafe/OpenRouter key
  reuse through stdin, preserving any existing Jevgrep credentials by default.
- Keep search opt-in and separately metered; bound subprocess lifetime/output,
  retain incomplete results honestly, and fall back to ordinary source discovery.

## [0.12.1] - 2026-10-01

- Managed Claude Makers and Checkers start with `--disallowedTools` denying direct rm
  binaries and wrappers: `Bash(/bin/rm:*)`, `Bash(/usr/bin/rm:*)`, `Bash(command rm:*)`,
  `Bash(\rm:*)`, `Bash(env rm:*)`, `Bash(xargs /bin/rm:*)`. Plain `rm` stays allowed so
  an operator's PATH guard still applies. Existing sandboxes are unchanged.
- Maker prompt rule: never call `/bin/rm` or `rm` on fixed paths; create scratch only with
  `mktemp -d` inside the task area and leave cleanup to Alloy/the gate.

## [0.12.0] - 2026-09-30

- Durable task owners, clone-independent logical IDs, lease heartbeats, closure
  receipts and cumulative budgets: 45 active minutes, initial implementation plus
  one correction by default. Owner flags can extend the total allowances.
- `cleanup --all-finished [--dry-run] [--older-than 24h]` verifies private archives
  (record, patch, recoverable commit bundle, files and manifest) before removing
  finished/abandoned worktrees. Squash/cherry-pick detection accepts content or
  patch-ID proof. Broken/missing-source work is recoverable from file archives.
  Optional archive location/upload hook and owner-response window are configurable.
- Execute-start hygiene retires stale closed tasks. Remote-keyed per-repository
  retained limits and measured free-disk/workspace guards replace clone-specific
  accounting; unrelated tasks have no global concurrency cap.
- Repeated blockers, no acceptance progress and budget expiry return the patch,
  failing reproduction and open decisions. Checker empty output, timeout and
  provider errors retry the unchanged revision twice without consuming Maker
  rounds, and are reported separately.
- Checkers read the owned worktree directly. Managed macOS Checkers deny writes
  to task/source trees and Git metadata under `sandbox-exec`; non-macOS Checkers
  require Codex's native read-only sandbox or refuse. Cursor temporary allocations are
  registered immediately and cleaned on failure, normal exit and signals.
- Explicit/automatic light mode uses one Maker, focused supplied gates and one
  cross-family Checker; protected paths retain all gates. Model pins, billing,
  opt-in routing, read-only panels and independent family checks are preserved.
- Correct managed-Maker permissions and bounded executable review documentation.

## [0.11.0] - 2026-09-29

**Upgrading:** on macOS, a Cursor CLI that is installed, logged in and passes the
sandbox self-test now joins the default panel (`ALLOY_PANELISTS` unset), using
`composer-2.5` unless you pin another model. Set `ALLOY_PANELISTS` to keep the
old panel. Cursor profiles for routing and `alloy execute` ship disabled; opt in
with `alloy setup --enable-cursor` or `alloy models enable --id ID`. Existing pins,
billing and profiles are preserved. `alloy setup --refresh-defaults` adds the new
profiles, including the enabled `codex-large-gpt-6-1-sol` (see below).

Cursor provider:

- Add Cursor as a panelist, managed Maker and managed Checker. The public name is
  `cursor`; the executable is still `cursor-agent`. `cursor-agent` is accepted as
  a legacy input name (`ALLOY_PANELISTS`, `--panelists`, routing profiles) and is
  normalized to `cursor`; run directories, manifests and usage always say
  `cursor`. Canonical settings win over the legacy ones (`ALLOY_BIN_CURSOR`,
  `ALLOY_CURSOR_MODEL`, `ALLOY_CURSOR_EFFORT` over their `..._AGENT_...`
  spellings); doctor warns when only the legacy model key is set.
- Cursor runs on macOS only. Every Cursor process (login status, version and help
  probes, model discovery, panels, Makers, Checkers) is started through one
  gateway that wraps it in `/usr/bin/sandbox-exec` with a profile Alloy generates,
  after a cached self-test of that profile. Without a working sandbox, on Linux
  and on any other platform, every Cursor role is refused, and
  `ALLOY_ALLOW_UNSANDBOXED=1` does not change that. Cursor CLI builds Alloy has
  not measured are refused too; the supported build for this release is
  `2026.09.28-64d2043`.
- Alloy never executes the `cursor-agent` shell launcher, or any wrapper script
  in front of it: the launcher needs a shell and several coreutils, which a
  panel or Checker sandbox denies, so on macOS every Cursor role was
  unavailable. Alloy follows the symlinks behind the configured path to the
  supported build's directory (behind a wrapper script it uses the supported
  build in Cursor's standard install location, without running the wrapper),
  checks that the build's `node` and `index.js` are regular files owned by you and
  not writable by group or others, and starts `<build>/node --use-system-ca
  <build>/index.js` directly, with `CURSOR_INVOKED_AS=cursor-agent` in its
  environment. The launcher's compile cache is reproduced inside the private
  runtime, never in your home cache.
- Cursor requires a one-time `AGENT_CLI_CREDENTIAL_STORE=file cursor-agent login`.
  The login lives in `~/.cursor/auth.json` (0600). Every Cursor child receives
  `AGENT_CLI_CREDENTIAL_STORE=file`; under Alloy the Cursor CLI is denied keychain
  access and cannot start `/usr/bin/security`. Alloy never reads the keychain.
  The pinned build writes `auth.json` directly and chmods it to 0600, with no temp
  or atomic-rename files. Only that literal file is write-granted, plus permission
  changes on the existing `~/.cursor` directory (the CLI chmods it to 0700).
  No other home files are writable, and symlinked credential paths are refused.
- Panels and Checkers run `--mode ask` inside the sandbox: a private
  per-dispatch runtime directory and the CLI file login are writable, process execution is denied except
  three literal paths (the Cursor CLI's own bundled Node runtime binary, the
  build's bundled `rg` and `/usr/bin/sw_vers`), and hard links
  are denied. `/bin/sh` and every other shell, `/usr/bin/open`, `/usr/bin/log` and
  everything else stay denied. Under Alloy, the OS sandbox denies shell execution and file writes outside the task's allowed paths; the model may be offered tools it cannot use. `/usr/bin/security` is denied
  in every role, and Alloy itself never runs `security`. Each
  of the three is verified before use. Makers run Cursor's normal agent mode inside the sandbox: only the
  non-Git contents of the Alloy-owned worktree, the private runtime and the CLI
  file login are writable, and Git metadata, the source checkout and everything else stay
  write-denied. No Cursor role receives `--force`, `--yolo`, auto-review or MCP
  approval flags; the final argv is checked against a closed grammar for each
  role, so mode, sandbox, worktree, plugin, session and subcommand controls
  cannot be added by a later rewrite.
- Cursor's own controls are not the boundary. In the recorded probe, plan mode and
  `--sandbox enabled` both wrote outside the workspace; ask mode refused in three
  runs, but it is a tool-mode control, not an operating-system guarantee. The
  macOS sandbox is the write boundary. Content fingerprints of the worktree and
  Git internals, and canary files outside it, only detect a change afterwards.
- Every Cursor role denies reads of a fixed list of credential locations (SSH,
  cloud, GPG, `gh`, npm, PyPI, Docker, Kubernetes, the login keychain directory,
  other agent CLIs' credential stores and Alloy's own configuration), of anything
  directly under `/private/tmp` or `/tmp` whose name contains "secret" (any case),
  and of any paths you add with `ALLOY_CURSOR_DENY_READ_PATHS` (comma-separated
  absolute paths, no globs); you can add denials but not remove built-in ones. `CURSOR_API_KEY` and `CURSOR_API_ENDPOINT` are scrubbed
  from every child environment and `--api-key`, `--endpoint` and `--header` are
  rejected. The Cursor child receives an explicit environment allowlist.
- Accepted residual risk, stated plainly: the Cursor process reads its own
  file login, can read the repository and uses
  the network. The profile cannot separate Cursor's legitimate reads and network
  from its model-facing read tool, so a Cursor role is not a data-exfiltration
  boundary and a Checker is not exfiltration-proof. Mitigations: ask mode for
  panels and Checkers, descendant-process denial (except the three executables above), the credential-read denials,
  redaction of JWT-shaped values, secret assignments and authorization headers
  before every persisted output, and a Checker packet built only from redacted
  text. Alloy never reads the keychain or runs `security`.
- Every Cursor call names one explicit model whose family is derived from its ID:
  `claude-` is Anthropic, `gpt-`/`codex` is OpenAI, `gemini-` is Google,
  `grok-`/`cursor-grok-` is xAI, and `composer-` is the new family `cursor`.
  `auto` and unknown prefixes are refused at every routing and dispatch step. A
  profile cannot claim a different family than its model's, and only a Cursor
  Composer profile may use family `cursor`. `--host-family` accepts `cursor`.
  Routing rubric is now version 5.
- Add five Cursor starter profiles, all disabled and billed as subscription:
  `cursor-large-composer-2-5`, `cursor-large-gpt-5-6-sol`,
  `cursor-large-claude-opus-5-5`, `cursor-medium-gemini-3-8-flash` and
  `cursor-large-grok-4-7`. Effort and fast variants travel inside `--model`
  (`[effort=...]`, `[fast=false]`); fast variants need a per-profile
  `cursor_fast: true` (`alloy models add --cursor-fast`). `alloy models refresh`
  lists Cursor models through the sandbox and records `auto` and unknown IDs as
  not routable.
- Model evidence rows now name the adapters they cover, and a match needs the same
  adapter, model, effort and fast state. Cursor has no benchmark row, so its
  profiles are always unmatched and cannot borrow another provider's evidence.
  Quota pacing compares the effective model family with the host's.
- Managed Cursor workers use `fresh_context_fallback`; native session reuse stays
  limited to Claude and Grok. A Maker or Checker that changes protected Git
  internals or a canary fails before gates or review, and the worktree is kept for
  inspection.
- Usage: Cursor's CLI has no usage source, so Cursor quota is `unknown` and never
  blocks routing. Two pools exist, `cursor:models` (`composer-*`, `cursor-grok-*`)
  and `cursor:other` (every other model served through Cursor, which draws the
  more expensive pool); set `quota_pools["cursor:models"]` or
  `quota_pools["cursor:other"]` `remaining_fraction` by hand to route on them.
  Setting `quota_pools.cursor` (the shared pool every shipped Cursor profile uses)
  blocks both. Per-call token counts are never treated as quota. An unknown usage
  provider no longer falls through to Claude's credentials.
- Limits of this release: Cursor does not run on Linux, there is no Cursor
  benchmark row, Cursor quota cannot be read live, and Alloy does not observe every
  filesystem change.
- Add an offline release-report verifier for the authenticated real-build gate
  and the composer-2.5 ask probe. Missing, skipped or incomplete evidence fails
  verification; accepted reports attach the complete ask record and both log hashes.
  Offline unit tests do not supply either live release record.

Usage and routing:

- Alloy no longer reads the macOS keychain for Claude quota, and `usage.keychain`
  is now ignored (it is still accepted so existing files load). Claude quota comes
  from an existing credentials file or `CLAUDE_CODE_OAUTH_TOKEN`; from the opt-in
  Claude Code status-line hook (`alloy usage --record-claude-statusline`); from
  recorded stream events (`claude -p ... --output-format stream-json --verbose |
  alloy usage --record-claude-stream`, and the `claude` runs Alloy itself makes,
  which now use `--output-format stream-json --verbose`; with
  `ALLOY_CAPTURE_USAGE=1` they use plain `json` and record nothing); or, only with `usage.claude_probe: true`,
  from one small Claude call per usage TTL. With none of these, Claude quota is
  unknown. Alloy installs no status-line hook.
- Antigravity's login check no longer runs `security`. On macOS a fresh `agy`
  login lives only in the keychain, which Alloy does not read, so a signed-out
  `agy` now shows `[ready]` in `alloy doctor` with auth `unknown` (JSON field
  `auth`); it used to show `installed_not_authed`. The first real run reports
  status `auth` if `agy` is not signed in.
- Add the `codex-large-gpt-6-1-sol` starter profile (GPT-6.1 Sol, large tier,
  medium effort and high effort for review, enabled; billing is your choice). It is
  the preferred large Codex profile. A `gpt-6-sol` pin still needs API-key
  billing. Recommend `usage.reserve_fraction: 0.15`; the default stays `0.1`.

Fixes already on this branch (agy 1.2.12 Checkers):

- Grant agy read access to the staged prompt directory and the worktree with
  path-scoped `read_file(<dir>)` rules, one per `--add-dir` root. agy 1.2.12
  ignores bare tool names, so the earlier Checker allow-list was deny-only and
  could pass without reading the worktree.
- Give agy `DEVNULL` as stdin. agy 1.2.12 treats a file on stdin as a `read_file`
  that headless mode denies, even when the directory is granted.
- Keep two agy settings grammars. agy 1.1 keeps bare read-tool names; agy 1.2.x
  uses path-scoped `read_file(...)` grants and is the fail-closed current grammar.
- For a linked-worktree Checker, grant agy the exact gitdir that `.git` points to
  and, only for the standard `<common>/worktrees/<id>` layout, that gitdir's
  common directory. Other layouts receive the exact gitdir only.
- Grant agy Checkers read access to the owner-private gate-log directory, and tell
  them in the prompt to read only inside the task worktree and that directory.

Known issues:

- Two tests can fail once under heavy machine load and pass on a re-run of the same
  code. They are not fixed in this release:
  `test_alloy.CursorJsonTests.test_secret_shaped_output_is_absent_from_every_persisted_sink`
  (the `header` case: `result.md` is missing) and
  `test_alloy.CursorManagedMakerTests.test_maker_gateway_requires_a_managed_linked_worktree_and_a_matching_cwd`
  (the `managed flag unset` case: `fingerprint refused: a directory changed while
  reading`). When the content tripwire cannot read a directory consistently, Alloy
  refuses the call, so the failure is a refusal and never a pass. Re-run once
  before treating either as a real failure.

## [0.10.0] - 2026-09-26

- Add profile `effort_by_mode`: implementation and independent review can use
  different effort, while explicit CLI effort overrides retain priority. Existing
  profiles remain unchanged on upgrade; the shipped Opus 5.5 profile uses medium
  implementation effort and high review effort.
- Give Jev separate Maker and Checker model cards and fit questions in the same
  make-routing request. Use review-specific judgments for Checker selection and
  retain both contexts for offline replay. Routing rubric is now version 4.
- Add `alloy models context --mode make|review` for equivalent keyless decisions.
  Every execute-round table shows each worker's effort.
- Teach the skill and worker prompts to distinguish missing edge cases, wrong
  approaches, unclear requirements and infrastructure failures before retrying.
  Keep required tests, independent review, permissions and correction bounds.
- Document the source and limits of the effort guidance. No new live benchmark,
  cache-hit, cost-reduction or quota-saving claim is made by this release.

## [0.9.1] - 2026-09-25

- Preserve Claude user settings, including permission deny rules and hooks, in
  lean mode. Optional MCP/skill context is still trimmed. The 0.9.0 cost reduction
  measured a different invocation and is not a verified saving for this version.
- Count routing failures in benchmark quality and keep missing Maker/Checker
  measurements or token costs unknown. Incomplete replay cannot pass the gate;
  the CLI exits nonzero and omits unsupported aggregate scores and intervals.
- Score Checker correctness rather than JSON validity. Label replay as a component
  proxy, not a measured end-to-end execute result.
- Replay Jev model-fit answers using their original ordered model cards for both
  routing decisions. Reject missing/mismatched context; historical classifier-only
  replay requires an explicit flag.
- Qualify the earlier routing claims: 0.9.0's aggregate cost/quality figures need
  re-evaluation with full coverage and model-fit evidence. No new live performance
  or complete execute-loop claim is made by this patch.

## [0.9.0] - 2026-09-25

Measured with the new `bench/` autoresearch evaluator: 48 tasks with hidden tests,
seeded-bug reviews and answer keys; every change kept only if quality held and
cost fell; final routing validated on a held-out split (q 0.917, all gates pass).
Details: `bench/RESULTS.md`.

**Upgrading:** existing `routing.json` files keep their profiles and policy. To adopt
the measured defaults, run `alloy setup --reset-defaults --non-interactive
--skip-live-test` (backs up the file; keeps Jev provider, billing modes and quota
pools). If you pinned `ALLOY_CODEX_MODEL=gpt-6-sol` with ChatGPT sign-in, that pin
makes the Codex panelist fail: use `gpt-5.6-sol` or remove the pin. Any Codex pin
also blocks the cheap Luna reviewer from routing.

- Prefer Jev routing (`--route`) when a configured key is available; host routing is
  the fallback or an explicit keyless choice.
- `alloy setup --reset-defaults` adopts the shipped profiles and policy wholesale.

- Fix managed execution on current CLIs: Antigravity (agy 1.2) Makers could not run
  their test commands, and Grok Makers could not edit files; both failed every task.
- Run `claude` panelists and workers with a lean context (no global MCP connectors,
  skills or user settings; project instructions still load). Paired bench run:
  cost −67%, wall time −24%, quality within noise. `ALLOY_CLAUDE_LEAN=0` opts out.
- Accept a Checker verdict wrapped in prose or a code fence (Claude plan mode does
  this); exactly one verdict is required and the packet receipt still applies.
  Recovered 4 of 12 correct Claude reviews that previously failed closed.
- Keep Grok panelists from cancelling their own answers: headless grok aborted the
  whole turn (exit 0, half a sentence) whenever the model reached for a tool needing
  approval. Read-only panels now get only read/search tools plus pre-approved page
  fetches. Grok dev reviews and consults went from 1/12 to 11/12.
- Routed consults require at least a medium-tier model (`policy.min_tier_by_mode`):
  Jev cannot see the repository a question is about and under-rated such questions.
  Existing configs keep their policy until they add the key.
- Ship `gpt-6-sol` disabled: Codex with ChatGPT-account sign-in rejects it, so the
  preferred large Codex profile failed every dispatch (and existing pins to it break
  the Codex panelist). Checkers fall back to working profiles.
- Per-mode capability tiers (`tier_by_mode`). Luna and Gemini Flash Low review at
  every tier while staying small-tier Makers; replayed on dev tasks this cut overall
  cost per solved task by a third at equal quality.
- Opt-in `policy.quota_pacing`: price subscription capacity by reset time, so quota
  that would expire unused is preferred; the host's own CLI is never discounted.
- `ALLOY_CAPTURE_USAGE=1` records provider-reported token usage per dispatch.
- Add `bench/`: 48 tasks with hidden tests, seeded-bug reviews and answer keys;
  production-path runners, list-price costing, quota floors and routing replay.

## [0.8.1] - 2026-09-22

- Add keyless setup and host model-context inspection; the skill selects explicit workers without requiring Jev.
- Host task tier, kind, risk and ambiguity feed the existing execution eligibility checks.

## [0.8.0] - 2026-09-22

- Ship public routing defaults and additive `setup --refresh-defaults` upgrades; each user supplies their own API key. No private configuration is distributed.
- Send bounded, allowlisted model metrics to Jev and request per-candidate task fit in the same request; preserve hard constraints, cost tolerance and unknown outcome metrics.

- Add GPT-6 Sol and Gemini 3.8 Flash low/medium/high plus Gemini 3.1 Pro low/high to starter routing profiles. Preserve existing profiles and billing settings.
- Add exact GPT-6 Sol capability and pricing references without transferring high-effort evidence to lower-effort Gemini variants.

Every Cursor spawn explicitly passes `--sandbox disabled`. Alloy's macOS
`sandbox-exec` profile is the enforced boundary; Cursor's own sandbox and ask/plan
modes are not relied on. A fresh 0700 runtime sets `CURSOR_DATA_DIR` and
`CURSOR_CONFIG_DIR` to its private state subdirectory and is removed after the
call through the system `rm` command (including any installed guard). `HOME` stays
unchanged; the CLI reads the literal `~/.cursor/auth.json` without copying or
symlinking it. Home projects/config, skills manifests, the build's `.running`
markers and `/dev/dtracehelper` remain write-denied. The compile cache also stays
inside this runtime. Under Alloy, the OS sandbox denies shell execution and file
writes outside the task's allowed paths; the model may be offered tools it cannot use.

### Validation
- 215 offline tests and skill validation pass, including additive/idempotent config upgrades, user settings preservation, model-card privacy and bounded Jev fit judgments. No paid inference used.

## [0.7.1] - 2026-09-22

### Changed
- Claude large starter uses Opus 5.5 at medium effort with a lower editable cost rank; Grok defaults to 4.7. Existing model pins and billing configuration remain intact.
- Refreshed Sol/Opus benchmark guidance and dated API price references in model advice, keeping subscription quotas separate from API prices.
- Every execute round emits and saves usage Markdown with worker assignments, including corrections and resumes. Both skills require visible chat rendering even when workers and usage are unchanged.

### Validation
- 210 offline tests (full suite plus added regression coverage) and skill validation; no paid model execution used for this release.

## [0.7.0] - 2026-09-19

### Added
- OpenRouter-backed Jev routing through the Decisions API, with a separate private key, provider selection and preserved TypeSafe model pins and credentials.
- Combined managed-execution readiness reports and `execute --check` without model inference or worktree creation.
- Exact Claude/Grok worker-session reuse where supported, short Maker correction updates, and explicit fresh-context fallback for other adapters.
- Revision-bound review packets containing the diff and test evidence; required context receipts reject incomplete or mismatched reviews, and oversized packets stop for task splitting.
- Execution setup/retry timing, blocking-step reporting, and separate test/review/deployment/live-verification states.

### Changed
- Skills display subscription usage and task/model assignments on every invocation and when delegation changes, with Markdown and plain-text presentation guidance.
- Managed workers suppress repeated waiting heartbeats; permissions, independent review, correction limits, required checks and merge-proof cleanup remain enforced.

### Validation
- 207 offline tests and skill validation pass, including session recovery, preserved permissions, aggregated readiness blockers and context-receipt failures.
- One live Jev/OpenRouter routing smoke test succeeded; no coding task was dispatched. Native session reuse is covered by mock CLIs and installed CLI help checks, not paid live execution.

## [0.6.0] - 2026-09-18

### Added
- Real `alloy execute`: an efficient Maker edits and tests in an owned Git worktree, an independent model family checks the result, and Alloy drives up to two correction rounds before a compact host handoff.
- Machine-readable file-write/command permissions; preserved read-only panels, model pins, billing and quota checks.
- `tasks`, bounded `resume`, `integrate` and proof-based `cleanup`, including external squash verification, crash recovery and a four-worktree retention cap per repository.
- Automatic removal of clean task worktrees/branches after verified integration; unfinished work and detailed task artifacts are retained.

### Validation
- 195 automated tests and skill validation pass, including offline end-to-end CLI execution, bounded correction, quota/pin checks, interruption recovery, process-status write failures, and merge/squash cleanup proofs.
- Provider write adapters have mock and local help-flag coverage; live provider write execution has not been evaluated.

## [0.5.0] - 2026-09-17

### Added
- Skill-startup automatic stable-release updates for clean official Git installs, with a daily cache, check-only/disabled modes, and nonblocking skips while Alloy runs are active.
- Preserve local work and developer branches, require a released starting commit and a fast-forward target, and report copied installs/worktrees as unsupported.
- Reload skill instructions after an update; all skills linked to the installation share the updated code.

### Validation
- 164 automated tests cover the dispatcher, routing, usage and updater, including local-edit protection, stable-release validation, concurrent runs, offline failures and fast-forward-only installation.

## [0.4.0] - 2026-09-17

### Added
- Evidence-based task preferences for exact model IDs and reasoning efforts, with dated sources, expiry, configurable cost tolerance and `alloy models advise`.
- Nine Jev task categories; comparable metered profiles use estimated dollars, while mixed billing retains quota-adjusted relative costs.
- Explicit verified-failure context for Jev and policy: capability escalation after failed attempts and per-task failed-profile exclusions. Existing pins, budgets, quota reserves and independent Checker constraints still apply.

### Changed
- New Sol starter profiles support large tasks. Existing profile tiers remain user-controlled.
- Document research strengths/limitations and preserve model-inversion adversarial review, the same Maker within a loop, and the two-fix-loop limit.

### Validation
- 149 automated tests cover evidence expiry, task preferences, metered comparisons, retry context and independent Checker eligibility.
- Prior live Jev rubric-v2 checks passed 50 complexity examples and 16 task-kind examples. These are synthetic classification checks, not measured coding-quality or cost improvements.

## [0.3.3] - 2026-09-17

### Fixed
- Display Claude Fable's separate weekly capacity from Claude's scoped usage response, alongside overall Claude limits, without another provider request.
- Apply the scoped limit to Fable routing while retaining shared limits. Ignore unknown and surface-specific scopes rather than applying them to unrelated models.
- Label recognized Claude model pools by name and avoid duplicate legacy/scoped buckets.

### Validation
- 135 automated tests pass, including Fable display, shared/scoped routing limits and scope isolation. A live usage read confirmed the separate Fable meter.

## [0.3.2] - 2026-09-17

### Changed
- Version-only patch release. Includes the Grok quota support and `/alloy-usage` command shipped in 0.3.1; no functional changes.

## [0.3.1] - 2026-09-17

### Added
- Invoke `/alloy-usage` directly in an agent, alongside `/alloy-execute`. The installer includes the new usage command.
- Show Grok's remaining included subscription credits and reset time in `alloy usage`, using the existing Grok CLI login and a cached billing request.
- Consider fresh Grok quota when routing tasks. Missing billing data, expired logins, team accounts and API-key overrides retain unknown capacity; on-demand spending caps never count as subscription quota.

### Validation
- 133 automated tests pass, including Grok parsing, credential/cache binding and sanitized HTTP failures. A live billing read confirmed the weekly quota meter without a model call.

## [0.3.0] - 2026-09-17

### Added
- Route tasks with TypeSafe Jev using `alloy route` or `panel --route`. Task complexity, uncertainty, provider independence, model pins and configured cost limits determine the eligible model profiles.
- Configure credentials and billing modes with `alloy setup`; maintain model profiles with `alloy models`, including discovery for Grok and Antigravity.
- View subscription capacity with `alloy usage`: Markdown meters for Codex, Claude and Antigravity, cached provider observations and session-scoped suppression of unchanged reports. Grok capacity remains explicitly unknown.
- Include fresh subscription headroom in routing decisions, with shared quota pools and a configurable reserve (10% by default). Stale or unavailable readings never become invented capacity.
- Record prompt-free routing decisions and normalized usage context in run artifacts. Add an explicit synthetic Jev evaluation command and routing/usage documentation.

### Changed
- Install the CLI into the user bin directory alongside agent skills; add optional setup and safe uninstall without deleting credentials or configuration.
- Request usage snapshots at session and turn checkpoints through the Alloy skill, and show meters when panels start.
- Keep Jev credentials out of downstream CLI environments and preserve read-only execution and independent Maker/Checker constraints.

### Validation
- 129 automated tests cover dispatch, routing, usage, installation and failure paths. Live validation includes 50 synthetic Jev cases and routed smoke tests across all four CLIs; these are not general quality or savings benchmarks.

## [0.2.2] - 2026-09-11

### Changed
- **SKILL.md: never detach a dispatch yourself.** The "Makers finished without
  waking the host" report turned out to be self-inflicted: the host had run
  `alloy panel` under `nohup … & disown` inside foreground tool calls, so the
  harness never held a handle on the process and nothing could report its
  completion. The long-dispatch guidance now forbids that explicitly — use the
  host's own background facility, never `nohup` / `disown` / `setsid` / a bare
  trailing `&` — and points at `alloy status` (0.2.1) as the recovery path
  when it has already happened. No dispatcher changes.

## [0.2.1] - 2026-09-11

Field report from the first `/alloy-execute` runs: a healthy Maker was killed at
the consult panel's 300 s ceiling while still reading the repo, the guidance
then pointed at the wrong fix (lower the effort), and a host that never got the
dispatcher's completion signal had no way to find out what had happened.

### Added
- **`panel --mode make` with its own default timeout (1800 s).** A Maker is one
  model that must explore an unfamiliar repo before it can emit a diff — a
  different workload from N consult panelists answering in parallel — and a
  timeout there is lost work, not a partial panel. `ALLOY_MAKER_TIMEOUT`
  overrides the default; `--timeout` overrides everything. The execute runbook
  now dispatches the Maker with `--mode make`.
- **Resumable panelists.** grok and claude now get a caller-chosen session id
  (`--session-id`, recorded as `session_id` in the manifest), so the CLI's
  saved session is known *before* dispatch. When alloy has to kill a panelist
  (timeout / stall) the manifest entry carries a ready-to-run `resume_hint`
  (read-only flags kept, `cd` to the cwd the session is keyed by) and the
  timeout log line prints it — the minutes of exploration are no longer thrown
  away. codex gets a "most recent session" hint (it assigns its own ids); agy
  none. Verified live: both CLIs save the session under the given id.
- **`alloy status [run-dir]`** — a run's progress read purely from disk: per-
  panelist state (`running` / `ok` / `timeout` / `abandoned` …), bytes produced,
  last-output age, and any resume hint. Defaults to the newest run; accepts a
  run dir or a manifest path; `--json` for machines. Exit `0` when the manifest
  exists, `4` while still running (or abandoned — it tells you which, by
  checking the dispatcher's pid recorded in the new `run.json`), `2` if no run.
  A host that never got the completion signal can now answer "is it done?"
  with one cheap call instead of trusting the harness.
- **The run dir is announced at dispatch start** (`run: <dir>` on stderr), the
  panel line shows the deadline (`timeout Ns each, mode X`), and `estimate`
  reports `timeout_s` / `maker_timeout_s` next to the call count, so the
  ceiling is visible before the burn, not after.
- Per-panelist `status.json` is now written at dispatch start (`running`, pid,
  `started_utc`) as well as at the end.

### Changed
- **SKILL.md timeout remedy reordered.** Read `stalled` and `output_bytes`
  first: still producing → raise `--timeout` or resume; genuinely stuck → lower
  the effort. The old text led with "make the model dumber".
- **SKILL.md long-dispatch guidance.** The dispatch blocks until done; if the
  host's tool-call timeout is shorter, run it in the background, wait for the
  notification, and confirm with `alloy status` — never delegate the wait to
  subagents, never poll in a loop. Execute mode gets its own "a Maker timeout
  is lost work" paragraph with the resume path, and the cost preflight now
  carries the deadlines.
- Adapter comments note that grok, codex exec, and claude -p have no headless
  deadline flag to mirror alloy's timeout (agy's `--print-timeout` remains the
  only one).

### Tests
- make-mode default / env / flag precedence; run dir announced and `run.json`
  written; `estimate` deadlines; grok+claude `--session-id` is a real UUID and
  recorded; a timeout records a read-only `resume_hint`; `status` on a finished
  run, newest-run default, an abandoned run (exit 4), and no runs (exit 2).

## [0.2.0] - 2026-09-09

### Added
- **`/alloy execute <task>` (alias `/alloy-execute <task>`): a light
  maker≠checker execute mode.** Alloy was review-and-advise only — the host
  still wrote every line. Execute keeps the host as Lead (it writes an 8-line
  SPEC from the prompt, gates, classifies, and is still the only thing that
  writes the tree) but moves the implementation *thinking* to a cheap **Maker**
  of a different model family, invoked read-only through the existing
  dispatcher (`panel --panelists <maker>`), which returns the change as a
  unified diff. The host applies it and runs the repo's tests, then dispatches
  a **Checker** round (`--mode review`, every ready family except the Maker's)
  that returns at most five labeled finding cards (`CONFIRMED` / `PLAUSIBLE` /
  `REFUTED` / `OUT-OF-SCOPE`). Only `CONFIRMED` findings of severity high+
  inside the diff's blast paths go back to the Maker; everything else is
  parked; at most two fix→review loops. No tickets, no workstream folders, no
  research/plan rounds — the full lifecycle stays as the long path. Routing is
  by token only: a bare `/alloy <task>` still means the lifecycle.
- **`alloy-execute/` alias skill.** A shim that defers to the main skill's
  execute runbook (no second copy of the rules), so `/alloy-execute` resolves
  on hosts that map slash commands to skill directories.
- **`install.sh` links every host present** — Claude Code, Codex
  (`~/.codex/skills`), Grok, Gemini CLI (`~/.gemini/skills`) and Antigravity
  (`~/.gemini/config/skills`) — for both `alloy` and `alloy-execute`. Codex
  gets an `agents/openai.yaml` display card. SKILL.md's dispatcher-path wording
  is now host-neutral.

### Unchanged (deliberately)
- `ask` / `debate` / `review` / `plan` / `doctor` / the lifecycle, and standing
  rules 1–6. `alloy panel` stays read-only; the Maker never writes the tree,
  and no CLI is ever given a write, auto-approve, or bypass flag. A
  write-capable `alloy make` worktree adapter is a possible later PR, not part
  of this one.

### Tests
- `validate_skill.py` now asserts the execute row, the alias, the "host does
  not implement the feature" rule, the five-card cap, the label taxonomy, the
  two-loop cap, and that the `alloy-execute` shim exists, is named correctly,
  and carries no duplicate runbook.

## [0.1.11] - 2026-08-19

### Fixed
- **No more macOS Keychain popup from the agy panelist.** agy keeps its OAuth
  token in the login keychain, and macOS resolves both the keychain search
  list and the *default* keychain through `$HOME` — so inside alloy's
  isolated agy HOME only the System keychain was in scope, and agy's token
  save asked for admin auth (the popup) on every refresh while the keychain
  copy of the token went permanently stale. The isolated HOME now gets a
  **generated** `com.apple.security.plist` pointing (by absolute path) at the
  user's real login keychain, so keyring reads and token-refresh saves work
  exactly as a normal `agy` run would — silently. Deliberately a generated
  file, never a symlink into `~/Library`: state/run dirs get zipped up and
  shared for debugging, and archivers dereference symlinks. Skipped entirely
  under API-key auth (agy never touches the keyring then) or when no login
  keychain exists. Auth state was always deliberately shared (same rationale
  as the existing `~/.gemini` links).
- **Keychain-only agy logins now count as authenticated.** The token *file*
  alloy checked for is a fallback agy writes only when a keyring save fails,
  so a healthy fresh install could look unauthenticated to `doctor`.
  `is_authed` now also does a metadata-only
  `security find-generic-password` existence check (service `gemini`,
  account `antigravity`) — it never reads the secret, so it can never
  trigger a keychain dialog itself.

- **Stale auth symlinks self-heal.** The `~/.gemini` auth links into the
  isolated agy HOME are now repaired when broken or pointing at an old path
  (home moved, state dir restored on another machine) instead of silently
  shadowing the real files forever.
- **Concurrent runs can no longer tear shared state files.** `write_atomic`
  uses a unique temp file per writer; two alloy processes sharing the agy
  HOME (panel + doctor, or two panels) previously raced on the same
  `.tmp` path and could corrupt `settings.json`.

### Tests
- macOS: generated-keychain-config unit tests (absolute paths +
  `DefaultKeychain` present, API-key and no-login-keychain skips, legacy
  dev-build symlink removal, and the no-symlinks-into-`~/Library`
  regression); keychain-auth unit tests (item present/absent, `security`
  timeout and OSError, Linux never probes, file-auth short-circuit) — all
  hermetic with fixture HOMEs and a faked subprocess, on every platform.

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
