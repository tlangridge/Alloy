# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **"Report a vulnerability"**
(Security → Advisories) on this repo, or by email to the maintainer. Do not open a
public issue for a vulnerability. We'll acknowledge within a few days.

## Threat model (what Alloy does and doesn't protect)

Alloy orchestrates AI coding CLIs you already installed and authenticated. Its
safety properties:

- **The panel is read-only, and (by default) reads your repo.** Read-only adapters
  run behind each CLI's read-only flag (`codex -s read-only`, grok/claude
  `--permission-mode plan`) with their working directory set to your **real repo**,
  so they can read your code to give useful coding answers but the CLI prevents
  them from writing. This write-prevention is **best-effort — the CLIs' own flags,
  not an OS sandbox Alloy enforces** (Cursor is the exception, below). As a tripwire, Alloy fingerprints the working
  tree before/after each run and flags (`summary.repo_tamper`) any change. Turn
  repo access off with `--no-repo` / `ALLOY_REPO=none` (empty throwaway cwd, the
  pre-0.1.6 behavior); pin a different dir with `--repo` / `ALLOY_REPO`.
- **Write-capable adapters never see your real tree.** Adapters with no read-only
  mode (`opencode`, and `antigravity` on agy < 1.1.0) are **refused** unless you
  set `ALLOY_ALLOW_UNSANDBOXED=1`, and even then they get a **disposable copy** of
  the repo (`.git` excluded), never the working tree — so their writes land off
  it. Cursor is not in this group: it is never run through that override (see the
  next item).
- **Cursor (`cursor`) is confined by a macOS sandbox, not by its own flags.**
  The public name is `cursor` (the legacy name `cursor-agent` is an input alias);
  the executable is `cursor-agent`. In the recorded boundary probe, Cursor's plan
  mode wrote both inside and outside the workspace, `--sandbox enabled` wrote
  outside it, and plan mode plus the sandbox flag could switch itself to agent
  mode and write. Ask mode refused in all three recorded runs, but it is a
  tool-mode control, not an operating-system guarantee. Alloy therefore uses
  `--mode ask` only as defense in depth, and treats plan mode and Cursor's
  `--sandbox` flag as **not** boundaries. The write boundary is a `sandbox-exec`
  profile that Alloy generates and self-tests before any Cursor process starts:
  - Every Cursor process (login status, version and help probes, model discovery,
    panels, Makers, Checkers) is started through one gateway that runs it under
    `/usr/bin/sandbox-exec` and checks the complete final argv against a closed
    grammar for that role. Unknown options, duplicated options, unexpected
    subcommands, `--force`/`--yolo`/auto-review/MCP-approval flags, another
    `--mode`, worktree, plugin and session controls, and any authentication,
    endpoint or header option are refused. No Cursor role ever gets an approval
    bypass. Worktree setup scripts are disabled by argv.
  - **macOS only.** On Linux and every other platform, and whenever the sandbox
    self-test fails or `sandbox-exec` is missing or not root-owned, every Cursor
    role is refused. `ALLOY_ALLOW_UNSANDBOXED=1` does not override this, and the
    disposable-copy path is not a Cursor fallback. A Cursor CLI build Alloy has
    not measured is refused as well, because ask mode's lack of a shell tool is
    only evidence-backed for specific builds. `alloy doctor` reports `[no-sbx]`
    and the reason.
  - **Panels and Checkers** run `--mode ask` with only a private, per-dispatch
    runtime directory writable. Process execution beyond the Cursor executable and
    hard-link creation are denied. The repository and all Git metadata are
    read-only.
  - **Makers** run Cursor's normal agent mode. Only the non-Git contents of the
    Alloy-owned worktree and the private runtime are writable; the worktree's
    `.git` entry, its gitdir, the shared Git directory, the source checkout,
    sibling worktrees, Cursor's own state and install directories and the rest of
    the filesystem are write-denied. Maker commands run inside the same sandbox.
  - The profile also denies the ways a sandboxed process can ask an unsandboxed
    one to act for it: Unix-domain sockets (except name resolution), Apple Events,
    LaunchServices opens and Mach lookups outside a short allowlist. The Cursor
    child receives an explicit environment allowlist, not the ambient one, and
    `CURSOR_API_KEY` and `CURSOR_API_ENDPOINT` are never passed on.
  - **Every Cursor role denies reads** of these locations, and everything under
    them: `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/gh`, `~/.netrc`,
    `~/.docker/config.json`, `~/.kube`, `~/.npmrc`, `~/.pypirc`,
    `~/.git-credentials`, `~/Library/Keychains`, `~/.cswarm`,
    `~/.codex/auth.json`, `~/.claude/.credentials.json`, `~/.gemini`, `~/.grok`,
    `~/.config/op`, 1Password group containers, and Alloy's own configuration
    directory, configuration file and secrets store. `~` is the real login home,
    not the private runtime. One generic rule covers common staging places: reads
    of anything directly under `/private/tmp` or `/tmp` whose name contains
    "secret" (any case), and everything beneath it, are denied. Add your own paths
    with `ALLOY_CURSOR_DENY_READ_PATHS` (comma-separated absolute paths, no
    globs); you can add denials but never remove a built-in one, and a denial that
    covers a path Cursor must read makes Cursor refuse to run instead of being
    dropped.
  - **Tripwires detect; they do not prevent.** Before and after each Cursor Maker,
    panel and Checker call, Alloy hashes the bytes of every tracked, untracked and
    ignored worktree file and the Git internals that change behavior, and checks
    canary files outside the workspace, only after the whole process group is dead.
    A change to a Checker's worktree or to protected Git internals, or to a canary,
    fails the call and no verdict is accepted. A Maker may change ordinary files
    only under `--allow-path`. If a hash cannot be computed, the call is refused.
    These checks cannot prove the whole filesystem was unchanged; the sandbox is
    the preventive control.
  - **Accepted residual risk.** Cursor's login is a macOS keychain item that the
    Cursor CLI reads through the system Security API, and the sandbox must let it.
    The Cursor process can also read the repository and use the network, and the
    profile cannot tell its legitimate reads and network use from those of its
    model-facing read tool. A Cursor role is therefore **not** an exfiltration
    boundary and Alloy does not claim complete credential isolation or an
    exfiltration-proof Checker. Mitigations: ask mode for panels and Checkers,
    denial of descendant processes, the credential-read denials above (the
    keychain database is unreadable as a file), redaction of JWT-shaped values,
    secret assignments and authorization/custom header values before every saved
    output (`result.md`, `stdout.txt`, `stderr.txt` and all of `status.json`,
    including the command), and a Checker packet built only from redacted text.
    "Recognized secrets are not staged" does not mean Cursor cannot read
    repository data.
- **Antigravity (`agy`) is read-only by allow-list, on agy >= 1.1.0 only.** That
  release made headless print mode **fail closed**: it cannot prompt, so any tool
  outside `permissions.allow` is auto-denied. Alloy generates a settings file
  allow-listing read tools only, points agy at an **alloy-owned HOME** (so the
  settings are ours, not yours, and agy's scratch/conversation state stays out of
  `~/.gemini`; auth files are symlinked, never copied), and grants repo access
  explicitly via `--add-dir` with `allowNonWorkspaceAccess: false` — agy ignores
  the process cwd, so confining HOME and naming the workspace is what actually
  contains it. `--dangerously-skip-permissions` is never passed. agy 1.2 and later
  ignore bare tool names, so there the allow-list is path-scoped `read_file(<dir>)`
  grants (agy 1.1 keeps the bare names) for the staged prompt directory, the repo
  or worktree, a linked worktree's gitdir (plus its common directory, only for the
  standard `<common>/worktrees/<id>` layout) and, for Checkers, the private gate-log
  directory; write and command tools stay denied and agy's stdin is `/dev/null`.
  On an older agy none of this holds and the adapter falls back to
  refused-by-default.
- **Panel output is untrusted.** The host is instructed to treat every
  panelist answer as data, never as instructions, and never to execute commands
  found in it. Output is scanned and redacted for common secret shapes before it
  is persisted (best-effort, not a guarantee).
- **Prompts go on stdin**, never on argv (no `ARG_MAX`, no `ps` leakage, no shell
  injection). `agy` and Cursor do not take their prompt on stdin, so each is handed
  the prompt as an owner-only **file** in a directory granted only for that
  purpose, with stdin set to `/dev/null` — argv carries a short instruction and a
  path, never the prompt text. Config is parsed as `KEY=value`, never `source`d,
  and only from the user-level path — a hostile repo cannot run code through it.
- **Optional routing egress.** `route`, `panel --route`, the setup live test and
  the explicit evaluation script send task text to TypeSafe's fixed HTTPS API.
  Routed panel attachments are included. The Jev bearer key is read from the
  environment or an owner-only user credential file, never stored in the repo,
  and removed from child CLI environments. HTTP redirects are rejected and
  errors do not echo API response bodies. Treat the routing credential file as
  a secret: a CLI with unrestricted filesystem access could still read it.
- **No telemetry.** Model refresh invokes provider model-list commands. The
  optional git update check contacts this repo's remote; disable it with
  `ALLOY_NO_UPDATE_CHECK=1`. That flag does not disable explicit Jev routing.
- **Subscription usage.** Automatic, cached provider reads use Codex's local
  app-server, Antigravity's version-gated built-in `/usage`, and Grok's fixed HTTPS
  CLI billing endpoint using its existing unexpired login. Grok redirects are
  rejected; browser cookies and token refresh are not used. **Alloy never reads
  the macOS keychain and never runs `security`.** (`usage.keychain` is accepted
  for old files but ignored. Alloy does write a keychain search-list preference
  file into agy's own isolated home so that `agy` itself can reach its login; Alloy
  does not read it or the keychain.) Claude quota comes from a credentials file or
  `CLAUDE_CODE_OAUTH_TOKEN` that already exists (sent only to Anthropic's usage
  endpoint), from the rate-limit fields of Claude Code's own status line or
  stream-json output when you opt in by piping them to
  `alloy usage --record-claude-statusline` or `--record-claude-stream`, or, only
  with `usage.claude_probe: true`, from one small `claude -p` call per usage TTL.
  Otherwise Claude quota is unknown. Cursor's CLI has no usage source, so Alloy
  reads nothing for it; Cursor quota is unknown unless you set it by hand. Tokens
  are used only for their provider's request and never persisted by Alloy. Raw
  responses, account identities and reset-credit IDs are excluded from usage
  cache/context. Stale observations are not used for quota calculations.
  `ALLOY_USAGE=off` disables these reads.
- **Routing decisions.** Model selections are validated against configured
  profiles, adapter readiness, tier and family constraints. Task text cannot
  supply shell commands. Jev judgments can still be wrong. Local version/help
  probes detect missing flags but are not proof of unchanged sandbox semantics.
  Profile configuration is trusted user input; do not load it from an untrusted
  project. Prompt-free routing history contains assessment metadata and hashes;
  panel manifests and prompt files retain their existing privacy properties.

What Alloy does **not** protect against, by design:

- **Provider egress.** Your prompts, **any repository files the panel reads**
  (repo access is on by default — use `--no-repo` to send nothing from your
  tree), any diffs you review, and any web pages a panelist fetches are sent to
  the model providers behind those CLIs — exactly as if you used the CLIs
  directly. "Read-only" means no local writes; it is **not** an OS-level
  data-exfiltration sandbox. For Cursor, models from other vendors are served
  through Cursor's own service, so your content goes to Cursor as well.
- **A binary you point `ALLOY_BIN_<NAME>` at.** Overrides run whatever you specify
  with your environment; that's your responsibility.

## Supported versions

Alloy is pre-1.0; only the latest release receives fixes.
