# Working on Alloy

When working on the Jev integration, use the official `typesafe-ai` skill.
It is installed for this workspace's user at
`~/.agents/skills/typesafe-ai/SKILL.md`. On another machine, install it with
`npx skills add typesafe-ai/skills --skill typesafe-ai --agent codex --global`.
If unavailable locally, read the official skill at
https://raw.githubusercontent.com/typesafe-ai/skills/main/skills/typesafe-ai/SKILL.md.
Read current TypeSafe API/question documentation for version-dependent changes.

Keep the runtime standard-library Python 3.8+ and routing opt-in. Routing targets
Codex, Claude, Grok and Antigravity (`agy`). Model profiles are configuration;
provider family can differ from the CLI family. Preserve user model pins,
billing settings, read-only consult/review panels and independent Maker/Checker
constraints. Managed execute authorizes Maker edits/tests in an owned worktree;
integration and cleanup must preserve unfinished work and require merge proof.

Run `python3 -m unittest discover -s tests -v` and
`python3 tests/validate_skill.py` for relevant changes. Tests must use mock CLIs
and fake Jev transport; live evaluation is an explicit separate action.
