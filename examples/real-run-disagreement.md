# Example: a real Alloy round where the panel disagrees

This is an actual, unedited Alloy round (it was run while building Alloy). It
shows the most valuable thing a panel does: **disagree**, and let the judge keep
both signals instead of averaging them away.

## The prompt

> In ONE sentence, what is the single biggest reliability risk when an
> orchestrator runs multiple AI coding CLIs in parallel and reads their combined
> output?

## Dispatch

```
$ alloy panel --prompt-file prompt.txt
[alloy] panel: codex, gemini (2 model call(s))
[alloy] codex: dispatching (read-only, timeout 280s)
[alloy] gemini: dispatching (read-only, timeout 280s)
[alloy] codex: ok in 10.4s (exit 0)
[alloy] gemini: ok in 13.6s (exit 0)
[alloy] done: 2/2 panelist(s) ok -> .alloy/runs/.../manifest.json
```

## The panel answers (verbatim from the run dir)

**codex** (`codex/result.md`):

> The biggest reliability risk is nondeterministic, interleaved output causing
> the orchestrator to misattribute messages or state to the wrong CLI and make
> incorrect decisions.

**gemini** (`gemini/result.md`):

> The single biggest reliability risk is encountering race conditions where
> multiple agents attempt to modify the same shared files or system state
> simultaneously, leading to silent code corruption and inconsistent repository
> states.

## The judge (`judge.json`, abridged)

```json
{
  "consensus": [
    {"claim": "parallel orchestration of CLIs has a single dominant reliability risk worth designing against", "panelists": ["codex","gemini"]}
  ],
  "contradictions": [],
  "partial_coverage": [
    {"panelist": "codex", "covers": "the READ path: interleaved/nondeterministic output -> misattribution"},
    {"panelist": "gemini", "covers": "the WRITE path: concurrent file/state mutation -> corruption"}
  ],
  "unique_insights": [
    {"panelist": "codex", "insight": "the orchestrator can attribute a message to the wrong CLI"},
    {"panelist": "gemini", "insight": "shared-state writes can silently corrupt the repo"}
  ],
  "blind_spots": ["neither mentioned a hung/unauthenticated CLI stalling the whole panel"],
  "confidence": "high that both are real; they answer different halves of the question, so this is complementary, not a conflict"
}
```

## The synthesis

The two models did not actually contradict each other — they answered different
halves of the question. **codex** focused on the *read* path (parallel output is
nondeterministic and interleaved, so an orchestrator can misattribute a message
to the wrong CLI) and **gemini** on the *write* path (concurrent agents mutating
shared files can silently corrupt state). Both are real; a single model would
likely have given you only one.

For Alloy itself, both are designed out: each panelist writes to its **own**
files (no interleaving, no misattribution) and runs **read-only in a throwaway
working directory** (no shared-state writes). The judge also flagged a blind spot
neither model raised — a hung/unauthenticated CLI stalling the panel — which
Alloy handles with non-TTY stdin and process-group timeouts.

> Cross-model agreement is a recommendation, not proof. You decide.
