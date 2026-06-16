<!-- Thanks for contributing to Alloy! Keep PRs small and focused. -->

## What & why

<!-- One or two sentences. Link any issue. -->

## Checklist

- [ ] `python3 -m unittest discover -s tests` passes (and I added/updated tests)
- [ ] `python3 tests/validate_skill.py` passes
- [ ] Stdlib-only (no new Python dependencies)
- [ ] Safety model intact (read-only panel, stdin prompts, untrusted output, no
      auto-approve flags, run artifacts outside the repo) — or I explain why not
- [ ] If I added an adapter: it's honest about `read_only`, and `experimental`
      unless I verified it live (see `docs/adding-a-panelist.md`)
- [ ] Docs updated if behavior or config changed
