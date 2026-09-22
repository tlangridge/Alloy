# Managed execution

`alloy execute` delegates implementation and testing to a provider CLI in an
Alloy-owned Git worktree. A different model family reviews the result read-only;
Alloy passes evidence back to the same Maker for up to two correction rounds.
The host receives a compact JSON handoff and decides whether to integrate.
This reduces host-agent implementation and transcript handling; actual token
savings depend on the task and are not measured or guaranteed.

## Start a task

Requirements: Python 3.8+, Git 2.31+, a clean committed repository on a branch,
and eligible Maker and Checker profiles from two families distinct from the host.
Codex, Claude, Grok and Antigravity (`agy` 1.1+) have managed-write adapters. CLI
help/version checks fail closed when required permission flags are unavailable.
These are compatibility checks, not proof that a particular CLI version correctly
enforces its permissions. Provider profiles remain editable configuration.

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
seconds per test command. `--max-fix-rounds` defaults to 2 and cannot exceed 2.
That permits at most three Maker and three Checker dispatches. Failed local tests
return to the Maker without spending a Checker call. Resumes share the original
attempt limit. `--max-estimated-usd` is a per-dispatch routing estimate, not a
hard provider billing limit or whole-task budget. Subscription quota information
can be cached or unavailable; unknown quota does not mean unlimited capacity.

## Readiness, sessions and review context

Add `--check` to the same execute command for a JSON readiness report. It checks
source cleanliness/branch, the four-worktree limit, configured models and pins,
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
worker profiles and receive full context on every call. No `--last` session
selection is used.

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
context receipt failures, and wall time to the locally verified result. Timings
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
# For an external squash, add this option to both commands:
# --integrated-commit FULL_COMMIT_HASH
```

Cleanup verifies that the exact reviewed commit is an ancestor of the recorded
local target branch. For squash merges it requires a single-parent commit on that
branch whose full binary diff exactly matches the task diff. Squashes with extra
changes or conflict adaptations do not qualify. Remote-only merges require local
branch synchronization before proof. No fuzzy patch matching and no force removal.

Only the registered Alloy worktree and its matching branch are removed. Local
tracked/untracked edits, new commits, missing review, a branch moved to another
worktree, or uncertain integration block cleanup. Ignored build/dependency files
are disposable when Git permits removal. A durable integration receipt supports
retrying cleanup after an interruption. Cleanup is idempotent; it never broadly
prunes Git worktrees. Diff, specification, gate results and model logs remain on
disk after worktree removal.

Alloy allows at most four retained tasks per repository. Failed/interrupted tasks
are not age-deleted: inspect and recover them. There is intentionally no automatic
abandon/discard operation for unintegrated work. Any manual destructive disposal
requires separately deciding how to preserve that work. Removing only a directory
outside Alloy does not mark a task cleaned and can leave Git registrations behind.

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

### Every-round usage display

Execute emits `ALLOY_ROUND_USAGE` on stderr before each Maker round, including
corrections and resumed rounds. Each event includes a Markdown usage table and
planned Maker/Checker assignments. The same text is in `round-N/usage.md` and
the public snapshot in `task.json` under `rounds[N].usage`. JSON stdout remains
machine-readable. The host must render every new round in chat, even when usage
or workers have not changed; tool output alone is insufficient. Normal cache
TTL and disabled/unavailable tracking behavior are preserved. Buffered hosts
can read unseen round files while waiting. Waiting polls need no repeated table.
