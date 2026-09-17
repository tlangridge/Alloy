# Jev routing

Alloy can ask Jev to assess a task, then choose a configured model through
Codex, Claude, Grok or Antigravity (`agy`). Routing is opt-in. Regular panels
retain their existing behavior.

## Install and setup

From your Alloy checkout:

```sh
./install.sh --setup
```

The installer links `alloy` into `~/.local/bin` and adds the skills to detected
hosts. It needs Python 3.8+, uses no sudo, and prints a PATH instruction if needed.
Restart your host session to discover the skill. For a custom location, set
`ALLOY_INSTALL_BIN_DIR` and optionally `SKILLS_DIR`. Re-run safely to update the
same checkout; conflicting files are preserved and reported.

Setup detects your CLIs, accepts a hidden Jev key, asks about billing and saves
editable starter profiles. It then makes one synthetic Jev-only test call.
Existing CLI logins are reused. You need only one compatible CLI for ordinary
routing; execute's independent Maker and Checker need additional families.

For agents or offline configuration:

```sh
alloy setup --non-interactive --skip-live-test \
  --billing codex=subscription --billing claude=subscription \
  --billing grok=unknown --billing antigravity=unknown
```

Use your actual billing modes. Supply `TYPESAFE_API_KEY` through your environment,
not an argv flag. Alternatively save only the key in `~/.config/alloy/jev-key`
with permissions `600`. Routing configuration lives in `routing.json` beside
it. `ALLOY_ROUTING_HOME` overrides this directory; otherwise XDG_CONFIG_HOME is
respected. No secret is stored in the repository or forwarded to child CLIs.

## Decide or execute

```sh
# JSON decision only; no coding model is invoked:
alloy route --prompt-file task.txt

# Choose one model and invoke it through the existing read-only dispatcher:
alloy panel --route --prompt-file task.txt

# Select an independent Maker; host family names are provider families:
alloy panel --route --mode make --host-family openai --prompt-file maker.txt

# A routed review must exclude the Maker's returned model family:
alloy panel --route --mode review --exclude-family xai --prompt-file review.txt
```

The JSON decision includes CLI, model, effort, model family, billing mode,
required tier, policy reason, rejected profiles, Jev probabilities, usage and
latency. A routed panel also records it in `manifest.json`. Prompt-free decision
history lives under the routing directory; ordinary panel artifacts still
contain the prompt. A route selects a new task; it does not switch the model in
an existing interactive session. The host still applies Maker diffs and tests.

`--panelists` restricts eligible adapters. Existing `ALLOY_*_MODEL` pins remain
binding: add a matching profile or remove a pin to let that CLI use alternatives.
Effort overrides are respected. `--profile ID` restricts the choice to a profile;
it does not override quality floors or other constraints. Missing keys, invalid
responses and lack of an eligible profile produce exit code 2 and no dispatch.
Low-confidence, ambiguous or high-risk tasks require a large-tier profile.

## Updating models

```sh
alloy models refresh
alloy models list

# Configure a new discovered model without editing code:
alloy models add --id agy-flash-new --cli antigravity \
  --model YOUR_MODEL_ID --family google --tier medium \
  --effort high --cost-rank 1 --billing-mode subscription

alloy models disable --id agy-flash-new
alloy models enable --id agy-flash-new
```

`models add` updates an existing ID when supplied again. For new profiles,
model family is explicit because Antigravity can expose other providers' models.
Model IDs are data, not routing code. `models refresh` lists models through Grok
and Antigravity; Codex and Claude use configured profiles because this integration
has no stable model-list command for them. Discovered IDs are not automatically
enabled or assigned capabilities. Catalog refresh preserves configured profiles.

Routing refreshes discovery after its configured TTL (default one day), or when
installed versions change. Failed discovery preserves previous observations and
reports errors. Every routing call probes CLI version/help and checks the
adapter's read-only eligibility. This detects missing invocation flags, but
cannot certify unchanged CLI permission semantics. Incompatible adapters are
excluded; substantial CLI changes can require adapter updates. Explicitly
configured model access is still best-effort until its first execution.

## Cost controls

Profiles carry a capability tier and a relative `cost_rank`. The resolver picks
the lowest rank after applying fresh quota-pressure adjustments among eligible
profiles. Exhausted or reserved live quota is excluded first. Starter ranks and tiers are editable
priors, not benchmark claims. Billing is subscription, metered or unknown;
unknown does not mean free. [Live subscription meters](usage.md) supply Codex,
Claude and Antigravity availability, with Grok reported as unknown.

For metered profiles, set `--input-per-million` and `--output-per-million` with
`models add`. Estimates use policy token assumptions (10,000 input and 2,000
output by default), not predictions of exact usage. You can filter selection:

```sh
alloy route --prompt-file task.txt --max-estimated-usd 0.10
```

This caps the **estimated downstream API cost** used for eligibility, not actual
provider billing or Jev charges. Unknown metered/unknown-billing profiles are
excluded when a ceiling is set. Subscription profiles instead use their quota
pool. Pools can be shared across profiles and set in `routing.json`:

```json
{"quota_pools": {"my-plan": {"remaining_fraction": 0.4, "reserve_fraction": 0.1}}}
```

Assign that pool with `models add --id PROFILE --quota-pool my-plan`. Missing
balances stay unknown; these manual pool values are separate from live provider
windows, which are refreshed automatically. Relative ranks
express how you trade off dollar spend and subscription use without adding
dollars to percentages. There is no automatic cross-model retry after execution:
failed or timed-out work is reported for host recovery, avoiding duplicate work.

## Verification and removal

```sh
python3 -m unittest discover -s tests -v
# Explicit paid Jev-only evaluation of 50 synthetic tasks:
python3 bin/evaluate-routing --output /tmp/jev-evaluation.json
./install.sh --uninstall
```

Uninstallation removes only this checkout's links. Credentials, configuration
and run history are retained. Setup/model edits save the preceding configuration
as `routing.json.bak`; unsupported schema versions fail without rewriting it.
