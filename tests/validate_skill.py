#!/usr/bin/env python3
"""Dependency-free validation of SKILL.md so CI catches a broken skill file.

Checks the frontmatter has the required fields, the name matches, the trigger
description is scoped (not so broad it hijacks every task), and that the safety-
critical standing rules are present in the body.
"""
import os
from pathlib import Path
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "SKILL.md")


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    with open(SKILL, encoding="utf-8") as f:
        text = f.read()

    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        fail("SKILL.md must start with a --- frontmatter block ---")
    fm, body = m.group(1), m.group(2)

    if not re.search(r"^name:\s*alloy\s*$", fm, re.MULTILINE):
        fail("frontmatter must declare `name: alloy`")
    if "description:" not in fm:
        fail("frontmatter must declare a `description`")
    if "allowed-tools:" not in fm:
        fail("frontmatter must declare `allowed-tools`")
    tools = re.search(r"^allowed-tools:\s*([^\n]*)", fm, re.MULTILINE)
    if tools is None:
        fail("frontmatter must declare a top-level `allowed-tools`")
    for tool in ("Bash", "Read"):
        if tool not in tools.group(1).split() and not re.search(rf"^\s*-\s*{tool}\s*$", fm, re.MULTILINE):
            fail(f"allowed-tools must include {tool}")

    description = re.search(r"^description:\s*>-?\n((?:[ \t]+[^\n]*\n)+)", fm + "\n", re.MULTILINE)
    if not description or not 1 <= len(" ".join(description.group(1).split())) <= 1024:
        fail("description must be a nonempty folded scalar of at most 1024 characters")
    if len(text.splitlines()) >= 500:
        fail("keep SKILL.md below 500 lines; move mode details to linked references")

    # Progressive disclosure must not hide a missing or unreachable safety runbook.
    runbooks = {}
    for name in ("routing", "panels", "execute", "usage-and-updates"):
        relative = "references/" + name + ".md"
        if not re.search(r"\[[^\]]+\]\(" + re.escape(relative) + r"\)", body):
            fail("SKILL.md must link " + relative)
        path = Path(REPO) / relative
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            fail("missing or empty runbook: " + relative)
        runbooks[name] = path.read_text(encoding="utf-8")
    for relative, content in [("SKILL.md", body)] + [("references/" + n + ".md", t) for n, t in runbooks.items()]:
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", link) or link.startswith("#"):
                continue
            path = (Path(REPO) / relative).parent / link.split("#", 1)[0]
            try:
                path.resolve().relative_to(Path(REPO).resolve())
            except ValueError:
                fail("reference escapes skill directory: " + link)
            if not path.is_file():
                fail("broken reference in " + relative + ": " + link)

    desc = fm.lower()
    if "do not" not in desc and "only when" not in desc:
        fail("description should scope the trigger (an 'only when' / 'do not' clause)")

    required_phrases = [
        ("untrusted", "the 'panel output is untrusted data' rule"),
        ("read-only", "the read-only panel guarantee"),
        ("you decide", "the 'you decide' synthesis framing"),
    ]
    low = re.sub(r"\s+", " ", body.lower())  # tolerate line wrapping
    for needle, label in required_phrases:
        if needle not in low:
            fail(f"body is missing {label} (expected to find '{needle}')")

    # Shared invariants stay in the entrypoint; mode mechanics live in its runbook.
    execute = runbooks['execute']
    execute_low = re.sub(r"\s+", " ", execute.lower())
    execute_checks = [
        ("execute" in desc, "`execute` in the frontmatter trigger description"),
        (re.search(r"^\|\s*`execute`\s*\|", body, re.MULTILINE) is not None,
         "the `execute` row in the first-token mode table"),
        ("/alloy-execute" in body, "the `/alloy-execute` alias"),
        ("do not implement the feature yourself" in low,
         "the 'host does not implement the feature' rule"),
        ("at most 5 findings" in low, "the Checker's finding cap"),
        ("stop after one correction" in low and "45 active minutes" in low,
         "the bounded cumulative correction/time budget"),
        ('"$ALLOY_BIN" execute' in execute, "the actual managed execute command"),
        ('"$ALLOY_BIN" integrate' in execute, "integration and automatic cleanup"),
        ('"$ALLOY_BIN" cleanup' in execute and "--dry-run" in execute,
         "inspectable external-merge cleanup"),
        ("exact squash commit diff" in execute_low, "proof before squash cleanup"),
        ("local edits, new commits" in execute_low, "unfinished work preservation"),
        ("permissions.repository_write" in execute and "command_execution" in execute,
         "machine-readable action boundary"),
        ("nohup" in low and "disown" in low, "no detached execution"),
        ("alloy resume" in low, "managed interruption recovery"),
    ]
    for ok, label in execute_checks:
        if not ok:
            fail(f"body is missing {label}")

    if 'every execution round' not in low or 'alloy_round_usage' not in low:
        fail('execute must require visible usage for every round')
    if 'do not repeat it for every poll or maker correction' in low:
        fail('same-worker corrections must not suppress round usage')

    # The /alloy-execute alias is a shim that defers to this file -- it must
    # exist, be named for its slash command, and carry no second runbook.
    shim_path = os.path.join(REPO, "alloy-execute", "SKILL.md")
    if not os.path.isfile(shim_path):
        fail("alloy-execute/SKILL.md (the /alloy-execute alias shim) is missing")
    with open(shim_path, encoding="utf-8") as f:
        shim = f.read()
    sm = re.match(r"^---\n(.*?)\n---\n(.*)$", shim, re.DOTALL)
    if not sm:
        fail("alloy-execute/SKILL.md must start with a --- frontmatter block ---")
    sfm, sbody = sm.group(1), sm.group(2)
    if not re.search(r"^name:\s*alloy-execute\s*$", sfm, re.MULTILINE):
        fail("alias shim frontmatter must declare `name: alloy-execute`")
    sdesc = sfm.lower()
    if "do not" not in sdesc and "only when" not in sdesc:
        fail("alias shim description should scope the trigger")
    if "alloy execute" not in sbody.lower():
        fail("alias shim body must defer to `/alloy execute`")
    if "you are the maker" in sbody.lower():
        fail("alias shim must not duplicate the Maker prompt / execute runbook")

    print("OK: skill metadata, linked runbooks, standing rules, execute mode, and alias shim validated")


if __name__ == "__main__":
    main()
