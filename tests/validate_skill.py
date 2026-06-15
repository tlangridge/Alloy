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

    if not re.search(r"^name:\s*fusion\s*$", fm, re.MULTILINE):
        fail("frontmatter must declare `name: fusion`")
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

    print("OK: SKILL.md frontmatter and standing rules validated")


if __name__ == "__main__":
    main()
