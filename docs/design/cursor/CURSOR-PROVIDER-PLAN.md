# Cursor provider implementation plan (Alloy 0.11.0)

Status: implementation-ready. This plan adds Cursor as a first-class panel,
managed Maker, and managed Checker provider without treating Cursor's own mode or
sandbox flags as a security boundary. The release target is `0.11.0`.

## Scope and verified baseline

The existing `CursorAgentAdapter` is only an experimental `cursor-agent` stub:
it inherits the base class's optimistic authentication result, reports
`read_only = False`, emits text, and is excluded from normal panels and managed
write execution. There are no Cursor routing profiles. (`bin/alloy:406-412`,
`bin/alloy:1011-1034`, `bin/alloy:1205-1223`,
`bin/alloy_execution.py:114-120`, `bin/alloy_routing.py:25-27`.)

The supplied CLI evidence establishes a positional prompt, JSON output,
`--model`, `--list-models`, `--mode ask`, and the dangerous approval flags. It
does **not** document stdin as a prompt transport. The recorded headless call put
the prompt on argv and returned `result`, `is_error`, `usage`, and `session_id`.
(`docs/design/cursor/CURSOR-FACTS.md:9-59`,
`docs/design/cursor/CURSOR-FACTS.md:361-365`.) The implementation therefore will
not infer stdin support.

The boundary evidence is decisive: plan mode wrote inside and outside the
workspace, `--sandbox enabled` wrote outside, and plan plus sandbox could switch
itself to Agent mode and write. The raw log contains three ask-mode runs—one
plain and two forceful—and all three refused; it does not contain the four runs
claimed by the summary. Ask mode is still a model/tool-mode control rather than
an OS boundary. (`docs/design/cursor/BOUNDARY-PROBE.txt:1-9`,
`docs/design/cursor/BOUNDARY-PROBE-README.md:6-18`.) `--mode ask` is defense in
depth; OS write isolation is the write boundary.

### Corrections to `PROVIDER-MAP.md`

The map was checked against the cited revision. Its main registry, routing,
execution, usage, test, release, and documentation locations are correct. The
following details are wrong or incomplete and must not be copied into the
implementation:

1. It implies a uniform `ALLOY_BIN_<NAME>` convention. The adapter path replaces
   hyphens with underscores, while the usage path currently concatenates the raw
   provider name. For `cursor-agent` those produce
   `ALLOY_BIN_CURSOR_AGENT` and `ALLOY_BIN_CURSOR-AGENT`, respectively.
   (`bin/alloy:393-401`, `bin/alloy_usage.py:241-247`.) Canonicalizing the public
   name to `cursor` removes this inconsistency; the legacy underscored key remains
   a compatibility fallback.
2. The current stub and guides say Cursor has no read-only mode
   (`bin/alloy:1011-1018`, `docs/adding-a-panelist.md:101-132`), but the captured
   CLI now has `--mode ask`. That newer mode is useful but is not sufficient:
   the probe shows why the plan still requires OS enforcement. This is an
   obsolete product conclusion, not evidence that the adapter may simply flip
   `read_only` to true.
3. The map calls the current worktree fingerprint a safety check, which is true,
   but it is only a post-run tripwire. The implementation must not describe it as
   prevention. The current panel path compares Git status and HEAD after the run,
   and managed review separately checks a clean worktree and unchanged HEAD.
   (`bin/alloy:1353-1360`, `bin/alloy:1904-1923`,
   `bin/alloy_execution.py:548-562`.)

No Cursor host-skill installation is in scope. `install.sh` currently installs
the Alloy binary and three skills into detected host skill directories
(`install.sh:21-42`). Running Cursor as a provider does not require teaching
Cursor to discover Alloy as a host, so `install.sh` and `agents/openai.yaml` will
not change.

## 1. Public name and compatibility

### Decision

The public provider/adapter name is **`cursor`**. The executable remains
`cursor-agent`; `agent` is not used because it is too generic to resolve safely.
`CursorAgentAdapter` may retain its Python class name, but its `name` becomes
`cursor`, it becomes non-experimental when the OS boundary is available, and
`ADAPTERS` has one canonical `cursor` entry. There must not be a second adapter
entry for the alias because that would duplicate doctor rows and panel calls.

Add `ADAPTER_ALIASES = {"cursor-agent": "cursor"}` and one
`normalize_adapter_name()` helper. Normalize at config/input boundaries, never in
run artifact output. The affected public keys are:

| Surface | Canonical value | Compatibility behavior |
| --- | --- | --- |
| `ALLOY_PANELISTS`, `--panelists` | `cursor` | Accept `cursor-agent`, normalize and deduplicate before lookup. |
| Binary override | `ALLOY_BIN_CURSOR` | If unset, read `ALLOY_BIN_CURSOR_AGENT`; canonical wins when both exist. |
| Model pin | `ALLOY_CURSOR_MODEL` | If unset, read `ALLOY_CURSOR_AGENT_MODEL`; warn once in doctor JSON/text that the alias is deprecated. |
| Effort pin | `ALLOY_CURSOR_EFFORT` | If unset, read `ALLOY_CURSOR_AGENT_EFFORT`; canonical wins. |
| Routing profile `adapter` | `cursor` | Normalize an imported `cursor-agent` value before validation and persist `cursor` on the next explicit save. |
| Usage provider and shared pool | `cursor` | Never create `cursor-agent` usage/cache/pool keys. |
| Run directory and manifest `name` | `cursor` | Always write `<run>/cursor` and `name: cursor`, even when selected through the alias. |

Files/functions:

- `bin/alloy`: change `CursorAgentAdapter.name`, the `ADAPTERS` registry,
  `Adapter.resolved_bin()`/a Cursor override, `selected_panelists()`, and explicit
  `--panelists` normalization in `cmd_panel()`. The current selection and run
  directory use adapter names directly (`bin/alloy:1226-1230`,
  `bin/alloy:1751-1755`, `bin/alloy:1874-1892`).
- `bin/alloy_routing.py`: add canonical `cursor` to the provider registry and
  normalize aliases in `load()`, `setup()`, and `models_command()` before
  validation. Current model/effort keys are generated from the registry
  (`bin/alloy_routing.py:25-27`), and profile commands persist the adapter value
  (`bin/alloy_routing.py:880-919`).
- `bin/alloy_usage.py`: use only the canonical `cursor` provider key in snapshots,
  labels, bindings, and pools. Current provider names are global constants
  (`bin/alloy_usage.py:22-23`).
- `tests/test_alloy.py`, `tests/test_routing.py`, and `tests/test_usage.py`: prove
  the alias selects exactly one canonical run, canonical environment variables
  win, legacy keys still work, and no persisted `cursor-agent` key remains.

## 2. OS isolation and role boundaries

### One boundary state and one spawn gateway

Add a Cursor-specific spawn gateway in `bin/alloy`. Boundary readiness is a
separate, read-only capability such as `cursor_boundary_ready`; it is not
represented by `read_only` and cannot be changed by the per-instance subclass
that currently sets Maker `read_only = False`
(`bin/alloy_execution.py:114-155`). `read_only` continues to describe the role;
boundary readiness describes whether any Cursor process may start.

Every Cursor process goes through this gateway: authentication `status`, version
and help probes, model discovery, ordinary/default/routed panels, managed Makers
and Checkers, and any release probe. No caller may invoke `cursor-agent`
directly. The gateway validates the boundary, validates the final argv, creates
the profile, then returns:

```text
/usr/bin/sandbox-exec -f <owner-private-profile.sb> <resolved-cursor-agent> ...
```

`run_panelist()` calls the gateway after all adapter/routing/managed argv
rewrites. At that final spawn point the gateway parses the complete argv against
separate, closed role grammars; it does not use a substring denylist. Unknown
options, duplicate singleton options, unexpected positional arguments, and a
subcommand in an inference call fail closed. The routing and execution metadata
paths call the same API rather than their current direct `subprocess.run()` sites
(`bin/alloy_routing.py:417-441`, `bin/alloy_execution.py:159-170`). Usage does
not spawn Cursor because the CLI has no usage source. Section 3 defines the exact
role grammars and the controls rejected after every rewrite.

Do not resolve `sandbox-exec` through `PATH`. Verify `/usr/bin/sandbox-exec` is a
regular, non-symlink, root-owned file not writable by group/other. Cache a
versioned, non-network preflight which uses the production profile generator and
proves allowed and denied operations. The preflight must prove both that a
direct read of a configured denied-read fixture fails and that the sandboxed
non-network CLI probe still starts and returns its expected output; testing only
writes is insufficient. A missing binary, invalid profile, unsupported CLI
version, failed read/write/process preflight, or uncertain path makes
`cursor_boundary_ready` false.

For 0.11.0, macOS is the only supported Cursor execution platform. On Linux and
other platforms every Cursor path fails closed. Doctor must say: `Cursor
installed/authenticated, but no supported OS write sandbox is available; Cursor
roles are refused.` `ALLOY_ALLOW_UNSANDBOXED=1` never overrides this rule, and
the old disposable-copy path is not a Cursor fallback.

### SBPL and writable-path rules

Both Cursor profiles are generated in `bin/alloy` in the same implementation
lane. The panel profile is also the discovery/metadata profile; thus panel,
Checker, Maker, `status`, version/help, and model discovery all receive the same
mandatory sensitive-read denials. The profiles default-deny writes, hard-link
creation, and process execution, then add only role-specific grants. Paths are
canonicalized, checked for symlinks and SBPL-escaped. The profiles include
explicit `file-link` denial and `file-write-create`/write grants only for the
exact allowlist; a path spelling through a symlink must not broaden the target.
Panel/Checker process execution is limited to the already-resolved Cursor
executable needed for the initial `sandbox-exec` handoff; descendant shell,
helper, and plugin execution is denied. There is no undefined “platform
bootstrap” exception. Maker process execution is enabled because that role must
run repository commands, but the write allowlist and sensitive-read denials
remain enforced. Worktree setup scripts are disabled by argv, not accommodated
with extra execution grants. If the installed CLI needs another executable for a
panel/Checker or an unrequested setup helper for a Maker, the preflight fails; do
not add a broad panel/Checker `(allow process*)` or broaden writable paths.

Every generated Cursor profile adds explicit `(deny file-read*)` rules for the
listed file itself and, where the entry is a directory, every descendant:

```text
~/.ssh
~/.aws
~/.gnupg
~/.config/gh
~/.netrc
~/.docker/config.json
~/.kube
~/.npmrc
~/.pypirc
~/.git-credentials
~/Library/Keychains
~/.openclaw/secrets
~/.cswarm
~/.codex/auth.json
~/.claude/.credentials.json
~/.gemini
~/.grok
~/.config/op
~/Library/Group Containers/*1password*
<resolved Alloy secrets root and its state, including the future `alloy secrets` store>
/private/tmp/anvil-secret.*
```

The two wildcard entries are emitted as anchored, SBPL-escaped regex rules;
ordinary entries are literal/subpath rules. Missing paths remain denied if later
created. Resolve `~` from the real login home, never the private runtime. Add
`ALLOY_CURSOR_DENY_READ_PATHS` to Alloy's parsed `KEY=value` config as a
comma-separated list of additional file or directory paths. Canonicalize each
entry without following a final symlink, reject relative/empty/ambiguous entries,
and union it with the built-in list; users may add denials but cannot remove a
built-in denial. Profile ordering must make these read denials non-overridable by
repository, staged-prompt, executable, runtime, or Maker worktree read grants.
The only intentional overlap is a user error: if an extra denial covers a
required executable/repository/prompt/runtime path, preflight fails closed
instead of dropping the denial.

Create each dispatch's writable runtime with an owner-private system temporary
directory, not below `<pdir>`, the configured `ALLOY_RUN_ROOT`, the source
checkout, any managed worktree, or any Git common directory. Before use, verify
with `realpath`, ancestry checks, and `git rev-parse --show-toplevel` that the
runtime and its `state`, `cache`, and `tmp` children are outside every relevant
repository and outside any repository containing `ALLOY_RUN_ROOT`. Keep `HOME`
pointing at the real login location but write-denied; export only the exact
private children as `XDG_STATE_HOME`, `XDG_CACHE_HOME`, and `TMPDIR`. For a panel
or Checker this private runtime is the only writable root. For a Maker the owned
worktree's non-Git contents are the only additional writable root. In every role,
explicitly deny writes to an ordinary checkout's `.git` directory, a linked
worktree's `.git` pointer file, the resolved worktree gitdir, and the Git common
directory. The Maker's broader worktree grant must not override those denials.
Resolve and verify all four locations before profile creation; ambiguity or a
nonstandard pointer fails closed. This is required because `git worktree add`
creates the linked pointer inside the otherwise writable worktree
(`bin/alloy_execution.py:629-646`).

Do not write-enable the real `~/.cursor`,
`~/.local/share/cursor-agent`, `~/Library/Caches`, the install/version tree,
`$HOME`, an Alloy run directory, or a system-temp parent. Cursor's login is not a
token file: the measured CLI uses macOS generic-password keychain items named
`cursor-access-token` and `cursor-refresh-token`, and no token file exists under
`~/.cursor` or the CLI install tree
(`docs/design/cursor/CURSOR-FACTS.md:368-370`). Direct reads of
`~/Library/Keychains` are denied in every role. The provider may use its normal
Security API access to its login item, while Alloy itself must never read the
keychain database or item. If the supported CLI cannot complete an authenticated
ask call with only the private runtime writable and all built-in sensitive-read
denials active, the release is blocked; do not widen the home grant to make it
work. Remove the private runtime after the process group is dead.

The profile permits the network needed to call Cursor. **Alloy explicitly
accepts the residual confidentiality risk** that the Cursor process uses its
keychain login item through the Security API, can read the repository, and uses
the network; SBPL cannot distinguish the CLI's legitimate in-process
repository reads/network from its model-facing read tool. This is not permission
to read arbitrary credential paths: every role has the mandatory deny list
above, including direct keychain-database reads. An in-process read tool cannot
read the Cursor login item as a file, and panel/Checker ask mode has no shell
with which to invoke a keychain client. SBPL cannot express a useful host rule
that separates the remaining allowed repository reads and provider network, so
do not claim or attempt host-based network isolation. The mitigations are:
panel/Checker ask mode; a supported-version probe proving that ask mode exposes
no shell tool; descendant-process denial; OS write denial; mandatory sensitive
file-read denials; JWT/assignment/header redaction before every persisted sink;
and a Checker prompt built only from a bounded, redacted review packet, never
from raw status/auth output, child environment/config, keychain data, or
unredacted Maker/gate output. “Checker never receives staged secrets” means Alloy
never places recognized secret material into the staged Checker packet; it does
not mean the in-process read tool cannot read repository data. These controls
reduce but do not close the accepted keychain-login/repository/network risk, and
documentation must not claim complete credential isolation or an
exfiltration-proof Checker.

Add defense-in-depth canaries outside the writable runtime and repositories.
Replace the current HEAD-plus-status tripwire (`bin/alloy:1353-1360`) with a
deterministic before/after **content** fingerprint for every Cursor panel and
Checker. Hash path, type, mode, symlink target, and file bytes for every tracked,
untracked, and ignored worktree entry; never follow a symlink while hashing. A
status line or filename-only listing is not a content fingerprint. Separately
hash the linked `.git` pointer when present and the content under the resolved
Git locations that can change behavior: `commondir`, `config`,
`config.worktree`, `hooks/`, `info/exclude`, `info/attributes`,
`info/sparse-checkout`, `HEAD`, `refs/`, and `packed-refs` in the worktree gitdir
and common dir as applicable. Include missing/present state so creation or
deletion changes the digest. In particular, digest the `commondir` file itself,
not only the directory to which it resolves. Refuse the call if enumeration
races, a file cannot be read, a path changes type, a Git location cannot be
resolved, or the digest is otherwise uncertain.

Every Git command Alloy runs in the unsandboxed parent—including `clean()`,
`scope()`, worktree setup, `git add`, `git commit`, and fingerprint/enumeration
commands—must go through one helper that prepends
`-c core.hooksPath=/dev/null -c core.fsmonitor=false` and sets
`GIT_CONFIG_NOSYSTEM=1`, `GIT_OPTIONAL_LOCKS=0`, `stdin=DEVNULL`, bounded output,
and a timeout. No path may invoke external diff/textconv helpers. This disables
repository hooks and command-valued `core.fsmonitor` for parent-side checks and
integration, rather than only for fingerprint Git. The current panel `_git()`
omits hook suppression (`bin/alloy:1283-1286`); the managed helper has
`core.hooksPath` but lacks the complete contract
(`bin/alloy_execution.py:29-38`). Repository `alias.*` entries are not a
built-in-command shadowing risk for the commands Alloy calls: Git's official
`alias.*` documentation says aliases that hide existing Git commands are
ignored (except deprecated commands):
https://git-scm.com/docs/git-config#Documentation/git-config.txt-alias. Keep
status and `scope()` for ordinary user-facing validation, but neither
`git status --ignored` nor the current ignored-dropping `scope()` is accepted as
the tamper proof (`bin/alloy_execution.py:82-102`). Managed Checker acceptance
uses the same content/Git-internals fingerprint in addition to clean/HEAD
(`bin/alloy_execution.py:559-560`). Compare fingerprints and outside-canary
content/metadata only after the whole process group is dead. Any mutation fails
the call and rejects a Checker verdict. This remains a tripwire, not prevention;
the SBPL write denial is the boundary. Retain process-group deadlines, descendant
kill, and persisted-output redaction (`bin/alloy:1363-1377`,
`bin/alloy:1482-1555`, `bin/alloy:1581-1604`).

Files/functions:

- `bin/alloy`: add the immutable Cursor boundary capability, private-runtime and
  SBPL builders for both roles, mandatory/extra sensitive-read denials, one spawn
  gateway, forbidden-argv validation, hardened parent Git helpers,
  content/Git-internals fingerprinting, and
  gateway/canary integration in
  `run_panelist()`, auth and version probes.
- `bin/alloy_routing.py`: use the gateway for help/version/model discovery.
- `bin/alloy_execution.py`: use the gateway for compatibility probes, report the
  real allowlist in `permissions()`, and reject boundary/canary failures before
  Maker gates or Checker verdicts.
- `tests/test_alloy.py` and `tests/test_execution.py`: inspect generated profiles
  with mock processes; assert every role and discovery deny every built-in and
  configured sensitive-read path; mutate bytes without changing
  filenames/status lines; mutate each protected Git-internal class; verify every
  parent Git subprocess has the complete hook/fsmonitor/system-config contract;
  and prove all unavailable/invalid boundary states refuse dispatch. The
  separate real macOS release gate is in section 9.

### Panel and Checker boundary

Cursor panels and Checkers use all of the following:

1. `-p --mode ask --output-format json` with a known, explicit model;
2. no shell tool in ask mode, verified for the supported Cursor version;
3. the macOS profile above, with only the private runtime writable and
   descendant process execution denied; and
4. full worktree/Git-internals content fingerprints plus outside canaries.

The repository and all Git metadata are read-only in the OS profile. The final
panel/Checker grammar requires exactly one `--mode ask`, `--sandbox enabled`,
`--skip-worktree-setup`, `--workspace <verified-repo>`, `--model
<validated-effective-model>`, `--output-format json`, `--trust`, `-p`, and one
bounded staged-file instruction. Reject every other option or command, including
`--plan`, `--plugin-dir`, `--add-dir`, `--resume`, `--continue`, `-w`,
`--worktree`, `--worktree-base`, and `worker`. Reject `--force`, `-f`, `--yolo`,
`--auto-review`, and `--approve-mcps`. `--sandbox disabled`, a duplicate sandbox
option, or any `--mode` value other than the one Alloy set also fails. The CLI
documents these controls at `docs/design/cursor/CURSOR-FACTS.md:34-73` and its
local worker subcommand at `docs/design/cursor/CURSOR-FACTS.md:76-104`.
`--sandbox enabled` remains defense in depth and provides no Alloy security
guarantee. Keep packet-receipt validation unchanged
(`bin/alloy_execution.py:376-400`).

`CursorAgentAdapter.read_only` is true for the panel/review role, while
`cursor_boundary_ready` is independently required. `default_panel_names()`,
selection, `run_panelist()`, managed `probe()`, and `estimate` all check the
boundary explicitly; none may infer it from `read_only`.

### Maker boundary

Cursor Makers use an explicit branch in
`bin/alloy_execution.py:worker_adapter()`; the final provider branch raises
unsupported rather than treating Cursor as Antigravity
(`bin/alloy_execution.py:114-155`). The Maker SBPL write allowlist is exactly:

- all non-Git content beneath the resolved Alloy-owned worktree; and
- the exact per-dispatch private runtime (`state`, `cache`, and `TMPDIR`).

The worktree `.git` pointer/directory, resolved worktree gitdir, linked Git common
directory, source checkout, sibling worktrees, real Cursor state/login/install
paths, credentials, and the rest of the filesystem remain write-denied.
Hard-link creation remains denied so a writable worktree/runtime name cannot
become an alias for an outside inode. Reads and provider network are available;
Maker command execution is allowed inside the same OS write boundary.

The Maker final grammar is also closed. It uses print mode's default agent
execution by omitting `--mode`, requires `--sandbox enabled`,
`--skip-worktree-setup`, the verified owned `--workspace`, one validated model,
JSON output, trust, and the bounded staged-file instruction. It rejects every
panel/Checker control listed above that is not part of that Maker grammar,
including every `--mode`/`--plan`, worktree/session/plugin/add-dir option or
subcommand, and it rejects `--force`/`-f`, `--yolo`, `--auto-review`, and
`--approve-mcps` after all rewrites. If the supported CLI cannot complete a
noninteractive managed edit/test run without one of those approval bypasses,
Cursor Maker support is release-blocked rather than widening the grammar. The
normal `scope(task)` check remains mandatory but is not the tamper proof
(`bin/alloy_execution.py:97-102`). Maker source edits are expected, so retain the
per-path content manifest behind the digest and classify before/after changes:
tracked, untracked, and ignored worktree paths may differ only under
`allow_paths`; protected Git internals and outside canaries may never differ.
This closes the current ignored-path omission without treating every legitimate
Maker edit as tamper. Run that comparison immediately after the Cursor process
and before gates/commit; any unreadable path or disallowed change retains the
worktree and skips review.

Managed Cursor sessions ship as `fresh_context_fallback` in 0.11.0. Native
session reuse remains restricted to Claude and Grok
(`bin/alloy_execution.py:233-250`) until a later design proves every resumed call
reapplies the model, worktree, role flags, and OS profile.

## 3. Prompt transport, authentication, and output

### Prompt transport

Use the Antigravity-style staged-file pattern because the Cursor facts document a
positional prompt and do not document stdin prompt ingestion. `-p` is the print
mode flag, not a "read stdin" flag (`docs/design/cursor/CURSOR-FACTS.md:13-30`).

For each dispatch, copy the complete prompt to
`<pdir>/prompt_in/prompt.md`, make the directory/file owner-only, grant Cursor
read access to that file/directory, set Cursor stdin to `DEVNULL`, and put only
this short instruction on argv:

```text
Read <absolute-json-quoted-path> in full for your instructions and answer them.
```

For a Maker, append the already-known owned worktree and scope reminder, still
without task text. For panels/Checkers, append a read-only reminder. Because
`subprocess.Popen` receives an argv list, no shell quoting is involved, but the
path must still be bounded and JSON-quoted for the model instruction.

Before a Checker prompt is staged, redact every packet source and the final
encoded packet with the common secret scrubber. The packet may contain only the
redacted goal, diff, bounded gate output, revision/receipt fields, paths, and
review instructions. It must not include environment/config values, raw auth or
status output, keychain data, subprocess commands containing secrets,
or unredacted Maker output. The current packet directly combines the task spec,
diff, and gate text (`bin/alloy_execution.py:253-269`), so tests inject a
recognized JWT/assignment/header secret independently into each source and prove
neither the saved review packet nor `<pdir>/prompt_in/prompt.md` contains it.
This staging rule is a mitigation for the accepted residual risk in section 2,
not a claim that Cursor's in-process read tool cannot open readable repository
data.

Generalize the current Antigravity-only stdin conditional into an adapter hook
such as `stdin_from_prompt = True`; set it false for Antigravity and Cursor. The
current runner otherwise opens the full prompt as stdin for every adapter except
Antigravity (`bin/alloy:1482-1493`). Tests must use a multi-megabyte prompt and
inspect `/proc`-equivalent/mock argv to prove the task text is absent from argv
and stdin while the staged file is complete.

### Authentication

Use only Cursor's native keychain login and commands:

- `cursor-agent login` is the user-facing authentication instruction;
- `CursorAgentAdapter.is_authed()` runs sandbox-wrapped `cursor-agent status`
  with `stdin=DEVNULL`, a short timeout, bounded output, the private runtime, and
  the cleaned child environment;
- return ready only for exit zero plus a recognized logged-in marker; unknown
  output fails closed as `installed_not_authed`/`auth_unknown`;
- mask any account text again before adding an optional `auth_detail` to doctor
  text or JSON. At most the first character and a masked domain suffix may be
  shown; raw status output is never persisted; and
- Alloy never invokes `security`, Keychain APIs, or reads
  `~/Library/Keychains` to obtain token values. The login item is not a file and
  Alloy does no exact-value token redaction based on keychain contents
  (`docs/design/cursor/CURSOR-FACTS.md:368-370`).

Alloy must never add `--api-key`, `--endpoint`, `-e`, `--header`, or `-H`, or use
`CURSOR_API_KEY`/`CURSOR_API_ENDPOINT`. Remove both environment names in
`bin/alloy_routing.py:clean_env()`, after config/environment merge in
`bin/alloy:run_panelist()`, and in `bin/alloy_usage.py:provider_env()`. After
every routed/managed rewrite, the final Cursor gateway rejects exact,
`--flag=value`, split-value, and attached short forms (`-eVALUE`, `-HVALUE`) of
the auth/endpoint/header controls. It also enforces the role's exact mode,
sandbox, and approval state: no force/auto-approval flag, no `--sandbox
disabled`, and no absent, duplicate, or alternate mode where the role grammar
requires one. The documented short forms are not aliases the validator may
normalize (`docs/design/cursor/CURSOR-FACTS.md:16-25`). Those environment paths
currently scrub only TypeSafe and OpenRouter routing keys
(`bin/alloy_routing.py:68-69`, `bin/alloy:1434-1445`,
`bin/alloy_usage.py:233-238`).

The common scrubber must recognize JWT-shaped values, secret assignments, and
authorization/custom-header value forms (`bin/alloy:263-315`). There is no
measured opaque Cursor-token byte shape and Alloy must not invent a synthetic
Cursor-specific value pattern or read the keychain for exact-value redaction.
Do not point `Popen` stdout/stderr at the final run-artifact sidecars as the
current runner does (`bin/alloy:1482-1493`). Drain both pipes without deadlock
into bounded in-memory capture, parse from that capture, and apply the scrubber
before every persisted sink: parsed `result` before `result.md`; captured stdout
and stderr before atomically creating `stdout.txt` and `stderr.txt`; and the
complete `status.json` payload, including every `command` element, before both
its first and final writes. Never briefly persist an unredacted argv or output
(`bin/alloy:1447-1450`, `bin/alloy:1500-1503`,
`bin/alloy:1586-1599`, `bin/alloy:1631-1637`). A regression fixture returns a
JWT-shaped value in the JSON `result` and repeats it on stderr; the test proves
the value is absent and the redaction marker is present in `result.md`, the
stdout and stderr sidecars, and `status.json`. Separate fixtures cover assignment
and header forms on every sink. The final cross-cutting suite sets poison values
in both process environment and Alloy config and spies on status, version, help,
discovery, usage, panel, Maker, and Checker subprocess classes.

### Invocation and JSON output

`CursorAgentAdapter.build_args()` emits:

```text
-p --mode ask --output-format json --workspace <repo-or-cwd>
--model <effective-model> --trust --sandbox enabled --skip-worktree-setup
<short-file-instruction>
```

That is the panel/Checker form. The Maker form omits `--mode ask` so the CLI uses
its normal agent execution; it does not add a different `--mode` or an approval
bypass. Metadata calls have separate exact grammars: `status`, version/help, and
`--list-models` only. Inference grammar never accepts a CLI subcommand. Always
passing `--skip-worktree-setup` prevents repository-controlled
`.cursor/worktrees.json` setup scripts even though Alloy never requests a Cursor
worktree (`docs/design/cursor/CURSOR-FACTS.md:67-73`).

`--model` is mandatory for every inference dispatch. A plain/default panel uses
the canonical pin (`ALLOY_CURSOR_MODEL`, then legacy
`ALLOY_CURSOR_AGENT_MODEL`) or the explicit safe default `composer-2.5`; routed
and managed calls use their effective profile model. Immediately before spawn,
derive the final model's family with `cursor_model_family()` and reject `auto`,
an empty model, every unknown prefix, duplicate/conflicting `--model` flags, or a
model changed after validation. This last check covers plain, default, env-pin,
routed, Maker, and Checker paths. Metadata-only `status`, help/version, and
`--list-models` calls do not take a model, but still use the sandbox gateway.

`--trust` only suppresses the interactive workspace prompt; it grants no
filesystem permission outside the OS profile. `build_args()` may reject obvious
bad input early, but only the spawn gateway's structural check of the fully
rewritten argv is authoritative. Tests mutate argv in both `worker_adapter()`
and `dispatch()`—the current post-build rewrite sites
(`bin/alloy_execution.py:123-148`, `bin/alloy_execution.py:404-423`)—and prove
that endpoint/header/auth, session, plugin, worktree, mode, sandbox, force, and
subcommand injection is refused before `sandbox-exec` starts.

Add a base `output_error(stdout, stderr)` hook returning `None`. Cursor parses one
bounded JSON object and:

- returns `result` as the answer;
- treats malformed/non-object JSON, missing/non-string `result`, or
  `is_error: true` as a failed run even when exit status is zero;
- retains the shared non-zero-exit failure behavior;
- records the provider's `session_id` separately as `provider_session_id`, never
  overwriting Alloy's process/session identifier;
- normalizes recognized nonnegative integer token fields from `usage`; unknown
  shapes produce `usage: null` rather than guessing; and
- passes extracted text through the existing secret redaction, output cap,
  timeout, and process-group kill paths.

The facts establish the output keys but not the nested usage schema
(`docs/design/cursor/CURSOR-FACTS.md:361-363`), so the mock suite must cover one
documented fixture shape plus missing/changed shapes; production code must be
defensive. No raw JSON field bypasses redaction.

Files/functions: `CursorAgentAdapter.build_args()`, `parse()`, `usage()`, and new
`output_error()` in `bin/alloy`; the status classification in
`run_panelist()` currently bases failure on timeout, stall, exit status, and an
empty parsed result (`bin/alloy:1596-1625`). Extend that ordering so non-zero exit
and `is_error` cannot be converted into success by a nonempty `result`.

## 4. Model families, profiles, routing, and effort

### Family is derived per Cursor model

Add `cursor` to the adapter registry and to the permitted family set. Add
`cursor` to `--host-family` choices because a host running Composer has family
`cursor`; those choices currently come from `FAMILIES.values()`
(`bin/alloy_routing.py:799-804`). Do not use the Cursor CLI name as the model
family.

Add `cursor_model_family(model)` after removing bracket overrides and a trailing
`-fast` marker:

| Model prefix | Family |
| --- | --- |
| `claude-` | `anthropic` |
| `gpt-` (including `gpt-*-codex-*`), exact `codex`, or `codex-` | `openai` |
| `gemini-` | `google` |
| `grok-`, `cursor-grok-` | `xai` |
| `composer-` | new family `cursor` |
| `auto` or any unknown prefix | unknown/ineligible |

Validation must require every Cursor profile's explicit `family` to equal the
derived family. Reject `model: auto`, an unknown model prefix, or a mismatch; a
user-provided family cannot relabel an unknown ID. In addition, any profile that
claims `family: cursor` is valid only when `adapter: cursor` and the normalized
model ID begins `composer-`. Thus a Codex/Claude/other adapter cannot label a GPT
or Claude model as `cursor`, and a Cursor-to-GPT profile must say `openai`.
Current validation only checks membership in `FAMILIES.values()`
(`bin/alloy_routing.py:119-139`), while managed selection trusts the resulting
three strings (`bin/alloy_execution.py:302-309`); both checks are required to
close that independence hole. Bump `RUBRIC_VERSION` from 4 to 5
(`bin/alloy_routing.py:23-30`).

Apply the same derivation at every exposure and dispatch boundary:
`model_context()` (so Jev never sees an invalid card), `resolve()`,
`routed_adapter()`, managed `select()`/`revalidate()`, and the final Cursor spawn
gateway. Plain and default panels are not exceptions: they always send the
explicit `composer-2.5` default or a validated pin. `auto`, `muse-spark-*`,
`kimi-*`, `glm-*`, and every other unknown-family ID may appear in discovery as
non-routable but can never be spawned (`docs/design/cursor/CURSOR-FACTS.md:111`,
`docs/design/cursor/CURSOR-FACTS.md:242-356`).

Fix quota pacing at `bin/alloy_routing.py:636`: compare `family(p)` with `host`,
not `FAMILIES.get(name)`. Eligibility already uses `family(p)` for exclusions
and Checker independence (`bin/alloy_routing.py:554-598`), and execute asserts
three distinct effective families (`bin/alloy_execution.py:302-309`). Tests must
prove:

- an Anthropic/Claude host can never select Cursor-to-Claude as Maker **or**
  Checker;
- an OpenAI/Codex Maker can never receive Cursor-to-GPT as Checker;
- Cursor Composer has family `cursor` and is independent of OpenAI, Anthropic,
  Google, and xAI;
- `auto` and unknown prefixes never enter a panel argv, routed card, or managed
  role;
- a non-Cursor adapter or non-Composer model cannot claim family `cursor`;
- canonical and legacy environment pins are re-derived and cannot change a
  selected role to the host's or Maker's family; and
- quota pacing treats Cursor-to-Claude as the host's Anthropic family and does
  not apply the outside-family discount. This test supplies a synthetic fresh
  Cursor usage window: actual Cursor usage is unknown, for which `pacing()`
  returns `None` (`bin/alloy_usage.py:496-546`) and cannot distinguish the old
  and new condition.

### Shipped profiles and discovery

Add these five small starter profiles to `data/routing-defaults.json`, all with
`adapter: cursor`, `billing_mode: subscription`, `quota_pool: cursor`, honest
`evidence: "Cursor discovery only; not benchmarked"`, and `enabled: false`:

| Profile ID | Model | Family | Tier | Default effort |
| --- | --- | --- | --- | --- |
| `cursor-large-composer-2-5` | `composer-2.5` | `cursor` | large | high |
| `cursor-large-gpt-5-6-sol` | `gpt-5.6-sol-high` | `openai` | large | high |
| `cursor-large-claude-opus-5-5` | `claude-opus-5-5-high` | `anthropic` | large | high |
| `cursor-medium-gemini-3-8-flash` | `gemini-3.8-flash-high` | `google` | medium | high |
| `cursor-large-grok-4-7` | `grok-4.7-high` | `xai` | large | high |

The supplied model list supports those namespaces and shows both ordinary and
fast variants (`docs/design/cursor/CURSOR-FACTS.md:42-46`,
`docs/design/cursor/CURSOR-FACTS.md:61-358`). Do not add Cursor rows to
`data/model-evidence.json` or `bench/profiles.json`: discovery/smoke data is not a
quality benchmark.

Evidence identity must include the adapter and effective effort, not only model
text and family. Extend the evidence catalog schema so every row declares the
`adapters` whose harness/provider the evidence covers and an explicit
fast/non-fast state. `bin/alloy_evidence.py` may return `matched` only when the
canonical adapter, exact normalized model ID, effective effort, and fast state
all match the row; a model-only candidate with a different effort remains
`effort-unverified` and supplies no preferred tasks. A Cursor profile is
therefore `unmatched` until a future benchmark row explicitly includes `cursor`
in `adapters`. The shipped evidence string is descriptive only and cannot grant
routing preference.

This is new work in `bin/alloy_evidence.py:26-47`: current `match()` checks only
model membership and family, then `assessment()` checks the configured effort.
That lets the Cursor Gemini profile collide with the existing
`gemini-3.8-flash-high`/`high` row
(`data/model-evidence.json:321-338`) and influence `task_fit`
(`bin/alloy_routing.py:614-625`). Migrate existing evidence rows to explicit
native adapters, pass the role's fully resolved evidence identity from
`model_context()` and `resolve()`, and test that same-family/same-model rows never
cross adapter or effort boundaries. Do not add Cursor benchmark evidence as part
of this feature.

`alloy models refresh` gets an explicit Cursor branch that runs sandbox-wrapped
`cursor-agent --list-models` with `stdin=DEVNULL`, clean env, bounded output, and
a timeout. Parse only full lines matching `<id> - <label>` after the `Available
models` header; classify each ID with `cursor_model_family()`, record `auto` and
unknown IDs as `routable: false`, and never infer family from the human label.
Retain the prior cache on non-zero exit or unrecognized output. Current discovery
is a Grok/Antigravity-only loop (`bin/alloy_routing.py:450-472`).

Guided `alloy setup` detects Cursor and asks whether to enable the shipped Cursor
profiles, defaulting to no. Add `--enable-cursor` for an explicit non-interactive
opt-in; `alloy models enable <profile-id>` remains the granular alternative.
`--refresh-defaults` continues to add missing profiles without changing existing
enabled states, and reset preserves account choices as it does now
(`bin/alloy_routing.py:214-254`). No Cursor profile becomes routable merely
because the CLI is installed.

### Effort mapping and fast variants

Cursor receives effort through its model ID/bracket override, never through the
current non-Codex catch-all `--effort` branch. The current routed adapter sends
Codex `model_reasoning_effort` and sends every other adapter `--effort`
(`bin/alloy_routing.py:850-875`); replace that with explicit provider branches
and a final unsupported-provider error.

Add `cursor_effective_model(model, effort, cursor_fast=False)`:

1. Parse and preserve existing bracket fields except `effort` and `fast`; parse
   an explicit bracket effort and the normalized ID's final
   `-none|-minimal|-low|-medium|-high|-xhigh|-max` suffix as model-ID effort.
   Match documented compound IDs before that generic suffix rule:
   `gpt-5.5-extra-high` is one indivisible base ID, not base
   `gpt-5.5-extra` plus effort `high`; strip only a final `-fast` when the
   profile explicitly opts in and preserve `-extra-high` in either case
   (`docs/design/cursor/CURSOR-FACTS.md:205-214`).
2. Implement the full precedence explicitly:
   `ALLOY_CURSOR_EFFORT`, then `effort_by_mode[role]`, then profile `effort`, then
   the parsed bracket/suffix effort, then no override (Cursor's model default).
   The existing `role_profile()` implements only the first three configuration
   levels and does not parse model IDs (`bin/alloy_routing.py:497-506`); do not
   cite it as implementing the fourth step.
3. Map `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max` directly to
   one `[effort=<value>]` field. If all levels are absent, omit that field rather
   than inventing an effort. Cursor does not ship an `ultra` spelling in the
   supplied list; a Cursor profile resolving to `ultra` fails validation rather
   than being silently downgraded.
4. Unless the profile explicitly sets `cursor_fast: true`, reject a base ID ending
   in `-fast`, reject `[fast=true]`, and emit `[fast=false]`. With the opt-in, emit
   `[fast=true]`; the opt-in is profile-specific and does not leak to other Cursor
   models.
5. Pass the resulting single string through `--model`. Family classification
   uses the normalized base ID. Evidence matching receives the canonical adapter,
   normalized base ID, effective effort, and fast state (or an equivalently
   normalized full effective model ID); bracket spelling must not collapse
   distinct evidence identities.

Extend profile validation so `cursor_fast`, when present, is boolean. Add it to
`models add` as `--cursor-fast`; default false. Shipped profiles never opt in.
Tests cover suffix effort IDs, the preserved `gpt-5.5-extra-high` compound ID,
thinking IDs, bracket replacement, role-specific effort, canonical and legacy
env overrides, unsupported `ultra`, every fast rejection/opt-in path, and the
adapter-plus-effective-effort evidence boundary.

## 5. Usage and quota

Add `cursor` to `PROVIDERS` and `LABELS` in `bin/alloy_usage.py`. Cursor has one
shared subscription quota pool named `cursor` regardless of whether a selected
model's family is Anthropic, OpenAI, Google, xAI, or Cursor. Add an explicit
`provider == 'cursor'` branch to `applicable()` before family/model-specific
logic; it always returns `['cursor']` plus an explicit user usage pool. Current
fallback behavior otherwise uses the adapter name as the pool
(`bin/alloy_usage.py:475-493`).

The captured CLI help/facts expose no usage command or subscription quota API.
`fetch(core, 'cursor', ...)` therefore returns a controlled
`UsageError('Cursor CLI exposes no subscription usage source')`; the normal
snapshot code records `status: unknown`, no windows, and never blocks routing.
The current snapshot already excludes unknown/stale readings from headroom
(`bin/alloy_usage.py:424-461`, `bin/alloy_usage.py:496-512`). Do not derive quota
from per-call JSON token usage.

Use `~/.cursor/agent-cli-state.json` metadata (path, mtime, size only) as Cursor's
cache binding and bind neither `CURSOR_API_KEY` nor `CURSOR_API_ENDPOINT`. Never
read or hash account contents. Add explicit provider validation before indexed
dictionaries.

Refactor `fetch()` so Claude is an explicit `provider == 'claude'` branch and the
final branch raises `UsageError('Unknown usage provider: ...')`. Today every name
that is not Grok, Codex, or Antigravity falls through to Claude's OAuth fetch
(`bin/alloy_usage.py:351-402`), while binding dictionaries index directly
(`bin/alloy_usage.py:329-348`). Tests must prove an unknown provider performs no
Claude credential read, Keychain call, or network request.

## 6. Complete hard-coded branch audit

Every site called out by `PROVIDER-MAP.md` gets an explicit branch and a test:

| Current site | Required implementation | Required regression test |
| --- | --- | --- |
| `bin/alloy_routing.py:417-441` `probe()` indexed required-flags map | Add Cursor flags (`--print`, `--output-format`, `--mode`, `--model`, `--list-models`), use the common sandbox gateway, and require OS boundary readiness; unknown adapter returns incompatible, not `KeyError`. | Compatible help passes only through the sandbox and preflight; each missing flag and unavailable sandbox fails closed. |
| `bin/alloy_execution.py:114-155` Maker allowlist and Antigravity `else` | Add explicit `elif ad.name == 'cursor'` before explicit `elif antigravity`; final `else` raises unsupported. Cursor uses the closed, non-force Maker grammar. | Cursor receives only the sandboxed Maker contract, including `--skip-worktree-setup` and no approval bypass; unknown provider cannot inherit Antigravity permissions. |
| `bin/alloy_execution.py:159-170` write help map | Add Cursor `--sandbox`, `--workspace`, `--model`, and `--skip-worktree-setup` checks plus OS preflight; reject force/auto-approval controls. | Missing flag or preflight refuses Maker; any force/mode/worktree/plugin/session injection refuses spawn; Checker also requires read-only preflight. |
| `bin/alloy_routing.py:850-875` effort catch-all | Add explicit Codex, Cursor-model-rewrite, supported `--effort` providers, and final fail-closed branch. | Unknown provider gets no guessed `--effort`; Cursor gets one rewritten `--model`. |
| `bin/alloy_evidence.py:26-47` model/family evidence match | Require canonical adapter plus exact effective model/effort/fast identity; migrate evidence rows to explicit adapters and leave Cursor without a benchmark row. | A Cursor Gemini/Claude/GPT/Grok profile remains `unmatched` even when its family, model text, and effort collide with native-provider evidence; another effort cannot borrow task preference. |
| `bin/alloy_usage.py:329-348` binding dictionaries | Add Cursor path/no-key binding and validate provider before lookup. | Cursor binds neither `CURSOR_API_KEY` nor `CURSOR_API_ENDPOINT`; unknown provider raises controlled error. |
| `bin/alloy_usage.py:351-402` Claude fallthrough | Make Grok/Codex/Antigravity/Cursor/Claude explicit; final unknown error. | Unknown provider cannot call Claude/Keychain/network. |
| `bin/alloy_routing.py:450-472` discovery loop | Add explicit Cursor `--list-models` parser; leave provider-specific commands explicit. | Parse valid list; reject malformed/`auto` routing; retain cache on failure. |
| `bin/alloy:393-401` versus `bin/alloy_usage.py:241-247` binary override key construction | Canonical `ALLOY_BIN_CURSOR`, legacy underscored fallback, one normalization helper. | Canonical wins; legacy works; no hyphenated environment key is consulted. |
| `bin/alloy:1205-1230`, `bin/alloy:1751-1805` default/selected panels | Register one canonical adapter, normalize alias, and require Cursor OS isolation even if `ALLOY_ALLOW_UNSANDBOXED=1`. | Default ready panel has Cursor once; alias has canonical run dir; unavailable sandbox always skips/refuses. |
| `bin/alloy:1482-1493` stdin special case | Generalize an adapter stdin hook; Cursor and Antigravity use `DEVNULL`. | Full prompt is only in staged file and never argv/stdin. |
| `bin/alloy:1283-1286`, `bin/alloy:1353-1360`, `bin/alloy_execution.py:29-38`, `bin/alloy_execution.py:82-102`, `bin/alloy_execution.py:532-535` parent Git/fingerprint | Route every parent Git call through the helper with `core.hooksPath=/dev/null`, `core.fsmonitor=false`, and `GIT_CONFIG_NOSYSTEM=1`; replace HEAD/status text with worktree bytes plus all protected Git-internals content, including `commondir`, `config.worktree`, `info/attributes`, and `info/sparse-checkout`. | Same-name ignored-file edits and every named Git-internal change are detected; inability to hash fails; clean/scope/add/commit/fingerprint Git all have the hardened argv/env; built-in commands are not replaced by `alias.*`. |
| `bin/alloy_usage.py:460-461`, `bin/alloy_routing.py:444-447` fixed worker counts | No sizing fix is needed: `executor.map` queues all provider inputs even when there are more inputs than workers. Keep the safe bound or derive it for clarity. | Inventory and usage snapshots contain Cursor exactly once and no test claims a fifth result was previously dropped. |

Also audit with `rg` for `cursor-agent`, provider tuples, `name ==`, indexed
provider maps, and provider `else` branches before landing. Each remaining
`cursor-agent` occurrence must be either the executable, the compatibility alias,
or historical release text.

## 7. Doctor, setup, models, and user-visible behavior

`doctor` currently enumerates `ADAPTERS`, reports auth/read-only/version/model,
and derives default-panel readiness from those fields (`bin/alloy:1934-2001`).
Extend its row with `os_boundary`, a masked `auth_detail`, and a specific
fail-closed reason. Required states:

- installed + logged in + validated macOS sandbox: ready/read-only;
- installed + not logged in: show `cursor-agent login`;
- installed + logged in + unsupported/missing sandbox: not usable, with the
  boundary message above;
- not installed: show the Cursor CLI install hint.

`estimate` must special-case Cursor readiness: require the explicit
`cursor_boundary_ready` capability and a known explicit model, and never let
`ALLOY_ALLOW_UNSANDBOXED=1` make Cursor count as ready. The current predicate
accepts any selected ready adapter when either `read_only` or
`allow_unsandboxed()` is true (`bin/alloy:2004-2007`). `status` stays generic and
needs no Cursor branch; it reads per-panelist files by directory
(`bin/alloy:2045-2113`). `update-check` remains provider independent
(`bin/alloy:2158-2165`). Do not add a resume hint for 0.11.0.

`setup`, `models --cli`, `models --family`, and `--host-family` obtain their
choices from routing registries (`bin/alloy_routing.py:743-841`), so adding the
canonical provider/family plus the explicit setup opt-in is sufficient. Preserve
all user model pins and billing selections during refresh/reset.

## 8. Documentation and release bookkeeping

Update exactly these user documents for the feature:

- `README.md`: list Cursor, canonical name, macOS boundary requirement, routing
  opt-in, and shared unknown quota.
- `SKILL.md`: add Cursor to panel/execute provider descriptions; state that
  Cursor panel/Checker uses ask mode **and** OS write denial, Maker uses a
  non-Git worktree allowlist, and no force/auto-approval bypass appears in any
  Cursor role.
- `alloy-execute/SKILL.md`: mirror the Cursor boundary and fail-closed rule.
- `alloy.config.example`: document `ALLOY_BIN_CURSOR`,
  `ALLOY_CURSOR_MODEL`, `ALLOY_CURSOR_EFFORT`, the legacy aliases, and why
  `CURSOR_API_KEY` and `CURSOR_API_ENDPOINT` are scrubbed; document the
  additive-only comma-separated `ALLOY_CURSOR_DENY_READ_PATHS`.
- `SECURITY.md`: replace the obsolete Cursor disposable-copy statement. State
  honestly that plan mode and Cursor's sandbox flag wrote outside the workspace,
  ask mode refused in the probe but is not the boundary, macOS `sandbox-exec` is
  the write boundary, Linux is refused in 0.11.0, only a per-dispatch private
  runtime (and non-Git Maker worktree content) is writable, canaries/content
  fingerprints are detection only, every role denies the documented sensitive
  credential paths, and the accepted keychain-login/repository/network
  confidentiality risk remains despite ask mode, no shell, persisted-sink
  redaction, and omission of recognized secrets from the staged Checker packet.
- `docs/adding-a-panelist.md`: replace the obsolete Cursor stub example with the
  real adapter's prompt, auth, output, and OS-wrapper contract.
- `docs/execution.md`: add Cursor Maker/Checker permissions, fresh-context
  behavior, family-by-model examples, and fail-closed platform behavior.
- `docs/routing.md`: document family derivation, `auto` exclusion, disabled
  shipped profiles, fast opt-in, effort rewriting, and setup/models enablement.
- `docs/usage.md`: document the shared Cursor pool as unknown/non-blocking and
  distinguish per-call tokens from subscription capacity.

The current docs list only four panel/managed providers or describe Cursor as
unsandboxed (`README.md:14-24`, `SKILL.md:35-49`,
`alloy.config.example:8-15`, `SECURITY.md:14-27`,
`docs/execution.md:12-17`); all must agree after the change.

Set `ALLOY_VERSION = "0.11.0"` in `bin/alloy` (currently `0.10.0` at
`bin/alloy:78`). Add the format-matching `CHANGELOG.md` heading
`## [0.11.0] - 2026-09-29` (the existing form is visible at
`CHANGELOG.md:6`) with the Cursor feature and an honest platform/safety note. The
same entry must also list these five fixes already present on this branch, using
the precise claims below:

1. agy 1.2.12 read grants for the staged prompt and worktree;
2. `DEVNULL` stdin for agy so stdin is not treated as a denied file read;
3. two agy settings grammars are retained: 1.1 uses bare read-tool names, while
   1.2.x uses path-scoped `read_file(...)` grants and is the fail-closed current
   grammar (`bin/alloy:780-807`; the 1.2.12 path-scoped assertion is
   `tests/test_alloy.py:612-636`, while the default 1.1.7 fixture and bare-name
   assertion are `tests/test_alloy.py:536-543` and
   `tests/test_alloy.py:640-674`);
4. linked-worktree `.git` indirection grants the exact gitdir and, only for the
   standard `<common>/worktrees/<id>` layout, its common directory; other
   layouts receive the exact gitdir only (`bin/alloy:894-909`); and
5. owner-private gate-log directory grants for Checkers.

Do not claim Cursor benchmark quality, Linux support, complete filesystem-change
observation, live quota visibility, or that a fifth provider was previously
dropped by a four-worker pool. No deployment is part of this release
implementation task.

## 9. Test plan and acceptance matrix

All component tests use mock `cursor-agent` and mock `sandbox-exec` executables.
The discoverable macOS release-gate module is the only test that invokes the real
non-provider `/usr/bin/sandbox-exec`; no test calls the live Cursor CLI, network,
Keychain, or a real provider account. Use existing mock-driven suites; current
coverage patterns live in
`tests/test_alloy.py`, `tests/test_routing.py`, `tests/test_execution.py`, and
`tests/test_usage.py` (`tests/test_alloy.py:19-64`,
`tests/test_routing.py:54-63`, `tests/test_execution.py:404-445`,
`tests/test_usage.py:29-32`).

Required coverage:

1. **Name/compatibility:** canonical and legacy selector/key behavior, one doctor
   row/call/run directory, canonical persistence.
2. **Auth/environment:** status success/failure/malformed output, masked account,
   JWT/assignment/header redaction on `result.md`, stdout/stderr sidecars and
   all of `status.json`, forbidden auth flags, no Alloy Keychain/security read,
   and both config and inherited `CURSOR_API_KEY`/`CURSOR_API_ENDPOINT`
   scrubbed.
3. **Prompt:** complete staged file, private modes, short argv, `DEVNULL`, huge
   prompt without `ARG_MAX`, no prompt substring in command/status.
4. **Panel/Checker sandbox:** generated read-only profile, exact final argv
   grammar, no dangerous/auth/session/plugin/worktree flags, mandatory setup-script
   skip, private-runtime/TMP writes allowed, real Cursor state/install and every
   other home/repo/system-temp path write-denied, every built-in/configured
   sensitive path read-denied, process execution and hard links denied, sandbox
   absent/self-test failure, and byte-level tamper rejection for
   tracked/untracked/ignored files and every protected Git internal.
5. **Maker sandbox:** non-Git owned-worktree content plus private runtime/TMP
   only, no force/auto-approval or Cursor worktree/setup scripts, all `.git`
   pointers/directories/gitdirs/common dirs write-denied, hard links denied,
   every built-in/configured sensitive path read-denied,
   ignored-aware content-manifest scope enforcement,
   Git-metadata-content/outside-canary rejection, and no unsandboxed fallback.
6. **JSON:** success, `is_error`, non-zero exit with result, malformed/missing
   result, JWT-shaped `result` redaction in `result.md` and both sidecars,
   assignment/header sink redaction, normalized/unknown usage, provider session
   ID, timeout and descendant kill.
7. **Families/independence/evidence:** all prefix mappings, Composer,
   auto/unknown, explicit model on every inference path, mismatched configured
   family, non-Cursor/non-Composer rejection for family `cursor`, Anthropic host
   versus Cursor-Claude, OpenAI Maker versus Cursor-GPT Checker, pin
   revalidation, adapter-plus-effective-effort evidence matching, Cursor
   cross-adapter evidence refusal, and pacing with a synthetic fresh Cursor
   window.
8. **Effort/fast:** role precedence, bracket and suffix forms, thinking models,
   preservation of `gpt-5.5-extra-high` as a compound base ID, the explicitly
   implemented model-ID/default fourth precedence step, unsupported effort,
   default fast denial, and explicit profile opt-in.
9. **Discovery/setup/profiles:** valid/malformed model list, cache retention,
   default-disabled shipped profiles, explicit setup/models enable, user pin and
   billing preservation.
10. **Usage:** shared Cursor pool for every family, unknown/non-blocking status,
    no per-call-token quota inference, unknown-provider fail-closed behavior.
11. **Every fallthrough:** one regression test for every row in section 6.
12. **Estimate/readiness:** Cursor is counted only with the separate boundary
    field and a known explicit model; `ALLOY_ALLOW_UNSANDBOXED` never helps.
13. **Docs/release:** a dedicated test reads `CHANGELOG.md`, `SECURITY.md`, the
    Cursor docs, and skills for the required sentences and forbidden claims.
    `tests/validate_skill.py` only checks skill frontmatter and fixed phrases
    (`tests/validate_skill.py:21-105`), so its success is not accepted as proof
    of release wording.
14. **Cross-cutting boundary invariant:** one final-suite test spies on every
    Cursor subprocess class—status, version/help, discovery, panel, managed
    Maker/Checker—and confirms forbidden argv/env values never cross a boundary
    after rewrites. It injects recognized secrets into every Checker packet
    source and proves none reaches the saved/staged prompt or any persisted sink.
    It asserts the sensitive-read deny set in every role/discovery profile and
    the hardened argv/environment on every parent Git call. It also proves no
    force/mode/sandbox/plugin/worktree/session/subcommand injection survives.
    Usage must prove it launches no Cursor process. This test runs after all four
    implementation lanes; no individual lane claims the global invariant.

Add `tests/test_cursor_sandbox_release_gate.py` as a discoverable `unittest`
module (the repository command uses the `test*.py` pattern). The class skips
cleanly only when `sys.platform != "darwin"`. On macOS it invokes the real
`/usr/bin/sandbox-exec` with profiles produced by the production generator and
verifies both role profiles. The probe covers: allowed private `TMPDIR` write;
denied write to a repository for panel/Checker; allowed non-Git worktree-content
write for Maker; denied writes to the worktree `.git` pointer/directory, resolved
gitdir, and common dir; denied write elsewhere under home/system temp; denied
hard-link creation from a repo file into a writable root; and a symlink traversal
attempt that cannot write its outside target. For both profiles it also creates a
sentinel under a configured extra denied-read root, proves a direct open fails,
then proves a sandboxed non-network CLI fixture still starts and emits its
expected output. This distinguishes a working profile with targeted read denials
from a profile that merely prevents all useful execution. On macOS, missing
`sandbox-exec`, an unexpected allow/deny/read result, a CLI-fixture failure, or
inability to exercise an operation fails the test; none is a skip. Mock-profile
unit tests do not satisfy this gate.

The existing CI matrix includes `macos-latest` but currently runs only generic
discovery and skill validation (`.github/workflows/ci.yml:9-24`). Add an explicit
`if: runner.os == 'macOS'` step that runs the release-gate module and fails the
job on any missing binary or unexpected operation result. Generic discovery also
runs it on macOS and reports one clean platform skip on non-macOS; the named CI
step makes the release boundary visible rather than relying on an easily renamed
test.

Add `tests/live/cursor_ask_release.py`, guarded against accidental execution by
`ALLOY_LIVE_CURSOR=1`. For each explicitly supported Cursor version, an operator
must separately authorize and record one authenticated ask-mode compatibility
run through the production sandbox. It uses an adversarial prompt, verifies no
shell tool/process was exposed or invoked, verifies repo/outside canaries, checks
the bounded JSON shape, and prints no account or credential. This is a
version-compatibility release gate, not a benchmark or a default test. The live
action is always reported separately from unit tests.

Final automated acceptance commands:

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_skill.py
python3 -m unittest discover -s tests -p 'test_cursor_sandbox_release_gate.py' -v
```

The first discovery command includes the gate on macOS and skips only its class
on non-macOS. The third is the explicit mandatory rerun on the supported macOS
release host and in the CI macOS job. Before cutting 0.11.0, an explicitly
authorized operator also runs the live ask-version gate above. Run `rg` audits
for dangerous flags and provider fallthroughs. Deployment remains out of scope.

## 10. Ordered implementation lanes

The lanes are dependency ordered and have non-overlapping edit sets. Each lane is
small enough for one managed Maker run. A Maker receives only the listed
allow-paths.

### Lane 1 — canonical adapter, prompt/auth/JSON, and both SBPL profiles

Depends on: none.

Allow-paths:

```text
bin/alloy
tests/mocks/mock_panelist.py
tests/test_alloy.py
```

Work: implement canonical naming/aliases, environment scrub at dispatch, native
status auth and masking, staged prompt/`DEVNULL`, JSON parsing/error hook, command
gateway, the separate immutable boundary field, private runtime, both the
panel/Checker and Maker SBPL profile generators, mandatory and configured
sensitive-read denials, hardened panel Git helpers, byte-content/Git-internals
fingerprints, canaries, doctor/capabilities, all persisted-sink redaction, and
version `0.11.0`. This lane owns all SBPL generation so Lane 3 can select a role
without editing `bin/alloy`. Keep Cursor unavailable on unsupported isolation.

Acceptance checks:

- canonical/legacy names and env keys behave as section 1 specifies;
- no prompt text reaches argv/status and dispatch scrubs both Cursor override
  variables locally; the cross-cutting all-subprocess claim waits for Lane 6;
- panel argv has ask/JSON, setup-script skip, one explicit known model, and no
  dangerous/auth/session/plugin/worktree flags;
- mock profiles allow only the exact private runtime (plus non-Git Maker
  worktree content), deny every Git metadata location, real Cursor state/install
  paths, hard links, panel shell execution, and all built-in/configured
  sensitive reads, and fail closed when missing;
- same-name ignored-file byte changes and every protected Git-internal byte
  change move the fingerprint, and every parent Git call in this lane has the
  hook/fsmonitor/system-config contract;
- JSON `is_error`, exit status, usage, session, timeout, redaction, and canary
  cases pass, including a JWT-shaped `result` absent from `result.md` and both
  sidecars;
- current non-Cursor adapter tests remain green.

Test command:

```bash
python3 -m unittest discover -s tests -p 'test_alloy.py' -v
```

### Lane 2 — routing, families, discovery, profiles, and effort

Depends on: Lane 1 canonical adapter and hooks.

Allow-paths:

```text
bin/alloy_routing.py
bin/alloy_evidence.py
data/routing-defaults.json
data/model-evidence.json
tests/test_routing.py
```

Work: register Cursor, bump rubric 5, derive/validate family per model, exclude
auto/unknown on every route and dispatch, forbid non-Cursor/non-Composer claims
of family `cursor`, add disabled profiles, setup opt-in, sandbox-wrap
`--list-models`, implement all four Cursor effort precedence steps, rewrite
effort/fast overrides while preserving `gpt-5.5-extra-high`, require
adapter-plus-effective-effort evidence identity, migrate existing evidence rows
to explicit native adapters without adding Cursor evidence, fix effective-family
quota pacing, and fail closed in provider branches.

Acceptance checks:

- all family and independence examples in section 4 pass;
- Composer is its own host family; `auto` and unknown IDs never dispatch;
- all shipped Cursor profiles are disabled, subscription-backed, and in pool
  `cursor`;
- every Cursor profile remains evidence-unmatched; cross-adapter and
  cross-effort evidence borrowing is impossible;
- discovery/cache and effort/fast/compound-ID tests pass;
- quota pacing uses effective model family under a synthetic fresh Cursor window;
- existing pins, billing, and non-Cursor profiles are preserved.

Test command:

```bash
python3 -m unittest discover -s tests -p 'test_routing.py' -v
```

### Lane 3 — managed Maker and Checker

Depends on: Lanes 1 and 2.

Allow-paths:

```text
bin/alloy_execution.py
tests/test_execution.py
```

Work: add explicit Cursor branches to permissions, Maker construction, help
probe through the common gateway, readiness, model/family revalidation, dispatch
boundary checks, managed content/Git-internals verification, and pre-stage
Checker packet redaction. Route every managed parent Git operation, including
clean/scope/worktree/add/commit/fingerprint, through the complete
hook/fsmonitor/system-config-disabled helper. `read_only=False` for Maker must not
change boundary readiness or bypass wrapping. Keep current scope,
packet-receipt, correction, integration, and cleanup invariants.

Acceptance checks:

- Cursor Maker has only the non-Git owned-worktree/private-runtime/TMP write
  allowlist and uses no force or auto-approval flag;
- Cursor Checker uses ask mode plus OS denial and cannot use Maker flags; both
  roles require setup-script skip, carry every sensitive-read denial, and reject
  session/plugin/worktree controls;
- absent sandbox and every missing help flag refuse the role;
- out-of-scope Maker edits including ignored files, same-name ignored-file
  content changes by a Checker, `commondir`/attributes/sparse-checkout and every
  other protected Git-internal change, and outside-canary mutations fail before
  review;
- clean/scope/worktree/add/commit/fingerprint Git all disable hooks and fsmonitor
  and ignore system config;
- recognized secrets in spec/diff/gate inputs are absent from the saved and
  staged Checker packet;
- three-family selection blocks Cursor-to-same-family combinations;
- Checker worktree/HEAD and packet-receipt checks still fail closed;
- Cursor sessions report fresh-context fallback.

Test command:

```bash
python3 -m unittest discover -s tests -p 'test_execution.py' -v
```

### Lane 4 — usage and quota

Depends on: Lane 2 canonical provider/profile semantics.

Allow-paths:

```text
bin/alloy_usage.py
tests/test_usage.py
```

Work: add canonical provider/label/binding, shared pool mapping, explicit unknown
Cursor usage, and fail-closed provider dispatch.

Acceptance checks:

- every Cursor-family model uses the single `cursor` subscription pool;
- unavailable quota is `unknown` and never blocks;
- neither Cursor API override is a binding or child env value;
- unknown provider cannot fall through to Claude, Keychain, or network;
- existing provider meters and stale-cache behavior remain green.

Test command:

```bash
python3 -m unittest discover -s tests -p 'test_usage.py' -v
```

### Lane 5 — documentation and release notes

Depends on: Lanes 1-4 so docs match shipped behavior.

Allow-paths:

```text
README.md
SKILL.md
alloy-execute/SKILL.md
alloy.config.example
SECURITY.md
docs/adding-a-panelist.md
docs/execution.md
docs/routing.md
docs/usage.md
CHANGELOG.md
```

Work: make every supported-provider, configuration, safety, routing, execution,
usage, and release statement match sections 1-8. Include all five branch fixes
precisely in the 0.11.0 changelog and make no unsupported
benchmark/Linux/quota/complete-confidentiality claim. Document the built-in
sensitive-read list, additive config path list, keychain-item facts, Alloy's
no-Keychain-read rule, and persisted-sink redaction.

Acceptance checks:

- all required documents name canonical `cursor` and legacy alias only where
  migration is explained;
- plan/sandbox boundary failures and ask+OS enforcement are stated honestly;
- Maker/Checker allowlists, macOS-only support, unknown quota, disabled profiles,
  endpoint/API-key scrubbing, no force bypass, mandatory sensitive-read denials,
  and explicitly accepted keychain-login/repository/network risk plus mitigations
  are consistent;
- skill validator passes, without treating it as validation of the other docs.

Test command:

```bash
python3 tests/validate_skill.py
```

### Lane 6 — cross-cutting and release gates

Depends on: Lanes 1-5.

Allow-paths:

```text
tests/test_cursor_release.py
tests/test_cursor_sandbox_release_gate.py
tests/live/cursor_ask_release.py
.github/workflows/ci.yml
```

Work: add the all-subprocess argv/environment spy, staged-Checker-secret and
docs/release wording checks, the discoverable real macOS SBPL operation probe,
including a denied-read plus runnable-CLI check, the explicit macOS CI step, and
the separately authorized live ask-version probe. This lane does not edit
implementation files or duplicate component unit tests.

Acceptance checks:

- poison `CURSOR_API_KEY`, `CURSOR_API_ENDPOINT`, staged packet secrets, and
  forbidden short/long flags reach no Cursor subprocess class, Checker prompt,
  or persisted sink;
- required changelog/security sentences are present and unsupported claims are
  absent independently of `validate_skill.py`;
- unittest discovers the gate, non-macOS skips only for platform, and the
  macOS CI step fails on missing `/usr/bin/sandbox-exec`;
- the real macOS profile passes TMP, repo/Git-metadata, outside-home, hard-link,
  symlink, denied-sensitive-read, and subsequent runnable-CLI checks for both
  roles;
- the explicitly authorized supported-version ask probe exposes/invokes no shell
  tool and changes no canary.

After Lane 6, run all acceptance commands from section 9. Do not commit, merge,
push, deploy, or run the live version gate without separate operator
authorization. The real non-provider `sandbox-exec` release gate is mandatory on
macOS and is not optional live evaluation.

## 11. Risks and open questions (with recommended answers)

1. **`sandbox-exec` is deprecated and may be absent on future macOS.**
   Recommendation: ship 0.11.0 fail-closed with the binary/self-test gate; plan a
   separate EndpointSecurity/Landlock/bubblewrap design rather than weakening the
   boundary.
2. **Linux has no implemented equivalent in this scope.** Recommendation: refuse
   all Cursor roles on Linux in 0.11.0. Do not make bubblewrap an implicit runtime
   dependency without its own boundary probe and packaging decision.
3. **Cursor uses keychain login state and the network.** Decision: accept this
   residual confidentiality risk explicitly for 0.11.0; it is not a solved
   credential or exfiltration boundary. The login is a keychain generic-password
   item, not a readable token file. Deny direct reads of
   `~/Library/Keychains` and every other listed credential path in all roles, and
   never let Alloy call `security`, a Keychain API, or inspect the keychain for
   exact-value redaction. The provider still uses its login item through the
   Security API, and SBPL cannot separate legitimate repository reads/network
   from the same process's model-facing read tool; host-based network rules
   cannot close that distinction. Mitigate with panel/Checker ask mode, a
   no-shell compatibility gate, descendant-process denial, OS write denial,
   mandatory sensitive-read denials, JWT/assignment/header redaction on every
   persisted sink, and a bounded redacted Checker packet that never stages
   recognized secrets. Keep state/install write-denied and block release if
   authenticated operation needs broader home writes or reads.
4. **The exact nested `usage` JSON schema is not established by the supplied
   facts.** Recommendation: normalize only recognized integer fields, otherwise
   record null. Per-call usage must never become subscription headroom.
5. **Parameterized effort support may vary by model.** Recommendation: use the
   documented bracket override, preserve documented compound IDs such as
   `gpt-5.5-extra-high`, reject unsupported local combinations before dispatch
   when known, and treat provider rejection as a visible failure; never silently
   change model or effort.
6. **Fast variants consume a different service tier/cost.** Recommendation:
   require per-profile `cursor_fast: true`, default false, and show the effective
   bracketed model in routing decisions/manifests.
7. **`auto` can change provider family between calls.** Recommendation: reject it
   everywhere. Every inference path, including plain/default panels and env pins,
   supplies an explicit model whose derived family is known.
8. **Content fingerprints and canaries cannot prove the whole filesystem was
   unchanged.** Recommendation: hash all worktree bytes and the enumerated Git
   internals, document those checks as tripwires, and keep the OS sandbox as the
   preventive control. Any sandbox, enumeration, fingerprint, or canary
   uncertainty fails closed.
9. **Cursor resume could bypass or drift from the original role settings.**
   Recommendation: ship fresh-context fallback. Add resume only after a dedicated
   test proves model, workspace, exact role grammar, and OS profile are reapplied.
10. **Should Cursor become a host skill installation target?** Recommendation:
    no in 0.11.0. Provider support is complete without changing `install.sh`; a
    Cursor-host integration is a separate user-facing feature.

## Definition of done

All six lanes are complete; every Cursor subprocess goes through the OS wrapper,
strips both Cursor API overrides, carries the built-in plus configured
sensitive-read denials, and passes its closed final argv grammar after all
rewrites; every inference has one explicit known-family model; panels/Checkers
are ask mode with no shell tool inside an OS write-denial boundary; Makers use no
force/auto-approval bypass and can write only non-Git content in the owned
worktree plus private runtime; boundary readiness is independent of role
`read_only`; routing excludes `auto` and unknown IDs, reserves family `cursor`
for Cursor Composer profiles, and cannot borrow cross-adapter/cross-effort
evidence; quota is a shared unknown/non-blocking Cursor pool; every provider
fallthrough is explicit; JWT/assignment/header forms are redacted from
`result.md`, stdout/stderr sidecars, all of `status.json`, and staged Checker
packets without Alloy reading the keychain; byte-content fingerprints cover
ignored files and every named Git internal, and every parent Git call disables
hooks/fsmonitor and system config; the version/changelog/docs explicitly accept
and mitigate the residual keychain-login/repository/network confidentiality
risk; unit/skill/release-wording tests pass; unittest and macOS CI run the real
hard-link/symlink/Git-metadata/outside/repo/TMP/denied-read/runnable-CLI gate; the
separately authorized supported-version ask probe passes; and no deployment or
unrequested live call occurs.
