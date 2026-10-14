# Subscription meters and routing context

Alloy reads remaining subscription capacity and renders it as Markdown suitable
for Codex, Claude, Grok, Antigravity, Muse and Cursor sessions. Usage reads do not call
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
| Muse | — | unknown | — | unavailable |

Every reported window appears separately, including model-specific windows. A
bar fills with **remaining** capacity, not consumed capacity. A reset passing is
not proof of replenishment; Alloy refreshes it. Failed refreshes keep the last
reading visible with its original observation age. Claude windows retain their own
freshness, so a failed refresh does not renew or discard an observation.

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
| Muse | No verified subscription usage source | Unknown; per-call tokens and model-card API prices do not establish remaining capacity |
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

A Claude Code terminal session can run `alloy usage --cached` to inspect local
observations without network access or a nested Claude process. `alloy usage`
adds bounded provider reads when their cache expires. A new local observation
appears immediately in both commands.

The available sources are:

1. **An existing OAuth credential.** `CLAUDE_CODE_OAUTH_TOKEN`, or the existing
   `.credentials.json` in `CLAUDE_CONFIG_DIR` (default `~/.claude`). Alloy calls
   Anthropic's usage endpoint without refreshing, rewriting or extracting a login
   from the keychain. This source can include model-specific weekly limits.
2. **Claude Code's native status line, configured explicitly.** Keep the command
   as a direct executable invocation:

   ```json
   {"statusLine": {"type": "command", "command": "alloy usage --record-claude-statusline"}}
   ```

   Alloy leaves Claude settings alone. The recorder prints a short meter and
   stores only normalized five-hour/seven-day quota, source/timing metadata,
   hashed profile/session references and response-counter baselines outside the
   repository. It does not store paths, prompts, conversation text or identities.

   Status-line redraws can happen without a new response. On Claude Code
   v2.1.251+, Alloy uses the documented `prompt_cache.requests` counter to detect
   progress within a session. A first-seen positive counter establishes an
   **unverified** baseline; the next increase establishes an observation, even
   when percentages are unchanged. A startup callback with explicit zero API
   duration can establish the baseline before the first response. Missing
   counters and unchanged or decreasing counters never renew freshness. After a
   same-session counter reset, restart the session or wait until the counter
   exceeds its previous high-water mark. Older Claude versions without the
   counter provide display-only history through this recorder.

   The preceding callback supplies a conservative time bound. The first response
   after a long gap can therefore remain stale; a subsequent response establishes
   a recent bound. Receipt time alone never makes quota fresh.
3. **Rate events from an existing Claude run.** Alloy-owned Claude dispatches
   capture their profile/auth binding and launch time before spawning the child.
   Their quota events use that launch time as a conservative observation bound:
   short runs can supply fresh data; long runs can supply stale data. A late
   completion keeps its own bound. Overlapping responses retain their evidence
   and enforce the tightest fresh constraint until a provably later response
   supersedes them. No additional model call is
   needed. `ALLOY_CAPTURE_USAGE=1` selects plain JSON output with no rate event.
   Piping buffered output into `alloy usage --record-claude-stream` records
   **unverified history**, because its response time cannot be established.
4. **A standalone probe, explicitly enabled.** `usage.claude_probe: true` permits
   a small Haiku inference call only when there is no fresh native reading. It
   remains off by default and is throttled by the provider cache. Inside Claude
   Code (`CLAUDECODE` set), Alloy skips this probe even on `--refresh`, preserving
   Claude's nesting guard. Use native observations for self-inspection.

Each `(pool, window)` keeps its own source, observation time, receipt time and
freshness basis. New shared readings preserve known scoped limits at their
original age; they cannot erase or rejuvenate a Sonnet, Opus or other scoped
constraint. Expired resets do not imply replenishment. Partial data is labeled
`partial`; fresh known exhaustion still blocks routing, while incomplete positive
headroom remains unknown. JSON exposes per-window status and sanitized attempt
reasons; Markdown explains missing sources, disabled probes and stale baselines.
The observation frontier is bounded. If too many overlapping readings prevent
complete retention, the window reports incomplete coverage and subscription
routing pauses until a verified response begins after the retained interval.
Known constraints never become spare capacity through truncation.

Observations are bound to the canonical Claude configuration directory and known
credential settings at ingestion. This identifies a local profile, **not a
verified account identity**. Switching accounts only inside the macOS keychain
may be invisible. After such a switch, run:

```sh
alloy usage --invalidate-claude
```

Then restart Claude Code to establish a new native response baseline. Separate
`CLAUDE_CONFIG_DIR` profiles provide clearer separation. Invalidation changes
only the local observation generation, preserving credentials and settings.
Legacy unbound snapshots remain unverified display history; a matching bound
OAuth cache retains its original age. `--cached` performs no migration writes.
API/proxy overrides leave subscription applicability unknown.
Rewriting a credentials file, including a routine token refresh, starts a new
baseline because Alloy cannot distinguish that rewrite from an account switch
without inspecting identity. Old observation generations beyond the maximum
one-hour TTL are pruned opportunistically, retaining four recent generations.
Lock files remain in place to preserve exclusion between concurrent writers.

The native field contract is documented in the
[Claude Code status-line reference](https://code.claude.com/docs/en/statusline).
The optional [mods API](https://code.claude.com/docs/en/plugins/mods/reference)
exposes `session.usage()`, but its quota entries carry no observation timestamp;
it is not used as a guaranteed server refresh.

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

Under quality-first routing, headroom and reset pacing distinguish equally
qualified workers. Spare capacity cannot overrule a stronger required role.
Unknown Muse capacity is reported explicitly; it is never treated as unlimited
or inferred from tokens in a run. Manual quota reserves remain binding.
