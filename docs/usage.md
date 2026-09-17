# Subscription meters and routing context

Alloy reads remaining subscription capacity and renders it as Markdown suitable
for Codex, Claude, Grok and Antigravity sessions. Usage reads do not call Jev or
launch a coding task. No separate menu-bar app is required.

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
| Grok | — | unknown | — | unavailable |

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
| Claude | Claude login OAuth → Anthropic usage endpoint | Uses existing CLI token/file or the default macOS `Claude Code-credentials` Keychain item; it never refreshes or rewrites CLI credentials |
| Antigravity | `agy -p /usage --output-format json` | Requires 1.1.11+ and a successful built-in usage report; unknown versions do not run print mode |
| Grok | Unavailable | `grok usage` is a session token/cost ledger, not verified remaining subscription capacity |

On this machine all three supported sources returned live limits. API/proxy
credential overrides disable ambiguous subscription probes rather than assuming
a different account's capacity applies. A profile explicitly billed as metered
never uses subscription quota for routing. For profiles whose billing is still
unknown, a successful native quota observation can guide availability without
assigning a dollar cost.

Cached readings are bound to the known native credential locations and relevant
authentication settings. File/account-source changes invalidate cached readings.
Changes occurring only inside Keychain or the Antigravity login service cannot
always be detected before TTL expiry; after switching accounts use
`alloy usage --refresh`. Usage bars never switch accounts or redeem reset credits.

Provider methods were verified against installed CLIs and the primary-source
[CodexBar Codex notes](https://github.com/steipete/CodexBar/blob/main/docs/codex.md),
[Claude notes](https://github.com/steipete/CodexBar/blob/main/docs/claude.md), and
[Antigravity notes](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md).
The implementation is independent stdlib Python, not copied Swift code or an
installation of CodexBar. These interfaces may change; malformed responses and
failed probes report unknown/stale rather than fabricated capacity.

## Routing policy

The lowest fresh remaining fraction across all applicable windows is the
profile's headroom. Defaults reserve the last 10% of a subscription. Profiles at
or below the reserve are excluded. Among remaining profiles, the relative cost
rank is divided by headroom: a mostly exhausted subscription becomes less
attractive. Profiles with unknown quota receive a small conservative multiplier
(1.25); they remain eligible rather than being represented as unlimited.

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
    "reserve_fraction": 0.1,
    "keychain": true
  }
}
```

These are members of the existing configuration, not a replacement file. Set
`ALLOY_USAGE=off` to disable provider reads and meters, or `usage.keychain=false`
to avoid macOS Keychain reads. Custom `CLAUDE_CONFIG_DIR` profiles never fall back
to the default global Keychain identity. No live provider calls run in tests.

Only normalized quota observations, source/freshness metadata and credential-
source digests are cached outside the repository. Tokens, emails, account IDs,
and reset-credit identifiers are discarded. Digests are omitted from display,
route context and manifests. Raw API bodies and Keychain secrets are not logged.
