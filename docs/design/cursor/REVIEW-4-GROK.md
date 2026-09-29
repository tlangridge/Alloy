I'll recheck only the three items left open in the round-3 review—R1-9, N1, and the read-scope major—against the revised plan, the Round 3 response, the login-store facts, and the code.The response claims all three are fixed. I'll read the plan sections it cites and compare them with the login-store facts and the current code paths.All three open items are fixed in the revised plan. The current code still has the old sinks and Git helper; the plan requires the corrections and matches the login-store facts.

## R1-9 — FIXED

The login store is keychain items `cursor-access-token` and `cursor-refresh-token`, with no token file and no byte shape (`CURSOR-FACTS.md:368-370`). The plan follows that: Alloy must not call `security`, must not read `~/Library/Keychains`, and must not invent a Cursor token pattern or do exact-value redaction (`CURSOR-PROVIDER-PLAN.md:237-244`, `:461-484`).

Recognized forms are scrubbed before every persisted sink. Parsed `result` is scrubbed before `result.md`; stdout and stderr are captured in memory and scrubbed before `stdout.txt` and `stderr.txt` are created; the whole `status.json` payload, including every `command` element, is scrubbed before the first and final writes (`:485-497`). That replaces the current path, which points `Popen` at the final sidecars and only rewrites them later (`bin/alloy:1482-1493`, `bin/alloy:1586-1599`), and the first `status.json` write that stores the raw argv (`bin/alloy:1447-1450`, `bin/alloy:1500-1503`).

The JWT fixture must show the value absent and the marker present in `result.md`, both sidecars, and `status.json`. Assignment and header fixtures cover every sink (`:493-497`; §9 tests 2, 6, and 14). The existing scrubber already has those three shapes (`bin/alloy:263-315`).

## N1 — FIXED

The digest now includes `commondir` (the file itself), `config`, `config.worktree`, `hooks/`, `info/exclude`, `info/attributes`, `info/sparse-checkout`, `HEAD`, `refs/`, and `packed-refs`, plus missing/present state (`CURSOR-PROVIDER-PLAN.md:277-286`). `git status` and `scope()` stay user-facing checks and are not the tamper proof (`:303-305`). Lane 3 rejects `commondir`, attributes, and sparse-checkout changes before review (`:1122-1125`).

Every unsandboxed parent Git command, including `clean()`, `scope()`, worktree setup, `git add`, `git commit`, and fingerprint Git, goes through one helper that prepends `-c core.hooksPath=/dev/null -c core.fsmonitor=false` and sets `GIT_CONFIG_NOSYSTEM=1` (`:288-298`). That covers the current helpers, which only set `core.hooksPath` or set nothing (`bin/alloy_execution.py:29-30`, `bin/alloy:1283-1286`, `clean()` at `bin/alloy_execution.py:82-83`, add/commit at `:532-535`). §6 and §9 tests 4–5 and 14 require that argv/env on those calls. `alias.*` is closed with the Git rule that aliases hiding real commands are ignored, cited at `https://git-scm.com/docs/git-config#Documentation/git-config.txt-alias` (`:298-302`).

## Read-scope major — FIXED

Every generated profile, including panel, Checker, Maker, status, version/help, and discovery, adds non-overridable `(deny file-read*)` rules for the listed credential paths and descendants: `~/.ssh`, `~/.aws`, the other CLI auth paths, `~/Library/Keychains`, the 1Password group-container pattern, the Alloy secrets root, and `/private/tmp/anvil-secret.*` (`CURSOR-PROVIDER-PLAN.md:159-215`). `ALLOY_CURSOR_DENY_READ_PATHS` can add denials and cannot remove a built-in. `~` is the real login home.

§9 tests 4–5 and 14 require the deny set in every role and discovery profile. The macOS release gate creates a sentinel under an extra denied-read root, proves a direct open fails, then proves the sandboxed CLI still runs (`:952-968`; Lanes 1, 3, and 6). §8 requires `SECURITY.md` to state the denials and to keep the accepted residual limited to keychain-login, repository reads, and provider network (`:829-837`, `:1259-1273`).

VERDICT: PASS