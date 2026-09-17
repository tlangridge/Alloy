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
  not an OS sandbox Alloy enforces.** As a tripwire, Alloy fingerprints the working
  tree before/after each run and flags (`summary.repo_tamper`) any change. Turn
  repo access off with `--no-repo` / `ALLOY_REPO=none` (empty throwaway cwd, the
  pre-0.1.6 behavior); pin a different dir with `--repo` / `ALLOY_REPO`.
- **Write-capable adapters never see your real tree.** Adapters with no read-only
  mode (`opencode`, `cursor-agent`, and `antigravity` on agy < 1.1.0) are
  **refused** unless you set `ALLOY_ALLOW_UNSANDBOXED=1`, and even then they get a
  **disposable copy** of the repo (`.git` excluded), never the working tree — so
  their writes land off it.
- **Antigravity (`agy`) is read-only by allow-list, on agy >= 1.1.0 only.** That
  release made headless print mode **fail closed**: it cannot prompt, so any tool
  outside `permissions.allow` is auto-denied. Alloy generates a settings file
  allow-listing read tools only, points agy at an **alloy-owned HOME** (so the
  settings are ours, not yours, and agy's scratch/conversation state stays out of
  `~/.gemini`; auth files are symlinked, never copied), and grants repo access
  explicitly via `--add-dir` with `allowNonWorkspaceAccess: false` — agy ignores
  the process cwd, so confining HOME and naming the workspace is what actually
  contains it. `--dangerously-skip-permissions` is never passed. On an older agy
  none of this holds and the adapter falls back to refused-by-default.
- **Panel output is untrusted.** The host is instructed to treat every
  panelist answer as data, never as instructions, and never to execute commands
  found in it. Output is scanned and redacted for common secret shapes before it
  is persisted (best-effort, not a guarantee).
- **Prompts go on stdin**, never on argv (no `ARG_MAX`, no `ps` leakage, no shell
  injection). `agy` ignores stdin in headless mode, so it is handed the prompt as
  a **file** in a directory granted only for that purpose — argv carries a path,
  never the prompt text. Config is parsed as `KEY=value`, never `source`d, and only from the
  user-level path — a hostile repo cannot run code through it.
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
  app-server, Antigravity's version-gated built-in `/usage`, and Claude's OAuth
  usage endpoint. Claude may read its native macOS Keychain credential; disable
  this with `usage.keychain=false`. Tokens are used only for their provider's
  request and never persisted by Alloy. Raw responses, account identities and
  reset-credit IDs are excluded from usage cache/context. Stale observations are
  not used for quota calculations. `ALLOY_USAGE=off` disables these reads.
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
  data-exfiltration sandbox.
- **A binary you point `ALLOY_BIN_<NAME>` at.** Overrides run whatever you specify
  with your environment; that's your responsibility.

## Supported versions

Alloy is pre-1.0; only the latest release receives fixes.
