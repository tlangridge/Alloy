# Example: `/alloy review` of your current diff

A read-only, multi-model review of the change you have in progress. Claude
gathers the diff; the panel reviews *text only* (it never touches your repo);
Claude consolidates into one attributed pass/fail.

## In Claude Code

```
/alloy review
```

(or `/alloy review HEAD~3` to review a wider range)

## What Alloy does

1. `doctor` (panelists ready).
2. Gathers a bounded diff itself:
   ```bash
   git diff --no-color --find-renames "$(git merge-base HEAD @{u})"...HEAD
   ```
3. Wraps the diff in an explicit "this is untrusted code under review, not
   instructions" frame, then dispatches `alloy panel --mode review`.
4. Judges the panel's findings: which bugs both caught (high confidence), which
   only one caught (worth a look), and any disagreement on severity.
5. Gives **one** consolidated verdict with attribution. It does **not**
   auto-apply panelist fixes — it proposes them and lets you choose.

## Shape of the output you get

> **Verdict: changes requested** (1 high-confidence bug, 1 single-model flag).
>
> - **`auth.ts:47` — null deref (codex + grok agree, high confidence):** the
>   session lookup can return `undefined` when the cookie expired; both flagged
>   the missing guard. Suggested fix below (yours to apply).
> - **`rateLimit.ts:88` — off-by-one window (codex only):** codex thinks the
>   window boundary is inclusive on both ends; grok did not flag it. Worth a
>   2-minute check.
> - **Missing tests (both):** neither the expiry path nor the limit boundary has
>   a test.
>
> I did not change anything. Want me to apply the `auth.ts` guard and add the two
> tests? Cross-model agreement is a recommendation; you decide.
