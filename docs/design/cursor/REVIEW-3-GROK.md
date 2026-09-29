I'll review the Cursor provider plan against the round-2 findings and the author's response, then judge only remaining blockers and majors.The response marks all eleven round-2 items fixed. I'll check those claims against the current plan text, not the status table.The plan is long enough that the status table can drift from the rules. I'll check the cited code and facts for each round-2 hole.Round-2 PARTIAL items and new findings, checked against the current plan text (the implementation is still unchanged). The accepted login-store plus network residual is stated with its mitigations, so it is not re-opened.

## Round-2 items

**R1-1 — FIXED.** §2 and §11 risk 3 accept that the Cursor process can read its login store and the repo and can use the network, and that SBPL cannot separate those reads from the in-process read tool. Mitigations named there are ask mode, a no-shell version probe, descendant-process denial, OS write denial, persisted-output redaction, and a bounded Checker packet that only strips recognized secrets. Docs are required to say the same and to avoid a credential-isolation claim.

**R1-2 — FIXED.** §2 replaces the HEAD/status tripwire with a before/after digest of path, type, mode, symlink target, and file bytes for every tracked, untracked, and ignored worktree entry, and it says a status line is not that digest. §9 tests 4–5 and Lane 1 require a same-name ignored-file byte change to move the digest.

**R1-9 — PARTIAL.** Command redaction, masked `auth_detail`, and Checker-packet scrubbing of recognized secrets are specified (§3, §9 test 14). The Cursor pattern is still only “a named Cursor token value pattern,” and the test is still a synthetic fixture of that pattern. `CURSOR-FACTS.md` still has no login-store byte shape. JWT, assignment, and header forms are covered; any other login secret echoed in `result` is still written to `result.md` and the stdout sidecar (`bin/alloy:1586-1599`). That disk sink is outside the accepted in-process read and network residual.

**R1-10 — FIXED.** The spawn gateway is a closed role grammar (§2, §3), and it rejects `-e`, `-H`, `-eVALUE`, `-HVALUE`, `--flag=value`, and split-value forms. Those shorts are not in the panel/Checker or Maker allowlists.

**R1-13 — FIXED.** Checker acceptance uses the content and Git-internals digest in addition to clean/HEAD, and any mutation rejects the verdict (§2). The Maker path keeps a per-path manifest and allows ignored-byte changes only under `allow_paths` (§2, Lane 3). `scope()` and `clean()` stay user-facing checks and are not the tamper proof.

**R1-21 — FIXED.** §8 now splits the citations: 1.2.x path-scoped grants are `bin/alloy:780-807` and `tests/test_alloy.py:612-636` (the 1.2.12 worktree test asserts `read_file(<path>)` at lines 634–635). The 1.1.7 default is `tests/test_alloy.py:536-543` (`MOCK_VERSION` `1.1.7` at line 543), and the bare-name assertion is `tests/test_alloy.py:640-674` (lines 657–659).

**N1 — PARTIAL.** Write denial covers the checkout `.git`, the linked `.git` pointer, the worktree gitdir, and the common dir, including for the Maker, and fingerprint Git uses `-c core.hooksPath=/dev/null` (§2, §6). That stops the original `.git/hooks/pre-commit` path. The digest still omits behavior-changing files the plan’s own list does not name: `commondir` and `info/attributes`. `git status` does not show either, so a `commondir` rewrite or an attributes-file change leaves both the digest and `clean()` unchanged. `core.hooksPath=/dev/null` does not stop `alias.*` or a command-valued `core.fsmonitor`. Those run in the unsandboxed parent (`bin/alloy_execution.py:29-30`, `clean()` at lines 82–83, `git add`/`commit` at lines 532–535) before the digest is compared. The plan only forbids hooks and external diff/textconv, and only on panel resolution and fingerprint Git.

**N2 — FIXED.** §4 and the §6 evidence row require `match()` to demand canonical adapter, exact normalized model id, effective effort, and fast state. Cursor stays `unmatched` until a row lists `cursor`. Lane 2 edits `bin/alloy_evidence.py` and migrates `data/model-evidence.json`. The collision with `gemini-3.8-flash-high` / `high` at `data/model-evidence.json:321-338` is an explicit negative test.

**N3 — FIXED.** Final argv is a closed grammar after `worker_adapter` and `dispatch` rewrites. Panel/Checker require `--skip-worktree-setup` and a single `--mode ask`. Both roles reject `--plugin-dir`, `--resume`, `--continue`, `-w` / `--worktree`, `--plan`, `worker`, force/auto-approval flags, and any other option or subcommand (§2, §3). There is no bootstrap exec exception. Cursor sessions stay `fresh_context_fallback`.

**N4 — FIXED.** The gate file is `tests/test_cursor_sandbox_release_gate.py`, so `python3 -m unittest discover -s tests` picks it up. It skips only when `sys.platform != "darwin"`. On macOS a missing `/usr/bin/sandbox-exec` or an unexercised operation fails the test. §9 and Lane 6 add an `if: runner.os == 'macOS'` CI step that runs that module. Current `.github/workflows/ci.yml:22-24` still does not; the plan requires the step.

**N5 — FIXED.** §4 matches `gpt-5.5-extra-high` before the generic `-high` suffix rule, preserves `-extra-high` when stripping a final `-fast`, and §9 test 8 plus §11 risk 5 require that.

## New findings

**Major. §2 read scope is wider than the accepted login-store residual.** Default-deny is writes, hard links, and process execution (§2). Reads are not limited to the login store, the executable, and the repo. Ask mode still has an in-process read tool (§2), and the profile allows provider network. Nothing denies reads of other credential paths (`~/.ssh`, `~/.aws`, other CLI auth files). The Maker role also has a shell. Those files can be sent off-box. Denying them does not conflict with the accepted login-store residual or with the ban on host-based network isolation. The plan never denies them and never accepts that wider exposure.

VERDICT: FAIL