I'll refute the Cursor provider plan against the design inputs and the current code, looking for write paths, family-independence holes, secrets, false claims, lane overlap, and changelog mistakes.The plan and probe notes are in. Next I’ll check those claims against the adapter, routing, execution, and usage code.The plan does not keep a Cursor Checker or panelist from writing outside the worktree, and several independence, secret, and acceptance claims do not hold against the current tree. VERDICT below is FAIL.

## 1. Checker and panelist can still write or cause side effects

**Blocker. Section 2, “Shared isolation helper” and “Panel and Checker boundary”.** The read-only profile still allows writes to `~/.cursor`, `~/.local/share/cursor-agent`, and `~/Library/Caches/cursor-compile-cache`, and it “permits the process, network”. Ask mode is explicitly not the boundary. Consequences:

- `~/.cursor/worktrees/<repo>/<name>` is a real git checkout (`CURSOR-FACTS.md:67-68`). A Checker can edit that checkout, replace CLI config, hooks, or MCP entries under `~/.cursor`, and have the next unsandboxed Cursor run execute them.
- `~/.local/share/cursor-agent` is the install tree the facts show `cursor-agent` points at (`CURSOR-FACTS.md:3`). Replacing that binary is a home-directory write that becomes code execution on the next launch.
- Process execution plus network is enough for `curl` or a similar client to exfiltrate the repo or the login files in `~/.cursor`. The canaries do not watch those allowlisted paths, and the plan says canaries are not preventive.

Fix: deny write to the whole home directory, including those three roots. Give the CLI an isolated state directory seeded from a copy of the login material, or a read-only bind of only the credential files it must read. Deny `process-exec` except the single resolved `cursor-agent` binary, and deny outbound network for panel and Checker runs.

**Blocker. Section 2, path rules.** The profile resolves paths and rejects symlinks at construction. It does not deny hard links. `link()` needs write permission only on the new directory. A Checker can hard-link a repo file into writable `~/.cursor` or `TMPDIR` and write it through the allowlisted path; both names share one inode. The post-run git fingerprint is not a substitute: it misses ignored files (`bin/alloy:1356` has no `--ignored`).

Fix: deny `file-link` / hard-link creation in the profile, and put the writable roots on a volume the repo cannot share. Add ignored paths to the tripwire.

**Blocker. Section 2, `TMPDIR` = `<pdir>/cursor-runtime`.** That directory is writable by design. The run directory is caller-controlled (`bin/alloy:1807-1811` already allows a run root inside a repo). Execution state is `ALLOY_RUN_ROOT`’s parent plus `execution` (`bin/alloy_execution.py:25-26`), so a root such as `/repo/.alloy/runs` puts the Checker `TMPDIR` inside the repo. If that directory is gitignored, `clean()` does not see it:

```82:83:bin/alloy_execution.py
def clean(repo):
    return not git(repo, 'status', '--porcelain', '--untracked-files=all')
```

An SBPL allow for `TMPDIR` inside a “read-only worktree” still permits the write. Fix: require the writable runtime directory to be outside the repo, the worktree, and the source checkout, and fail closed when `realpath` says otherwise.

**Major. Section 2, “Maker boundary”, and `bin/alloy_execution.py:122`.** The plan makes `read_only` mean “OS preflight succeeded”, then tells Lane 3 to keep the current subclass smash that forces `read_only` False on the instance that actually dispatches. `run_panelist` uses that flag to decide whether a managed dispatch is legal (`bin/alloy:1407-1409`) and how repo access is labeled. A wrapper that skips the sandbox when `read_only` is false runs the Maker unsandboxed with `--force`. Fix: store boundary readiness on a separate field the subclass cannot overwrite, and call `wrap_command` for every Cursor spawn regardless of `read_only`.

## 2. Family independence can still be bypassed

**Major. Section 4, “Omit `--model` only for a non-routed plain panel”.** Once the boundary preflight passes, `default_panel_names()` includes every non-experimental read-only adapter (`bin/alloy:1221-1223`). Omitting `--model` selects the CLI default `auto` (`CURSOR-FACTS.md:111` and `:366`) without calling `cursor_model_family()`. `ALLOY_CURSOR_MODEL=auto` does the same on a plain panel. Routed make mode never sees that string, but the default panel is the normal multi-model path, and Auto can be the same vendor as the host or another seat. Fix: never spawn Cursor without an explicit model id whose derived family is known. Reject `auto` on panels as well as on profiles.

**Major. Section 4, “Non-Cursor profiles retain their existing explicit-family override”.** Validation only checks that a family is in `FAMILIES.values()` (`bin/alloy_routing.py:129-130`). Adding `cursor` to that set lets a Codex or Claude profile declare `family: cursor`. `select()` only compares the three stored strings (`bin/alloy_execution.py:308-309`). A GPT checker labeled `cursor` then counts as independent of an OpenAI host. The derivation check applies only to `adapter == cursor`. Fix: derive family from the model id for every profile that claims family `cursor`, and reject any non-Composer id in that family.

**Major. Section 4, the pacing fix at `bin/alloy_routing.py:636`.** The line to change is real:

```636:637:bin/alloy_routing.py
            if pressure is not None and FAMILIES.get(name) != host:
                p["effective_cost_rank"] = p["cost_rank"] * max(pressure, .1)
```

`name` is the adapter, so a Cursor-Claude profile whose registry default is `cursor` gets the outside-family discount on an Anthropic host. Comparing `family(p)` is the right condition, but section 5 forces Cursor usage to `unknown`, and `pacing()` returns immediately when headroom is missing:

```532:533:bin/alloy_usage.py
    if headroom(profile, snapshot) is None:
        return None
```

With that snapshot the discount is absent whether or not line 636 is fixed. The CLI-wide pin `ALLOY_CURSOR_MODEL` is also one string for every family (`MODEL_KEYS` is per adapter, `bin/alloy_routing.py:26`). It can force the only eligible Cursor profile onto Claude while a Composer host is declared `--host-family cursor` (section 4’s reason for adding that choice). Fix: test pacing with a synthetic fresh Cursor window and an Anthropic host, and reject a Cursor pin whose derived family equals the host or the Maker when the role is make or review.

**Major. Section 4, prefix table.** `cursor-grok-*` is xAI in the table, which matches `CURSOR-FACTS.md:366`. The same function strips only a trailing `-fast` and then applies prefixes. That is not what leaves a hole. The hole is models the table marks unknown (`muse-spark-*`, `kimi-*`, `glm-*` in `CURSOR-FACTS.md:242-356`) and `auto`: they stay legal on an unrouted panel via `ALLOY_CURSOR_MODEL`, because rejection is specified only for profiles, cards, and managed roles. Fix: run `cursor_model_family()` on the argv model for every dispatch and refuse unknown and `auto`.

## 3. Secrets

**Blocker. Section 3, “Authentication”.** Scrubbing `CURSOR_API_KEY` does not cover the native login store. The profile grants read of the filesystem and write/read of `~/.cursor`, and it allows network. The Checker can read that store and send it out. `SECRET_PATTERNS` (`bin/alloy:263-280`) has no Cursor token shape, so a token echoed in `result` is persisted. `status.json` stores `command` with no redaction pass (`bin/alloy:1447-1450`, written again at `1637`).

Fix: keep the credential files out of the Checker filesystem (isolated home or a read-only file list), deny Checker network, and redact status argv the same way as stdout.

**Major. Section 3, the three scrub sites.** The facts also define `CURSOR_API_ENDPOINT` (`CURSOR-FACTS.md:21-25`). The plan never strips it. The CLI will send the native login token to that endpoint even when `CURSOR_API_KEY` is gone. `--api-key` is banned; `--endpoint` and `--header` are not. Fix: drop `CURSOR_API_ENDPOINT` in `clean_env()`, `run_panelist()`, and `provider_env()`, and reject `--endpoint`, `--header`, and `--api-key` in `build_args`.

## 4. Claims about the current code that are false

**Major. Section 7, `estimate`.** The plan says `bin/alloy:2004-2019` “counts only selected ready read-only adapters”, so Cursor is included only when the boundary is ready. The predicate is:

```2005:2007:bin/alloy
    ready = [r for r in _doctor_rows() if r["status"] == "ready"
             and r["name"] in selected_panelists()
             and (r["read_only"] or allow_unsandboxed())]
```

`ALLOY_ALLOW_UNSANDBOXED=1` counts a non-read-only Cursor row. The plan does not change this function, and section 6’s “refuse even if `ALLOY_ALLOW_UNSANDBOXED=1`” applies to dispatch, not `estimate`. Fix: require the OS-boundary capability here, and do not treat `allow_unsandboxed()` as readiness for `cursor`.

**Major. Section 4, effort precedence.** The plan says `ALLOY_CURSOR_EFFORT`, then `effort_by_mode`, then profile effort, then “the model ID’s own/default effort (`bin/alloy_routing.py:497-506`)”. `role_profile` stops at the environment override. It never parses `-high`, `-xhigh`, or a bracket out of the model id (`bin/alloy_routing.py:497-506`). Fix: implement that fourth step in `cursor_effective_model` and stop citing `role_profile` as if it already exists.

**Major. Section 2, the worktree tripwire.** The plan says the panel fingerprint and the managed clean/HEAD check catch worktree mutation, and says to keep them (`bin/alloy:1353-1360`, `bin/alloy:1904-1913`, `bin/alloy_execution.py:548-565`). `clean()` and the fingerprint omit `--ignored`. `scope()` then drops ignored paths again:

```98:99:bin/alloy_execution.py
    paths = git(task['worktree'], 'diff', '--name-only', '--no-renames', '-z', task['base']).split('\0')
    paths += git(task['worktree'], 'ls-files', '--others', '--exclude-standard', '-z').split('\0')
```

A Checker write to a gitignored file does not fail the check the plan calls the backstop. Fix: compare status with `--ignored`, and fail the verdict on any ignored-path change.

**Minor. Section 6, worker-pool row.** `ThreadPoolExecutor(max_workers=4)` at `bin/alloy_routing.py:446-447` and `bin/alloy_usage.py:460-461` still returns every item from `executor.map`. A fifth provider is queued, not dropped. Fix: delete that diagnosis; still add an explicit `cursor` branch.

**Minor. Scope baseline.** “Ask mode refused four of four probes” (opening section, citing `BOUNDARY-PROBE-README.md:11` and `BOUNDARY-PROBE.txt:1-9`) does not match the log. The file has three ask runs (lines 2, 6, and 7), not two plain plus two forceful. Fix: cite the three recorded ask runs, or add the missing plain run to the log before calling it four of four.

## 5. Lanes and acceptance checks

**Blocker. Section 10, Lanes 1 and 3.** The Maker write allowlist is a `bin/alloy` profile (section 2). Lane 1’s work list only builds the read-only sandbox. Lane 3’s allow-paths are `bin/alloy_execution.py` and `tests/test_execution.py`, and its acceptance requires “owned-worktree/state/cache/TMP only”. The lane that must make Maker writes succeed cannot edit the profile generator. The “non-overlapping edit sets” claim is false for this behavior. Fix: put both SBPL profiles in Lane 1’s work list, or add `bin/alloy` to Lane 3 and drop the non-overlap claim.

**Major. Section 9 item 4 and Lane 1 acceptance.** Those checks require “denied worktree/home/sibling/system-temp writes”. Section 2 allows three home subtrees. A test that denies all of `$HOME` rejects the profile the plan says to ship. A test that allows `~/.cursor` does not prove home is denied. Mock `sandbox-exec` (section 9) only shows that a simulator honored a string. It does not prove macOS enforcement. The live smoke is “not a release gate”. Fix: split assertions into allowlisted roots versus every other home path, and make a real `sandbox-exec` probe a release gate on macOS.

**Major. Section 3 versus Lane 1.** Lane 1 acceptance says `CURSOR_API_KEY` never reaches argv or env, and its command is only `test_alloy.py`. `clean_env()` is `bin/alloy_routing.py:68-69` (Lane 2). `provider_env()` is `bin/alloy_usage.py:233-238` (Lane 4). Discovery, routing probe, usage, and Checker subprocesses are outside that test file. Fix: one test that spies on every Cursor subprocess class, run in the final suite, not claimed as done at the end of Lane 1.

**Major. Section 9 item 12 and Lane 5.** `python3 tests/validate_skill.py` checks `SKILL.md` frontmatter and a fixed phrase list (`tests/validate_skill.py:44-105`). It does not open `CHANGELOG.md`, `SECURITY.md`, or the Cursor allowlist text. “Skill validator passes” does not prove the safety wording or the five changelog bullets. Fix: add a test that reads those files for the required sentences and fails on Linux support, benchmark quality, or live quota.

**Major. Lane 2 acceptance, “quota pacing uses effective model family”.** As written, Cursor pressure is always `None`, so the old and new comparisons behave the same. Fix: drive `resolve()` with a fresh synthetic `cursor` window and assert the Anthropic host does not take the outside-family discount for `claude-opus-5-5-high` on adapter `cursor`.

## 6. Release and changelog

**Major. Section 8.** The five bullets are real tree behavior (agy path grants and 1.2 settings in `bin/alloy:780-907`, `DEVNULL` at `bin/alloy:1489-1491`, gate-log mode `0o700` in the review path). Two of the required sentences are still wrong:

- “canonical agy 1.2.12 Checker settings” is the `ver >= (1, 2, 0)` branch (`bin/alloy:786-795`), which drops `allowNonWorkspaceAccess` and the bare tool names. The 1.1 settings path is still what `tests/test_alloy.py:657-660` asserts. The note has to say there are two grammars, and that 1.2.x is the fail-closed one.
- “linked/common gitdir” is only the gitdir plus its grandparent when the parent directory is named `worktrees` (`bin/alloy:900-907`). Other `gitdir:` layouts do not get the common dir. The note has to say that.

**Minor. Section 8 heading.** Current notes are `## [0.10.0] - 2026-09-26`. A bare `0.11.0` heading does not match that format, and Lane 5’s validator will not catch a missing date or a missing bullet.

**Minor. Section 6 worker-count row, repeated as a release risk.** Do not changelog a “fifth worker was dropped” fix. `max_workers=4` does not drop the fifth `map` result.

VERDICT: FAIL