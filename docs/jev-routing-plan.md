# Jev routing research and implementation plan

Researched 2026-09-17. Initial implementation and live checks are complete;
see [the implementation guide](routing.md) and [validation results](routing-validation.md)
for shipped behavior and remaining limitations. This document records the design;
future-facing items below are not all automatic in the initial implementation. The user wants mixed cost optimization:
metered API spend and subscription quota consumption, tracked separately.

## What we verified

Jev is TypeSafe's decision model. It evaluates supplied state using typed
questions; it does not write code or generate explanations. Its direct HTTP API
is `POST https://api.typesafe.ai/v1/systemone`, authenticated with a bearer key.
Requests contain `model`, `state`, and `questions`. Supported questions are
`choice` (categorical), `score` (ordered rubric), and `noul` (yes/no probability).
Responses contain `answers` and token `usage`. See the
[API reference](https://docs.typesafe.ai/api).

The current version is `jev-1.13.0`; `jev-latest` currently resolves to it. Pin
the version for evaluation reproducibility. Published pricing is $0.042 per
million input tokens, with free output tokens. A 2,000-input-token routing call
would therefore cost $0.000084; 10,000 such calls would cost $0.84. Actual input
usage includes the questions, so measure the returned usage. Published limits
are 250,000 tokens/second and 1,200 requests/minute, explicitly subject to change.
See [models and pricing](https://docs.typesafe.ai/models).

Official SDKs exist for [Python](https://docs.typesafe.ai/sdk/python) and
[JavaScript](https://docs.typesafe.ai/sdk/javascript). Their standard key variable
is `TYPESAFE_API_KEY`. Python SDK requirements are newer than Alloy's documented
Python 3.8 baseline; a small stdlib HTTP client would preserve Alloy's dependency
and runtime policy.

TypeSafe recommends narrow, independent questions in one request, with ordinary
code combining the answers and controlling side effects. Same-request answers
do not feed into one another. This supports a classifier followed by a local
policy resolver. See [development guidance](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
and the official [intent-routing example](https://docs.typesafe.ai/patterns/intent-routing).

Confidence summarizes an answer distribution; it is not the measured likelihood
that a downstream coding model will complete a task. Structured outputs also do
not guarantee correct judgments. Tune thresholds on our tasks rather than
copying documentation thresholds. See [confidence](https://docs.typesafe.ai/confidence)
and the [AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer).

## Local integration context

`bin/alloy` is a standard-library Python dispatcher. Existing adapters supply
model arguments, readiness checks, read-only execution, timeouts and manifests.
The default panel uses every ready, nonexperimental read-only adapter. Model
overrides exist, but there is no semantic router or billing registry. `estimate`
counts model calls, not dollars or subscription consumption.

The local `doctor --json` check reports these adapters ready:

| Adapter | Currently configured model | Initial routing eligibility |
| --- | --- | --- |
| Codex | `gpt-5.6-sol` | Yes; add verified model/effort profiles |
| Grok | `grok-4.6` | Yes |
| Claude | CLI default, not pinned | Yes; resolve explicit profiles |
| Antigravity (`agy`) | `gemini-3.6-flash-high` | Yes |
| OpenCode / Cursor | CLI defaults | Exclude initially: experimental, no read-only enforcement |

Readiness is an auth/config heuristic, not proof every model is accessible.
Google routing uses Antigravity (`agy`), as specified by the user; a standalone
Gemini CLI adapter is out of scope. The model ID above is the configured model
identifier, not the CLI name. Use the Google family for family-separation rules.
Subscription quota pools must be configured separately from model family: two
CLIs may share a quota, or use different subscriptions.

`SKILL.md` currently selects the execute Maker with a fixed host-family table.
It requires another family for the Maker and an independent Checker. The new
resolver must encode those constraints, preserve explicit modes and model
overrides, and keep the host responsible for applying diffs and running tests.

## Proposed behavior

One portable Alloy entry point can be called from any host CLI. It selects the
model for a new task or subtask; it does not transparently replace the model in
an already running interactive session.

1. Collect the task, explicit mode/role, host family, bounded scope information,
   required capabilities, and candidate availability.
2. Ask Jev independent questions about task kind, complexity, ambiguity, and
   risk. Keep question definitions versioned and reviewable. Send only the
   task and necessary context; attached source text is explicit.
3. Apply deterministic eligibility rules: installed/authenticated adapter,
   supported model and effort, required tools, family separation, quota pool,
   budget, explicit overrides, and cooldowns.
4. Choose the least costly eligible profile that meets the required capability
   tier. Unknown complexity or low confidence falls back to the configured
   stronger profile or host, within budget. Do not silently substitute a weaker
   model when the required tier is unaffordable.
5. Dispatch through existing adapters, record the decision and outcome, and
   escalate only on useful evidence such as failed validation or an unavailable
   model. Retrying a timeout and changing models are distinct policies.

Illustrative tiers, pending actual model access and success measurements:

| Task | Starting policy |
| --- | --- |
| Localized, well-specified edit or extraction | Cheap qualified profile, such as Luna or Flash |
| Multi-file feature or ordinary debugging | Balanced qualified profile |
| Architecture, difficult concurrency, security-sensitive change | Strong qualified profile and independent review where required |
| Ambiguous request or insufficient context | Gather context or retain host handling |

These are hypotheses to evaluate, not claims about model performance. An
execute Maker may be excluded even if cheapest because it shares the host family.

## Adapting to new models and CLI releases

This is a core requirement. Model IDs must be data, not branches in routing
code or a fixed list embedded in Jev's questions. Jev assesses task requirements;
the local resolver matches those requirements to the current eligible catalog.

Keep three independently versioned components:

- Task rubric and routing policy: capability requirements, risk rules, cost
  preferences and escalation behavior.
- Model catalog: model IDs, aliases, provider family, supported efforts,
  capabilities, billing metadata, evidence sources and verification timestamps.
  Separate discovered availability from configured or measured capability.
- CLI adapters: argument construction, discovery, authentication checks,
  permission enforcement, output parsing and usage extraction. Adding a model
  supported by an existing adapter should normally require only catalog data;
  a new CLI or incompatible CLI release may require adapter code.

Proposed commands (not implemented yet):

```text
alloy models refresh       # discover available models where supported
alloy models list          # show availability, verification and metadata age
alloy doctor               # check installed versions and adapter compatibility
alloy route --prompt-file task.txt
```

Discovery uses documented, bounded model-list operations when a CLI/provider
offers them. Otherwise accept user-defined profiles; there is no assumption of
a universal model-list endpoint. Refreshes merge discovery with user overrides
without replacing billing settings, explicit pins or exclusions. Refreshing
does not upgrade CLI binaries or launch billable model probes. Cache discovery
with a configurable expiry and keep a last-known-good snapshot for outages.
On normal routing, check installed CLI versions locally and invalidate affected
capability checks when a version changes.

Newly discovered models appear immediately as candidates for configuration or
evaluation. Discovery alone does not establish their quality, cost, tool support
or account access. Automatic eligibility requires sufficient metadata and
compatibility under the user's policy; allow explicit profiles to supply that
metadata without a router release. Unknown prices remain unknown. Aliases may
move, so store both requested and resolved IDs when the provider reports them,
and preserve explicit model pins.

Verify adapter behavior using version information and bounded help/capability
probes plus fixture tests from supported releases. Do not infer safe execution
from version numbers alone. Changes to read-only permissions or ambiguous CLI
behavior make the affected adapter ineligible until verified; never compensate
with permission-bypass flags. Optional usage fields may degrade to unknown,
while invalid result formats must be reported rather than treated as success.

If a model disappears or an invocation reports an unsupported model/effort,
invalidate that profile, perform at most one relevant refresh, and resolve an
eligible fallback within the original budget and family constraints. Restrict
automatic redispatch to failures known to precede execution; otherwise preserve
the session/result for recovery to avoid duplicate work. Record catalog,
rubric and adapter versions with each decision so regressions can be reproduced.

Add tests for model addition/removal, alias changes, expired/offline catalogs,
preservation of overrides, CLI version changes, unsupported flags, changed
output formats and permissions, and bounded fallback. Use recorded fixtures and
mock CLIs so compatibility checks do not require paid inference.

## Mixed billing policy

Maintain a user-level profile registry with `adapter`, `model`, `effort`,
`family`, `capabilities`, `billing_mode`, `quota_pool`, `cost_rank`, and optional
dated input/output/cache prices. Billing mode is explicitly configured as
`subscription`, `metered`, or `unknown`; credential presence cannot establish it.

For metered calls, estimate dollars using observed usage for similar tasks and
configured prices; track actual provider-reported usage when available. For
subscriptions, use documented quota information where accessible, configurable
reserves, and relative consumption ranks. Missing quota data remains unknown.
Subscription usage is not free merely because its marginal invoice is zero.

Apply separate spend and quota constraints first, then configurable relative
preferences. Do not add raw dollars and quota percentages together. Account for
Jev calls, reviews, retries, and escalation when measuring total task cost.
Budget estimates cannot become hard dollar guarantees unless the target CLI
supports enforceable limits.

## Installation and first-run setup

Ease of installation is a core requirement. Extend the existing installer and
add `alloy setup`; users should not need to edit JSON, create symlinks manually,
or configure every supported model before their first routing decision. Keep
the stdlib runtime approach; no background service, database or Node dependency
is needed for routing.

The initial supported installation path remains the repository's `install.sh`.
Make it install the CLI into a user-owned executable directory as well as link
the skills into detected supported hosts. Use no sudo, preserve unrelated
files, and provide a precise PATH instruction only when necessary. Existing
skill-only installations must be able to run setup through `bin/alloy`. Do not
advertise a package-manager command until a tested package is actually published.

Proposed first-run flow:

1. Detect Codex, Claude, Grok and Antigravity (`agy`), their versions and auth
   status. Reuse existing CLI authentication. Missing CLIs are optional; one
   compatible CLI is enough for routing, with independent review unavailable
   when there are insufficient model families.
2. Accept the Jev key through a hidden prompt, or reuse `TYPESAFE_API_KEY` when
   present. Store a prompted key outside the repo in a dedicated user credential
   file with owner-only permissions and a private parent directory; never put
   it in command arguments, shell history or child CLI environments. Allow
   environment-only use without storing a copy.
3. Show a compact billing table for the detected CLIs. Ask only for missing
   billing modes: subscription, metered API or unknown. Provide editable starter
   model profiles and a default balanced policy that respects mixed billing;
   advanced prices, quota reserves and capability tuning are optional. Clearly
   mark unknown costs rather than claiming precise savings.
4. Discover models where supported and validate local compatibility. Show what
   is usable and a specific next action for each problem. Setup remains resumable
   if the key, network or provider authentication is unavailable.
5. Finish with a small synthetic Jev routing test and display the chosen CLI,
   model, effort and policy reason. State that this calls Jev but does not launch
   a downstream coding task. Offer a skip-live-test option for offline setup.

Target a working first route in a few minutes on a machine with an authenticated
supported CLI. Re-running setup preserves existing preferences and credentials.
Provide noninteractive setup for agents/CI using flags plus an environment key,
without hidden prompts. Updates must migrate versioned configuration atomically
and preserve a backup. Uninstallation removes Alloy-owned links/files only and
retains user configuration unless explicitly asked to remove it.

Test fresh install, missing Python, PATH not configured, existing installation,
conflicting files, one-CLI setup, no available CLI, offline setup, invalid key,
noninteractive setup, repeat setup and configuration migration in isolated
temporary homes. The quickstart must match the tested installation flow.

## Implementation and validation sequence

1. Add the installer improvements and guided `alloy setup` flow above alongside
   an opt-in `alloy route --prompt-file ...` command that emits a validated
   JSON decision without launching another model. Implement the Jev client,
   rubric, profile registry, resolver, and local decision log. Avoid global
   environment mutation when choosing per-dispatch model settings.
2. Use an injected fake transport and existing mock CLIs to test valid and
   malformed responses, missing keys, timeout, 401/422 errors, bounded 429/529
   backoff, confidence fallback, explicit overrides, unavailable models,
   shared quotas, budgets, and family constraints. Ensure the Jev credential
   is never logged or forwarded to child CLIs; existing generic environment
   inheritance requires an explicit exclusion.
3. With the key installed, run one minimal API smoke test, then a versioned
   dataset of roughly 50 synthetic tasks covering complexity, ambiguity,
   adversarial task instructions, and availability variations. Separate rubric
   tuning examples from held-out checks. Compare with a static tier baseline.
   Record classifications, probabilities, p50/p95 latency and actual token cost.
4. Connect opt-in routing to panel dispatch and the execute skill. Test the
   selected model/effort arguments and manifest entries with mock CLIs. Run
   existing regression checks and update README/SECURITY network disclosures.
5. Run a small bounded end-to-end comparison on disposable fixture repositories.
   Measure validated task success, total spend/quota indicators, latency,
   retries, and escalation. Retain manual selection as the baseline until
   routing demonstrates useful savings at acceptable success rates.

The API key can be supplied locally through `TYPESAFE_API_KEY` or a protected
user-level credential file; do not commit it. No key is needed for mock tests.

## User-supplied precedent

[AgentNative's X post](https://x.com/agentnative_/status/2100624941326500122)
was verified through the browser after direct retrieval returned HTTP 403.
It proposes building an Eve/Vercel AI Gateway agent that routes simple,
intermediate and complex tasks to different model tiers, with the selected
route prominently visible. The post itself provides no implementation
repository or routing benchmark. Its gateway-based architecture differs from
this project's use of authenticated local CLIs and their subscription pools.
The useful product idea to carry over is a visible, auditable routing decision.
Because Jev cannot generate prose explanations, Alloy should render its reason
from the returned rubric values and the policy rules that selected the profile.
