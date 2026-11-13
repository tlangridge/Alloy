# Model evidence — November 13, 2026

Alloy optimizes for work quality and fewer revisions. Model cards provide
conservative task priors, not probabilities of finishing a local task. Tool
access, model availability, family independence, pins, billing and quota reserves
are checked separately. The objective is `quality_first` for new setups; older
configurations require explicit migration.

## Maintenance findings

The November review checked official model specifications, CLI model guidance,
Agent Skills guidance and agent-workflow research before changing the skill.
The resulting changes are additive profiles, updated evidence, a shorter skill
entrypoint and linked mode runbooks. Existing IDs, efforts, disabled profiles,
model pins, billing and quota settings remain preserved by refresh.

Current OpenAI documentation and Codex model metadata support GPT-6 Luna and
GPT-6.1 Terra alongside Sol and Astra. Anthropic documents Haiku 5.5 in Claude
Code and Fable 5.2 for demanding work. Carbon became generally available on
November 10 and Hydrogen launched November 12. AGY 1.5.8 account discovery
confirmed Carbon low/medium/high, Hydrogen low/medium/high/xhigh and both
Orchestrator IDs. Account listings vary; Argon remains available on the inspected
account and its existing profiles are retained. New Carbon profiles require a
fresh authoritative listing. Orchestrator is a fixed mixed-model workflow, not
an adjustable Carbon effort tier or a certified managed Maker.

Meta's November 6 update describes specialized models for its Muse and Meta AI
products without supplying new Muse Code IDs in that announcement. Keep the
existing Wonder Full CLI profile rather than inventing identifiers. Cursor
still lists Composer 2.5, but its current plans use weekly native-model capacity
shared with Grok; legacy plans retain different pools. Check the actual plan,
effort restrictions and prepaid third-party billing before enabling profiles.
Alloy's manual Cursor pool names are compatibility labels, not a statement that
every account has two independent included allowances.

The [Agent Skills specification](https://agentskills.io/specification) and
[Codex skill guidance](https://learn.chatgpt.com/docs/build-skills) recommend a
compact entrypoint with references loaded as needed. Shared constraints remain
in SKILL.md; detailed routing, panel, usage and execute workflows are linked
there. Review targets must come from the intended base rather than a guessed
previous commit. Implementation stays within existing authorization, and extra
panel rounds need a specific evidence gap instead of a fixed ceremony.

## Current profiles

| Model and harness | Useful prior | Important limit |
| --- | --- | --- |
| GPT-6 Luna in Codex | Focused coding, tests and repeatable transformations | Small tier; no promotion to difficult independent reviews. Starter effort is high following Codex guidance, not the API's medium default. |
| GPT-6.1 Terra in Codex | Scoped coding, concise writing and image understanding | Medium tier; Codex CLI 0.159.0+ is documented. Vision still needs verified CLI attachment support. |
| Claude Haiku 5.5 | Bounded coding and short tool tasks | Small tier; start medium, consider high for verification. Low can skip checks in long prompts. Prompts above 100K have different API rates. |
| Claude Fable 5.2 (5.1 retained) | Demanding reasoning and long-running engineering | Disabled pending explicit account/billing opt-in. Noninteractive Claude Code can charge usage credits without prompting. High starter effort; no local outcome advantage is claimed. |
| GPT-6.1 Sol in Codex | Implementation, debugging, software architecture, orchestration | API image tools do not prove image generation in a CLI session. Medium Maker and high review are defaults, not universal optima. |
| Claude Opus 5.5 | Software design, debugging, UI design, independent review | Published results use several efforts and harnesses. The xhigh profile is an option for difficult work, not an automatic override of pins. |
| Claude Sonnet 5.5 | Implementation, debugging and routine verification | A distinct model identity with separate evidence; preserve existing Sonnet profiles. |
| Gemini 4 Carbon in AGY | Long-horizon coding, architecture and investigation | Plan-gated; new profiles require a fresh exact account listing. Low/medium/high only. |
| Gemini 4 Hydrogen in AGY | Everyday coding and fast execution | Medium-tier prior; xhigh does not establish large-review qualification. |
| Orchestrator in AGY | Carbon/Argon planning with Hydrogen execution | Fixed effort, disabled by default, no managed Maker contract. No single-model evidence transfer. |
| Gemini 4 Argon in AGY | Complex coding, reasoning, orchestration and multimodal understanding | The documented efforts are low, medium and high. Output is text; no native image generation. API context limits do not establish AGY limits. |
| Meta Muse Wonder Full in Muse Code | Software engineering, reasoning, UI design and cross-family review | Full subscription access differs from Wonder API access. Published max-effort scores do not establish xhigh performance. Managed writes remain uncertified. |
| GPT-6 Astra in Codex | Difficult reasoning, scientific and terminal workflows | An available specialist candidate, not a universal winner. |

The profile catalog also retains older configured models. Refresh adds missing
profiles without renaming old IDs, enabling disabled profiles, removing pins or
changing billing. A current authoritative account listing can rule out an
unavailable ID; stale or advisory discovery cannot.

Primary sources:

- [Codex model selection and CLI access](https://learn.chatgpt.com/docs/models)
- [GPT-6 Luna specification](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [GPT-6.1 Terra specification](https://developers.openai.com/api/docs/models/gpt-6.1-terra)
- [GPT-6.1 Sol specification](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [Claude Opus 5.5 model and evaluation methodology](https://www.anthropic.com/claude-opus-5-5)
- [Claude Sonnet 5.5 model](https://www.anthropic.com/claude-sonnet-5-5)
- [Haiku 5.5 specification and tiered API pricing](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
- [Claude model lineup, including Fable 5.1](https://platform.claude.com/docs/en/models/overview)
- [Claude Code model and effort settings](https://code.claude.com/docs/en/model-config)
- [Claude API effort guidance](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Gemini 4 Argon specification](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon)
- [Carbon availability and introductory pricing](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-carbon-now-available/)
- [Hydrogen model and pricing](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-hydrogen/)
- [AGY models and fixed Orchestrator workflow](https://antigravity.google/docs/models)
- [Fable 5.2 release](https://www.anthropic.com/claude-fable-and-mythos-5-2)
- [Grok models](https://docs.x.ai/developers/models)
- [Argon in Antigravity](https://www.antigravity.google/blog/gemini-4-argon-in-google-antigravity)
- [AGY headless protocol](https://www.antigravity.google/docs/cli/headless/)
- [Muse Wonder release](https://research.meta.ai/blog/muse-wonder)
- [Meta specialized-model rollout](https://research.meta.ai/blog/specialized-models-for-muse-and-metaai)
- [Muse Wonder model card](https://research.meta.ai/static/muse-wonder-model-card)
- [Cursor current models, plans and legacy differences](https://cursor.com/docs/models-and-pricing)
- [Agent scaling research](https://arxiv.org/abs/2512.08296)
- [LLM routing benchmark](https://arxiv.org/abs/2601.07206)
- [TypeSafe API](https://docs.typesafe.ai/api)

## API reference prices reviewed November 9

USD per million tokens, direct Standard text rates. These are evidence fields,
not automatic billing configuration or subscription consumption estimates.

| Model | Input | Output | Cached input | Context condition |
| --- | ---: | ---: | ---: | --- |
| GPT-6.1 Sol | 2.00 | 10.00 | 0.10 | Up to 272K prompt tokens |
| GPT-6.1 Terra | 1.00 | 5.00 | 0.05 | Up to 272K prompt tokens |
| GPT-6 Luna | 0.10 | 0.50 | 0.01 | Up to 272K prompt tokens |
| Claude Sonnet 5.5 | 2.00 | 10.00 | 0.10 | Standard text rates |
| Claude Haiku 5.5 | 0.10 | 0.50 | 0.01 | Up to 100K prompt tokens |
| Claude Haiku 5.5 | 0.50 | 2.50 | 0.05 | Above 100K prompt tokens |

OpenAI requests above 272K input tokens charge twice the input/cache rates and
1.5 times the output rate for the full request. Cache writes, tools, speed
modes, regional processing and other provider charges are additional. See the
exact model sources above before configuring metered prices. Older catalog
prices retain their earlier review dates; the catalog revision does not reverify
them or extend its existing expiry.

## API additions reviewed November 13

Fable 5.2 standard API text rates are $8 input, $40 output and $0.20 cached input
per million tokens; fast mode is $16/$80. Hydrogen is $1.50/$7.50 across its
documented 1M context. Carbon introductory rates are $2/$10 through November 30;
its catalog card conservatively records the subsequent $4/$20 list rates and
states the introductory exception. These are API references, not CLI bills.

Older row and price review dates remain unchanged. The catalog still expires on
December 16; this update does not extend unverified evidence. Doctor and routing
expose stale or near-expiry warnings. Tests use an isolated catalog clock so
expiry behavior is tested without making the whole suite depend on today's date.

## Policy interpretation

`data/model-evidence.json` matches the exact adapter, model, effort and fast
state. No native benchmark credit transfers to a different CLI harness. Its
preferences are editorial, categorical judgments. Jev's Noul questions can
adjust suitability conservatively; they do not predict downstream correctness.
Unknown measurements remain null. Evidence expires rather than silently
following future aliases.

Quality-first routing filters hard constraints, compares suitability, then
uses quota-adjusted ranks or comparable configured prices among equally
qualified candidates. It jointly selects Maker and Checker, considering the
weaker role first. Three distinct families remain required for managed execute.
Material acceptance ambiguity stops Maker dispatch. Repeated verified quality
failures raise the required tier; transport failures do not.

UI design, software architecture, orchestration, image understanding and image
generation are distinct task kinds. Vision input does not establish an image
output tool. A fresh exact model/effort/CLI capability attestation cannot grant
permissions or add an unsupported managed writer. Rendered artifacts require
real image bytes, bounded scoped access, an attachment mapping and a matching
review receipt. Textual descriptions cannot substitute for viewing the image.

## What is measured

Historical component results are documented in `bench/RESULTS.md`. The small
seeded-review sample does not justify large-tier qualification for a small
Checker. Prior combined execute estimates are component proxies, not complete
Maker/Checker/correction outcomes. Do not use them as success rates or promote
models from them.

`alloy outcomes` records prompt-free local process metadata: identities,
revision, gates, reviews, transport calls and corrections. A passed gate and
review do not prove independent correctness or user acceptance; those fields
remain null.

`bench/execute.py` provides a separate opt-in complete execute evaluation using
production selection and lifecycle controls. Hidden correctness tests run after
all workers stop and are never part of their context. Every worker attempt is
counted, including review transport retries. Worker API list-price equivalents remain
separate from subscription consumption. Router usage and latency are reported
separately; total API spend stays unknown when router consumption is unpriced. No new frontier outcome advantage is
claimed without a representative live run on the same fixtures and harness.

Future calibration should retain failures, retries, latency and token usage;
report sample sizes and uncertainty by role, task kind, effort and harness.
Process readiness, hidden-test correctness, integration and user acceptance
must remain separate. Independent review should target material failure modes;
extra agents and agreement alone are not evidence of correctness.
