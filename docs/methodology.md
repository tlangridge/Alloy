# Methodology: how alloy maps to "Fusion beats Frontier"

alloy is a local reimplementation of the panel-of-models idea OpenRouter
describes under the name **Fusion**. The core claim, from their write-up: *"synthesizing
the results of multiple models can significantly outperform what individual
models are capable of"* — and notably, a meaningful part of the lift comes from
the **synthesis step itself**, not just from having more models.

## The three roles

OpenRouter's hosted Fusion router has three roles. alloy keeps the same shape
but realizes them with local tools:

| Fusion role | What it does | In alloy |
|---|---|---|
| **Panel** (analysis models) | Up to 8 models answer the prompt **in parallel**. | The local CLIs (`codex`, `gemini`, …), run in parallel and read-only by `bin/alloy`. |
| **Judge** | Reads all panel answers and produces **structured analysis** — it *compares, it does not merge*: consensus, disagreements, partial coverage, unique insights, blind spots. | **Claude** (the host), producing `judge.json`. |
| **Calling / synthesis model** | Writes the final answer **grounded in the judge's analysis**. | **Claude**, in its synthesis step. |

The hosted router defaults to a 3-model panel (≈ Claude Opus + a GPT + Gemini
Pro) and reports roughly 4–5× the cost of a single completion for that default.
The practical advice that shaped alloy's design:

- **Diversity over quantity.** Three models from different families beat five
  near-duplicates. alloy's default panel (`codex` = a GPT family, `gemini` =
  Gemini family, judged/synthesized by Claude) is deliberately cross-family.
- **Use the strongest model as the synthesizer.** alloy makes Claude — the host
  — the judge and synthesizer.
- **Fusion is for thinking, not for raw codegen.** Multi-model synthesis helps on
  research, planning, review, and high-stakes decisions; it *dilutes* line-by-line
  code generation. alloy therefore uses the panel for the decision-heavy stages
  and leaves code writing to Claude.
- **"If the cost of being wrong exceeds the cost of querying multiple models, use
  Fusion."** That is the one-line decision rule for when to reach for `/alloy`.

## Why "compare, don't merge" matters

A naive multi-model wrapper averages answers and produces confident mush. The
value is the opposite: a panel is most useful when it **disagrees**, because the
disagreement is information. alloy's judge step is required to attribute every
consensus claim to named panelists and to keep contradictions visible, so you see
"codex says X, gemini says not-X, here's who's right and why" rather than a
smoothed-over paragraph that hides the conflict.

## The Claude-as-judge bias (and the honest answer to "isn't this rigged?")

Claude is both the judge and the synthesizer here, and it is *not* a neutral
juror — an LLM judging a panel and then writing the final answer can favor its
own framing. alloy handles this honestly rather than pretending the judge is
neutral:

1. **The judge output is written to disk** (`judge.json` in the run directory),
   so its reasoning is auditable, not hidden.
2. **Anti-sycophancy is a standing rule:** panelist *agreement is not proof of
   correctness* (shared training data → correlated errors). Thin-but-unanimous
   consensus must be flagged, not rubber-stamped.
3. **Disagreements are surfaced**, with attribution, so you can overrule Claude's
   read.
4. The honest framing alloy always ends on: **cross-model agreement is a
   recommendation; you decide.**

A future `ALLOY_JUDGE=codex|gemini` override will let the independence-minded
rotate the judge role to a different model. It is intentionally *not* the default:
rotating the judge adds latency, another auth dependency, and the CLI judges are
weaker at structured comparison — and it is not truly independent anyway when all
models saw the same prompt. The mitigation that actually works is structural
discipline (the schema + attribution + anti-sycophancy rule above), not swapping
which model holds the gavel.

## What alloy is not

- It is not local inference. Your prompts and diffs are sent to the providers
  behind each CLI.
- It is not an answer-merger. It is a disagreement surfacer.
- It is not a code-writing swarm. The panel is read-only; Claude writes.

## Sources

- OpenRouter, *Fusion beats Frontier* — https://openrouter.ai/blog/announcements/fusion-beats-frontier/
- OpenRouter docs, *Fusion router* — https://openrouter.ai/docs/guides/routing/routers/fusion-router
- Digital Applied, *OpenRouter Fusion: multi-model AI responses guide* —
  https://www.digitalapplied.com/blog/openrouter-fusion-multi-model-ai-responses-guide
