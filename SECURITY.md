# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **"Report a vulnerability"**
(Security → Advisories) on this repo, or by email to the maintainer. Do not open a
public issue for a vulnerability. We'll acknowledge within a few days.

## Threat model (what Alloy does and doesn't protect)

Alloy orchestrates AI coding CLIs you already installed and authenticated. Its
safety properties:

- **The panel is read-only.** Panelists run behind each CLI's read-only sandbox
  flag (`codex -s read-only`, `gemini --approval-mode plan`) **and** in a throwaway
  temp working directory, so they cannot read or write your repository. Adapters
  with no real read-only mode (`opencode`, `cursor-agent`) are **refused** unless
  you set `ALLOY_ALLOW_UNSANDBOXED=1`.
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

- **Provider egress.** Your prompts, any diffs you review, and any web pages a
  panelist fetches are sent to the model providers behind those CLIs — exactly as
  if you used the CLIs directly. "Read-only" means no local writes; it is **not**
  an OS-level data-exfiltration sandbox.
- **A binary you point `ALLOY_BIN_<NAME>` at.** Overrides run whatever you specify
  with your environment; that's your responsibility.

## Supported versions

Alloy is pre-1.0; only the latest release receives fixes.
