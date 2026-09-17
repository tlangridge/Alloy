# Routing validation — 2026-09-17

Implemented on `codex/jev-routing`. See [routing.md](routing.md) for supported
commands and limits. No claim of general coding quality or cost savings follows
from these small checks.

## Automated checks

- 104 unit/integration tests passed using mock CLIs and fake Jev responses.
- Coverage includes routing tiers, confidence/risk escalation, family separation,
  new model profiles, model pins, metered estimates, shared quota reserves,
  response validation, credential isolation, retries, discovery failures,
  changed help output, setup preservation and install/reinstall/uninstall.
- Both the repository skill validator and the skill-creator validator passed.
- `bash -n install.sh` and `git diff --check` passed. ShellCheck is not installed
  locally; the repository CI retains its ShellCheck job.

## Live Jev evaluation

The explicit evaluation script ran the 50 versioned synthetic tasks in
`tests/fixtures/routing_tasks.json` through `jev-1.13.0` with rubric version 1.
All 50 matched their declared acceptable tier ranges. The set is deliberately
simple and includes 25 development and 25 held-out examples; the rubric was
not tuned on the resulting evaluation output. A preceding smoke test informed
clarification of the ambiguity question before this dataset was evaluated.

- Required tiers: 20 small, 8 medium, 22 large.
- Median Jev latency: 354.5 ms; p95: 535 ms (API client timing, excluding CLI discovery).
- Input usage: 29,647 tokens, approximately $0.001245 at the documented
  $0.042/million input-token price.
- The always-large baseline fits 30/50 declared ranges; it fails the 20 simple
  task checks because unnecessary escalation is explicitly disallowed there.
- This measures agreement with our synthetic policy labels, not probability
  calibration, real task success, subscription consumption or dollar savings.

The local full evaluation report is `/tmp/alloy-jev-evaluation.json`; regenerate
with `python3 bin/evaluate-routing --output /tmp/jev-evaluation.json` (paid Jev
calls). The fixture set and script are tracked source files; runtime reports and
credentials are not committed.

## Live dispatch and code checks

All four routed CLI smoke calls returned the expected `ROUTING_SMOKE_OK` output:
Codex (`gpt-5.6-luna`), Claude (`sonnet`), Grok (`grok-4.6`) and Antigravity
(`gemini-3.6-flash-high`). Each call explicitly pinned one profile to verify its
adapter, used no repository access and had a 60-second execution timeout. The
Codex test used per-call overrides to avoid the user's existing model pin.

A separate temporary repository contained an incorrect `add` function plus
positive and negative input tests. A routed Maker with an OpenAI host selected
Antigravity; a fixed Codex baseline ran independently. Both returned a minimal
unified diff, both applied cleanly to separate copies, and both passed the two
tests. Neither run triggered the repository-tamper check. The host applied the
patches and ran tests; the CLIs remained read-only.

Antigravity dispatch took 12.8 seconds; the fixed Codex dispatch took 50.8
seconds. These are single runs on one tiny task, not a performance benchmark.
Full manifests remain in the user's Alloy run directory.

## Known limits

- Default capability tiers and cross-billing cost ranks are editable priors.
  New discovered models require configured capability/billing metadata before
  routing; discovery alone does not qualify them.
- CLI auth and model availability are best-effort until execution. Version/help
  probes do not certify sandbox behavior. There is no automatic cross-model
  retry after a dispatched task fails or times out.
- Live Codex, Claude and Antigravity quota sources are now included (see the
  follow-up validation below); Grok remains unknown. Downstream actual-cost
  aggregation is not included. An estimated spend ceiling is not a
  provider-enforced billing cap.
- Existing user model pins remain effective. This user's per-CLI billing modes
  were still unknown at validation time.

The official TypeSafe skill was installed for Codex with the skills CLI and used
for the final review. Its current API, Choice, intent-routing and confidence
classification cookbook guidance informed the review. Future maintainers should
follow `AGENTS.md` and re-check current docs when changing this integration.

## Follow-up: live subscription capacity

The usage integration passed the full 124-test suite. The additional tests cover
provider response normalization, shared and model-specific pools, missing/null
values, freshness, failed refreshes, reset boundaries, credential-source changes,
quota-aware selection, independent Checker capacity, Markdown suppression,
RPC handshakes and subprocess deadlines. No live provider reads run in tests.

A live `alloy usage --refresh` returned Codex weekly, Claude five-hour/weekly,
and both Antigravity quota groups. Grok correctly reported unknown. A live Jev
route included all four provider observation states and selected Antigravity's
Gemini profile using approximately 88.8% limiting-window headroom. The route's
normalized context omitted credentials and account identifiers. This one check
verifies integration, not an end-to-end savings claim.

Usage needs no Jev key and makes no generation calls. Default reads are cached
for 120 seconds. Session/turn display is requested by the Alloy skill; the CLI
does not install global hooks into other products. See [usage.md](usage.md) for
source details, freshness policy and controls.

## Release verification: 0.3.0

The release suite passed 129 tests. Five additional regressions ensure that a
reserved independent Checker respects model pins, family exclusions, task tier,
manual quota reserves and spend limits, while allowing a different Maker profile.
