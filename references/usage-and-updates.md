# Visible usage and updates

Read this at invocation and at execution round boundaries.

**Every Alloy invocation must show a usage table and a task-routing statement
in the host's visible chat**, including the execute alias. Tool output alone
is not sufficient. At invocation, run:

```bash
"$ALLOY_BIN" usage --format markdown
```

Render the returned Markdown directly, outside a code fence, under a short
**Alloy · <mode>** label. Keep the existing ten-cell capacity bars, percentages,
reset times, model-specific pools and freshness/unknown labels. Use native
Markdown tables; if the host cannot render tables, use one compact plain-text
line per provider/window with the same values. Avoid HTML, color-only indicators
or host-specific widgets. If usage is disabled or unavailable, show that status
instead of inventing a meter or enabling tracking. For `usage` mode, this is the
requested command: honor its options (including JSON) and do not run it twice.

Immediately below the meter, state **what task goes to which CLI/model and why**.
For one assignment, use one sentence. For multiple assignments, use a compact
table with `Task / role | CLI · model | Status / reason`. Include the host's
judging role when applicable; do not guess its model ID. Use exact model IDs
from actual routing decisions, manifests or managed task records. Before these
exist, label assignments **pending selection** (or **planned** for explicit
profiles); update the statement when dispatch confirms them. Never claim a
worker ran merely because a profile was recommended. For diagnostic/setup/usage
commands, say **No tasks dispatched**; for `route`, say **Selected; not executed**.

Show the meter plus updated assignments for **every execution round**, including
Maker corrections, retries, resumes and new workstreams, even with the same workers
and unchanged quota readings. Also show it after a reroute or quota failure.
Never use `--if-changed` to suppress a round-boundary table. Do not repeat it for
ordinary waiting polls. Use cached readings within their normal two-minute lifetime; do not force a refresh simply to redraw
the table. Use `--refresh` after a quota error and `--cached` for offline context.
Do not make an extra Jev call just to populate the display.

For interim checks during the same invocation, use
`usage --if-changed --session <stable-session-id>` at a new user turn while Alloy
work is active and after a long run. Render nonempty output; suppression here
does not replace the required invocation/delegation display. Each panel also
includes its startup snapshot in the manifest and stderr. In the final answer,
briefly identify the actual workers and outcome so the result remains clear if
progress messages are collapsed.

Treat only fresh quota as evidence. Provider windows are shared subscription
capacity, not this task's token count. Keep Antigravity's Gemini and Claude/GPT
pools separate, and preserve Codex/Claude model-specific windows. Grok reads included-credit usage from its CLI billing endpoint when available.
Alloy never reads the macOS keychain, so Claude quota may be unknown unless a
credentials file, the opt-in status-line hook (`alloy usage
--record-claude-statusline`) with an established response baseline, or the opt-in
standalone `usage.claude_probe` is in place. Inside Claude Code, use
`alloy usage --cached` for local self-inspection; the probe is always skipped.
Status-line redraws never renew freshness. After switching accounts within the
same keychain-backed profile, run `alloy usage --invalidate-claude` and restart
Claude Code. See [usage](../docs/usage.md#claude-quota-without-the-keychain);
do not read the keychain yourself to fill it in. Alloy has no live Cursor usage
reader. Its legacy-compatible manual pools, `cursor:models` (composer-*,
cursor-grok-*) and `cursor:other` (other models through Cursor), are unknown unless
the user sets them by hand. Current Cursor plans can share weekly native-model
capacity with Grok and charge third-party models from prepaid credit; legacy
plans differ. Confirm the actual plan, account and model settings before enabling
profiles. Do not treat these compatibility labels as independent included
allowances or double-count a shared subscription. Prefer Cursor-native models
when appropriate; preserve explicit billing choices. See the dated plan sources
in `docs/model-research.md`.
The router uses this snapshot itself; do not override its
family/tier constraints or treat unknown capacity as unlimited. Never redeem
reset credits or change subscriptions as part of displaying usage.

Then run the throttled automatic updater at the start of each skill invocation,
before dispatching work (at most one network check per 24 hours):

```bash
"$ALLOY_BIN" update-check
```

This installs newer published stable releases for clean official Git installations
on main/master. No confirmation is needed. On `UPDATED`, read the updated
`SKILL.md` from disk before proceeding and mention the new version once. This
updates the CLI and every skill symlink to that installation. Do not run an
updater during an execute loop or retry an update in the same invocation.

Local changes, developer branches, non-release commits, and active Alloy runs
prevent installation. Never reset/stash local changes or force an update.
Copied skills.sh installs/worktrees report `UPDATE_UNSUPPORTED`; mention the
manual upgrade path once (`npx skills update` for skills.sh), then proceed.
Offline failures and throttled/skipped checks do not block the task.

Users can set `ALLOY_AUTO_UPDATE=0` for check-only operation or
`ALLOY_NO_UPDATE_CHECK=1` to disable checks altogether. Respect these settings;
do not ask permission or run a manual installer to bypass them. `--check-only`
reports without installing; `--force` bypasses only the daily timer.

## Cursor login and containment

Use `AGENT_CLI_CREDENTIAL_STORE=file cursor-agent login` for requested Cursor
setup. Cursor children use the 0600 file store at `~/.cursor/auth.json` rather
than the keychain. Alloy's sandbox permits bounded credential refresh and a
private runtime; read-only roles have a narrow executable allow-list. See
`docs/execution.md` (Cursor roles) for grants and supported CLI versions.
Do not change login storage automatically to make a blocked run proceed.
