# Host or Jev routing

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

## Use Jev through OpenRouter

You can use an OpenRouter key instead of a direct TypeSafe key:

```sh
alloy setup --jev-provider openrouter --non-interactive --skip-live-test
```

Save just your key in `~/.config/alloy/openrouter-key` with permissions `600`,
or set `OPENROUTER_API_KEY`. Environment credentials take precedence. The same
routing-directory overrides apply. Keys are never forwarded to coding CLIs.
This selects `jev_provider: "openrouter"` in `routing.json`, using
`openrouter_model: "~typesafe/jev-latest"` by default. Set `openrouter_model`
explicitly to pin another supported Jev version. Existing profiles, billing
settings, and the direct TypeSafe `jev_model` pin are preserved.

Alloy sends its task state and typed questions to OpenRouter's
[Decisions endpoint](https://openrouter.ai/openapi.json)
(`https://openrouter.ai/api/alpha/decisions`), not chat completions. OpenRouter
bills the Jev routing call; your coding CLIs still use their existing billing
modes. The endpoint is alpha. Alloy requires complete confidence/probability
answers and fails closed if the service response is incompatible. It never
falls back to a different service or credential. Decision history records
`jev_provider`, the returned model, latency and token usage (including cost
when supplied by OpenRouter).

Switch back with `alloy setup --jev-provider typesafe --non-interactive
--skip-live-test` (on one line). Your saved direct key remains available.
Without an explicit provider setting, existing installations use TypeSafe.

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
an existing interactive session. Managed `alloy execute --route` delegates edits,
tests and correction to provider CLIs in an owned worktree; the host judges and
integrates. See [managed execution](execution.md).

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

Profiles carry a capability tier and a relative `cost_rank`. The resolver uses fresh quota-pressure adjustments, then permits a bounded
cost premium for documented task fit (see below). When all eligible profiles
have metered prices, estimated dollars replace relative ranks. Exhausted or reserved live quota is excluded first. Starter ranks and tiers are editable
priors, not benchmark claims. Billing is subscription, metered or unknown;
unknown does not mean free. [Live subscription meters](usage.md) supply Codex,
Claude, Grok and Antigravity availability when their local quota sources are available.

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

## Evidence-informed task recommendations

See [model research](model-research.md) for strengths, limitations and sources.
`alloy models advise` reports known model evidence, pinned alternatives and newer
candidates without modifying configuration. Route JSON now includes the top three
eligible recommendations and the selection cost basis.

The router uses Jev's task kind to favor documented strengths within 25% of the
cheapest eligible cost for medium/large tasks. Small tasks stay cost-first. Prices
are directly compared only when all eligible profiles are metered with known
prices; mixed billing retains configured relative ranks and quota pressure.

Optional `routing.json` policy fields:

```json
{"use_model_evidence": true, "task_fit_cost_slack": 0.25, "kind_confidence_floor": 0.65}
```

`quota_pacing` (default `false`) prices subscription capacity by pace instead of
by remaining fraction alone: pressure = (share of the window still to run) /
(share of quota left), worst window wins. Capacity that will reset unused
becomes cheap (a Codex window with 20% left and 9% of the week to run scores
0.47 instead of 5.0); a window running short becomes dear. The host's own CLI
keeps the conservative remaining-fraction rule, because the host session draws
on the same subscription. Reserves still exclude a pool outright. Pacing
assumes steady use; enable it if your own usage is not front-loaded.

A profile's `tier` is its capability for every mode unless `tier_by_mode`
overrides it for one mode. The starter Luna and Gemini Flash Low profiles are
small-tier Makers with `{"review": "large"}`: on alloy-bench they found seeded
bugs as reliably as large models (Luna 5/6, Flash Low 6/6) at 1–5% of the
cost, while as Makers they fell behind on medium and large changes.
The starter `gpt-6-sol` profile ships disabled: Codex with ChatGPT-account
sign-in rejects that model. Enable it (`alloy models enable --id
codex-large-gpt-6-sol`) only with API-key billing.

`min_tier_by_mode` sets a minimum tier per mode. The shipped default is
`{"consult": "medium"}`: a panel question's difficulty lives in the repository,
which the classifier never sees. On alloy-bench, Jev rated such questions "small"
and the router's cheapest model answered a third of them wrongly; the floor
raised routed consult accuracy from 0.67 to 0.83 at lower cost per correct answer.

Set `use_model_evidence` to false for cost-only ranking. Exact model/effort matching
and catalog expiry prevent old research from silently applying to new models.
Existing profile tiers stay authoritative; `models advise` suggests adjustments.
For custom models, `alloy models add --id PROFILE --task-preferences debugging,review`
updates preferences; an empty string clears them. These are user priors, not
measured success rates. Metadata never overrides hard eligibility constraints.

## Recurring failures

Pass observed bug symptoms and confirmed failing gates in the task prompt, plus
`--prior-failures N` for verified quality failures on this task. Jev sees the count;
policy requires at least medium after one failure and large after two. Repeat
`--failed-profile ID` to exclude known failed profiles for a deliberately restarted
attempt. Unknown IDs and exclusions without a failure count are rejected before
inference. Exclusions apply to reserved Checkers too; pins and budgets still hold.
These observations are stored with each routing decision, not inferred from CLI
exit codes or treated as permanent model-wide penalties. Auth/outage failures do
not count. Execute retains the same Maker, independent adversarial Checker and
two-fix-loop limit. A restart needs its own authorization; no automatic rerouting.

Token efficiency remains an estimate: metered selection uses configured token
budgets and prices, while subscription selection uses quota pressure and relative
cost ranks. Actual provider-specific tokens per successful fix are not yet
learned from outcomes, and no calibrated expected-success probability is claimed.


## Model context sent to Jev (rubric 3)

The same request now includes up to 32 enabled, CLI-ready, model-pin-compatible
candidate cards: exact model/family/effort, configured tier, billing mode,
relative cost rank, configured token estimates and estimated API spend, fresh
quota headroom and snapshot time, shared quota pool, evidence status/sources,
strengths/limitations, and verified failures on this task. Fields are allowlisted;
credentials, CLI diagnostic text and arbitrary configuration are never copied.
Profiles beyond the card limit remain eligible through deterministic policy.

One independent Noul question per card assesses supported task fit. This adds
questions and input tokens but no second network round trip. These are advisory
judgments, not measured task success probabilities. Fits at or above .75 promote
task preference; at or below .25 remove it; intermediate or absent answers retain
the dated prior. Thresholds require offline/live evaluation on representative
work before any claim of improved accuracy. Malformed probabilities fail closed.
Only matched effort-specific evidence or explicit user task preferences can
influence fit. Stale/unmatched evidence cannot gain credibility from Jev's answer.
Small tasks and `use_model_evidence=false` retain cost-based ranking. In the latter
case no model-fit questions are requested. All hard filters and the existing
cost-tolerance ceiling remain enforced in code, as does independent review.

Decision history records the model cards and selected fit judgment for audit.
Measured success rate, tokens per successful fix and latency are explicitly null:
Alloy does not yet have enough verified, model/effort/task-specific outcome data
to estimate them. Known failures are task-specific, not global penalties.
No paid inference was used to validate this change; tests use a fake transport.

## Shipped configuration upgrades

`data/routing-defaults.json` is the public source for new-install profiles and
policy. It contains no credentials or account-specific billing. Each user supplies
their own TypeSafe or OpenRouter key as described above. Model evidence ships
separately in `data/model-evidence.json`; both files update with Alloy releases.

For existing installations, run:

```sh
alloy setup --refresh-defaults --non-interactive --skip-live-test
```

This backs up the private config and adds missing adapter/model pairs. Existing
profiles, disabled models, effort settings, pins, provider selection and policy
remain unchanged. New profiles inherit subscription billing only when that CLI's
existing profiles all agree on it; metered or mixed billing requires explicit
configuration. No key is created and no model inference occurs. Repeating the
command is idempotent. `models advise` reports any model-pin conflicts afterward.


## Keyless host routing

Jev is an optional acceleration layer. `alloy setup --keyless` skips both the
credential prompt and synthetic inference test, even without `--skip-live-test`.
It preserves existing credentials and provider selection. Add `--non-interactive`
for unattended setup; explicit `--billing` settings are still accepted.

`alloy models context` returns safe model cards and public quota information for
the host, with no Jev inference or credential access. The host reads the bundled
model evidence, assesses the task and chooses explicit profiles. Execute accepts
`--maker-profile`, `--checker-profile`, `--task-tier`, `--task-kind`, `--task-risk`
and `--task-ambiguous` without `--route`. Risk/ambiguity require large-tier workers;
explicit tiers apply to Maker and Checker. Host-provided confidence records an
explicit assessment, not a measured probability. Old manual callers retain the
small default; the skill requires an explicit tier.

Host decisions remain subject to live eligibility, quotas, budget limits, model
pins and three-family review. Keyless does not mean free provider execution or
unauthenticated CLIs. No paid fallback runs automatically if Jev fails: the host
reports the failure and chooses explicit profiles. Jev-enabled routing remains
available through `--route` with the user's own key.
