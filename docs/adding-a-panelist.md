# Adding a panelist

A panelist is one CLI Alloy can dispatch to. Adding one is a small, well-defined
adapter in `bin/alloy`. The goal is that supporting a new CLI is a ~30-line pull
request, not a reverse-engineering project.

## The 5-function adapter contract

Every adapter answers five questions. They map to methods on the `Adapter` base
class in `bin/alloy`:

1. **detect** — *is this CLI installed?* (`detect()` / `resolved_bin()`): is the
   binary on `PATH` (or overridden via `ALLOY_BIN_<NAME>`)?
2. **auth** — *is it actually logged in?* (`is_authed()` → `auth_state()`):
   presence on `PATH` says nothing about login state. Use a **cheap, no-token**
   heuristic — an env var or a credentials file — so `doctor` does not spend
   money. Return `ready` / `installed_not_authed` / `not_installed`.
3. **invoke-read-only** — *how do I run it read-only?*
   (`build_args(prompt_path, last_message_path, mode)`): return the argv **after**
   the binary, including the CLI's read-only flag. The engine feeds the prompt on
   **stdin**, so most adapters need nothing for input. If your CLI reads its prompt
   from a **file** instead (e.g. Grok's `--prompt-file`), pass the `prompt_path`
   argument. Either way, never put the prompt text in argv.
4. **parse** — *where is the clean answer?* (`parse(stdout, stderr, last_message)`):
   return the answer text. Never return stderr as the answer (CLIs put banners,
   telemetry, and warnings there). Strip ANSI if needed (`strip_ansi` helper).
5. **capabilities** — *what can it do?* (`read_only`, `experimental`,
   `model()`): set the class attributes. If the CLI has **no real read-only
   mode**, set `read_only = False`; the engine will refuse to dispatch to it
   unless the user sets `ALLOY_ALLOW_UNSANDBOXED=1`.

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

    def build_args(self, prompt_path, last_message_path, mode):
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

## Worked example: `cursor-agent` (an adapter with no read-only mode)

`cursor-agent --print` runs non-interactively but, per its own help, *"has access
to all tools, including write and bash"* — it has **no** read-only sandbox flag.
That is exactly the case the `read_only` capability exists for:

```python
class CursorAgentAdapter(Adapter):
    name = "cursor-agent"
    bin = "cursor-agent"
    read_only = False               # <-- no read-only mode; engine will refuse by default
    experimental = True
    install_hint = "see https://cursor.com/cli"
    auth_hint = "cursor-agent login"

    def is_authed(self) -> bool:
        return bool(os.environ.get("CURSOR_API_KEY"))  # + creds-file check

    def build_args(self, prompt_path, last_message_path, mode):
        # NB: even in --print mode this can write files and run bash. It is only
        # contained by alloy's throwaway cwd. Never pass -f/--force.
        return ["--print", "--output-format", "text"]

    def parse(self, stdout, stderr, last_message):
        return strip_ansi(stdout).strip()
```

Because `read_only = False`, `bin/alloy panel` skips it (recording the reason in
the manifest) unless the user explicitly sets `ALLOY_ALLOW_UNSANDBOXED=1`. This
keeps "I added an adapter" from silently weakening Alloy's safety promise.

> Lesson: an adapter is more than an invocation string. The `read_only` and
> `auth` answers are what keep Alloy safe and honest.
