# Response to Review 1

Every finding was checked against the current `bin/`, `data/`, and `tests/`
implementation before revising the plan. “Fixed” means the plan now requires the
correction or records the residual risk and release gate; it does not claim the
implementation already exists.

| # | Finding (short) | Severity | Decision | Where in the plan | Rejection code evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Writable real Cursor state plus process/network access was unsafe and the confidentiality risk was unstated | Blocker | fixed | §2 “SBPL and writable-path rules”; §2 “Panel and Checker boundary” | — |
| 2 | Hard links could bypass path grants and ignored files escaped the tripwire | Blocker | fixed | §2 “SBPL and writable-path rules”; §9 release gate | — |
| 3 | Checker `TMPDIR` could be placed inside a repository through `ALLOY_RUN_ROOT` | Blocker | fixed | §2 “SBPL and writable-path rules” | — |
| 4 | Maker `read_only=False` could erase boundary readiness and bypass wrapping | Major | fixed | §2 “One boundary state and one spawn gateway”; §10 Lane 3 | — |
| 5 | Plain/default panels could omit `--model` or use `auto` | Major | fixed | §3 “Invocation and JSON output”; §4 “Family is derived per Cursor model” | — |
| 6 | A non-Cursor or non-Composer profile could claim family `cursor` | Major | fixed | §4 “Family is derived per Cursor model” | — |
| 7 | Pacing and env-pin revalidation did not prove effective-family independence | Major | fixed | §4 “Family is derived per Cursor model”; §9 test 7 | — |
| 8 | Unknown Cursor model prefixes remained legal on unrouted panels | Major | fixed | §3 “Invocation and JSON output”; §4 “Family is derived per Cursor model” | — |
| 9 | Native-login tokens could be read/echoed and `status.json.command` was unredacted | Blocker | fixed | §2 “SBPL and writable-path rules”; §3 “Authentication” | — |
| 10 | `CURSOR_API_ENDPOINT`, `--endpoint`, and `--header` were not blocked | Major | fixed | §3 “Authentication”; §3 “Invocation and JSON output” | — |
| 11 | `estimate` could count Cursor through `ALLOY_ALLOW_UNSANDBOXED` | Major | fixed | §7 “Doctor, setup, models, and user-visible behavior” | — |
| 12 | The fourth effort-precedence step was cited as existing but was not implemented | Major | fixed | §4 “Effort mapping and fast variants” | — |
| 13 | Worktree checks omitted ignored paths | Major | fixed | §2 “SBPL and writable-path rules”; §9 tests 4–5 | — |
| 14 | The worker-pool row implied a false fifth-provider omission | Minor | fixed | §6 worker-count audit row | — |
| 15 | The plan claimed four ask runs but the raw log contains three | Minor | fixed | “Scope and verified baseline” | — |
| 16 | Lane 3 required Maker SBPL changes but could not edit the Lane 1 generator | Blocker | fixed | §10 Lane 1 owns both profiles; Lane 3 only selects them | — |
| 17 | Sandbox assertions conflated allowed home roots with denied home paths, and mocks could not establish real macOS enforcement | Major | fixed | §2 “SBPL and writable-path rules”; §9 test 4 and real `sandbox-exec` release gate; §10 Lane 6 | — |
| 18 | Lane 1 could not prove secret scrubbing across routing, usage, and managed paths | Major | fixed | §9 test 14; §10 Lane 6 | — |
| 19 | `validate_skill.py` did not validate changelog/security wording | Major | fixed | §9 test 13; §10 Lane 6 | — |
| 20 | The pacing test was ineffective while Cursor headroom was unknown | Major | fixed | §4 family tests; §9 test 7; §10 Lane 2 | — |
| 21 | Two required Antigravity changelog sentences overstated current behavior | Major | fixed | §8 “Documentation and release bookkeeping” | — |
| 22 | The proposed changelog heading did not match repository format | Minor | fixed | §8 “Documentation and release bookkeeping” | — |
| 23 | The repeated release-risk wording could imply a dropped fifth worker | Minor | fixed | §8 “Documentation and release bookkeeping” | — |

Totals: **23 fixed, 0 rejected**.

## Round 2

Every PARTIAL and new finding in `REVIEW-2-GROK.md` was checked against the
current `bin/`, `data/`, `tests/`, and `.github/` tree before the plan was
revised. In particular, the current implementation uses HEAD/status text rather
than file bytes (`bin/alloy:1353-1360`), drops ignored files from managed scope
checks (`bin/alloy_execution.py:82-102`), matches evidence without adapter
identity (`bin/alloy_evidence.py:26-47`), and has no explicit macOS gate step
(`.github/workflows/ci.yml:9-24`). “Fixed” means the revised plan now requires
the correction or explicitly accepts the lead-approved residual risk; it does
not claim that implementation already exists.

| # | Finding (short) | Severity | Decision | Where in the plan | Rejection code evidence |
| --- | --- | --- | --- | --- | --- |
| R1-1 | Login-store reads plus provider network remain an in-process Checker exfiltration risk | Blocker | fixed | §2 “SBPL and writable-path rules”; §11 risk 3 | — |
| R1-2 | Ignored-file byte edits were invisible to the filename/status tripwire | Blocker | fixed | §2 “SBPL and writable-path rules”; §9 tests 4–5 | — |
| R1-9 | Native login material could be echoed into persisted or staged Checker output | Blocker | fixed | §2 “SBPL and writable-path rules”; §3 “Prompt transport” and “Authentication”; §9 test 14 | — |
| R1-10 | Short endpoint/header forms `-e` and `-H` escaped the auth-control denylist | Major | fixed | §3 “Authentication”; §3 “Invocation and JSON output” | — |
| R1-13 | Managed Checker acceptance still trusted ignored-blind clean/status checks | Major | fixed | §2 “SBPL and writable-path rules”; §10 Lane 3 | — |
| R1-21 | The agy changelog citation pointed the 1.2.12 claim at a 1.1.7 test | Major | fixed | §8 “Documentation and release bookkeeping” | — |
| N1 | Worktree fingerprints omitted behavior-changing Git internals, Maker could write its linked `.git` pointer, and panel Git lacked hook suppression | Major | fixed | §2 “SBPL and writable-path rules”; §6 panel Git/fingerprint row; §9 tests 4–5 | — |
| N2 | Cursor profiles could borrow native-provider benchmark preference for the same model/family | Major | fixed | §4 “Shipped profiles and discovery”; §6 evidence-match row; §10 Lane 2 | — |
| N3 | Post-build argv rewrites could inject plugins, sessions, worktrees, setup scripts, modes, sandbox/approval controls, or subcommands | Major | fixed | §2 “Panel and Checker boundary” and “Maker boundary”; §3 “Authentication” and “Invocation and JSON output” | — |
| N4 | The real macOS sandbox gate was neither unittest-discoverable nor an explicit macOS CI step | Major | fixed | §9 release gate and acceptance commands; §10 Lane 6 | — |
| N5 | Generic effort-suffix parsing would corrupt the documented `gpt-5.5-extra-high` model ID | Minor | fixed | §4 “Effort mapping and fast variants”; §11 risk 5 | — |

Round 2 totals: **11 fixed, 0 rejected**.

## Round 3

Every PARTIAL and new finding in `REVIEW-3-GROK.md` was accepted and resolved in
the plan. The measured login store is a macOS keychain item rather than a token
file (`CURSOR-FACTS.md:368-370`), so the plan does not claim exact-value
redaction or have Alloy inspect the keychain. “Fixed” means the revised plan now
requires the correction; it does not claim the implementation already exists.

| # | Finding (short) | Severity | Decision | Where in the plan | Rejection code evidence |
| --- | --- | --- | --- | --- | --- |
| R1-9 | Persisted output relied on an unspecified Cursor token pattern and could retain a secret echoed in `result` | Blocker | fixed | §2 “SBPL and writable-path rules”; §3 “Authentication”; §9 tests 2, 6, and 14 | — |
| N1 | The digest omitted `commondir`/attributes/sparse settings, and parent Git did not uniformly disable hooks, fsmonitor, and system config | Major | fixed | §2 “SBPL and writable-path rules”; §6 parent Git/fingerprint row; §9 tests 4–5 and 14; §10 Lanes 1 and 3 | — |
| New major | Every Cursor role could read unrelated credential paths and send them over the provider network | Major | fixed | §2 “SBPL and writable-path rules”; §8 documentation; §9 tests 4–5, 14, and macOS release gate; §10 Lanes 1, 3, 5, and 6 | — |

Round 3 totals: **3 fixed, 0 rejected**.
