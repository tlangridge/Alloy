# Example: `/alloy ask` for a high-stakes architecture decision

`ask` is the cheapest, safest mode and the best place to start. Use it when the
cost of being wrong is higher than the cost of asking several models.

## In Claude Code

```
/alloy ask We have a 200k-row/day ingestion pipeline on Postgres. Should we move
to event sourcing, add a CQRS read model, or just partition + add read replicas?
Optimize for a 3-person team. Give trade-offs and a recommendation.
```

## What Alloy does

1. Runs `doctor` (2 panelists ready: codex, grok).
2. Writes the question to a temp file and dispatches one read-only round:
   `alloy panel --prompt-file ... --mode consult`.
3. Reads `manifest.json`, then each `ok` panelist's `result.md`.
4. **Judges**: which option each model favored, where they agreed (e.g. "don't
   jump to event sourcing for a 3-person team"), where they split (CQRS vs.
   partitioning), and what neither addressed (operational/on-call cost).
5. **Synthesizes** an answer that names who recommended what, surfaces the real
   trade-off, folds in repo/team context Claude has, and ends with *you decide*.

## Shape of the output you get

> **Consensus (codex + grok):** event sourcing is overkill for a 3-person team
> at 200k rows/day; the write volume does not justify the operational burden.
>
> **Disagreement:** codex leans *partition + read replicas* (lowest new
> machinery); grok leans a *CQRS read model* (better read scaling headroom). My
> read: start with partitioning + replicas because it solves today's bottleneck
> with the least new failure surface for a small team; revisit CQRS only if read
> patterns diverge sharply from writes.
>
> **Blind spot neither raised:** the on-call cost of whichever you pick — for 3
> people, that should be the deciding factor.
>
> Cross-model agreement is a recommendation, not proof. You decide.
