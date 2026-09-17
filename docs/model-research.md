# Model evidence and routing — 2026-09-17

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
| Claude Opus 5 | Broad software engineering and knowledge work | Large default; newer Fable evidence is stronger on some difficult agent tasks. |
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
