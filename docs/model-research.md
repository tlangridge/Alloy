# Model evidence — October 13, 2026

Alloy optimizes for work quality and fewer revisions. Model cards provide
conservative task priors, not probabilities of finishing a local task. Tool
access, model availability, family independence, pins, billing and quota reserves
are checked separately. The objective is `quality_first` for new setups; older
configurations require explicit migration.

## Current frontier profiles

| Model and harness | Useful prior | Important limit |
| --- | --- | --- |
| GPT-6.1 Sol in Codex | Implementation, debugging, software architecture, orchestration | API image tools do not prove image generation in a CLI session. Medium Maker and high review are defaults, not universal optima. |
| Claude Opus 5.5 | Software design, debugging, UI design, independent review | Published results use several efforts and harnesses. The xhigh profile is an option for difficult work, not an automatic override of pins. |
| Claude Sonnet 5.5 | Implementation, debugging and routine verification | A distinct model identity with separate evidence; preserve existing Sonnet profiles. |
| Gemini 4 Argon in AGY | Complex coding, reasoning, orchestration and multimodal understanding | The documented efforts are low, medium and high. Output is text; no native image generation. API context limits do not establish AGY limits. |
| Meta Muse Wonder Full in Muse Code | Software engineering, reasoning, UI design and cross-family review | Full subscription access differs from Wonder API access. Published max-effort scores do not establish xhigh performance. Managed writes remain uncertified. |
| GPT-6 Astra in Codex | Difficult reasoning, scientific and terminal workflows | An available specialist candidate, not a universal winner. |

The profile catalog also retains older configured models. Refresh adds missing
profiles without renaming old IDs, enabling disabled profiles, removing pins or
changing billing. A current authoritative account listing can rule out an
unavailable ID; stale or advisory discovery cannot.

Primary sources:

- [GPT-6.1 Sol specification](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [Claude Opus 5.5 model and evaluation methodology](https://www.anthropic.com/claude-opus-5-5)
- [Claude Sonnet 5.5 model](https://www.anthropic.com/claude-sonnet-5-5)
- [Gemini 4 Argon specification](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon)
- [Argon in Antigravity](https://www.antigravity.google/blog/gemini-4-argon-in-google-antigravity)
- [AGY headless protocol](https://www.antigravity.google/docs/cli/headless/)
- [Muse Wonder release](https://research.meta.ai/blog/muse-wonder)
- [Muse Wonder model card](https://research.meta.ai/static/muse-wonder-model-card)
- [Agent scaling research](https://arxiv.org/abs/2601.07206)
- [TypeSafe API](https://docs.typesafe.ai/api)

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
