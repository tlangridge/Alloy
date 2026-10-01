# Adding a panelist

A panelist is one CLI Alloy can dispatch to. Adding one is a small, well-defined
adapter in `bin/alloy`. The goal is that supporting a new CLI is a ~30-line pull
request, not a reverse-engineering project.

## The 5-function adapter contract

Every adapter answers five questions. They map to methods on the `Adapter` base
class in `bin/alloy`:

1. **detect** — *is this CLI installed?* (`detect()` / `resolved_bin()`): is the
   binary on `PATH` (or overridden via `ALLOY_BIN_<NAME>`, with hyphens in the
   name turned into underscores)? An adapter whose public name differs from its
   older spelling lists both override keys in `bin_env_keys`, canonical first.
2. **auth** — *is it actually logged in?* (`is_authed()` → `auth_state()`):
   presence on `PATH` says nothing about login state. Use a **cheap, no-token**
   heuristic — an env var or a credentials file — so `doctor` does not spend
   money. Return `ready` / `installed_not_authed` / `not_installed`. Never read
   the macOS keychain or run `security` to answer this. If the login cannot be
   observed, override `auth_status()` to report `unknown` (as `AntigravityAdapter`
   does on macOS), treat it as usable, and let the first real dispatch report an
   `auth` failure, rather than guessing.
3. **invoke-read-only** — *how do I run it read-only?*
   (`build_args(prompt_path, last_message_path, mode, ctx)`): return the argv
   **after** the binary, including the CLI's read-only flag. The engine feeds the
   prompt on **stdin**, so most adapters need nothing for input. If your CLI reads
   its prompt from a **file** instead (e.g. Grok's `--prompt-file`), pass the
   `prompt_path` argument. If it accepts neither (agy and Cursor), set
   `stdin_from_prompt = False`, copy the prompt to an owner-only staged file, give
   the CLI read access to just that file, and put a short instruction with the
   file's path on argv. Whichever way, never put the prompt text in argv.
   `ctx` carries the run's `{repo, pdir, cwd, timeout_s}` for CLIs that need to be
   *told* which directory they may read (agy's `--add-dir`), that want a scratch
   file of their own (write it under `pdir`), or that have an internal deadline
   worth aligning with alloy's.
4. **parse** — *where is the clean answer?* (`parse(stdout, stderr, last_message)`):
   return the answer text. Never return stderr as the answer (CLIs put banners,
   telemetry, and warnings there). Strip ANSI if needed (`strip_ansi` helper).
5. **capabilities** — *what can it do?* (`read_only`, `experimental`,
   `model()`): set the class attributes. If the CLI has **no real read-only
   mode**, set `read_only = False`; the engine will refuse to dispatch to it
   unless the user sets `ALLOY_ALLOW_UNSANDBOXED=1`. If read-only-ness depends on
   the *installed version*, make `read_only` a property that checks
   `cli_version()` — see `AntigravityAdapter`, which is read-only only on
   agy >= 1.1.0. If the CLI is only safe inside an operating-system boundary you
   provide, set `requires_os_boundary = True` instead: the adapter then runs only
   when that boundary is validated, and `ALLOY_ALLOW_UNSANDBOXED` can never
   override it. That is a separate fact from `read_only`, which only describes the
   role. See the Cursor example below.

There is also an optional sixth hook: **`prepare_env(ctx)`**, returning env
overrides for the child process. Use it when a CLI's only real safety control is
its own config file — point `HOME` at an alloy-owned directory holding settings
you generated, rather than mutating the user's dotfiles. `AntigravityAdapter` is
the worked example.

Further optional hooks change nothing by default: `capture_in_memory` (drain the
child's pipes into bounded memory so unredacted output never reaches the run
directory), `kill_group_on_exit`, `open_scope()` (a per-dispatch resource that is
released only after the process group is dead), `wrap_argv()` (the final spawn
gateway, called with the fully rewritten argv), `before_spawn()` and
`after_exit()` (a tripwire), `output_error()` (a failure an exit status of zero
would hide), `redact_stdout()`, `provider_meta()`, `usage()`,
`permission_overrides()` and `doctor_extra()`.

## Template

```python
class MyToolAdapter(Adapter):
    name = "mytool"                 # what users put in ALLOY_PANELISTS
    bin = "mytool"                  # the executable on PATH
    read_only = True                # does it have a verified read-only mode?
    experimental = False            # ship only verified adapters as non-experimental
    install_hint = "npm install -g mytool"
    auth_hint = "mytool login   (or set MYTOOL_API_KEY)"

    def is_authed(self) -> bool:
        # cheap, no-token check: env var or a credentials file
        if os.environ.get("MYTOOL_API_KEY"):
            return True
        return os.path.isfile(os.path.expanduser("~/.mytool/auth.json"))

    def model(self):
        return setting("ALLOY_MYTOOL_MODEL")   # optional per-adapter override

    def build_args(self, prompt_path, last_message_path, mode, ctx=None):
        # The engine feeds the prompt on STDIN, so most adapters return only flags
        # plus the read-only flag. (If your CLI needs a prompt file instead, pass
        # prompt_path, e.g. ["--prompt-file", prompt_path].) Never include
        # --yolo / auto-approve / bypass flags.
        args = ["--print", "--read-only", "--no-color"]
        if self.model():
            args += ["--model", self.model()]
        return args

    def parse(self, stdout, stderr, last_message):
        return strip_ansi(stdout).strip()
```

Then register it:

```python
ADAPTERS = {
    "codex": CodexAdapter(),
    "mytool": MyToolAdapter(),     # <-- add here
    "antigravity": AntigravityAdapter(),
}
DEFAULT_PANEL_ORDER = ["codex", "grok", "mytool"]   # if it should run by default
```

## Verify it

```bash
bin/alloy doctor                 # your adapter should show up with the right status
echo "Say READY." | bin/alloy panel --panelists mytool --timeout 60
```

Add a mock in `tests/mocks/` and a case in `tests/test_alloy.py` so CI exercises
your adapter's failure modes (timeout, nonzero exit, empty output) without
spending tokens. See the existing `tests/mocks/mock_panelist.py` mock.

## Worked example: `cursor` (safe only inside an OS boundary)

`cursor-agent --print` runs non-interactively with access to write and shell
tools. It has an ask mode, a plan mode and a `--sandbox` flag, but in the recorded
probe plan mode and the sandbox flag both wrote outside the workspace, and ask mode
is a tool-mode control, not an operating-system guarantee. So none of Cursor's own
flags can be the safety answer, and the real adapter, `CursorAgentAdapter` in
`bin/alloy`, answers the five questions differently from the template above:

- **Name and detect.** The public name is `cursor`; the executable is
  `cursor-agent`. `ADAPTER_ALIASES` maps the old input name `cursor-agent` to
  `cursor`, applied by `normalize_adapter_name()` where names enter (config,
  `--panelists`, routing profiles) and never in run output, so there is exactly
  one registry entry, one doctor row and one run directory.
  `bin_env_keys = ("ALLOY_BIN_CURSOR", "ALLOY_BIN_CURSOR_AGENT")` keeps the legacy
  key as a fallback.
- **Setup.** Cursor requires a one-time `AGENT_CLI_CREDENTIAL_STORE=file cursor-agent login`.
  The login lives in `~/.cursor/auth.json` (0600). Every Cursor child receives
  `AGENT_CLI_CREDENTIAL_STORE=file`; under Alloy the Cursor CLI is denied keychain
  access and cannot start `/usr/bin/security`. Alloy never reads the keychain.
  The pinned build writes `auth.json` directly and chmods it to 0600, with no temp
  or atomic-rename files. Only that literal file is write-granted, plus permission
  changes on the existing `~/.cursor` directory (the CLI chmods it to 0700).
  No other home files are writable, and symlinked credential paths are refused.

- **Auth.** `is_authed()` runs `cursor-agent status` through the sandbox gateway
  (stdin `/dev/null`, short timeout, bounded output) and reports ready only for
  exit code zero plus a recognized logged-in marker; anything else fails closed.
  The account text is masked before it reaches doctor. The login itself is a
  file login that Cursor manages: Alloy never reads the keychain, never runs
  `security`, and never uses `CURSOR_API_KEY`, `CURSOR_API_ENDPOINT`, `--api-key`,
  `--endpoint` or `--header`. `auth_state()` can also return `sandbox_unavailable`.
- **Invoke.** `stdin_from_prompt = False`. `build_args()` stages the prompt as an
  owner-only file and emits `-p --mode ask --output-format json --workspace <repo>
  --model <model> --trust --sandbox disabled --skip-worktree-setup <instruction>`,
  where the instruction is a short fixed sentence naming the staged file. A Maker
  omits `--mode ask`. `--model` is always present and always names a model with a
  known family; `auto` and unknown IDs are refused.
- **The OS wrapper.** `requires_os_boundary = True`. `open_scope()` creates an
  owner-private runtime and canary files outside every repository. `wrap_argv()`
  is the only way to obtain a Cursor command line: it validates the boundary,
  parses the complete final argv against a closed grammar for the role, writes
  the profile, and returns `/usr/bin/sandbox-exec -f <profile> <build>/node
  --use-system-ca <build>/index.js ...`, where `<build>` is the pinned build
  directory that `cursor_resolve_build()` finds behind the configured
  `cursor-agent` path without executing anything. Status, version, help and model
  discovery use the same gateway; by design no code path runs `cursor-agent`
  directly. A panel or Checker profile allows exactly three literal executables
  (the build's `node`, its bundled `rg` and
  `/usr/bin/sw_vers`), each verified first; the CLI's own code starts the last
  two and Alloy never runs them. Any doubt raises `CursorBoundaryError` and
  the run is refused before anything starts. It works on macOS only.
- **Parse.** The answer is the JSON object's `result`. `output_error()` fails a run
  whose JSON is malformed, has no string `result` or says `is_error`, even with
  exit status zero. `provider_meta()` keeps Cursor's `session_id` as
  `provider_session_id`, separate from Alloy's own, and `usage()` normalizes
  only recognized non-negative integer token fields (otherwise `null`; per-call
  tokens are never subscription quota). `capture_in_memory = True` and
  `redact_stdout()` mean nothing unredacted is ever written to the run directory.
- **Capabilities.** `read_only` is true for a panel or Checker and is cleared on
  the per-dispatch copy used as a Maker; the boundary is the separate read-only
  `cursor_boundary_ready`, never inferred from `read_only`, so a Maker is wrapped
  exactly like a Checker. `before_spawn()` and `after_exit()` fingerprint the
  worktree and Git internals and check canaries after the process group is dead;
  that is a tripwire, and the sandbox is the boundary. `permission_overrides()`
  reports the real write allowlist, and `doctor_extra()` adds `os_boundary`, a
  masked `auth_detail`, a specific refusal reason and deprecation warnings.

Because the boundary is unavailable off macOS, `bin/alloy panel` skips Cursor there
and records why. Adding a CLI that needs an OS boundary means providing the boundary,
the closed argv grammar and the tripwire together; flipping `read_only` to true is
never enough.

> Lesson: an adapter is more than an invocation string. The `read_only`, `auth`
> and boundary answers are what keep Alloy safe and honest.


## Managed execution capability

Read-only panel support does not automatically grant managed-write support.
`bin/alloy_execution.py` explicitly supports write modes for Codex, Claude, Grok,
Antigravity and Cursor (each has its own branch; an unknown adapter is refused
rather than inheriting another's permissions), checks the installed help flags,
and uses per-dispatch adapter copies. Adding a new CLI requires a reviewed write policy and mock lifecycle
coverage; do not route unsupported CLIs into a writable worktree by default.

`status.json.permissions` distinguishes `repository_write` from
`command_execution`, records scope/enforcement, and discloses OS and Git metadata
isolation. A normal panel remains read-only. See [managed execution](execution.md)
for the complete contract and cleanup invariants.

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
