# Choose effort for the role

Model capability, task complexity and reasoning effort are separate choices.
Use a quick implementation cycle when the user can review a bounded result;
spend more verification effort where an error is costly or hard to expose.
Managed execution is autonomous between handoffs, so it does not imply that
all Makers should run at low effort.

These are routing priors informed by [Thariq Shihipar's September 25 article](https://claude.dev/blog/spending-your-effort/),
not measured Alloy success rates. Its Claude examples and vendor benchmark runs
do not establish matching effort curves for Codex, Grok or Gemini. Effort names
and supported levels differ across models and CLIs. No cache or quota savings
are promised for a subprocess invocation.

## Configure the roles

A profile can retain its default effort and override individual modes:

```json
{
  "effort": "medium",
  "effort_by_mode": {
    "make": "medium",
    "review": "high"
  }
}
```

This is a fragment of a model profile in `routing.json`. Valid mode keys are
`make`, `review`, `consult`, and `debate`. Omitted modes use `effort`; null lets the
CLI inherit its default. `ALLOY_<CLI>_EFFORT` overrides still win, including
`inherit`/`default`. Existing configurations are preserved on upgrade. The shipped
Opus 5.5 profile uses medium for implementation and high for review; adopt that
field deliberately, not by resetting unrelated custom configuration.

For a supervised sketch, a user can configure `make: low` on a model that supports
it. For autonomous bug fixing or verification, consider medium/high after checking
its model evidence. Reserve max for a deliberate difficult task with enough time
and quota. Increasing effort grants no extra permissions and does not authorize
additional features, deployment, or an unbounded retry loop.

With Jev, `make` requests include separate Maker and independent-review model
cards and fit questions in one call. The Checker uses review-specific judgments,
not the Maker's implementation fit. Code still enforces model pins, independent
families, availability, quota and estimated spend constraints. Effort is fixed
when a task is created; changed settings stop revalidation rather than silently
switching an active worker. Token-based cost estimates remain estimates, not
hard billing caps or measured effort multipliers.

Without Jev, inspect `alloy models context --mode make` and
`alloy models context --mode review` before selecting explicit profiles. Show the
chosen model **and effort** alongside the usage table at every round boundary.

## Diagnose before escalating

- Missing edge cases: provide a concrete failure and focused verification, such
  as a boundary test, comparison against a reference, or property test.
- Wrong approach or domain rule: revisit the evidence or algorithm; more tokens
  spent repeating the same assumption are not a remedy.
- Unclear product intent: resolve the material requirement before another build.
  Extra effort is not a substitute for the user's decision.
- Authentication, capacity or tooling failures: fix readiness; do not count them
  as model-quality failures or upgrade to a more expensive model automatically.

Required repository checks still run. The independent Checker remains read-only;
proposed mutating checks belong to the Maker or authorized host. Keep before/after
acceptance evidence separate from tests passed, deployment and verified live
behavior. After the correction limit, retain the worktree for the Lead's decision.

## Evaluate the change

Save role-specific cards with Jev answers. Benchmark replay requires
`model_context`/`fit_*` for the selected role and, for a Maker task,
`review_model_context`/`review_fit_*` for its Checker. Capture fresh evidence when
model or effort changes. Evaluate complete execute loops separately from the
component proxy; report actual elapsed time, correctness, retries and quota use.
