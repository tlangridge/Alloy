# Methodology: how Alloy maps to "Fusion beats Frontier"

Alloy is a local reimplementation of the panel-of-models idea OpenRouter
describes under the name **Fusion**. The core claim, from their write-up: *"synthesizing
the results of multiple models can significantly outperform what individual
models are capable of"* — and notably, a meaningful part of the lift comes from
the **synthesis step itself**, not just from having more models.

## The three roles

OpenRouter's hosted Fusion router has three roles. Alloy keeps the same shape
but realizes them with local tools:

| Fusion role | What it does | In Alloy |
|---|---|---|
| **Panel** (analysis models) | Up to 8 models answer the prompt **in parallel**, each with web search/fetch. | The local CLIs (`codex`, `gemini`, …), run in parallel, read-only, and web-search-enabled by `bin/alloy`. |
| **Judge** | Reads all panel answers and produces **structured analysis** — it *compares, it does not merge*: consensus, disagreements, partial coverage, unique insights, blind spots. | **Claude** (the host), producing `judge.json`. |
| **Calling / synthesis model** | Writes the final answer **grounded in the judge's analysis**. | **Claude**, in its synthesis step. |

The hosted router defaults to a 3-model panel (≈ Claude Opus + a GPT + Gemini
Pro) and reports roughly 4–5× the cost of a single completion for that default.
The practical advice that shaped Alloy's design:

- **Diversity over quantity.** Three models from different families beat five
  near-duplicates. Alloy's default panel (`codex` = a GPT family, `gemini` =
  Gemini family, judged/synthesized by Claude) is deliberately cross-family.
- **Use the strongest model as the synthesizer.** Alloy makes Claude — the host
  — the judge and synthesizer.
- **Fusion is for thinking, not for raw codegen.** Multi-model synthesis helps on
  research, planning, review, and high-stakes decisions; it *dilutes* line-by-line
  code generation. Alloy therefore uses the panel for the decision-heavy stages
  and leaves code writing to Claude.
- **"If the cost of being wrong exceeds the cost of querying multiple models, use
  Fusion."** That is the one-line decision rule for when to reach for `/alloy`.

**Web research, like Fusion.** Fusion enables `web_search`/`web_fetch` for every
panelist. Alloy matches this: codex runs with `tools.web_search=true` and gemini's
`google_web_search` is auto-accepted in plan mode, so the panel can pull in current
facts (e.g. "the latest release of X") instead of reasoning only from its training
data. It stays read-only — search is a hosted tool, not local shell — and
`ALLOY_WEB=0` turns it off (codex). This was the one place Alloy used to diverge
from Fusion; it no longer does.

## Why "compare, don't merge" matters

A naive multi-model wrapper averages answers and produces confident mush. The
value is the opposite: a panel is most useful when it **disagrees**, because the
disagreement is information. Alloy's judge step is required to attribute every
consensus claim to named panelists and to keep contradictions visible, so you see
"codex says X, gemini says not-X, here's who's right and why" rather than a
smoothed-over paragraph that hides the conflict.

## The Claude-as-judge bias (and the honest answer to "isn't this rigged?")

Claude is both the judge and the synthesizer here, and it is *not* a neutral
juror — an LLM judging a panel and then writing the final answer can favor its
own framing. Alloy handles this honestly rather than pretending the judge is
neutral:

1. **The judge output is written to disk** (`judge.json` in the run directory),
   so its reasoning is auditable, not hidden.
2. **Anti-sycophancy is a standing rule:** panelist *agreement is not proof of
   correctness* (shared training data → correlated errors). Thin-but-unanimous
   consensus must be flagged, not rubber-stamped.
3. **Disagreements are surfaced**, with attribution, so you can overrule Claude's
   read.
4. The honest framing Alloy always ends on: **cross-model agreement is a
   recommendation; you decide.**

A future `ALLOY_JUDGE=codex|gemini` override will let the independence-minded
rotate the judge role to a different model. It is intentionally *not* the default:
rotating the judge adds latency, another auth dependency, and the CLI judges are
weaker at structured comparison — and it is not truly independent anyway when all
models saw the same prompt. The mitigation that actually works is structural
discipline (the schema + attribution + anti-sycophancy rule above), not swapping
which model holds the gavel.

## What Alloy is not

- It is not local inference. Your prompts and diffs are sent to the providers
  behind each CLI.
- It is not an answer-merger. It is a disagreement surfacer.
- It is not a code-writing swarm. The panel is read-only; Claude writes.

## On debate rounds (and the "bully effect")

Alloy's optional `debate` round (a second pass where panelists critique each
other's *anonymized* answers) is gated deliberately, because the research on
multi-agent debate is mixed. It improves **objective** tasks — math, reasoning,
factuality, code-correctness — especially with a **diverse** panel. But it can
*lower* accuracy when a confident, persuasive-but-wrong agent pulls the others
into agreement (sycophancy / conformity); a single such agent has been measured
cutting group accuracy 10–40%. The mitigations Alloy uses — anonymizing answers,
weighting evidence over assertiveness, keeping the host judge as the arbiter,
triggering only on a genuine objective disagreement, and running a single round —
come straight from that literature. That is why debate is off by default and used
rarely.

## Sources

- OpenRouter, *Fusion beats Frontier* — https://openrouter.ai/blog/announcements/fusion-beats-frontier/
- OpenRouter docs, *Fusion router* — https://openrouter.ai/docs/guides/routing/routers/fusion-router
- Digital Applied, *OpenRouter Fusion: multi-model AI responses guide* —
  https://www.digitalapplied.com/blog/openrouter-fusion-multi-model-ai-responses-guide
- Du et al., *Improving Factuality and Reasoning in Language Models through Multiagent Debate* — https://arxiv.org/abs/2305.14325
- *Talk Isn't Always Cheap: Understanding Failure Modes in Multi-Agent Debate* — https://arxiv.org/abs/2509.05396
- *Measuring and Mitigating Identity Bias in Multi-Agent Debate via Anonymization* — https://arxiv.org/abs/2510.07517
