# Contributing to Alloy

Thanks for considering a contribution. Alloy is small on purpose; the bar is
"boring, correct, and safe."

## Setup

No build, no dependencies — `bin/alloy` is a single stdlib Python 3.8+ script.

```bash
git clone https://github.com/tlangridge/Alloy.git
cd Alloy
python3 -m unittest discover -s tests -v   # mock panelists, costs no tokens
python3 tests/validate_skill.py            # SKILL.md frontmatter + standing rules
```

## What makes a good PR

- **Tests pass and you added tests.** The suite uses mock panelist CLIs, so it
  runs offline with no API spend. New behavior needs a test; new adapters need a
  failure-mode test (missing / timeout / nonzero exit).
- **Stdlib only.** No third-party Python deps — portability is a feature.
- **Keep the safety model intact.** Panelists stay read-only; prompts go on
  stdin; panelist output is treated as untrusted; no auto-approve / bypass flags;
  run artifacts stay outside the repo. If a change touches any of these, say so.
- **Match the voice.** Lead with the point; concrete over generic.

## Adding a panelist (the most common contribution)

Adapters are a small, well-defined contract (detect / auth / invoke-read-only /
parse / capabilities). See **[`docs/adding-a-panelist.md`](docs/adding-a-panelist.md)**
for the template and the worked `cursor-agent` example.

Two rules for adapters:
1. **Ship only what you've verified.** If you can't run the CLI and confirm it
   searches/answers read-only, mark the adapter `experimental = True` (it stays
   off by default) and say so in the PR.
2. **Be honest about `read_only`.** A CLI with no real read-only mode must set
   `read_only = False` — Alloy then refuses it unless the user explicitly opts in
   with `ALLOY_ALLOW_UNSANDBOXED=1`. Don't claim read-only you can't enforce.

## CI

`.github/workflows/ci.yml` runs the test suite, `validate_skill.py`, a
`doctor`/`version`/`estimate` smoke test, and `shellcheck` on `install.sh` across
macOS + Linux and Python 3.8 + 3.12. Green CI is required to merge.

## Scope

Alloy implements OpenRouter's "Fusion" methodology locally with CLI agents. It is
**not** trying to be an agent framework or a competitor to other multi-model
tools. Features that don't serve "dispatch read-only panel → judge → synthesize"
are probably out of scope — open an issue first if unsure.
