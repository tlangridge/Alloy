# Subscription meters and routing context

Alloy reads remaining subscription capacity and renders it as Markdown suitable
for Codex, Claude, Grok, Antigravity and Cursor sessions. Usage reads do not call
Jev or launch a coding task, and they make no model call unless you opt in to the
Claude probe described below. Alloy never reads the macOS keychain. No separate
menu-bar app is required.

```sh
alloy usage                                      # Markdown, refresh if needed
alloy usage --format json                        # normalized machine-readable snapshot
alloy usage --refresh                            # fresh bounded provider reads
alloy usage --cached                             # offline, no provider access
alloy usage --if-changed --session my-session     # quiet unless capacity/status changes
```

An illustrative display (these percentages are examples):

| Provider / pool | Window | Available | Resets in | Status |
| --- | --- | --- | --- | --- |
| Codex | 7d | `██████░░░░` 60% | 2d 4h | fresh |
| Claude | 5h | `███████░░░` 70% | 1h 20m | fresh |
| Antigravity / Gemini | weekly | `█████████░` 90% | 4d | fresh |
| Grok | weekly | `█████░░░░░` 51% | 5d 22h | fresh |
| Cursor | — | unknown | — | unavailable |

Every reported window appears separately, including model-specific windows. A
bar fills with **remaining** capacity, not consumed capacity. A reset passing is
not proof of replenishment; Alloy refreshes it. Failed refreshes keep the last
reading visible as stale, with its original observation age.

## Session behavior

The Alloy skill asks the host to render the meter at session start, new turns
while Alloy work is active, before delegation and after long runs or quota
failures. Each panel prints its startup meter and includes `subscription_usage`
in its manifest. Each route returns the same normalized quota context with the
decision. The generic CLI cannot intercept every turn inside another product;
the installed skill or a host integration must call `alloy usage` at those
checkpoints. No invasive global hooks are installed.

Provider reads share a two-minute cache across local sessions. `--if-changed`
uses a separate marker per session and suppresses output until a 5-percentage-
point band, reset timestamp or freshness status changes. It suppresses display,
not the underlying TTL-based refresh. If omitted, the session ID is taken from
`CODEX_THREAD_ID`, then `ALLOY_SESSION_ID`, then the current directory. Pass a
stable ID explicitly when multiple sessions share a directory.

## Sources and limits

| Provider | Source | Limitations |
| --- | --- | --- |
| Codex | Local `codex app-server` → `account/rateLimits/read` | Auth/version dependent; actual window duration is used, not an assumed five-hour window |
| Claude | An existing OAuth credential file or `CLAUDE_CODE_OAUTH_TOKEN` → Anthropic usage endpoint; otherwise Claude Code's own rate-limit fields, recorded by the opt-in status-line hook or a recorded stream; otherwise the opt-in probe | Never reads the macOS keychain and never refreshes or rewrites CLI credentials; unknown when no source is available. See [Claude quota without the keychain](#claude-quota-without-the-keychain) |
| Antigravity | `agy -p /usage --output-format json` | Requires 1.1.11+ and a successful built-in usage report; unknown versions do not run print mode |
| Grok | CLI billing REST endpoint with the existing login | Included-credit percentage and billing-period reset; no inference |
| Cursor | None: the CLI exposes no usage command or quota API | Always unknown unless you set a pool by hand; see [Cursor pools](#cursor-pools) |

API/proxy credential overrides disable ambiguous subscription probes rather than
assuming a different account's capacity applies. A profile explicitly billed as metered
never uses subscription quota for routing. For profiles whose billing is still
unknown, a successful native quota observation can guide availability without
assigning a dollar cost.

Cached readings are bound to the known native credential locations and relevant
authentication settings. File/account-source changes invalidate cached readings.
Changes occurring only inside the Antigravity login service cannot always be
detected before TTL expiry; after switching accounts use `alloy usage --refresh`.
Cursor's cache binding uses only the path, modification time and size of its
local state file, never its contents. Usage bars never switch accounts or redeem reset credits.

Provider methods were verified against installed CLIs and the primary-source
[CodexBar Codex notes](https://github.com/steipete/CodexBar/blob/main/docs/codex.md),
[Claude notes](https://github.com/steipete/CodexBar/blob/main/docs/claude.md), and
[Antigravity notes](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md).
The implementation is independent stdlib Python, not copied Swift code or an
installation of CodexBar. The CodexBar Claude notes describe a keychain path that
Alloy deliberately does not use. These interfaces may change; malformed responses and
failed probes report unknown/stale rather than fabricated capacity.

## Routing policy

The lowest fresh remaining fraction across all applicable windows is the
profile's headroom. Defaults reserve the last 10% of a subscription. Profiles at
or below the reserve are excluded. Among remaining profiles, the relative cost
rank is divided by headroom: a mostly exhausted subscription becomes less
attractive. Profiles with unknown quota receive a small conservative multiplier
(1.25); they remain eligible rather than being represented as unlimited. Cursor
profiles are unknown until you set a Cursor pool by hand.

A 15% reserve is a reasonable starting point (`"reserve_fraction": 0.15` below;
the shipped default remains 0.1). Readings can lag behind use by up to the cache
lifetime, hand-set Cursor pools only change when you change them, and interactive
sessions draw on the same subscriptions, so the extra 5 points leave more room.

Required capability tiers, explicit model pins and independent family constraints
still apply. Stale quota is excluded from calculations. Jev continues assessing
task complexity independently; quota policy is deterministic local code, and
the returned decision includes the observation used.

Antigravity's Gemini pool and its Claude/GPT pool are separate. Claude's common
windows apply alongside known model-specific weekly windows. Additional Codex
limit IDs are displayed separately; map specialized profiles explicitly with
`alloy models add --id PROFILE --usage-pool POOL_ID`. That explicit mapping adds a specialized window alongside known common
windows, so a specialized allowance cannot bypass a general subscription limit. Manual `quota_pools` reserves remain additional constraints.

In `~/.config/alloy/routing.json`, optional settings are:

```json
{
  "usage": {
    "enabled": true,
    "ttl_seconds": 120,
    "reserve_fraction": 0.15,
    "claude_probe": false
  }
}
```

These are members of the existing configuration, not a replacement file. Set
`ALLOY_USAGE=off` to disable provider reads and meters. `usage.claude_probe`
(default false) opts in to the Claude probe below. `usage.keychain` is still
accepted so existing files load, but it is ignored: Alloy never reads the macOS
keychain and never runs `security`. Custom `CLAUDE_CONFIG_DIR` profiles use their
own credentials file only. No live provider calls run in tests.

Only normalized quota observations, source/freshness metadata and credential-
source digests are cached outside the repository. Tokens, emails, account IDs,
and reset-credit identifiers are discarded. Digests are omitted from display,
route context and manifests. Raw API bodies are not logged.

### Claude quota without the keychain

On macOS, Claude Code stores its login in the keychain by default, and Alloy does
not read it, so an existing credentials file may be absent there. Alloy tries
these sources in order and uses the first that works:

1. **An existing credential.** `CLAUDE_CODE_OAUTH_TOKEN`, or `.credentials.json`
   in the Claude configuration directory when the file exists. The token goes only
   to Anthropic's usage endpoint and is never refreshed or rewritten.
2. **A recorded rate-limit snapshot (opt-in).** Claude Code reports its own
   five-hour and seven-day windows. Point its status-line command at
   `alloy usage --record-claude-statusline` to record them whenever Claude Code
   refreshes its status line:

   ```json
   {"statusLine": {"type": "command", "command": "alloy usage --record-claude-statusline"}}
   ```

   Alloy installs nothing and never edits your Claude settings. The command
   prints a one-line meter and never fails the status line. You can also record a
   run's stream events with
   `claude -p "..." --output-format stream-json --verbose | alloy usage --record-claude-stream`;
   that command reads the stream and prints only the meter line, so it suits a
   call made for that purpose. Claude runs that Alloy itself makes (the `claude`
   panelist and managed Claude workers) print the same stream, and Alloy records
   their rate-limit event into the same snapshot at no extra cost, unless usage is
   off, `usage.enabled` is false, `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` is
   set, or `ALLOY_CAPTURE_USAGE=1` switches those runs to plain `json` output,
   which carries no rate-limit event. Alloy's `claude` runs use
   `--output-format stream-json --verbose` otherwise. A snapshot older than `usage.ttl_seconds` is shown as stale and excluded
   from quota calculations.
3. **The probe (opt-in).** With `usage.claude_probe: true`, and only when neither
   source above gave a fresh reading, Alloy runs one tiny `claude -p` call (Haiku,
   no saved session, no MCP servers) and reads its rate-limit event; the result is
   cached for the usage TTL unless you pass `--refresh`. This is a real model call that spends a very small amount of
   Claude quota, so it is off by default.

If none of these applies, Claude quota is unknown and never blocks routing.
`ANTHROPIC_API_KEY` or `ANTHROPIC_BASE_URL` leaves it unknown, because that
account's capacity may not be the subscription's.

### Cursor pools

Cursor's CLI has no usage command or quota API, and the token counts in a call's
JSON output are not subscription capacity, so Alloy reads no Cursor usage and
never derives quota from per-call tokens. Cursor has two subscription pools:

| Pool | Models | Note |
| --- | --- | --- |
| `cursor:models` (Cursor Models) | `composer-*` and `cursor-grok-*` | Cursor's own models |
| `cursor:other` (Other Models) | Every other model served through Cursor: Claude, GPT, Gemini and `grok-*` models | Draws the more expensive pool |

Prefer Cursor-native models. Every other model through Cursor draws the more
expensive pool.

Both pools are `unknown`, and unknown does not block routing, unless you describe
them in `routing.json`:

```json
{"quota_pools": {
  "cursor:models": {"remaining_fraction": 0.60},
  "cursor:other": {"remaining_fraction": 0.25, "reserve_fraction": 0.15}}}
```

A pool with a valid `remaining_fraction` shows as `manual (operator-set)` and
counts toward routing headroom. It is read from the file every time and never
cached, so an edit takes effect on the next read. Alloy cannot refresh it: keep it
current yourself. A pool at or below its own `reserve_fraction` (default 0.1) or
the global `usage.reserve_fraction` excludes the profiles that draw on it.

All shipped Cursor profiles also carry the shared quota pool name `cursor` (see
[routing](routing.md#cost-controls)). Setting `quota_pools.cursor` to a
`remaining_fraction` at or below its reserve blocks every Cursor profile, whichever
of the two pools it draws on. Use `cursor:models` or `cursor:other` to limit only
one of them.

### Grok billing source

Alloy makes one bounded GET to `https://cli-chat-proxy.grok.com/v1/billing?format=credits`,
using the existing unexpired login in `~/.grok/auth.json` (`GROK_HOME` is respected).
It reads `creditUsagePercent`, or the legacy included `used / monthlyLimit` ratio.
The billing period determines the reset and weekly/monthly label. On-demand spend
caps are never treated as subscription quota. Missing fields, expired credentials,
team logins and API-key overrides leave capacity unknown. Alloy does not refresh
tokens, read browser cookies or persist identities. Credential-file changes invalidate
the usage cache. The existing two-minute cache and quota routing policy apply.

This is an undocumented provider interface and may change. The approach is also
documented by [CodexBar](https://github.com/steipete/CodexBar/blob/main/docs/grok.md).

Use `/alloy-usage` in an agent for the dedicated usage command. `install.sh` installs
this alias alongside `/alloy` and `/alloy-execute`; `alloy usage` is the terminal equivalent.

Claude model limits from `limits[].kind = weekly_scoped` are displayed separately,
including **Claude / Fable**. Fable routing observes both the shared Claude windows
and its own weekly limit. `is_active` describes the current selection and does not
hide a reported bucket. Unknown model scopes and surface-specific limits are not
assumed to apply to every Claude model. No additional provider request is needed.
