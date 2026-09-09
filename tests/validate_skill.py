#!/usr/bin/env python3
"""Dependency-free validation of SKILL.md so CI catches a broken skill file.

Checks the frontmatter has the required fields, the name matches, the trigger
description is scoped (not so broad it hijacks every task), and that the safety-
critical standing rules are present in the body.
"""
import os
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
    for tool in ("Bash", "Read"):
        if not re.search(rf"^\s*-\s*{tool}\s*$", fm, re.MULTILINE):
            fail(f"allowed-tools must include {tool}")

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

    # Execute mode (0.2.0): routed by token, documented, host does not implement.
    execute_checks = [
        ("execute" in desc, "`execute` in the frontmatter trigger description"),
        (re.search(r"^\|\s*`execute`\s*\|", body, re.MULTILINE) is not None,
         "the `execute` row in the Step 1 first-token table"),
        ("/alloy-execute" in body, "the `/alloy-execute` alias"),
        ("do not implement the feature yourself" in low,
         "the 'host does not implement the feature' rule"),
        ("at most 5 finding cards" in low, "the Checker's <=5-card cap"),
        ("confirmed | plausible | refuted | out-of-scope" in low,
         "the finding-card label taxonomy"),
        ("stop after two fix" in low, "the <=2 fix->review loop cap"),
        ("--panelists <maker>" in body, "the Maker dispatched via `--panelists`"),
    ]
    for ok, label in execute_checks:
        if not ok:
            fail(f"body is missing {label}")

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

    print("OK: SKILL.md frontmatter, standing rules, execute mode, and alias shim validated")


if __name__ == "__main__":
    main()
