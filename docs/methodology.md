# Evidence for Alloy workflows

Alloy takes inspiration from OpenRouter Fusion's independent answers followed
by comparison and synthesis. It also supports routed single-worker consults
and a separate managed execution workflow. These have different costs and
verification contracts; a panel is not the default for every task.

## Match the workflow to the question

Use one qualified read-only worker for ordinary consultation. Use an explicit
panel when the request needs independent approaches or competing hypotheses.
The host compares answers and synthesizes conclusions, preserving material
disagreements and checking evidence. Panel breadth is a choice, not a promise
that every installed CLI must run.

Managed execute uses one Maker, local gates and an independent Checker. The
host, Maker and Checker must have three distinct model provider families.
A CLI hosting several providers does not become a new independent family.
The Maker edits and tests in an owned worktree; the Checker reviews the exact
revision read-only. The host judges integration, which is separate from a pass.

[Building effective agents](https://www.anthropic.com/research/building-effective-agents)
recommends starting with simple workflows and adding orchestration where it
improves the result. [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296)
finds that coordination benefits depend on task structure and that more agents
can introduce overhead and propagate errors. These support Alloy's preference
for bounded, task-specific orchestration. They do not establish a local quality
improvement, a universal winning architecture or a subscription saving.

## Judge evidence rather than agreement

Record concise conclusions and supporting evidence in `judge.json`, not private
chains of thought. Attribute claims and contradictions to contributing workers.
Compare the proposed explanation against source code, primary documentation,
observable outputs and executable checks. Multiple workers can share incorrect
assumptions, so a majority is insufficient proof.

The host has useful task context but also its own framing and model biases.
A fresh process from the host's family is another perspective; it does not
supply independent cross-family verification. Judge answers on evidence, without
preferring the host's family. Missing or failed responses are not votes.
Cross-model agreement remains a recommendation for the user to assess.

Optional debate is a single rebuttal round after a substantive disagreement on
a checkable point, with at least two different families. Anonymize the initial
answers and demand sources or concrete counterexamples. Prefer a direct test
or authoritative source when it can settle the issue. Debate can also encourage
conformity; neither persuasiveness nor convergence establishes correctness.

## Keep execution and review bounded

Default managed execution permits an initial implementation and one correction
within 45 active minutes per logical task, shared across relaunches and resumes.
Each Checker review can retry transport failures twice on the same revision;
these retries do not become implementation failures or authorize another Maker
round. Malformed nonempty reviews fail closed.

A review contains at most five evidence-backed findings. A blocker needs a
reproduction or concrete expected/actual counterexample within the scoped
change. No defect found is a valid outcome. The Maker verifies findings before
changing code. Repeated blockers, no acceptance progress or budget expiry
return the patch and open decisions; they do not trigger endless debate.

Successful local gates and independent review are process evidence. Hidden-test
correctness, integration, deployment and user acceptance remain distinct
outcomes. Cleanup requires proof of integration or a verified archive and must
preserve unfinished work. See [managed execution](execution.md).

## Measure the actual task

Published scores and model cards are dated priors. Record model, adapter,
effort, fast state and role; changing any of these changes the evaluation
identity. Codex Ultra can add subagents and must not inherit single-worker
measurements. API list prices do not establish subscription usage, and API tool
support does not certify the CLI's actual tools or permission boundary.

Compare representative tasks on the same harness and acceptance checks. Retain
failures, corrections, latency and token usage, report sample sizes, and keep
unknown success rates unknown. The small component samples in
[benchmark results](../bench/RESULTS.md) do not qualify a small Checker for
demanding reviews. Complete execute evaluation is separate, explicitly opt-in
work; ordinary tests use mock CLIs and fake router transport.

## Primary references

- [OpenRouter Fusion design](https://openrouter.ai/blog/announcements/fusion-beats-frontier/)
  and [router documentation](https://openrouter.ai/docs/guides/routing/routers/fusion-router)
- [Improving Factuality and Reasoning in Language Models through Multiagent Debate](https://arxiv.org/abs/2305.14325)
- [Talk Isn't Always Cheap: Understanding Failure Modes in Multi-Agent Debate](https://arxiv.org/abs/2509.05396)
- [Agent Skills specification](https://agentskills.io/specification) and
  [Codex skill guidance](https://learn.chatgpt.com/docs/build-skills): concise
  entrypoints with mode-specific references loaded as needed
