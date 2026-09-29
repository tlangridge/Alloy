I'll re-check each round-1 finding against the revised plan and the code, then look for new ways the Cursor Checker path can still write, leak, or claim false evidence.The response table treats all 23 findings as fixed in the plan. I’ll check those claims against the current adapter, routing, and execution code, including the line citations.The revised plan closes most of the round-1 holes on paper. The tree in `bin/`, `data/`, and `tests/` is unchanged, so “fixed” below means the new requirements actually close the hole. Several do not.

## Round-1 findings

1. **PARTIAL.** Writable `~/.cursor`, the install tree, and `~/Library/Caches` are now write-denied, and the login-store plus network exfiltration is stated as residual (§2). That residual is the original Checker exfiltration path: the profile still default-allows filesystem read and permits provider network, and ask mode is only “no shell,” not “no read tool” (`CURSOR-FACTS.md:34-37`). Disclosure does not stop the Cursor process from reading the login store and sending it.

2. **PARTIAL.** Hard-link denial plus a mandatory `sandbox-exec` probe are specified (§2, §9). Content edits of ignored files that already exist still do not change `git status --porcelain --ignored=matching`; the extra “listing/fingerprint of ignored paths” does not require hashing file bytes. `scope()` is explicitly kept as it is (`bin/alloy_execution.py:97-99`), and that command drops ignored paths.

3. **FIXED.** The writable runtime must be an owner-private temp directory outside `<pdir>`, `ALLOY_RUN_ROOT`, every checkout, every managed worktree, and every Git common dir, checked with `realpath` and `git rev-parse --show-toplevel` (§2). That closes the `ALLOY_RUN_ROOT` inside-repo case at `bin/alloy:1807-1811` and `bin/alloy_execution.py:25-26`.

4. **FIXED.** `cursor_boundary_ready` is separate from `read_only`, and every Cursor spawn goes through the gateway after argv rewrites (§2). That matches the subclass smash at `bin/alloy_execution.py:122` and the `read_only` gate in `run_panelist` at `bin/alloy:1407-1409`.

5. **FIXED.** Every inference path must pass an explicit model; `auto` is rejected; the plain-panel default is `composer-2.5` (§3, §4). That covers `default_panel_names()` at `bin/alloy:1221-1223` and the CLI default `auto` in `CURSOR-FACTS.md:111`.

6. **FIXED.** `family: cursor` is valid only for `adapter: cursor` and a `composer-` model, and derivation is reapplied at `model_context`, `resolve`, `select`/`revalidate`, and spawn (§4). That closes validation that only checks `FAMILIES.values()` (`bin/alloy_routing.py:129-130`) and the three-string compare at `bin/alloy_execution.py:308-309`.

7. **FIXED.** Pacing compares `family(p)` with the host, and the test must use a synthetic fresh Cursor window because real Cursor headroom makes `pacing()` return `None` (`bin/alloy_usage.py:532-533`, `bin/alloy_routing.py:636-637`). Pin re-derivation is required so a CLI-wide `ALLOY_CURSOR_MODEL` cannot keep a stale family (§4).

8. **FIXED.** Unknown prefixes, including `muse-spark-*`, `kimi-*`, and `glm-*`, are refused on panel, pin, routed, and managed spawns (§3, §4). `CURSOR-FACTS.md:242-356` is the right list.

9. **PARTIAL.** `status.json.command` is redacted on both writes (`bin/alloy:1447-1450`, `bin/alloy:1500-1503`, `bin/alloy:1637`), and both Cursor env vars are stripped. The new `SECRET_PATTERNS` entry has no on-disk token shape from the facts, and the test uses a synthetic fixture of the implementer’s own regex. Native login material can still be echoed into `result.md`. The process can still read that store (§2).

10. **PARTIAL.** Long `--api-key`, `--endpoint`, and `--header` are stripped and rejected (§3). The facts also define `-e` and `-H` (`CURSOR-FACTS.md:20-25`). The plan never rejects those short forms, so an argv rewrite can still retarget the login token.

11. **FIXED.** `estimate` must require `cursor_boundary_ready` and a known model, and `ALLOY_ALLOW_UNSANDBOXED` must not count (§7). The current predicate is still `read_only or allow_unsandboxed()` at `bin/alloy:2005-2007`.

12. **FIXED.** The fourth effort step is specified as new work in `cursor_effective_model`, and the plan says `role_profile()` does not parse model ids (`bin/alloy_routing.py:497-506`) (§4).

13. **PARTIAL.** The plan adds `--ignored=matching` (§2, §9 tests 4–5) but still treats a status listing as a mutation check. An existing ignored file keeps the same `!!` line when its contents change. `clean()` at `bin/alloy_execution.py:82-83` and the Checker accept at `bin/alloy_execution.py:559-560` stay blind to that.

14. **FIXED.** The worker-pool row now says `executor.map` queues the fifth provider (`bin/alloy_routing.py:446-447`, `bin/alloy_usage.py:460-461`) and forbids a “dropped worker” claim (§6, §8).

15. **FIXED.** The plan counts three ask runs in `BOUNDARY-PROBE.txt:2,6-7`, not four (§ “Scope and verified baseline”). The README’s “4 of 4” line is correctly called a bad summary.

16. **FIXED.** Lane 1’s allow-paths include `bin/alloy` and both SBPL profiles; Lane 3 only selects them (§10).

17. **FIXED.** Allowlisted roots are separated from denied home paths, and a real `/usr/bin/sandbox-exec` probe is a release failure if it cannot run (§2, §9, §10 Lane 6).

18. **FIXED.** The all-subprocess secret spy is a final-suite test after Lanes 1–4, and Lane 1 no longer claims it (§9 test 14, §10 Lane 6). `clean_env()` is `bin/alloy_routing.py:68-69`; `provider_env()` is `bin/alloy_usage.py:233-238`.

19. **FIXED.** A dedicated wording test is required, and `tests/validate_skill.py:21-105` is explicitly not that test (§9 test 13).

20. **FIXED.** The pacing test is tied to a synthetic fresh window so `pressure is not None`, which is the only way line 636 can be distinguished (§4, §9 test 7).

21. **PARTIAL.** The two-grammar sentence matches the code: 1.2.x is the `ver >= (1, 2, 0)` branch at `bin/alloy:786-795`; 1.1 still emits bare names and `allowNonWorkspaceAccess` at `bin/alloy:796-807`. The linked-worktree sentence matches `bin/alloy:900-907`. The required changelog parenthetical cites `tests/test_alloy.py:640-674`, but that test uses default `MOCK_VERSION=1.1.7` (`tests/test_alloy.py:543`) and asserts bare names in `allow[:8]` (`tests/test_alloy.py:657-660`). The 1.2.12 path-scoped assertion is the earlier test at `tests/test_alloy.py:624-636`.

22. **FIXED.** The heading `## [0.11.0] - 2026-09-29` matches `CHANGELOG.md:6`.

23. **FIXED.** §8 says not to claim a fifth provider was dropped.

## New findings

**Major. §2, panel fingerprint.** The tripwire never sees `.git` internals, and the panel Git helper will execute a hook the tripwire missed. `git status` does not list `.git/config`, `.git/hooks`, or `.git/info/exclude`. The plan’s fingerprint is HEAD plus status (`CURSOR-PROVIDER-PLAN.md` §2). Panel Git is `_git()` at `bin/alloy:1283-1286`, which does not pass `-c core.hooksPath=/dev/null`. Managed Git does (`bin/alloy_execution.py:30`). If the sandbox fails open, a Checker can write `.git/hooks/pre-commit` and the post-run status command runs that hook as the unsandboxed Alloy parent. A linked Maker worktree is created with `git worktree add` (`bin/alloy_execution.py:646`); its `.git` file sits inside the Maker write allowlist, so retargeting that pointer is a write the profile allows. Fix: deny writes to `.git`, the worktree gitdir, and the common dir even for the Maker; hash those paths in the tripwire; run every fingerprint Git command with `core.hooksPath=/dev/null`.

**Major. §4, shipped profiles and evidence.** `cursor-medium-gemini-3-8-flash` is `gemini-3.8-flash-high` / family `google` / effort `high`, and the plan says evidence matching uses that base id (§4). `match()` compares model id and family only (`bin/alloy_evidence.py:26-30`). That exact row exists (`data/model-evidence.json:321-338`) with `applicable_efforts` including `high`, so `assessment()` returns `matched`. `resolve()` then sets `task_fit` from that result (`bin/alloy_routing.py:614-625`, `649`). No lane edits `bin/alloy_evidence.py`. After `--enable-cursor`, an unbenchmarked Cursor seat inherits Gemini benchmark preference. The profile string “Cursor discovery only; not benchmarked” is not what routing reads. Fix: `match()` must require the evidence row’s adapter, or Cursor profiles must always be `unmatched`.

**Major. §2–§3, argv boundary.** The gateway’s reject list is the three long auth flags (§3). After that, `worker_adapter` and `dispatch` rewrite argv (`bin/alloy_execution.py:124-148`, `413-422`). These documented controls are not rejected and are not in `build_args`: `--plugin-dir` (`CURSOR-FACTS.md:65-66`) loads code into the one process the profile allows to run, so descendant `process-exec` denial does not cover it; `--resume` / `--continue` (`CURSOR-FACTS.md:40-41`) resume a prior session that may not be ask mode; `-w` / `--worktree` (`CURSOR-FACTS.md:67-69`); the `worker` command, which runs tool calls on this machine (`CURSOR-FACTS.md:85-90`); `--plan`. `--skip-worktree-setup` defaults to false, so worktree setup runs `.cursor/worktrees.json` scripts (`CURSOR-FACTS.md:72-73`). The plan never passes the skip flag. Maker exec is allowed, and “required platform bootstrap” is undefined, so a preflight that needs a shell for those scripts widens exec. Fix: allowlist the Checker/Maker argv, always pass `--skip-worktree-setup`, and reject the flags above, including `-e` and `-H`.

**Major. §9–§10, release gate versus CI.** `tests/cursor_sandbox_release_gate.py` does not match unittest’s `test*.py` pattern, so `python3 -m unittest discover -s tests` does not run it. `.github/workflows/ci.yml:22-24` does not run it either, including on `macos-latest`. The plan’s routine acceptance is unittest plus `validate_skill.py`. The gate that is supposed to prove hard links, symlinks, and outside writes is a manual command. Green CI does not exercise it. Fix: run that script from the macOS CI job and fail the job if `sandbox-exec` is missing.

**Minor. §4, effort suffixes.** `gpt-5.5-extra-high` is a real id (`CURSOR-FACTS.md:213-214`). The suffix grammar treats a final `-high` as effort, so the dispatched id becomes `gpt-5.5-extra` plus `[effort=high]`. Family stays `openai`, but it is not the model that was validated. Preserve `-extra-high` as part of the base id.

VERDICT: FAIL