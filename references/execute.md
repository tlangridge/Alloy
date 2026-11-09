# Managed execute host workflow

Read this before execute, resume, integration or cleanup.

Offload implementation, tests and adversarial correction to the provider CLIs.
**Do not implement the feature yourself.** You are the Lead/Judge, receiving a
compact result instead of relaying patches and full transcripts. The Maker,
Checker and host must have three distinct **model families**, even when a CLI
can serve models from several families. Normal `alloy panel` remains read-only.

### 1. Scope the task

Write a concise SPEC covering: goal, current behavior, desired behavior, allowed
paths, non-goals, acceptance criteria, test commands, and handoff criteria.
Include a concrete reproduction and before/after acceptance check in the SPEC.
If authorized Jevgrep discovery supplied context, include relevant native excerpts
and their source revision as reference evidence; preserve the SPEC's actual requirements.
Keep local tests, deployment, and live behavior verification as separate outcomes.
Use the user's existing authorization. Resolve missing requirements before
spending provider tokens; do not add an approval ceremony for an authorized task.
Start from a clean committed checkout on the intended target branch. Never
stash, reset, or commit unrelated user work just to satisfy this condition.

Run `alloy models list` to inspect configured profiles; run `alloy setup` if
needed (use `alloy setup --keyless --non-interactive` when Jev is not configured). Preserve model pins and billing preferences. Show the usage table and task assignments as required in SKILL.md. Explain that execute defaults to an initial Maker call
plus one correction within 45 active minutes per logical task. Checker transport
failures can retry the unchanged revision twice per review without another Maker.
The ordinary successful path uses two worker dispatches, or four with a
correction. With transport retries at both reviews, the default implementation
allowance can reach eight worker dispatches, subject to the active budget.
Provider-level authentication retries can add calls; do not promise a fixed
six-call billing cap. Estimated spend limits
apply **per provider dispatch**, not as a hard whole-task billing cap.

### 2. Dispatch once

Write the SPEC outside the source repository, then invoke the actual CLI:

```bash
"$ALLOY_BIN" execute --prompt-file /absolute/path/spec.txt --repo /absolute/path/repo \
  --host-family openai --route --allow-path src --allow-path tests \
  --test 'python3 -m unittest discover -s tests -v'
```

Add `--check` to the execute command when a readiness report is needed before
dispatch; normal execute also checks readiness. Show the combined blocker report
instead of attempting workers one at a time.

Set `--host-family` to your actual model family, not automatically to your CLI's
(a host running Cursor's Composer is family `cursor`). A Cursor worker's family is
the vendor of its model (`claude-*` Anthropic, `gpt-*` OpenAI, `gemini-*` Google,
`grok-*` xAI, `composer-*` `cursor`), so a Cursor-served Claude model is never
independent of an Anthropic host.
Prefer `--route` whenever Jev routing is authorized/configured and its key is
available (unless the user explicitly requests keyless mode); otherwise replace
it with `--maker-profile <id> --checker-profile <id>`. Jev assesses the task once;
code chooses eligible workers and rechecks model pins, billing, compatibility and
quota reserves before each dispatch. It never silently changes models mid-loop.
The same Maker verifies Checker evidence before fixing; unsupported claims must
be challenged, not blindly obeyed. Independent Checker contexts reduce shared
assumptions. Each review returns at most 5 findings with path, evidence and a
scoped remedy. Malformed reviews fail closed. Stop after one correction by default;
the runtime shares active budget and implementation rounds across resumes and
relaunches. Repeated blockers or no acceptance progress stop earlier. Owner flags
may extend the total allowance; retain pins, billing and independent review.

Each round emits `ALLOY_ROUND_USAGE` with the usage table and planned worker roles
on stderr and saves `round-N/usage.md` plus a public snapshot in the task record.
When this event appears, immediately render its table and assignments in visible
chat, outside code fences, even on corrections with unchanged workers. If the
host buffers output, read the saved round files while waiting and render each
unseen round once. Tool output alone does not satisfy this requirement.

Maker commands use explicit edit/test permissions. `--allow-path` is validated
after execution, not an OS confinement boundary. Codex uses `workspace-write`;
Claude/Grok use `acceptEdits` and Bash permissions; Antigravity uses `accept-edits`
and a private per-run settings directory with write/command tools. A Cursor Maker
runs Cursor's normal agent mode inside the macOS sandbox and can write only the
non-Git contents of its worktree, a private runtime and the CLI file login; a Cursor Checker runs
`--mode ask` with that runtime and the CLI file login writable. Cursor profiles ship disabled, so
enable them only when the user asks (`alloy setup --enable-cursor` or `alloy
models enable --id ID`). If the sandbox is unavailable the role is refused. No
sandbox bypass flags. Inspect `task.json` and each worker's `status.json` for machine-readable
`permissions.repository_write`, `command_execution`, enforcement and scope.

Never detach dispatch with `nohup`, `disown`, or shell backgrounding. Keep the
terminal/tool session attached and wait for completion. Report new results,
failures, blockers and decisions; avoid repeated “still running” updates. Use
`blocking_step` to identify what prevents completion. Reuse sessions through Alloy;
never manually resume a provider to bypass its bounds or permissions.
Use `"$ALLOY_BIN" tasks` to locate active/retained task IDs and records. A timeout
retains the worktree; inspect the error and subprocess status, then use
`"$ALLOY_BIN" resume <task-id>` if there are remaining attempts. Never resume the
provider session directly or reset the attempt count. An exhausted loop goes to
the host for a decision, not another unbounded retry.

### 3. Judge, integrate, clean up

Exit 0 with `state: ready` means explicit tests and independent review passed.
It does **not** mean merged. Read the compact JSON packet, `changes.patch`, and
recorded gate/review results as needed; do not ingest every transcript by default.
Report any limitations. The host may judge directly or use a separately authorized
judge. No deployment or remote push is implied.

When integration is within the user's authorized task:

```bash
"$ALLOY_BIN" integrate <task-id>           # fast-forward, then verified cleanup
# Or: "$ALLOY_BIN" integrate <task-id> --squash
```

The source checkout must still be clean, on its original branch, at the task's
base. If it advanced, start a fresh task/review or integrate externally under the
host's normal workflow; do not force reset it. Integration automatically removes
the clean Alloy-owned worktree and branch, retaining logs, diff and receipt.

For a merge performed outside Alloy:

```bash
"$ALLOY_BIN" cleanup <task-id> --dry-run
"$ALLOY_BIN" cleanup <task-id>
# Squash: add --integrated-commit <full-commit-hash> to both commands.
```

Single-task cleanup requires ancestry proof, exact squash commit diff or full
content/patch-ID proof on the default branch. Local edits, new commits, incomplete
review or uncertain integration prevent single-task merge cleanup. For finished
abandoned work, use `"$ALLOY_BIN" cleanup --all-finished --dry-run` to inspect the
archive disposition, then the same command without `--dry-run`. Alloy verifies
an archive before force-removing only its owned worktree and pruning stale Git
registrations. Never manually force-remove unfinished work. Execute-start hygiene
does the same for closed tasks idle over 24 hours; owner-response windows and
archive upload hooks are configurable. Four retained tasks per remote repository
remain the default; disk guards run hygiene before refusing new worktrees.

Finish with the task ID, workers, changes, test/review outcome, and whether it is
ready, integrated/cleaned, or retained with a reason. See `docs/execution.md` for
the lifecycle and capability contract.
