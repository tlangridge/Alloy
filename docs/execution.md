# Managed execution

`alloy execute` delegates implementation and testing to a provider CLI in an
Alloy-owned Git worktree. A different model family reviews the result read-only;
Alloy passes evidence back to the same Maker for one correction by default.
The host receives a compact JSON handoff and decides whether to integrate.
This reduces host-agent implementation and transcript handling; actual token
savings depend on the task and are not measured or guaranteed.

## Start a task

Requirements: Python 3.8+, Git 2.31+, a clean committed repository on a branch,
and eligible Maker and Checker profiles from two families distinct from the host.
Codex, Claude, Grok, Antigravity (`agy` 1.1+) and Cursor (macOS only) have
managed-write adapters. CLI help/version checks fail closed when required
permission flags are unavailable. These are compatibility checks, not proof that
a particular CLI version correctly enforces its permissions. Provider profiles
remain editable configuration. Cursor profiles ship disabled; see
[Cursor roles](#cursor-roles).

Use `alloy setup --skip-live-test` if profiles are not configured, then
`alloy models list`. Preserve existing model pins and billing settings. Setup
without `--skip-live-test` performs a live Jev test. Write a scoped specification
outside the repository with explicit acceptance criteria and test commands.

```sh
alloy execute --repo /path/to/repo --prompt-file /path/to/spec.txt \
  --host-family openai --maker-profile claude-small --checker-profile grok-large \
  --allow-path src --allow-path tests --test 'python3 -m unittest discover -s tests -v'
```

The example profile IDs must exist in your configuration. Choose actual profiles
with `alloy models list`. Host family means model provider, which may differ from
the CLI vendor. To use configured Jev routing, replace the two profile options
with `--route`. Explicit profile options also constrain routed choices. Jev runs
once for the original task; code enforces eligibility, pins, budget estimates,
billing and available quota before each dispatch. Repeated rounds retain the same
workers; no silent fallback or automatic family changes.

Repeat `--allow-path` and `--test` as needed. `--allow-path .` explicitly permits
changes throughout the worktree. A file path includes only that file; a directory
includes descendants. Paths cannot be absolute or contain `..`. Tests are explicit
shell commands run in the worktree, with no input and with bounded execution time.
Dependencies and ignored local environment files are not copied from the source
checkout. Include needed setup in the test commands or project instructions.

`--timeout` defaults to 1800 seconds per worker. `--test-timeout` defaults to 600
seconds per test command. `--max-fix-rounds` defaults to 1 (initial implementation
plus one correction); `ALLOY_MAX_FIX_ROUNDS` configures the default. The cumulative
active execution budget is 45 minutes (`ALLOY_TASK_BUDGET_MINUTES` or
`--budget-minutes`). Worker and gate deadlines are capped by the remaining budget.
Idle time between executions does not consume it. Failed local tests return to
the Maker without spending a Checker call. Repeated confirmed blockers, no
acceptance progress or budget expiry stop execution with a patch, failing
reproduction and open decisions. Transport failures count separately: empty
Checker output, timeout or provider error gets at most two retries of the same
revision and packet, without another Maker, commit or gate round. Malformed
nonempty verdicts and mismatched context receipts fail closed.

Every task records an `owner`, `logical_task_id`, attempt ID and lease heartbeat.
The default logical identity is the remote repository plus exact specification
hash; supply `--logical-task-id issue-123` when the specification may change across
clones or relaunches. Only one attempt of that logical task can execute at once.
Active seconds and implementation rounds accumulate across attempts and resumes.
Use `--owner` or `ALLOY_OWNER` to identify the person responsible. An owner can
extend the cumulative limits with `alloy resume TASK_ID --budget-minutes 90
--max-fix-rounds 3`, or those same options on a relaunch with the same logical ID.
These are total allowances, not additional allowances. `--max-estimated-usd` is a per-dispatch routing estimate, not a
hard provider billing limit or whole-task budget. Subscription quota information
can be cached or unavailable; unknown quota does not mean unlimited capacity.

`--light`, or an automatically small diff (at most `ALLOY_LIGHT_DIFF_LINES`,
default 80 patch lines) uses one Maker and one cross-family Checker with the
focused gates supplied by `--test`. All explicit gates still run. Changes under
tests, CI, migrations, security or auth, and protected policy/lock files, use the
full gate path even with `--light`. The normal execution path also uses one
Maker/Checker pair; light mode never relaxes independence, pins or receipts.

## Readiness, sessions and review context

Add `--check` to the same execute command for a JSON readiness report. It checks
source cleanliness/branch, retained-worktree and disk resource limits, configured models and pins,
authentication indicators, quota/budget eligibility, CLI permission support, and
whether independent Maker/Checker families are available. It reports blockers
together without calling Jev, launching a worker, or creating a worktree. Normal
execute performs the same preflight and rechecks selection before dispatch.
Local checks cannot prove a model's provider-side entitlement or that a stored
login has not expired; those can still fail on the first call.

Claude and Grok reuse a separate exact session ID per role when their help output
supports both `--session-id` and `--resume`. Resumes reapply the model, scope and
permission flags, preserve the worktree and original attempt limit, and send the
Maker a short update with revision-qualified finding IDs and failed checks.
Interrupted calls retain their session identity. A failed resume stops for
inspection instead of silently restarting. Codex, Antigravity and incompatible
CLI versions currently report `fresh_context_fallback`; they retain the same
worker profiles and receive full context on every call. Cursor always reports
`fresh_context_fallback`: no `--resume` or `--continue` is ever built for it, and
a stored record cannot switch it to resume. No `--last` session selection is used.

Each Checker receives a bounded, self-contained packet: goal, exact base/tip,
changed filenames, complete diff, test commands/results and bounded test output.
It can inspect needed dependencies in the worktree. The verdict must acknowledge
the packet hash, revision and context completeness; missing or mismatched receipts
stop the run. This verifies the response corresponds to the supplied packet, not
that the model understood every line. Packets over 96 KB stop for a smaller task
split, preserving the worktree instead of silently dropping code. Full artifacts
remain on disk. Reviews require concrete failure examples; the Maker may challenge
unsupported findings with code/test evidence. Unresolved disagreements reach the
host at the existing correction bound; independent review is never waived.

Required repository checks still run every round; this change does not cache
checks or run potentially mutating tests alongside the Checker. Successful gate
records include their reviewed revision. Define a reproduction/acceptance check
in the SPEC; the Maker is asked for before/after evidence. The final handoff keeps
local tests, independent review, deployment and live verification separate.
Passing local gates does not imply deployment or verified live behavior.

The compact result exposes the current `blocking_step` and `metrics`: startup
milliseconds to the first worker dispatch (a proxy, not time to its first useful
output), worker setup milliseconds, fresh starts, resumed calls, review retries,
context receipt failures, separate review transport failures/retries, cumulative
implementation rounds and active seconds, and wall time to the locally verified result. Timings
include waits across task resumes. Managed workers suppress repeated waiting
heartbeats; report phase results, failures, blockers and decisions in chat.

## Lifecycle and cleanup

```text
execute -> Maker edits/tests -> local test gates -> independent Checker
              ^                      |                    |
              +------ bounded correction <------ concrete findings
                                                          |
                                                        ready
                                                          |
                                                      integrate
                                                          |
                                             prove integration -> cleaned
```

Execution never merges, pushes or deploys automatically. Exit 0 / `state: ready`
means tests and independent review passed. It leaves the task worktree available
for host inspection. Exit 3 / `needs_attention` means inspect the recorded failure;
configuration/usage errors return exit 2. Signals retain interrupted work.

```sh
alloy tasks                              # compact list, including retained tasks
alloy resume TASK_ID                     # unfinished tasks, remaining attempts only
alloy integrate TASK_ID                  # fast-forward, then automatic cleanup
alloy integrate TASK_ID --squash         # squash commit, then automatic cleanup
```

Integration requires the source checkout to remain clean, on the original target
branch and at the original base commit. If it advanced, rebase/re-review through
a new task or integrate externally under the host's normal workflow. The reviewed
worktree must still be clean and at the reviewed tip. Git hooks are disabled for
Alloy's Git bookkeeping; required validation belongs in the explicit test gates.
Alloy-created commits use `Alloy <alloy@localhost>`; provider CLIs are instructed
not to commit or modify Git metadata.

After a merge outside Alloy:

```sh
alloy cleanup TASK_ID --dry-run
alloy cleanup TASK_ID
# To prove a specific external squash, optionally add:
# --integrated-commit FULL_COMMIT_HASH
```

Single-task cleanup requires the independently reviewed worktree to remain clean
and unchanged. Integration proof accepts ancestry, exact squash diff, or full
changed-path content equality / stable patch-ID equivalence on the default branch.
Thus externally squashed or cherry-picked work can be detected without a supplied
commit hash, including a matching patch followed by later edits. Alloy does not
fetch; synchronize local default-branch refs for remote-only merges.

```sh
alloy cleanup --all-finished --dry-run --older-than 24h
alloy cleanup --all-finished --older-than 24h
```

Batch cleanup also closes unmerged finished tasks as **abandoned**. It skips active
and locked tasks and checks saved worker processes. Before every removal it saves
the task record, binary patch against the base, a Git bundle of task commits and
a file tarball, plus `MANIFEST.json` with checksums, owner, logical ID and bundle
prerequisites. The bundle includes all commits after base (a conservative superset
of unpushed commits); restore it into a repo containing the recorded base. Bundles
and archive bytes are verified before removal. Broken or missing-source tasks use
a file archive excluding `.git`, `node_modules`, `.next`, `dist`, `build` and
`coverage`; these caches are disposable. Tracked and untracked ordinary files,
including dirty work, are preserved. Symlinks are archived without following them.

Archives default to `<execution-state>/archive/`; configure `ALLOY_ARCHIVE_DIR`
outside source/worktrees. An optional trusted `ALLOY_ARCHIVE_UPLOAD_HOOK` command
gets the archive directory in `ALLOY_ARCHIVE_PATH`; a failed hook prevents removal.
Configure it for your storage provider (for example R2); no uploads occur by
default. Archives and task logs have no automatic expiry. After verification,
Alloy removes only the owned worktree with `git worktree remove --force`, prunes
stale registrations, and deletes its matching branch. When the source is gone,
it uses the system `rm` guard. Any refusal retains work and reports the exact path.
A closure receipt records `merged` with proof, or `abandoned`, and the archive.

Every execute runs the same hygiene before admission. Integrated, failed,
interrupted and needs-attention tasks idle over 24 hours are eligible, as is stale
merged work. Running and recently updated tasks remain. Set
`ALLOY_CLEANUP_GRACE_HOURS` to a nonzero response window to write an owner notice
before abandoned cleanup; the default is zero (archive immediately after expiry).
Notices live at `tasks/ID/owner-notice.json`; operators surface them to owners.
Resuming updates activity and protects the task. No external messages are sent.

There is no machine-wide concurrency count. Four retained worktrees per logical
repository remain the default (`ALLOY_REPO_RETAINED_CAP`); the remote URL keys this
limit across clones, with Git common-dir identity for repositories without a
remote. SSH/HTTPS forms share identity. Before creation, free disk must be at least
`ALLOY_MIN_FREE_GB` (15 GiB) and retained workspaces must fit
`ALLOY_RETAINED_BUDGET_GB` (10 GiB). If short, hygiene runs again and admission is
refused only if still short, with measured resource values. Archive storage counts
against free disk; use an external archive volume if local capacity is tight.

## Machine-readable action boundary

Each task's `task.json` records role permissions; every worker `status.json`
records the actual CLI command and its permissions. Example Maker contract:

```json
{
  "repository_write": true,
  "command_execution": "allowed",
  "repository_scope": "managed_worktree",
  "enforcement": "provider_cli_permissions",
  "os_isolation": false,
  "scope_validation": "post_run_path_check",
  "network": "provider_policy",
  "git_metadata_isolated": false
}
```

Checker permissions set `repository_write: false`,
`command_execution: "provider_read_only_policy"`, and
`scope_validation: "post_run_change_check"`. File writes and command permissions
are separate fields. They describe what Alloy requested and how it checks the
result; they are not a new OS permission system.

| Maker CLI | Requested policy | Enforcement limit |
| --- | --- | --- |
| Codex | `workspace-write`, approval policy `never` | Codex workspace sandbox; approval-required actions fail |
| Claude | `acceptEdits`, Read/Glob/Grep/Edit/Write/Bash tools, Bash allowed | Provider permission system; no Alloy OS sandbox |
| Grok | `acceptEdits`, Read/Glob/Grep/Edit/Write/Bash tools, Bash allowed | Provider permission system; no Alloy OS sandbox |
| Antigravity | `accept-edits`, `--sandbox`, private per-run write/command allowlist | Provider sandbox/settings; not certified as OS confinement |
| Cursor (macOS only) | Normal agent mode (no `--mode`), no force or auto-approval flag, closed argument grammar | Alloy-generated `sandbox-exec` write boundary; Cursor's own flags are not the boundary. See [Cursor roles](#cursor-roles) |

Cursor differs from the rows above: it runs inside an Alloy-generated macOS
`sandbox-exec` profile, and its permissions record says so (next section).

Consult/review panels retain their existing read-only flags. Antigravity Maker
settings never reuse the shared read-only panel settings directory. No global
permission-bypass flags are added. The Maker verifies review claims against the
code before correcting them; a Checker pass requires a valid structured response
with zero findings. Tests alone cannot substitute for the independent review.

A Git worktree isolates normal edits from the source checkout, **not arbitrary
shell behavior**. It shares Git metadata with the source repository; allowed paths
are checked after execution. Provider tools, project hooks and explicit test
commands run with the user's permissions. The scope check does not prevent a
shell command from writing elsewhere or making network calls. Use trusted projects
and provider sandbox policies appropriate to the task. Paths and post-run checks
must not be represented as a hard security boundary.

## Cursor roles

Cursor can serve as Maker or Checker on macOS only. Alloy refuses every Cursor
role, and does not fall back to a disposable copy or to Cursor's own flags, when
the platform is not macOS, `/usr/bin/sandbox-exec` is missing or not root-owned,
the profile self-test fails, or the installed Cursor build is not one Alloy has
measured. `ALLOY_ALLOW_UNSANDBOXED=1` never changes this. Boundary readiness is a
separate check from a role's read-only flag, so a Maker is wrapped exactly like a
Checker. `alloy doctor` shows `[no-sbx]` and the reason, and `--check` reports
Cursor as unavailable.

Cursor requires a one-time `AGENT_CLI_CREDENTIAL_STORE=file cursor-agent login`.
The login lives in `~/.cursor/auth.json` (0600). Every Cursor child receives
`AGENT_CLI_CREDENTIAL_STORE=file`; under Alloy the Cursor CLI is denied keychain
access and cannot start `/usr/bin/security`. Alloy never reads the keychain.
The pinned build writes `auth.json` directly and chmods it to 0600, with no temp
or atomic-rename files. Only that literal file is write-granted, plus permission
changes on the existing `~/.cursor` directory (the CLI chmods it to 0700).
No other home files are writable, and symlinked credential paths are refused.

| Role | Cursor mode | Writable | Process execution |
| --- | --- | --- | --- |
| Checker | `--mode ask` | The per-dispatch private runtime and CLI file login | Denied except three literal paths: the Cursor CLI's own bundled Node runtime binary, the build's bundled `rg` and `/usr/bin/sw_vers` |
| Maker | Cursor's normal agent mode (no `--mode`) | Non-Git contents of the owned worktree, the private runtime and CLI file login | Allowed inside the same write boundary; `/usr/bin/security` denied |

Alloy never runs the `cursor-agent` shell launcher or any wrapper script in front
of it. The launcher needs a shell and several coreutils, which a Checker's
sandbox denies. Alloy follows the symlinks behind the configured path to the
supported build's directory (behind a wrapper script it uses the supported
build in Cursor's standard install location, without running the wrapper),
checks that the build's `node` and `index.js` are regular files owned by you and
not writable by group or others, and starts `<build>/node --use-system-ca
<build>/index.js ...` directly. A Checker's sandbox allows exactly three
executables: that `node`, the build's bundled `rg` and
`/usr/bin/sw_vers`. `/bin/sh` and every other shell, `/usr/bin/open`,
`/usr/bin/log` and everything else stay denied. Under Alloy, the OS sandbox denies shell execution and file writes outside the task's allowed paths; the model may be offered tools it cannot use.
`/usr/bin/security` is denied in every role, and Alloy itself never runs it. Alloy checks `node` and `rg` like `index.js`
(regular files, owned by you, not writable by group or others) and
`sw_vers` like `sandbox-exec` (regular, non-symlink, root-owned, not writable by
others) before any Cursor process starts. A Maker's sandbox allows process
execution generally, so it allows these three too, but denies `/usr/bin/security`. The launcher's `CURSOR_INVOKED_AS` and compile-cache
settings are reproduced in the child environment, with the compile cache inside
the private runtime instead of your home cache.

For both roles the worktree's `.git` entry, its gitdir, the shared Git directory,
the source checkout, sibling worktrees, Cursor's other state and install
directories and the rest of the filesystem are write-denied; hard links are
denied; the fixed list of credential paths (and any you add with
`ALLOY_CURSOR_DENY_READ_PATHS`) cannot be read; worktree setup scripts are skipped;
and no force, auto-approval, MCP-approval, plan, plugin, session or worktree
option is ever passed. Alloy checks the complete final command line against a
closed grammar before starting the sandbox, so a later rewrite cannot add one.
Each call names one explicit model with a known family.

The permissions record is explicit. For a Cursor Maker it contains:

```json
{
  "repository_write": true,
  "command_execution": "allowed_in_worktree",
  "enforcement": "macos_sandbox_exec",
  "os_isolation": true,
  "git_metadata_isolated": true,
  "scope_validation": "content_fingerprint_tripwire",
  "write_allowlist": ["owned_worktree_non_git_content", "private_runtime_state",
                      "private_runtime_cache", "private_runtime_tmp"],
  "cursor_mode": "agent_default",
  "approval_bypass": false,
  "sensitive_reads_denied": true,
  "setup_scripts_skipped": true
}
```

A Cursor Checker reports `repository_write: false`, `command_execution: "denied"`,
`cursor_mode: "ask"` and the three private-runtime write entries. These recorded entries describe
workspace/runtime grants; both roles also receive the file-login refresh and
directory chmod allowances described above.

**Family by model.** Independence is judged on the family derived from the model
ID, not from the CLI name. With an OpenAI host, `cursor-large-claude-opus-5-5`
(Anthropic) can be the Maker and `cursor-large-composer-2-5` (family `cursor`)
can be the Checker. With an Anthropic host, a Cursor-served Claude model can be
neither. A Cursor-served GPT model can never check an OpenAI Maker. Cursor
Composer is its own family, independent of OpenAI, Anthropic, Google and xAI.
`auto` and unknown model IDs are never dispatched.

**Detection, not prevention.** The sandbox is the boundary. In addition, after the
Cursor process group is dead, Alloy compares byte-level fingerprints of the
worktree (tracked, untracked and ignored files, with their modes and symlink
targets) and of the Git internals that change behavior, and checks canary files
outside the workspace. For a Maker, ordinary files may differ only under
`--allow-path`, including ignored files, which the normal scope check omits;
Git internals and canaries may never differ. For a Checker nothing may differ.
The check runs before the test gates or the review verdict is used. Any change, or
any path that cannot be read or hashed, stops the task with the worktree retained
and review skipped, and the task is then kept for inspection and cannot be resumed
in place. These checks cannot prove the whole filesystem was unchanged.

Every Git command Alloy itself runs (cleanliness, scope, worktree setup, add,
commit, fingerprints) disables hooks and `core.fsmonitor`, ignores system
configuration, detaches stdin and bounds output and time. The Checker packet is
redacted before it is saved and before it is staged for Cursor. Cursor's own
login is a file that Cursor reads and refreshes itself; Alloy never reads the keychain.
Reads of the repository and the provider network stay available, so a Cursor role
is not an exfiltration boundary; see [SECURITY.md](../SECURITY.md). The sandbox
covers the Cursor process and what it starts. Your `--test` gate commands are run
by Alloy with your permissions, outside that sandbox, as for every other provider.

### Cursor release evidence

After the offline suite and skill validation pass, an explicitly authorized
operator runs both release gates on the release Mac, outside any Maker sandbox.
Use the supported build and the file login described above. The real-build gate
uses version and authenticated status calls without provider inference; the ask
probe makes one provider inference call with composer-2.5 only. Neither belongs
in the offline test suite. Offline tests and the stand-in CI gate do not supply this live evidence.

Run from the repository root in bash or zsh. Keep logs outside the checkout:

```sh
set -e
set -o pipefail
report_dir="$(mktemp -d "${TMPDIR:-/tmp}/alloy-cursor-release.XXXXXX")"
ALLOY_CURSOR_SANDBOX_GATE=1 ALLOY_CURSOR_BUILD_GATE=1 \
  python3 -m unittest discover -s tests -p 'test_cursor_sandbox_release_gate.py' -v \
  2>&1 | tee "$report_dir/build-gate.log"
# Continue only after the build gate passes without skips.
ALLOY_LIVE_CURSOR=1 ALLOY_LIVE_CURSOR_MODEL=composer-2.5 \
  python3 tests/live/cursor_ask_release.py \
  2>&1 | tee "$report_dir/ask-gate.log"
python3 tests/live/cursor_ask_release.py --verify-report "$report_dir" \
  > "$report_dir/release-report.json"
```

Attach both logs and `release-report.json` to the release report, along with the
tested revision, any uncommitted patch and each command's exit status; neither
gate may be skipped.
The build log must show
`test_status_reaches_the_authenticated_state_under_the_production_panel_profile`
passing, together with the exact three-executable allowlist and shell/security
denial checks. Include the complete `CURSOR_ASK_RELEASE_RECORD` JSON line from
the ask log, with `passed: true`, model `composer-2.5`, the supported build and
every check true. A missing record, failed gate or skipped gate leaves release
verification incomplete; do not infer a pass from the offline suite.

`--verify-report` runs offline and never starts Cursor. It refuses absent or
duplicate ask records, incomplete or failed checks, models other than
composer-2.5, unsupported builds, and missing or skipped real-build results.
The JSON report includes the complete ask record and SHA-256 hashes of both logs.
This validates supplied evidence; the operator remains responsible for recording
both actual runs on the release Mac and identifying the tested revision and patch.

## Storage and recovery

Default state is `$XDG_STATE_HOME/alloy/execution` (or
`~/.local/state/alloy/execution`). With `ALLOY_RUN_ROOT`, execution lives in the
sibling `execution` directory. State must be outside the source repository.
Task records, prompts and results use private files; logs are best-effort secret
redacted. Specs and source diffs can still contain sensitive project material.
The Jev key is removed from worker and test subprocess environments.

Records include task/base/tip IDs, selected workers, allowed paths, test commands,
rounds, review verdicts and integration receipts. Per-task locks prevent concurrent
resume/integrate/cleanup; repository locks serialize Alloy lifecycle mutations.
Saved process IDs guard against resuming while a worker may still be alive.
External editors and Git commands do not honor Alloy's locks: avoid concurrent
manual mutations of a task worktree during execution or cleanup.

Checkers read the same task worktree directly; there is no per-round repository
copy. On macOS, managed non-Cursor Checkers also run through `sandbox-exec` with
writes denied to the task tree, source checkout and shared Git metadata. Their
CLI read-only flags remain in place. Cursor retains its stronger dedicated OS
sandbox and tripwires. On other platforms Codex uses its native read-only sandbox;
other managed Checkers refuse without an OS boundary. This restriction applies
to managed execute, while consult/review panels retain their existing policies.
Post-call revision/tamper checks still run. Every Cursor temporary runtime is
registered immediately and cleaned after dispatch, at exit and on SIGINT/SIGTERM.
Signals retain implementation work and its cumulative budget for recovery.

### Every-round usage display

Execute emits `ALLOY_ROUND_USAGE` on stderr before each Maker round, including
corrections and resumed rounds. Each event includes a Markdown usage table and
planned Maker/Checker assignments. The same text is in `round-N/usage.md` and
the public snapshot in `task.json` under `rounds[N].usage`. JSON stdout remains
machine-readable. The host must render every new round in chat, even when usage
or workers have not changed; tool output alone is insufficient. Normal cache
TTL and disabled/unavailable tracking behavior are preserved. Buffered hosts
can read unseen round files while waiting. Waiting polls need no repeated table.

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
