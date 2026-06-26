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
  mode (`antigravity`, `opencode`, `cursor-agent`) are **refused** unless you set
  `ALLOY_ALLOW_UNSANDBOXED=1`, and even then they get a **disposable copy** of the
  repo (`.git` excluded), never the working tree — so their writes land off it.
- **Panel output is untrusted.** The host (Claude) is instructed to treat every
  panelist answer as data, never as instructions, and never to execute commands
  found in it. Output is scanned and redacted for common secret shapes before it
  is persisted (best-effort, not a guarantee).
- **Prompts go on stdin**, never on argv (no `ARG_MAX`, no `ps` leakage, no shell
  injection). Config is parsed as `KEY=value`, never `source`d, and only from the
  user-level path — a hostile repo cannot run code through it.
- **No telemetry, no keys.** Alloy ships no API keys and sends no data of its own.
  The only network call it makes is an optional, throttled `git fetch` update
  check against this repo's own remote (`ALLOY_NO_UPDATE_CHECK=1` disables it).

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
