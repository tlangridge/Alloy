# Model evidence and routing — refreshed 2026-09-22; measured 2026-09-25

## Measured on alloy-bench (2026-09-25)

Unlike the vendor evidence below, these are local measurements of Alloy's own
roles (execute Maker, execute Checker, read-only consult) on 48 original tasks
with hidden tests, through each CLI's real Alloy invocation. Small samples (4–12
tasks per cell): use them to rank, not as precise rates. Full tables: `bench/RESULTS.md`.

- **Makers:** gpt-5.6-sol solved every coding task (24/24 across splits) at ~$0.5/task
  list price; Gemini 3.8 Flash High 11/12 dev and 12/12 holdout at ~$0.3–0.4; Luna
  10/12 at ~$0.02; Flash Low perfect on small tasks but slow and costly on large ones;
  Grok 4.7 reasons heavily at default effort (20-minute timeouts on 7/8 harder tasks).
- **Checkers:** Luna (5/6, 5/6) and Gemini Flash Low (6/6, 5/6) found seeded bugs as
  reliably as large models at 1–5% of their cost; the starter profiles review at
  every tier (`tier_by_mode`).
- **Consult:** Gemini 3.1 Pro 6/6; routed consults are floored at medium tier because
  the classifier cannot see the repository a question is about.
- **Availability:** Codex with ChatGPT sign-in rejects gpt-6-sol; the profile ships disabled.

## What the evidence supports

These are editorial routing priors, not measured probabilities that a model will
finish an Alloy task. Public evaluations use different harnesses, tool budgets,
reasoning efforts and benchmark versions. API token prices are not subscription
quota costs, and cheaper tokens do not guarantee a cheaper completed task.

| Model | Useful strengths | Limits and routing interpretation |
| --- | --- | --- |
| GPT-5.6 Luna | Cost-sensitive bounded tasks | Keep the small-task tier; explicit tests and documentation are reasonable uses. Less difficult reasoning/security capability than Sol. |
| GPT-5.6 Terra | Routine implementation and verification | Medium-tier balance; avoid assuming Sol-level capability on difficult investigations. |
| GPT-5.6 Sol | Complex debugging, technical reasoning, research | The previous medium starter tier was too restrictive: new starter profiles classify Sol as large. Still not a universal best choice. |
| GPT-6 Astra | Difficult terminal/scientific workflows and complex reasoning | Strong candidate for hard work. High API token price and effort selection require attention; it is not automatically cheapest or best on every task. |
| Claude Sonnet 5 | Efficient multi-step coding and debugging | Medium default; lower cybersecurity capability than Opus. Its tokenizer can increase token counts versus the predecessor. |
| Claude Opus 5 | Broad software engineering and knowledge work | Legacy profile retained; Opus 5.5 is the new large starter. |
| Claude Fable 5.1 | Difficult debugging, scientific agents and application building | Large default. Respect the distinct Fable subscription pool. Published success does not establish local CLI performance. |
| Grok 4.6 | Application building and knowledge work | Keep large capability, but do not give debugging/review a specialty preference based on a composite intelligence score alone. |
| Gemini 3.6 Flash high | Efficient implementation and multimodal/UI work | Medium default; older generation. Preserve existing profiles rather than silently changing model IDs. |
| Gemini 3.8 Flash high | Improved long-horizon engineering and multi-step reasoning | A large-tier candidate to evaluate, not an automatic upgrade. Availability, the agy harness and effort variants must be checked. |

Sources and interpretation:

- [OpenAI GPT-5.6 announcement](https://openai.com/index/gpt-5-6/)
  compares the three sizes. The task preferences above are our conservative
  interpretation; they are not per-task success rates from the publisher.
- [OpenAI Astra announcement](https://openai.com/index/gpt-6-astra/) and
  [model specification](https://developers.openai.com/api/docs/models/gpt-6-astra)
  support complex-work positioning. The documented $10/$50 input/output per
  million tokens is API pricing, not a conversion for Codex subscriptions.
- [Anthropic Sonnet 5](https://www.anthropic.com/news/claude-sonnet-5),
  [Opus 5](https://www.anthropic.com/news/claude-opus-5), and
  [Fable 5.1](https://www.anthropic.com/claude-fable-and-mythos-5-1)
  describe different cost/capability positions. Fable's reported Terminal-Bench
  4.0 result is 55.8% versus Opus 5's 52.3% in that table; these are not Alloy
  measurements or directly comparable to Terminal-Bench 3.0.
- [xAI Grok 4.6](https://x.ai/news/grok-4-6) reports CursorBench 3.2 at
  69.9% versus Sol's 67.2%, but Terminal-Bench 3.0 at 26% versus 34.6%.
  This is the concrete reason not to collapse its strengths into one ranking.
- [Google Gemini 3.6](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-6-flash-3-5-flash-lite-3-5-flash-cyber/)
  emphasizes token efficiency;
  [Gemini 3.8](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/)
  emphasizes stronger long-horizon coding at its introductory API price.
- [Artificial Analysis comparison](https://artificialanalysis.ai/models/comparisons/gpt-6-astra-high-vs-grok-4-6)
  independently illustrates mixed results across terminal tasks and knowledge
  work, and why task cost is not proportional to token price. Index revisions
  make historic aggregate scores unsuitable as permanent config constants.
- [TypeSafe confidence](https://docs.typesafe.ai/confidence) and
  [intent routing](https://docs.typesafe.ai/patterns/intent-routing) support
  separating the semantic judgment from deterministic policy. Confidence measures
  distribution concentration, not the probability of downstream success.

## How the evidence changes Alloy

Jev rubric 2 distinguishes implementation, debugging, review, research,
architecture, frontend, testing, documentation and other. Its four judgments still
run in one request. Complexity/risk/ambiguity gates remain unchanged. Explicit
review mode overrides task-kind classification for specialty ranking.

After filtering by tier, CLI availability, model pins, family independence, quota
reserves and budget, Alloy finds the cheapest eligible option. Small tasks retain
that choice. For medium/large work, a model with a documented task preference may
win within a configurable 25% cost tolerance. The tolerance is a policy assumption,
not an empirically optimal threshold. Low kind confidence (below .65) disables
specialty preference rather than trusting an uncertain label.

If every eligible profile is metered and has configured prices, costs are compared
in estimated dollars. Otherwise the existing quota-adjusted relative ranks apply.
The tolerance is in the selected cost basis, not always dollars. Recommendations
include the cost basis, cheapest eligible alternative, top three eligible profiles,
sources, caveats, evidence revision and content hash. A zero-cost configured option
has a zero tolerance band; the router never divides by a zero rank.

`data/model-evidence.json` contains exact model IDs and dated priors. Unknown models
and floating aliases such as `sonnet` and `opus` do not inherit a newer model's
benchmarks. `applicable_efforts` is an editorial applicability range, not a claim
that every listed effort was benchmarked. Unverified efforts receive no specialty
preference. Evidence expires on 2026-12-16; stale/unavailable evidence falls back to
cost-only selection. The router does not scrape or self-update the catalog.

`alloy models advise` is a read-only report of evidence matches, suggested tiers,
blocked model pins and unconfigured candidates. It does not enable discovered
models or change the user's billing/model/effort choices. A user can set
`--task-preferences debugging,review` for a measured custom profile; those explicit
preferences override bundled evidence and are labelled user-configured.

## Validation and remaining uncertainty

Automated policy tests isolate specialty selection, bounded cost premiums, unknown
models/efforts, stale evidence, overrides, quota/budget preservation, comparable
metered prices and read-only advice. Existing Maker/Checker and quota tests continue
to run. Synthetic Jev evaluations check classification only; they do not measure
real coding success, dollars saved, or subscription quota consumed.

Next calibration should compare completed tasks under the same CLI harness,
repository, effort and test gate, retaining failures and retries in total cost.
No such downstream benchmark is claimed by this change. Published evidence alone
cannot justify removing user pins, assigning dollar costs to subscriptions, or
inventing fine-grained success percentages.

Validation on 2026-09-17: all 145 unit tests and skill validation passed. Live
Jev rubric v2 accepted 50/50 existing complexity cases and classified 16/16 held-out
task-category cases correctly. The two runs used 47,948 reported input tokens;
no downstream model execution was included. These small synthetic sets are
regression checks, not a calibrated accuracy estimate on real workloads.

## September 22 refresh: Opus 5.5, Sol and current prices

Opus 5.5 medium becomes the Claude large starter (`claude-opus-5-5`). Its
relative cost rank is 3 instead of 4: a conservative, editable efficiency prior,
not a measured subscription multiplier. Existing configurations are not migrated.
Sol stays large at rank 2.5; pins and independent model-family checks still win.
Grok's default becomes 4.7; explicit older model pins remain valid.

Anthropic reports FrontierCode 54.6% and CursorBench 52.5% for Opus 5.5 medium.
Its headline TerminalBench 66.4% uses xhigh, versus Astra high at 57.9%; most
other headline results use max. Astra remains ahead on reported science
(64.6% vs 58.7%) and automation (41.4% vs 40.0%). These vendor comparisons
have different efforts and harnesses, and some Claude evaluations use fallback
models. They justify a coding preference, not a universal winner or a local
success probability. [Launch methodology](https://www.anthropic.com/claude-opus-5-5).

Standard direct API USD per million tokens, checked September 22:

| Model | Input | Cached input | Output | Source |
| --- | ---: | ---: | ---: | --- |
| GPT-5.6 Luna | 0.20 | 0.02 | 1.20 | [OpenAI](https://developers.openai.com/api/docs/models/gpt-5.6-luna) |
| GPT-5.6 Terra | 2 | 0.20 | 12 | [OpenAI](https://developers.openai.com/api/docs/models/gpt-5.6-terra) |
| GPT-5.6 Sol | 4 | 0.40 | 20 | [OpenAI](https://developers.openai.com/api/docs/models/gpt-5.6-sol) |
| GPT-6 Astra | 10 | 1 | 50 | [OpenAI](https://developers.openai.com/api/docs/pricing) |
| Claude Sonnet 5 | 2 | 0.20 | 10 | [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) |
| Claude Opus 5.5 | 4 | 0.20 | 20 | [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) |
| Claude Fable 5.1 | 10 | 0.25 | 50 | [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) |
| Grok 4.7 | 2 | not recorded | 6 | [xAI](https://x.ai/api) |
| Gemini 3.8 Flash | 0.75 | 0.075 | 3.75 | [Google](https://ai.google.dev/gemini-api/docs/pricing) |

Sol's promotional rate lasts at least through November 21; Gemini's through
December 31 (then 1.50/0.15/7.50). OpenAI long-context rates differ above 272K
input tokens. Cache writes/storage, tools and fast/batch tiers are extra or
separately priced. Gemini API prices do not establish agy subscription costs.
New GPT-6 Sol/Luna prices are listed by OpenAI too; they are distinct models,
not aliases for the requested GPT-5.6 profiles, so this refresh does not silently
swap them in.

`models advise` exposes dated `api_pricing` for matched models. It does not
populate billing mode, rewrite configured prices or assume an OpenRouter or
subscription rate equals direct API pricing. Confirm actual billing and copy
applicable rates into metered profiles only. Jev classifies the task; code does
cost arithmetic and applies quota headroom, evidence and independent-family
constraints. No extra Jev request or price scraping is needed on each prompt.


## GPT-6 Sol and Gemini profile additions

GPT-6 Sol is now an explicit large-tier starter at relative rank 2, alongside
retained GPT-5.6 Sol. The [official model page](https://developers.openai.com/api/docs/models/gpt-6-sol)
positions it for complex coding and agents, with standard API prices of $2 input,
$0.20 cached input and $10 output per million tokens. These are not subscription
multipliers. Its task preferences remain conservative priors, not local benchmarks.

Starter profiles also include Gemini 3.8 Flash low/medium/high and Gemini 3.1 Pro
low/high. All five IDs were listed by `agy models` on September 22. Capability
tiers and relative costs are editable assumptions; lower-effort variants do not
inherit high-effort benchmark evidence. Actual access is checked at dispatch.
Existing installations need explicit profile updates; setup does not overwrite
user configuration or remove model pins automatically.
