#!/usr/bin/env python3
"""Lane 6 of the Alloy 0.11.0 Cursor provider: the cross-cutting release gates.

Every lane before this one tests its own component. This module owns the claims that
only hold when all of them are put together, and it deliberately does not repeat a
component test:

  * the ONE final-suite invariant: every Cursor subprocess class (login status, version
    and help probes, model discovery, plain and routed panels, managed Maker and
    Checker, and the sandbox self-test) is spied on at the point of `Popen`, with
    poison in both the process environment and Alloy's config, and nothing forbidden
    ever crosses that boundary; usage launches no process at all; no force / mode /
    sandbox / plugin / worktree / session / subcommand / auth injection survives a
    rewrite;
  * recognised secrets injected into EVERY Checker packet source never reach the saved
    packet, the staged prompt or any Checker-facing persisted sink;
  * the release wording (CHANGELOG 0.11.0, SECURITY, the Cursor docs and the skills),
    checked independently of tests/validate_skill.py, including unsupported claims;
  * no operator-specific internal name in any file of the repository;
  * the wiring of the real macOS sandbox gate (tests/test_cursor_sandbox_release_gate.py):
    discoverable, skips only for the platform (and, for the class that starts the real Cursor
    runtime, only on a runner that says it can have no Cursor at all), fails (never skips) on
    macOS without /usr/bin/sandbox-exec or with a Cursor that cannot start, and named in the
    macOS CI job.

Everything here runs against mocks: the mock sandbox-exec and a fake cursor-agent from
tests/mocks and tests/test_execution.py. No real provider, network, keychain, browser
or Cursor CLI is used, and HOME is never set or changed.
"""
import collections
import contextlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GATE = HERE / "test_cursor_sandbox_release_gate.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"


# The credential locations every role must deny reads of (the plan's built-in list, general stores
# only). Deliberately NOT read from production: dropping an entry from the shipped tuple must
# fail this suite rather than silently shrink it.
BUILTIN_SENSITIVE = (".ssh", ".aws", ".gnupg", ".config/gh", ".netrc", ".docker/config.json", ".kube",
                     ".npmrc", ".pypirc", ".git-credentials", "Library/Keychains", ".cswarm",
                     ".codex/auth.json", ".claude/.credentials.json", ".gemini", ".grok", ".config/op")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# =============================================================================================
# 1. No operator-specific internal name in any file of the repository
# =============================================================================================
# Alloy is a public repository. These names identify one operator's private setup; none may
# appear in any tracked or new file, whatever its type. THIS file is the only one that may
# name them (it has to, to forbid them).
INTERNAL_NAMES = ("openclaw", "anvil-secret", "/users/", "yulanbot", "hezlead")


def repository_files():
    """Every file that is, or would be, committed: tracked plus untracked-not-ignored (so a
    file this very change adds is scanned too). Falls back to a walk outside a checkout."""
    try:
        ran = subprocess.run(
            ["git", "-C", str(ROOT), "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
             "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, check=True, timeout=60,
            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_OPTIONAL_LOCKS="0"))
        names = [n for n in ran.stdout.decode("utf-8", "surrogateescape").split("\0") if n]
        found = [ROOT / n for n in names]
    except (OSError, subprocess.SubprocessError):
        found = []
        for base, dirs, files in os.walk(str(ROOT)):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
            found.extend(Path(base) / f for f in files)
    return sorted(p for p in found if p.is_file() and not p.is_symlink())


def find_internal_names(paths, exclude=()):
    """[(relative path, term)] for every file whose NAME or bytes contain a forbidden term
    (case-insensitive). Reports the term, never the surrounding text."""
    skip = set(os.path.realpath(str(p)) for p in exclude)
    hits = []
    for path in paths:
        if os.path.realpath(str(path)) in skip:
            continue
        rel = os.path.relpath(str(path), str(ROOT))
        try:
            data = path.read_bytes().lower()
        except OSError:
            hits.append((rel, "unreadable"))
            continue
        lowered = rel.lower()
        for term in INTERNAL_NAMES:
            if term.encode("utf-8") in data or term in lowered:
                hits.append((rel, term))
    return hits


class InternalNameTests(unittest.TestCase):
    def test_no_file_in_the_repository_names_an_operator_specific_path_or_person(self):
        files = repository_files()
        self.assertGreater(len(files), 100, "the repository listing looks wrong")
        # the spec's own scope: docs, README, SKILL files, CHANGELOG, bin/, data/ ... all present
        listed = set(os.path.relpath(str(p), str(ROOT)) for p in files)
        for required in ("README.md", "CHANGELOG.md", "SKILL.md", "alloy-execute/SKILL.md", "bin/alloy",
                         "data/routing-defaults.json", "docs/execution.md", "tests/test_alloy.py",
                         "tests/test_cursor_sandbox_release_gate.py", "tests/live/cursor_ask_release.py"):
            self.assertIn(required, listed)
        self.assertEqual(find_internal_names(files, exclude=[Path(__file__)]), [])

    def test_the_scan_can_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(os.path.realpath(tmp))
            clean = base / "clean.txt"
            clean.write_text("nothing to see\n")
            for term in INTERNAL_NAMES:
                for text in (term, term.upper(), "prefix " + term.title() + " suffix"):
                    dirty = base / "dirty.txt"
                    dirty.write_bytes(("line one\n" + text + "\n").encode())
                    hits = find_internal_names([clean, dirty])
                    self.assertEqual([t for _p, t in hits], [term], text)
            named = base / ("hez" + "lead-notes.md")
            named.write_text("harmless body\n")
            self.assertEqual([t for _p, t in find_internal_names([named])], ["hez" + "lead"])
            self.assertEqual(find_internal_names([dirty], exclude=[dirty]), [])
            binary = base / "blob.bin"
            binary.write_bytes(b"\x00\x01OpenClaw\xff")
            self.assertEqual([t for _p, t in find_internal_names([binary])], ["openclaw"])


# =============================================================================================
# 2. Release wording: CHANGELOG 0.11.0, SECURITY, the Cursor docs and the skills
# =============================================================================================
# tests/validate_skill.py only checks skill frontmatter and a few fixed phrases; its success is
# not proof of release wording. These checks read the documents themselves.
#
# The documents the 0.11.0 feature changed. Older CHANGELOG entries legitimately contain words
# such as "benchmark" or "Linux", so only the 0.11.0 section of CHANGELOG.md is scanned for
# unsupported claims; the other files are scanned whole.
DOCS_CHANGED_IN_0_11_0 = (
    "README.md", "SKILL.md", "alloy-execute/SKILL.md", "alloy-usage/SKILL.md", "alloy.config.example",
    "SECURITY.md", "docs/adding-a-panelist.md", "docs/execution.md", "docs/routing.md", "docs/usage.md")
RELEASE = "0.11.0"
RELEASE_HEADING = "## [0.11.0] - 2026-09-29"


def changelog_section(version=RELEASE):
    """The text of one CHANGELOG entry: from its `## [version]` heading to the next `## [`."""
    raw = read("CHANGELOG.md")
    match = re.search(r"(?m)^## \[" + re.escape(version) + r"\][^\n]*\n", raw)
    if not match:
        raise AssertionError("CHANGELOG.md has no %s entry" % version)
    rest = raw[match.start():]
    nxt = re.search(r"(?m)^## \[", rest[len(match.group(0)):])
    return rest if not nxt else rest[:len(match.group(0)) + nxt.start()]


def plain(text):
    """Documentation text with the markup that wraps lines or emphasises words removed, so a
    sentence split across lines, a `code span` and a **bold** phrase all read as plain prose."""
    for old, new in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"')):
        text = text.replace(old, new)
    text = re.sub(r"(?m)^\s*#+ ?", "", text)          # markdown headings and config-file comments
    text = text.replace("`", "").replace("**", "")
    return re.sub(r"\s+", " ", text).strip()


def blocks(raw):
    """Paragraphs, list items, table rows and code lines of a document, as raw text."""
    out, current = [], []

    def flush():
        if current:
            out.append("\n".join(current))
            del current[:]
    for line in raw.splitlines():
        stripped = line.strip()
        starts_new = bool(re.match(r"(?:[-*+] |\d+\. |\||```)", stripped))
        if not stripped or starts_new:
            flush()
        if stripped:
            current.append(line)
    flush()
    return out


def sentences(raw):
    """Sentences of a document. A sentence ends at ./!/? followed by a capital, a quote or an
    opening bracket, so `e.g. on Linux` and version numbers stay in one piece."""
    found = []
    for block in blocks(raw):
        found.extend(s for s in re.split(r'(?<=[.!?])\s+(?=[A-Z"(\[<])', plain(block)) if s)
    return found


_NEGATION = re.compile(r"\b(?:not|no|never|cannot|without|nor|neither|refus\w*|unmatched|unknown|"
                       r"unavailable|unsupported|isn't|doesn't|aren't|can't|won't)\b|n't\b", re.I)

# (name, pattern, context, absolute)
#   pattern  what makes a sentence a claim of that kind
#   context  the sentence is only considered when it also matches this (None: always)
#   absolute True: never allowed, however phrased; False: allowed only when the same sentence
#            is a negation or a limitation ("Cursor does not run on Linux")
UNSUPPORTED_CLAIMS = (
    ("Linux support", r"\blinux\b", r"\bcursor\b", False),
    ("benchmark quality", r"\bbenchmark", r"\bcursor\b", False),
    ("Cursor superiority", r"\b(?:outperform\w*|beats?|best[- ]in[- ]class|state[- ]of[- ]the[- ]art|"
                           r"better than|higher[- ]quality)\b", r"\bcursor\b", True),
    ("live quota", r"\b(?:live|real[- ]?time)\b", r"\bcursor\b.*\b(?:quota|usage|capacity|pools?)\b|"
                                                  r"\b(?:quota|usage|capacity|pools?)\b.*\bcursor\b", False),
    ("complete filesystem-change observation",
     r"\b(?:every|all|any|whole|entire|complete)\b[^.;]{0,30}\bfile ?system\b|\bfile ?system[- ]change", None, False),
    ("credential isolation or exfiltration protection",
     r"\bcredential isolation\b|\bexfiltration\b|\b(?:complete|full|total|guaranteed) (?:confidentiality|secrecy)\b",
     None, False),
    ("a fifth provider previously dropped by a four-worker pool",
     r"\bfour[- ]worker\b|\bworker pool of (?:four|4)\b|\bfifth (?:provider|panelist|adapter|result|entry)\b"
     r"[^.;]{0,80}\b(?:dropp\w+|omitted|lost|discarded)\b|\bpreviously (?:dropped|lost|omitted)\b", None, True),
)


# The shapes an unsupported claim takes when it is stated outright. These are judged on the
# CLAUSE (up to the previous comma or semicolon), not the whole sentence, so a long sentence that
# happens to contain a "not" elsewhere cannot launder "Alloy shows live Cursor quota".
POSITIVE_CLAIMS = (
    ("Linux support", r"\b(?:supports?|supported|works?|runs?|running|usable|available|enabled)\b[^.;,]{0,25}\blinux\b"
                      r"|\bcursor\b[^.;,]{0,25}\blinux\b"),
    ("benchmark quality", r"\bcursor\b[^.;,]{0,60}\b(?:benchmark\w*|outperform\w*|beats?|top[- ]tier)\b"
                          r"|\b(?:benchmark\w*|measured) (?:quality|score|accuracy)\b"),
    ("live quota", r"\b(?:shows?|provides?|reports?|displays?|reads?|fetches?|offers?|gives?|has|exposes?)\b[^.;,]{0,30}"
                   r"\b(?:live|real[- ]?time)\b[^.;,]{0,25}\b(?:quota|usage|capacity|meters?)\b"
                   r"|\b(?:live|real[- ]?time)\b[^.;,]{0,15}\bcursor\b[^.;,]{0,15}\b(?:quota|usage|capacity)\b"
                   r"|\bcursor\b[^.;,]{0,20}\b(?:quota|usage|capacity)\b[^.;,]{0,25}\b(?:live|real[- ]?time)\b"
                   r"|\bcursor\b[^.;,]{0,30}\b(?:has|exposes|provides|offers|reports)\b[^.;,]{0,10}\b(?:a |an )?(?:usage|quota)\b"
                   r"[^.;,]{0,10}\b(?:api|command|source|endpoint)\b"),
    ("complete filesystem-change observation",
     r"\b(?:observes?|detects?|catches|tracks?|monitors?|proves?|guarantees?|notices)\b[^.;,]{0,30}"
     r"\b(?:every|all|any|whole|entire|complete)\b[^.;,]{0,25}\bfile ?system\b|\bcomplete file ?system\b"),
    ("credential isolation or exfiltration protection",
     r"\b(?:provides?|gives?|offers?|guarantees?|achieves?|is|are)\b[^.;,]{0,20}\b(?:complete|full|total|perfect) "
     r"(?:credential|secret)s? isolation\b|\bexfiltration[- ](?:proof|safe)\b"
     r"|\b(?:is|are) an? (?:data[- ])?exfiltration (?:boundary|sandbox)\b|\bprevents? (?:data[- ])?exfiltration\b"),
)


def unsupported_claims(text):
    """[(claim, sentence)] for every sentence that makes a claim the release does not support.

    Two layers. A sentence that is about a claimed topic (Linux, benchmarks, live quota, filesystem
    observation, credential isolation, a fifth provider) must itself be a negation or a limit
    ("Cursor does not run on Linux"); and a sentence that STATES a claim outright must not, in its
    own clause, carry a negation. Both are heuristics for prose, backed by the required-sentence
    check, which pins the exact honest wording."""
    found = []
    for sentence in sentences(text):
        for name, pattern, context, absolute in UNSUPPORTED_CLAIMS:
            if not re.search(pattern, sentence, re.I):
                continue
            if context and not re.search(context, sentence, re.I):
                continue
            if absolute or not _NEGATION.search(sentence):
                found.append((name, sentence[:160]))
        for name, pattern in POSITIVE_CLAIMS:
            for match in re.finditer(pattern, sentence, re.I):
                start = max(sentence.rfind(d, 0, match.start()) for d in ".;,") + 1
                if not _NEGATION.search(sentence[start:match.end()]):
                    found.append((name, sentence[:160]))
                    break
    return found


# (file, what the sentence establishes, pattern on the document's plain text)
REQUIRED_WORDING = (
    # -- CHANGELOG, 0.11.0 entry -------------------------------------------------------------
    ("CHANGELOG", "Cursor is macOS only", r"Cursor runs on macOS only"),
    ("CHANGELOG", "no sandbox, Linux or any other platform: every role refused, override never helps",
     r"on Linux and on any other platform, every Cursor role is refused, and ALLOY_ALLOW_UNSANDBOXED=1 does not change that"),
    ("CHANGELOG", "every Cursor process goes through one sandboxed gateway",
     r"Every Cursor process \(login status, version and help probes, model discovery, panels, Makers, Checkers\) is "
     r"started through one gateway that wraps it in /usr/bin/sandbox-exec"),
    ("CHANGELOG", "panels and Checkers: ask mode plus OS write denial",
     r"Panels and Checkers run --mode ask inside the sandbox: a private per-dispatch runtime directory and the CLI file login are writable, "
     r"process execution is denied except three literal paths \(the Cursor CLI's own bundled Node runtime binary, the build's "
     r"bundled rg and /usr/bin/sw_vers\), and hard links are denied\. /bin/sh and every other shell, "
     r"/usr/bin/open, /usr/bin/log and everything else stay denied\. Under Alloy, the OS sandbox denies shell execution and file writes outside the task's allowed paths; the model may be offered tools it cannot use\. /usr/bin/security is denied in every role, and Alloy itself never runs security\. Each of the three is verified before use"),
    ("CHANGELOG", "the launcher and any wrapper are never executed; the build's node is started directly",
     r"Alloy never executes the cursor-agent shell launcher, or any wrapper script in front of it.*"
     r"starts <build>/node --use-system-ca <build>/index\.js directly, with CURSOR_INVOKED_AS=cursor-agent in its environment"),
    ("CHANGELOG", "the launcher's compile cache is reproduced inside the private runtime",
     r"The launcher's compile cache is reproduced inside the private runtime, never in your home cache"),
    ("CHANGELOG", "known issue: two load-sensitive tests, named, not fixed",
     r"Known issues: .*Two tests can fail once under heavy machine load and pass on a re-run of the same code\. They are "
     r"not fixed in this release: test_alloy\.CursorJsonTests\.test_secret_shaped_output_is_absent_from_every_persisted_sink "
     r".*test_alloy\.CursorManagedMakerTests\.test_maker_gateway_requires_a_managed_linked_worktree_and_a_matching_cwd"),
    ("CHANGELOG", "Makers: only non-Git worktree content and the private runtime",
     r"only the non-Git contents of the Alloy-owned worktree, the private runtime and the CLI file login are writable, and Git metadata, "
     r"the source checkout and everything else stay write-denied"),
    ("CHANGELOG", "no force/auto-approval bypass in any role",
     r"No Cursor role receives --force, --yolo, auto-review or MCP approval flags"),
    ("CHANGELOG", "plan mode and the sandbox flag wrote outside the workspace",
     r"plan mode and --sandbox enabled both wrote outside the workspace"),
    ("CHANGELOG", "ask mode refused but is not the boundary",
     r"ask mode refused in three runs, but it is a tool-mode control, not an operating-system guarantee"),
    ("CHANGELOG", "the macOS sandbox is the write boundary", r"The macOS sandbox is the write boundary"),
    ("CHANGELOG", "fingerprints and canaries only detect", r"only detect a change afterwards"),
    ("CHANGELOG", "sensitive reads are denied and additive-only",
     r"Every Cursor role denies reads of a fixed list of credential locations"),
    ("CHANGELOG", "configured denials add, never remove",
     r"ALLOY_CURSOR_DENY_READ_PATHS \(comma-separated absolute paths, no globs\); you can add denials but not remove built-in ones"),
    ("CHANGELOG", "API key and endpoint are scrubbed and rejected",
     r"CURSOR_API_KEY and CURSOR_API_ENDPOINT are scrubbed from every child environment and --api-key, --endpoint and "
     r"--header are rejected"),
    ("CHANGELOG", "accepted keychain-login / repository / network residual risk",
     r"Accepted residual risk, stated plainly: the Cursor process reads its own file login, can read the repository and uses the network"),
    ("CHANGELOG", "not an exfiltration boundary",
     r"a Cursor role is not a data-exfiltration boundary and a Checker is not exfiltration-proof"),
    ("CHANGELOG", "redaction and a redacted Checker packet mitigate it",
     r"redaction of JWT-shaped values, secret assignments and authorization headers before every persisted output, and a "
     r"Checker packet built only from redacted text"),
    ("CHANGELOG", "Alloy never reads the keychain", r"Alloy never reads the keychain or runs security"),
    ("CHANGELOG", "explicit model whose family comes from its ID; auto refused",
     r"Every Cursor call names one explicit model whose family is derived from its ID"),
    ("CHANGELOG", "auto and unknown IDs refused everywhere",
     r"auto and unknown prefixes are refused at every routing and dispatch step"),
    ("CHANGELOG", "all Cursor starter profiles ship disabled and subscription-billed",
     r"five Cursor starter profiles, all disabled and billed as subscription"),
    ("CHANGELOG", "fast variants need an explicit opt-in", r"fast variants need a per-profile cursor_fast: true"),
    ("CHANGELOG", "fresh-context sessions", r"Managed Cursor workers use fresh_context_fallback"),
    ("CHANGELOG", "Cursor quota is unknown and never blocks",
     r"Cursor's CLI has no usage source, so Cursor quota is unknown and never blocks routing"),
    ("CHANGELOG", "per-call tokens are not quota", r"Per-call token counts are never treated as quota"),
    ("CHANGELOG", "the honest limits of the release",
     r"Limits of this release: Cursor does not run on Linux, there is no Cursor benchmark row, Cursor quota cannot be "
     r"read live, and Alloy does not observe every filesystem change"),
    # the five fixes already on the branch, with the claims exactly as the plan states them
    ("CHANGELOG", "agy fix 1: read grants for the staged prompt and the worktree (agy 1.2.12)",
     r"Grant agy read access to the staged prompt directory and the worktree with path-scoped read_file\(<dir>\) rules, "
     r"one per --add-dir root\. agy 1\.2\.12 ignores bare tool names"),
    ("CHANGELOG", "agy fix 2: DEVNULL stdin",
     r"Give agy DEVNULL as stdin\. agy 1\.2\.12 treats a file on stdin as a read_file that headless mode denies"),
    ("CHANGELOG", "agy fix 3: two settings grammars",
     r"Keep two agy settings grammars\. agy 1\.1 keeps bare read-tool names; agy 1\.2\.x uses path-scoped "
     r"read_file\(\.\.\.\) grants and is the fail-closed current grammar"),
    ("CHANGELOG", "agy fix 4: the exact gitdir, and the common directory only for the standard layout",
     r"grant agy the exact gitdir that \.git points to and, only for the standard <common>/worktrees/<id> layout, that "
     r"gitdir's common directory\. Other layouts receive the exact gitdir only"),
    ("CHANGELOG", "agy fix 5: owner-private gate-log directory for Checkers",
     r"Grant agy Checkers read access to the owner-private gate-log directory"),
    # -- SECURITY --------------------------------------------------------------------------------
    ("SECURITY", "plan mode wrote inside and outside the workspace",
     r"plan mode wrote both inside and outside the workspace"),
    ("SECURITY", "the sandbox flag wrote outside", r"--sandbox enabled wrote outside it"),
    ("SECURITY", "ask mode refused but is not the boundary",
     r"Ask mode refused in all three recorded runs, but it is a tool-mode control, not an operating-system guarantee"),
    ("SECURITY", "sandbox-exec is the write boundary",
     r"The write boundary is a sandbox-exec profile that Alloy generates and self-tests before any Cursor process starts"),
    ("SECURITY", "macOS only; Linux refused; the override never helps",
     r"macOS only\. On Linux and every other platform, and whenever the sandbox self-test fails or sandbox-exec is "
     r"missing or not root-owned, every Cursor role is refused\. ALLOY_ALLOW_UNSANDBOXED=1 does not override this"),
    ("SECURITY", "only the private runtime is writable for a panel or Checker",
     r"a private, per-dispatch runtime directory and the CLI file login writable"),
    ("SECURITY", "process execution is denied except exactly three literal paths",
     r"Process execution is denied except exactly three literal paths: the Cursor CLI's own bundled Node runtime binary "
     r"\(<build>/node\), the build's bundled rg and /usr/bin/sw_vers\. /bin/sh and every other shell, "
     r"/usr/bin/open, /usr/bin/log and everything else stay denied, and hard-link creation is denied"),
    ("SECURITY", "why the three are safe to allow, and that Alloy itself never runs security",
     r"Under Alloy, the OS sandbox denies shell execution and file writes outside the task's allowed paths; the model may be offered tools it cannot use. /usr/bin/security is "
     r"denied in every role\. Alloy itself never runs security\. Before any Cursor process "
     r"starts, Alloy checks that node and rg are regular files owned by you and not writable by group or others, and that "
     r"sw_vers is a regular, non-symlink, root-owned file not writable by others; a failed check refuses the role"),
    ("SECURITY", "the launcher and any wrapper are never executed",
     r"Alloy never executes the cursor-agent shell launcher, or any wrapper script in front of it\..*"
     r"starts the build's bundled Node runtime directly: <build>/node --use-system-ca <build>/index\.js"),
    ("SECURITY", "only non-Git worktree content and the runtime are writable for a Maker",
     r"Only the non-Git contents of the Alloy-owned worktree, the private runtime and the CLI file login are writable"),
    ("SECURITY", "no approval bypass in any role", r"No Cursor role ever gets an approval bypass"),
    ("SECURITY", "tripwires detect, they do not prevent", r"Tripwires detect; they do not prevent"),
    ("SECURITY", "the sandbox is the preventive control", r"the sandbox is the preventive control"),
    ("SECURITY", "every role denies the documented sensitive paths",
     r"Every Cursor role denies reads of these locations, and everything under them"),
    ("SECURITY", "denials add, never remove",
     r"you can add denials but never remove a built-in one"),
    ("SECURITY", "accepted keychain-login / repository / network risk",
     r"Accepted residual risk\. Cursor's login is a file that the Cursor CLI can read and refresh"),
    ("SECURITY", "not an exfiltration boundary, no complete credential isolation",
     r"not an exfiltration boundary and Alloy does not claim complete credential isolation or an exfiltration-proof Checker"),
    ("SECURITY", "the mitigations do not close the risk",
     r"Mitigations: ask mode for panels and Checkers, denial of descendant processes other than the three executables above, "
     r"the credential-read denials above"),
    ("SECURITY", "persisted-sink redaction covers every sink",
     r"\(result\.md, stdout\.txt, stderr\.txt and all of status\.json, including the command\)"),
    ("SECURITY", "omitting recognised secrets from the packet is not read isolation",
     r'Recognized secrets are not staged"? does not mean Cursor cannot read repository data'),
    ("SECURITY", "API key and endpoint are never passed on",
     r"CURSOR_API_KEY and CURSOR_API_ENDPOINT are never passed on"),
    ("SECURITY", "Alloy never reads the keychain",
     r"Cursor CLI is denied keychain access and cannot start /usr/bin/security\. "
     r"Alloy never reads the macOS keychain and never runs security\."),
    *tuple((key, "file login, never keychain", pattern)
           for key in ("CHANGELOG", "SECURITY", "README", "PANELIST_GUIDE")
           for pattern in (r"AGENT_CLI_CREDENTIAL_STORE=file cursor-agent login",
                           r"login lives in ~/.cursor/auth\.json \(0600\)",
                           r"Cursor CLI is denied keychain access and cannot start /usr/bin/security")),
    # -- README ----------------------------------------------------------------------------------
    ("README", "Cursor is macOS only", r"the Cursor provider runs on macOS only"),
    ("README", "confined by a macOS sandbox, not by its own flags",
     r"Cursor is confined by a macOS sandbox, not by its own flags"),
    ("README", "no force or auto-approval flag", r"No Cursor role gets a force or auto-approval flag"),
    ("README", "refused on Linux and without a sandbox; the override never helps",
     r"Cursor is refused on Linux and whenever the sandbox is unavailable; ALLOY_ALLOW_UNSANDBOXED never overrides that"),
    ("README", "accepted risk, not an exfiltration boundary", r"a Cursor role is not an exfiltration boundary"),
    ("README", "detection only", r"Content fingerprints and canaries only detect changes"),
    ("README", "profiles ship disabled", r"Cursor profiles ship disabled"),
    ("README", "quota unknown", r"Cursor quota is unknown unless you set it by hand"),
    ("README", "doctor shows the missing-sandbox state", r"\[no-sbx\] cursor"),
    ("README", "the deny-path setting is documented",
     r"ALLOY_CURSOR_DENY_READ_PATHS \| _\(unset\)_ \| extra comma-separated absolute paths Cursor may not read; adds to the "
     r"built-in credential list, never removes from it"),
    # -- SKILL.md and alloy-execute/SKILL.md ------------------------------------------------------
    ("SKILL", "Cursor panel: ask mode inside a macOS sandbox", r"cursor runs ask-mode inside a macOS sandbox-exec profile"),
    ("SKILL", "plan mode / --sandbox are not boundaries, ask mode is defence in depth",
     r"plan mode and Cursor's --sandbox flag are not boundaries, and --mode ask is defense in depth"),
    ("SKILL", "refused on Linux and [no-sbx]; the override never applies",
     r"It is refused on Linux and whenever doctor shows \[no-sbx\]; do not try to work around that, and "
     r"ALLOY_ALLOW_UNSANDBOXED never applies to it"),
    ("SKILL", "no force or auto-approval flag in any Cursor role",
     r"no force or auto-approval flag in any Cursor role"),
    ("SKILL", "Maker: non-Git worktree content and a private runtime only",
     r"A Cursor Maker runs Cursor's normal agent mode inside the macOS sandbox and can write only the non-Git contents of "
     r"its worktree, a private runtime and the CLI file login"),
    ("SKILL", "Checker: ask mode, only the runtime writable",
     r"a Cursor Checker runs --mode ask with that runtime and the CLI file login writable"),
    ("SKILL", "profiles ship disabled and the role is refused without the sandbox",
     r"Cursor profiles ship disabled.*If the sandbox is unavailable the role is refused"),
    ("EXECUTE_SKILL", "Cursor only inside the sandbox boundary",
     r"Cursor \(macOS only\) is a valid Maker or Checker only inside Alloy's sandbox-exec boundary"),
    ("EXECUTE_SKILL", "Checker ask mode, Maker non-Git content, no bypass flag",
     r"a Checker uses --mode ask with a private runtime and the CLI file login writable, a Maker can write only non-Git worktree content, "
     r"and no Cursor role gets a force or auto-approval flag"),
    ("EXECUTE_SKILL", "plan mode and --sandbox are not boundaries",
     r"Cursor's plan mode and --sandbox flag are not boundaries"),
    ("EXECUTE_SKILL", "fail closed and never override",
     r"refuses the role; report that, do not work around it, and never set ALLOY_ALLOW_UNSANDBOXED for it"),
    ("EXECUTE_SKILL", "profiles ship disabled", r"Cursor profiles ship disabled"),
    ("USAGE_SKILL", "Cursor quota is unknown unless set by hand",
     r"Cursor shows unknown unless the user sets its two pools"),
    # -- alloy.config.example --------------------------------------------------------------------
    ("CONFIG", "canonical settings", r"ALLOY_BIN_CURSOR=/absolute/path/to/cursor-agent"),
    ("CONFIG", "model pin", r"ALLOY_CURSOR_MODEL=composer-2\.5"),
    ("CONFIG", "effort pin", r"ALLOY_CURSOR_EFFORT=high"),
    ("CONFIG", "legacy aliases are deprecated",
     r"Legacy names, read only when the canonical one is unset \(the canonical key wins\): ALLOY_BIN_CURSOR_AGENT, "
     r"ALLOY_CURSOR_AGENT_MODEL \(deprecated; doctor warns\), ALLOY_CURSOR_AGENT_EFFORT"),
    ("CONFIG", "additive-only deny list",
     r"Additive only: the built-in list .* always applies and cannot be removed"),
    ("CONFIG", "the API key and endpoint are scrubbed, not supported",
     r"CURSOR_API_KEY and CURSOR_API_ENDPOINT are deliberately NOT supported: Alloy removes both from every child "
     r"process's environment"),
    ("CONFIG", "refused on Linux; the override never helps",
     r"Cursor is refused on Linux and whenever its sandbox is unavailable, and ALLOY_ALLOW_UNSANDBOXED never overrides that"),
    # -- the Cursor documents ----------------------------------------------------------------------
    ("ROUTING", "family from the model ID; auto and unknown refused",
     r"auto can change providers between calls, so it and every unknown model ID are refused at every step"),
    ("ROUTING", "profiles ship disabled", r"Profiles ship disabled\. Five starter profiles use adapter cursor"),
    ("ROUTING", "no Cursor benchmark row", r"Cursor has no benchmark row, so every Cursor profile is unmatched"),
    ("ROUTING", "fast variants are opt-in per profile",
     r"they are refused \(-fast IDs, \[fast=true\]\) unless the profile sets cursor_fast: true"),
    ("ROUTING", "effort travels inside --model", r"Alloy never passes --effort to Cursor"),
    ("ROUTING", "explicit setup enablement", r"alloy setup --enable-cursor"),
    ("ROUTING", "unknown quota does not block", r"Unknown quota does not block routing"),
    ("USAGE", "tokens are not capacity",
     r"the token counts in a call's JSON output are not subscription capacity, so Alloy reads no Cursor usage and never "
     r"derives quota from per-call tokens"),
    ("USAGE", "unknown does not block", r"Both pools are unknown, and unknown does not block routing"),
    ("EXECUTION", "macOS only; refused otherwise; the override never helps",
     r"Cursor can serve as Maker or Checker on macOS only\. Alloy refuses every Cursor role"),
    ("EXECUTION", "the override never helps", r"ALLOY_ALLOW_UNSANDBOXED=1 never changes this"),
    ("EXECUTION", "the two roles' allowlists",
     r"\| Checker \| --mode ask \| The per-dispatch private runtime and CLI file login \| Denied except three literal paths: the Cursor "
     r"CLI's own bundled Node runtime binary, the build's bundled rg and /usr/bin/sw_vers \|"),
    ("EXECUTION", "the launcher and any wrapper are never executed; only the build's node is allowed",
     r"Alloy never runs the cursor-agent shell launcher or any wrapper script in front of it\..*"
     r"starts <build>/node --use-system-ca <build>/index\.js \.\.\. directly\. A Checker's sandbox allows exactly three "
     r"executables: that node, the build's bundled rg and /usr/bin/sw_vers\. /bin/sh and every other "
     r"shell, /usr/bin/open, /usr/bin/log and everything else stay denied\. Under Alloy, the OS sandbox denies shell execution and file writes outside the task's allowed paths; the model may be offered tools it cannot use\. /usr/bin/security is denied in every role, and Alloy itself never runs it"),
    ("EXECUTION", "a closed grammar rejects a later rewrite",
     r"Alloy checks the complete final command line against a closed grammar before starting the sandbox"),
    ("EXECUTION", "detection, not prevention", r"Detection, not prevention\. The sandbox is the boundary"),
    ("EXECUTION", "not an exfiltration boundary", r"a Cursor role is not an exfiltration boundary"),
    ("PANELIST_GUIDE", "the real adapter's contract",
     r"is the only way to obtain a Cursor command line"),
    ("PANELIST_GUIDE", "the staged prompt", r"stdin_from_prompt = False"),
    ("PANELIST_GUIDE", "no direct spawn", r"by design no code path runs cursor-agent directly"),
    ("PANELIST_GUIDE", "the build's node is the only executable a panel or Checker profile allows",
     r"returns /usr/bin/sandbox-exec -f <profile> <build>/node --use-system-ca <build>/index\.js \.\.\..*"
     r"A panel or Checker profile allows exactly three literal executables \(the build's node, its bundled rg and "
     r"/usr/bin/sw_vers\), each verified first; the CLI's own code starts the last two and Alloy "
     r"never runs them"),
)

DOC_FILES = {
    "CHANGELOG": None,      # the 0.11.0 entry only
    "SECURITY": "SECURITY.md", "README": "README.md", "SKILL": "SKILL.md",
    "EXECUTE_SKILL": "alloy-execute/SKILL.md", "USAGE_SKILL": "alloy-usage/SKILL.md",
    "CONFIG": "alloy.config.example", "ROUTING": "docs/routing.md", "USAGE": "docs/usage.md",
    "EXECUTION": "docs/execution.md", "PANELIST_GUIDE": "docs/adding-a-panelist.md",
}


def document(key):
    return changelog_section() if key == "CHANGELOG" else read(DOC_FILES[key])


def load_alloy_module():
    """The production module, only for facts the documents must agree with."""
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("alloy_release_facts", str(ROOT / "bin" / "alloy"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ReleaseWordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = dict((key, plain(document(key))) for key in DOC_FILES)
        cls.facts = load_alloy_module()

    def test_every_required_sentence_is_present(self):
        missing = ["%s: %s" % (key, why) for key, why, pattern in REQUIRED_WORDING
                   if not re.search(pattern, self.text[key], re.I | re.S)]
        self.assertEqual(missing, [])

    def test_cursor_setup_stays_inside_the_worked_example_list(self):
        example = read("docs/adding-a-panelist.md").split("## Worked example: `cursor`", 1)[1]
        setup = re.search(r"(?ms)^- \*\*Setup\.\*\* (.*?)(?=^- \*\*Auth\.\*\*)", example)
        self.assertIsNotNone(setup, "file-login setup needs its own worked-example bullet")
        lines = setup.group(0).rstrip().splitlines()
        self.assertTrue(all(not line.strip() or line.startswith("  ") for line in lines[1:]),
                        "setup paragraphs must remain indented inside the list")
        self.assertIn("AGENT_CLI_CREDENTIAL_STORE=file cursor-agent login", setup.group(0))

    def test_release_instructions_capture_the_live_record_without_claiming_offline_proof(self):
        text = read("docs/execution.md")
        self.assertIn("ALLOY_LIVE_CURSOR=1 ALLOY_LIVE_CURSOR_MODEL=composer-2.5", text)
        self.assertIn("python3 tests/live/cursor_ask_release.py", text)
        self.assertIn('2>&1 | tee "$report_dir/ask-gate.log"', text)
        self.assertIn("CURSOR_ASK_RELEASE_RECORD", text)
        self.assertIn("every check true", text)
        self.assertIn("set -o pipefail", text)
        self.assertIn('--verify-report "$report_dir"', text)
        self.assertIn('> "$report_dir/release-report.json"', text)
        self.assertIn("Offline tests and the stand-in CI gate do not supply this live evidence.", text)

    def test_release_instructions_require_the_authenticated_real_build_gate_and_its_log(self):
        text = read("docs/execution.md")
        self.assertIn("ALLOY_CURSOR_SANDBOX_GATE=1 ALLOY_CURSOR_BUILD_GATE=1", text)
        self.assertIn("python3 -m unittest discover -s tests -p 'test_cursor_sandbox_release_gate.py' -v", text)
        self.assertIn('2>&1 | tee "$report_dir/build-gate.log"', text)
        self.assertIn("test_status_reaches_the_authenticated_state_under_the_production_panel_profile", text)
        self.assertIn("neither gate may be skipped", plain(text))
        self.assertIn("outside any Maker sandbox", text)

    def test_mach_policy_comment_does_not_claim_keychain_access(self):
        # The security explanation must agree with the file-only credential policy.
        text = read("tests/test_alloy.py")
        comment = re.search(r"(?m)^\s*# Mach services that act for a caller.*(?:\n\s*#.*)*", text)
        self.assertIsNotNone(comment)
        self.assertNotRegex(plain(comment.group(0)), r"keychain login item.*stay reachable")
        self.assertIn("keychain services stay denied", plain(comment.group(0)))

    def test_no_document_still_says_the_launcher_or_the_cursor_executable_is_what_may_run(self):
        for key, text in self.text.items():
            for stale in (r"Denied except the Cursor executable", r"Process execution beyond the Cursor executable",
                          r"<cursor-agent> \.\.\.", r"execution is denied except the Cursor executable",
                          r"one literal path", r"is the only executable a Checker's sandbox allows",
                          r"the only executable a panel or Checker profile allows",
                          r"denied except the Cursor CLI's own bundled Node runtime binary[ ,.|]"):
                self.assertNotRegex(text, stale, "%s still says: %s" % (key, stale))

    def test_the_changelog_entry_is_the_latest_and_matches_the_shipped_version(self):
        raw = read("CHANGELOG.md")
        headings = re.findall(r"(?m)^## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})$", raw)
        self.assertEqual(headings[0], (RELEASE, "2026-09-29"))
        self.assertTrue(changelog_section().startswith(RELEASE_HEADING))
        self.assertEqual(self.facts.ALLOY_VERSION, RELEASE)
        self.assertGreater(len(headings), 2)
        self.assertEqual(len(set(h[0] for h in headings)), len(headings), "a duplicate release heading")

    def test_no_unsupported_claim_in_the_0_11_0_changelog_entry_or_the_changed_docs(self):
        found = []
        found.extend(("CHANGELOG 0.11.0", n, s) for n, s in unsupported_claims(changelog_section()))
        for rel in DOCS_CHANGED_IN_0_11_0:
            found.extend((rel, n, s) for n, s in unsupported_claims(read(rel)))
        self.assertEqual(found, [])

    def test_the_scan_is_scoped_to_the_0_11_0_entry(self):
        """Older entries legitimately contain such words: only the 0.11.0 entry is scanned, and a
        bad claim inside it is still found."""
        def fake(rel, body):
            return lambda name: body if name == "CHANGELOG.md" else read(name)
        older_bad = "Cursor now supports Linux and is benchmarked.\n"
        for label, current, expect_hit in (("clean 0.11.0, bad older entry", "Cursor does not run on Linux.\n", False),
                                            ("bad 0.11.0", "Cursor now supports Linux.\n", True)):
            body = ("# Changelog\n\n## [0.11.0] - 2026-09-29\n\n" + current +
                    "\n## [0.10.0] - 2026-09-26\n\n" + older_bad)
            with patch.object(sys.modules[__name__], "read", side_effect=fake("CHANGELOG.md", body)):
                section = changelog_section()
                self.assertNotIn("0.10.0", section, label)
                self.assertEqual(bool(unsupported_claims(section)), expect_hit, label)
                self.assertTrue(unsupported_claims(read("CHANGELOG.md")), "the unscoped scan would flag the older entry")

    def test_the_claim_scanner_can_fail_and_does_not_flag_honest_limits(self):
        bad = ("Cursor now supports Linux.",
               "Cursor works on Linux and macOS.",
               "Cursor is benchmarked and ranks first.",
               "Cursor outperforms every other provider.",
               "Alloy shows live Cursor quota in doctor.",
               "Alloy observes every filesystem change.",
               "A Cursor role gives complete credential isolation.",
               "The Checker is exfiltration-proof.",
               "Cursor is the fifth provider and was previously dropped by a four-worker pool.",
               "A fifth provider result was silently dropped.",
               # a negation elsewhere in a long sentence must not launder the claim
               "Alloy shows live Cursor quota, and the token counts in a call are not subscription capacity.",
               "Cursor's CLI has a usage API, and Alloy never derives quota from per-call tokens.",
               "Alloy detects every filesystem change, but it is not a data-exfiltration boundary.",
               "Cursor is benchmarked, and it does not run on Linux.")
        for sentence in bad:
            self.assertTrue(unsupported_claims(sentence), sentence)
        good = ("Cursor does not run on Linux.",
                "Cursor is refused on Linux and whenever the sandbox is unavailable.",
                "Cursor has no benchmark row.",
                "Cursor discovery only; not benchmarked.",
                "Cursor quota cannot be read live.",
                "Alloy does not observe every filesystem change.",
                "Alloy does not claim complete credential isolation or an exfiltration-proof Checker.",
                "A Cursor role is not an exfiltration boundary.",
                "Cursor is the fifth provider.",
                "Cursor's CLI has no usage command or quota API, so Alloy reads no Cursor usage.",
                "Alloy never claims Cursor is exfiltration-proof or that it observes every filesystem change.",
                "Cursor's CLI has no usage source, so Cursor quota is unknown.")
        for sentence in good:
            self.assertEqual(unsupported_claims(sentence), [], sentence)
        # a claim broken across wrapped lines and markup is still found
        self.assertTrue(unsupported_claims("Cursor is\n`supported` on\nLinux."), "wrapped claim")

    def test_the_required_sentence_check_can_fail(self):
        for key, why, pattern in REQUIRED_WORDING:
            self.assertIsNone(re.search(pattern, "an unrelated sentence about nothing", re.I | re.S), why)

    def test_security_lists_every_built_in_sensitive_read_the_code_denies(self):
        security = self.text["SECURITY"]
        for rel in tuple(self.facts._CURSOR_HOME_DENIALS) + BUILTIN_SENSITIVE:
            self.assertIn("~/" + rel, security, rel)
        # and the one generic rule for staging places, plus the pattern-based ones
        self.assertIn("1Password group containers", security)
        self.assertIn('whose name contains "secret"', security)
        # the same fixed list is named, in prose, by the changelog and the execution guide
        self.assertIn("credential", self.text["CHANGELOG"])

    def test_the_changelog_names_every_supported_cursor_build_and_every_shipped_cursor_profile(self):
        section = plain(changelog_section())
        for version in self.facts.CURSOR_SUPPORTED_VERSIONS:
            self.assertIn(version, section)
        data = json.loads(read("data/routing-defaults.json"))
        cursor = [p for p in data["profiles"] if p["adapter"] == "cursor"]
        self.assertTrue(cursor)
        for profile in cursor:
            # the documents say "ship disabled" and "billed as subscription": the data must agree
            self.assertIs(profile["enabled"], False, profile["id"])
            self.assertEqual(profile["billing_mode"], "subscription", profile["id"])
            self.assertIn(profile["id"], section)
            self.assertIn(profile["id"], self.text["ROUTING"])

    def test_every_document_the_feature_changed_exists_and_names_cursor(self):
        for rel in DOCS_CHANGED_IN_0_11_0:
            self.assertTrue((ROOT / rel).is_file(), rel)
            self.assertRegex(read(rel), r"(?i)cursor", rel)


# =============================================================================================
# 3. The cross-cutting Cursor boundary invariant
# =============================================================================================
# One final-suite test set that runs after (and independently of) the component tests. It puts a
# spy on `subprocess.Popen` itself -- the point where a process really starts -- and drives every
# Cursor subprocess class through the PRODUCTION code paths, behind the mock sandbox-exec and a
# fake cursor-agent. The component suites test each class alone; nothing else asserts the global
# claim that no forbidden argv or environment value crosses any boundary after every rewrite.
import test_execution as te      # noqa: E402  (module import: its test classes are not collected here)

core, e = te.core, te.e
routing = core.routing
usage = routing.usage

POISON = {
    "CURSOR_API_KEY": "poison-cursor-key-7e1d90",
    "CURSOR_API_ENDPOINT": "https://poison-endpoint.invalid/v1",
    "TYPESAFE_API_KEY": "poison-router-key-a1b2c3",
    "OPENROUTER_API_KEY": "poison-router-key-d4e5f6",
    "SSH_AUTH_SOCK": "/private/tmp/poison-agent.sock",
    "AWS_SECRET_ACCESS_KEY": "poison-aws-0a1b2c",
    "GITHUB_TOKEN": "poison-gh-3d4e5f",
    "OPENAI_API_KEY": "poison-openai-6a7b8c",
}
POISON_VALUES = tuple(POISON.values())
# Names the private runtime always overwrites (they are provided to the child, never inherited): an
# ambient value must never be what a Cursor process sees.
AMBIENT_OVERWRITTEN = {"AGENT_CLI_CREDENTIAL_STORE": "default", "CURSOR_INVOKED_AS": "agent", "NODE_COMPILE_CACHE": "/private/var/poison-compile-cache"}
# What may be in a Cursor child's environment: the production allowlist, the exact private
# runtime and the terminal defaults; the tests add only the mock's own knobs and the locale.
RUNTIME_ENV = ("HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR", "NO_COLOR", "TERM", "CI",
               "CURSOR_INVOKED_AS", "NODE_COMPILE_CACHE", "AGENT_CLI_CREDENTIAL_STORE")

# Every control the release must never let reach Cursor, in the spellings a rewrite could use.
FORBIDDEN_LONG = ("--force", "--yolo", "--auto-review", "--approve-mcps", "--plan", "--plugin-dir",
                  "--add-dir", "--resume", "--continue", "--worktree", "--worktree-base",
                  "--api-key", "--endpoint", "--header")
FORBIDDEN_SHORT = ("-f", "-w", "-e", "-H")
INFERENCE_FLAGS = ("-p", "--trust", "--skip-worktree-setup")
INFERENCE_VALUE_FLAGS = ("--output-format", "--workspace", "--model", "--sandbox", "--mode")
METADATA = tuple(t + ["--sandbox", "disabled"] for t in (["status"], ["--version"], ["--help"], ["--list-models"]))


def forbidden_tokens(argv):
    """Every token in argv that is a forbidden control: exact, `--flag=value`, or an attached
    short form (`-eVALUE`, `-HVALUE`, `-fx`). Independent of the production validator."""
    found = []
    for tok in argv:
        if not isinstance(tok, str) or not tok.startswith("-"):
            continue
        if tok in FORBIDDEN_LONG or tok in FORBIDDEN_SHORT:
            found.append(tok)
        elif any(tok.startswith(f + "=") for f in FORBIDDEN_LONG):
            found.append(tok.split("=", 1)[0] + "=...")
        elif re.match(r"^-[efHw][^-]", tok):
            found.append(tok[:2] + "...")
    return found


def inference_problems(tail, maker):
    """Everything wrong with a print-mode Cursor tail (after the executable), from the plan's
    closed grammar: exactly one of each control, `--mode ask` for a panel/Checker and no
    `--mode` for a Maker, `--sandbox enabled`, JSON output, one explicit known model, one
    bounded staged-file instruction, and nothing else."""
    problems = ["forbidden " + t for t in forbidden_tokens(tail)]
    counts = collections.Counter(t for t in tail if t.startswith("-"))
    for flag in INFERENCE_FLAGS + INFERENCE_VALUE_FLAGS:
        want = 0 if (flag == "--mode" and maker) else 1
        if counts[flag] != want:
            problems.append("%s appears %d times, expected %d" % (flag, counts[flag], want))
    unknown = [t for t in counts if t not in INFERENCE_FLAGS + INFERENCE_VALUE_FLAGS]
    problems.extend("unknown option " + t for t in unknown)
    values, positional, i = {}, [], 0
    while i < len(tail):
        tok = tail[i]
        if tok in INFERENCE_VALUE_FLAGS and i + 1 < len(tail):
            values[tok] = tail[i + 1]
            i += 2
            continue
        if not tok.startswith("-"):
            positional.append(tok)
        i += 1
    if values.get("--output-format") != "json":
        problems.append("output format is not json")
    if values.get("--sandbox") != "disabled":
        problems.append("sandbox is not disabled")
    if not maker and values.get("--mode") != "ask":
        problems.append("mode is not ask")
    model = values.get("--model", "")
    if not model or model.startswith("auto") or core.cursor_model_family(model) is None:
        problems.append("the model is not one explicit known-family model")
    if not os.path.isabs(values.get("--workspace", "")):
        problems.append("workspace is not absolute")
    if len(positional) != 1 or tail[-1] != (positional or [None])[0]:
        problems.append("expected exactly one trailing instruction, got %r" % (positional,))
    else:
        text = positional[0]
        if not text.startswith('Read "') or "prompt_in/prompt.md" not in text or len(text) > 4096:
            problems.append("the instruction is not the bounded staged-file pointer")
    return problems


class SpawnSpy(object):
    """Records every process start (argv, environment, stdin, cwd) and lets it happen."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()
        self._real = subprocess.Popen

    def __call__(self, argv, *args, **kwargs):
        env = kwargs.get("env")
        record = {"argv": list(argv) if isinstance(argv, (list, tuple)) else argv,
                  "env": dict(env) if env is not None else None, "stdin": kwargs.get("stdin"),
                  "cwd": kwargs.get("cwd"), "shell": bool(kwargs.get("shell"))}
        with self._lock:
            self.calls.append(record)
        return self._real(argv, *args, **kwargs)

    def __enter__(self):
        self._patch = patch.object(subprocess, "Popen", side_effect=self)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class InvariantBase(te.CursorManagedBase):
    """The managed-execution fixture (real temporary Git repo, fake cursor-agent behind the mock
    sandbox-exec) with the fake CLI taught `--list-models`, plus the audit of a spy's record."""

    @classmethod
    def setUpClass(cls):
        super(InvariantBase, cls).setUpClass()
        text = Path(cls.cli).read_text()
        marker = "if argv == ['--help', '--sandbox', 'disabled']:"
        assert text.count(marker) == 1
        listing = ("if argv == ['--list-models', '--sandbox', 'disabled']:\n"
                   "    log('models'); print('Available models'); print('composer-2.5 - Composer 2.5')\n"
                   "    print('claude-opus-5-5-high - Claude Opus 5.5'); print('auto - Auto'); raise SystemExit(0)\n")
        Path(cls.cli).write_text(text.replace(marker, listing + marker, 1))

    def setUp(self):
        super(InvariantBase, self).setUp()
        self.real_dispatch()
        self.patch_e("probe", side_effect=te.REAL_PROBE)          # the status/help probes are real too
        self.plan(maker_writes=[dict(path="file.txt", text="new\n")])
        self.cli_real = os.path.realpath(self.cli)                    # the launcher: Alloy must never start it
        self.node_real = os.path.realpath(self.install.node)            # the build's own runtime
        self.index_real = os.path.realpath(self.install.index)

    # -- classification and audit ------------------------------------------------------------ #
    def classify(self, call):
        argv = call["argv"]
        if isinstance(argv, str):
            return "shell"
        if os.path.basename(argv[0]) == "git":
            return "git"
        if argv[0] == core.SANDBOX_EXEC:
            if os.path.realpath(argv[3]) == self.cli_real:
                return "LAUNCHER-STARTED"             # the bash launcher must never be executed, sandboxed or not
            if os.path.realpath(argv[3]) == self.node_real:
                tail = argv[6:]                       # sandbox-exec -f <profile> <node> --use-system-ca <index.js> <tail>
                if any(tail == m for m in METADATA):
                    return "metadata:" + tail[0].lstrip("-")
                return "inference"
            if argv[3] == "/bin/bash" and argv[4] == "-c" and "ALLOY_PREFLIGHT_PROBE" in argv[5]:
                return "selftest"
            return "sandbox-other"
        if (os.path.realpath(argv[0]) in (self.cli_real, self.node_real)
                or os.path.basename(argv[0]) in ("cursor-agent", "agent", "node")):
            return "UNWRAPPED-CURSOR"
        return "other"

    def cursor_children(self, spy):
        return [c for c in spy.calls if self.classify(c).split(":")[0] in ("metadata", "inference", "selftest", "sandbox-other")]

    def audit(self, spy, expect=()):
        """The global claims, asserted over every recorded process start."""
        kinds = collections.Counter(self.classify(c) for c in spy.calls)
        self.assertNotIn("UNWRAPPED-CURSOR", kinds, "a Cursor process was started outside the sandbox gateway")
        self.assertNotIn("LAUNCHER-STARTED", kinds, "the bash launcher was started")
        self.assertNotIn("sandbox-other", kinds)
        self.assertFalse(os.path.exists(self.install.marker), "the bash launcher was executed")
        for want in expect:
            self.assertGreater(kinds[want], 0, "no %s spawn was exercised (saw %s)" % (want, dict(kinds)))
        home = core.cursor_login_home()
        allowed = set(core.CURSOR_ENV_ALLOW) | set(RUNTIME_ENV)
        prefixes = tuple(core.CURSOR_ENV_ALLOW_PREFIXES)
        for call in spy.calls:
            kind = self.classify(call)
            argv = call["argv"]
            label = kind if isinstance(argv, str) else "%s %s" % (kind, argv[:6])
            if kind == "git":
                self.assertEqual(argv[:2], ["git", "-C"], label)
                self.assertEqual(argv[3:7], ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"], label)
                self.assertIsNotNone(call["env"], label)
                self.assertEqual(call["env"].get("GIT_CONFIG_NOSYSTEM"), "1", label)
                self.assertEqual(call["env"].get("GIT_OPTIONAL_LOCKS"), "0", label)
                self.assertEqual(call["stdin"], subprocess.DEVNULL, label)
                for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_EXTERNAL_DIFF"):
                    self.assertNotIn(name, call["env"], label)
                continue
            if kind == "shell":                       # the user's own --test gate command
                self.assertIsNotNone(call["env"], "a gate command inherited the whole environment")
                for name in ("CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
                    self.assertNotIn(name, call["env"], label)
                continue
            if kind.split(":")[0] not in ("metadata", "inference", "selftest"):
                continue
            # ---- a Cursor process: sandbox-exec -f <profile> <exe> <tail> ----
            self.assertEqual(argv[0], core.SANDBOX_EXEC, label)
            self.assertTrue(os.path.isabs(argv[0]), "sandbox-exec must never be resolved through PATH")
            self.assertEqual(argv[1], "-f", label)
            self.assertTrue(argv[2].endswith(os.sep + "profile.sb"), label)
            self.assertTrue(os.path.basename(os.path.dirname(argv[2])).startswith("alloy-cursor-"), label)
            self.assertEqual(call["stdin"], subprocess.DEVNULL, label)
            env = call["env"]
            self.assertIsNotNone(env, "a Cursor process inherited the whole environment: " + label)
            extra = sorted(n for n in env if n not in allowed and not n.startswith(prefixes))
            self.assertEqual(extra, [], "environment names outside the allowlist: " + label)
            self.assertEqual(env["HOME"], home, label)
            self.assertEqual(env["AGENT_CLI_CREDENTIAL_STORE"], "file", label)
            for name in ("XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
                self.assertIn(os.sep + "alloy-cursor-", env[name], label)
                self.assertFalse(str(self.base) in env[name], "runtime inside the test workspace: " + label)
            for name in POISON:
                self.assertNotIn(name, env, "%s reached %s" % (name, label))
            blob = json.dumps(argv) + json.dumps(env)
            for value in POISON_VALUES + (AMBIENT_OVERWRITTEN["NODE_COMPILE_CACHE"],):
                self.assertNotIn(value, blob, "a poison value reached " + label)
            if kind != "selftest":
                # the build's own node, started directly; never the launcher, never a shell
                self.assertEqual(argv[3:6], [self.node_real, "--use-system-ca", self.index_real], label)
                self.assertEqual(env["CURSOR_INVOKED_AS"], "cursor-agent", label)
                self.assertTrue(env["NODE_COMPILE_CACHE"].startswith(env["XDG_CACHE_HOME"] + os.sep), label)
            tail = argv[6:] if kind != "selftest" else []
            self.assertEqual(forbidden_tokens(tail), [], label)
            if kind.startswith("metadata"):
                self.assertIn(tail, METADATA, label)
            elif kind == "inference":
                maker = "--mode" not in argv
                self.assertEqual(inference_problems(tail, maker), [], label)
                self.assertEqual(argv[3], self.node_real, label)
        return kinds

    def profiles(self):
        return [p.read_text() for p in sorted(Path(self.dump).glob("*.sb"))]

    def audit_profiles(self):
        """The sensitive-read deny set is in EVERY profile: panel, Checker, Maker, metadata,
        discovery and the self-test; and none grants a write or an execution it should not."""
        self.assertTrue(set(BUILTIN_SENSITIVE) <= set(core._CURSOR_HOME_DENIALS),
                        "the shipped deny list lost an entry: %s" % sorted(set(BUILTIN_SENSITIVE) - set(core._CURSOR_HOME_DENIALS)))
        profiles = self.profiles()
        self.assertGreater(len(profiles), 8)
        roles = collections.Counter(re.search(r"role=(\w+)", p).group(1) for p in profiles)
        self.assertEqual(set(roles), {"panel", "maker"})
        home = core.cursor_login_home()
        decide = te.MOCKMOD.sbpl_decision
        for profile in profiles:
            self.assertTrue(profile.startswith("(version 1)"))
            for rel in BUILTIN_SENSITIVE:
                for suffix in ("", "/child/x"):
                    for op in ("file-read-data", "file-read-metadata"):
                        self.assertEqual(decide(profile, op, home + "/" + rel + suffix), "deny", (rel, op))
            self.assertEqual(decide(profile, "file-read-data", home + "/Library/Group Containers/g.1password.x/y"), "deny")
            self.assertEqual(decide(profile, "file-read-data", "/private/tmp/some-secret-file"), "deny")
            self.assertEqual(decide(profile, "file-link", "/x"), "deny")
            for path in (home + "/x", home + "/.cursor/x", "/private/tmp/x", "/private/var/tmp/x", "/usr/local/x"):
                self.assertEqual(decide(profile, "file-write-create", path), "deny", path)
            self.assertEqual(decide(profile, "network-outbound", "/private/tmp/poison-agent.sock"), "deny")
            self.assertNotIn("(allow process*", profile)
            if "role=panel" in profile:
                self.assertIn("(deny process-exec*)", profile)
            self.assertEqual(decide(profile, "mach-lookup", "com.apple.coreservices.launchservicesd"), "deny")

    def scan_sinks(self, values, roots, skip=()):
        """[(path, value)] for every file under roots that contains one of the values."""
        hits = []
        for root in roots:
            for base, _dirs, files in os.walk(str(root)):
                for name in files:
                    path = os.path.join(base, name)
                    if path in skip or os.path.islink(path):
                        continue
                    try:
                        data = Path(path).read_bytes()
                    except OSError:
                        continue
                    hits.extend((path, v) for v in values if v.encode() in data)
        return hits


class CursorBoundaryInvariantTests(InvariantBase):
    def exercise(self):
        """Every Cursor subprocess class through the production paths, under poison."""
        ad = core.ADAPTERS["cursor"]
        ad.__dict__.pop("_auth_cache", None)
        big = self.base / "big-prompt.txt"
        marker = "PANEL-PROMPT-MARKER-%s" % uuid.uuid4().hex
        big.write_text(marker + "\n" + ("Explain the module in detail.\n" * 50000))
        self.assertGreater(big.stat().st_size, 1_400_000)
        self.plan(no_receipt=True)                        # a panel answer, not a review verdict
        with patch.dict(os.environ, dict(POISON, **AMBIENT_OVERWRITTEN)), patch.object(core, "_CONFIG", dict(POISON)), \
                patch.object(core, "_CURSOR_PREFLIGHT", {}):
            # login status, version and help probes, model discovery: each through the gateway
            self.assertTrue(ad.is_authed())
            binary = ad.resolved_bin()
            self.assertEqual(core.cursor_metadata("version", binary)[0], 0)
            self.assertEqual(core.cursor_metadata("help", binary)[0], 0)
            self.assertEqual(routing.probe(core, "cursor")["compatible"], True)
            found = routing.discover_cursor(core)
            self.assertIn("composer-2.5", found["models"])
            self.assertNotIn("auto", found["models"])
            # a plain panel with a multi-megabyte prompt, a routed panel, and a panel whose
            # adapter tries to smuggle every override into the child environment
            plain = core.run_panelist(ad, str(big), str(self.base / "runs" / "plain" / "cursor"), 60, 100000,
                                      "consult", repo=str(self.repo))
            self.assertEqual(plain["status"], "ok", plain.get("error"))
            routed_ad = routing.routed_adapter(core, self.decision("composer-2.5", "routed"))
            routed = core.run_panelist(routed_ad, str(self.prompt), str(self.base / "runs" / "routed" / "cursor"),
                                       60, 100000, "consult", repo=str(self.repo))
            self.assertEqual(routed["status"], "ok", routed.get("error"))

            class Smuggler(core.CursorAgentAdapter):
                def prepare_env(self, ctx=None):
                    env = super(Smuggler, self).prepare_env(ctx)
                    env.update((k, v) for k, v in POISON.items() if k in (
                        "CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"))
                    return env
            smuggled = core.run_panelist(Smuggler(), str(self.prompt), str(self.base / "runs" / "smuggle" / "cursor"),
                                         60, 100000, "consult", repo=str(self.repo))
            self.assertEqual(smuggled["status"], "ok", smuggled.get("error"))
            # a managed Maker and a managed Checker (real dispatch, tripwires, gates, integration)
            self.plan(maker_writes=[dict(path="file.txt", text="new\n")])
            with contextlib.redirect_stderr(io.StringIO()):
                code, task = self.create()
            self.assertEqual(code, 0, task.get("error"))
            self.assertEqual(self.action(task, "integrate"), 0)
        return marker

    def test_no_forbidden_argv_or_environment_value_crosses_any_cursor_boundary(self):
        with SpawnSpy() as spy:
            marker = self.exercise()
        kinds = self.audit(spy, expect=("selftest", "metadata:status", "metadata:version", "metadata:help",
                                        "metadata:list-models", "inference", "git", "shell"))
        # the whole run reached the gateway and nothing else: N inference calls, all sandboxed
        inference = [c for c in spy.calls if self.classify(c) == "inference"]
        self.assertGreaterEqual(len(inference), 5)                     # 3 panels + Maker + Checker
        modes = collections.Counter("ask" if "--mode" in c["argv"] else "agent" for c in inference)
        self.assertGreaterEqual(modes["ask"], 4)                       # 3 panels + Checker
        self.assertEqual(modes["agent"], 1)                            # the Maker: no --mode at all
        self.assertGreater(kinds["git"], 20)
        # the multi-megabyte panel prompt never rode on argv, and it reached the staged file whole
        for call in spy.calls:
            if not isinstance(call["argv"], str):
                self.assertLess(sum(len(a) for a in call["argv"]), 8192, call["argv"][:5])
                self.assertNotIn(marker, json.dumps(call["argv"]))
            self.assertNotIn("Change file.txt to new", json.dumps(call["argv"]))
        staged = self.base / "runs" / "plain" / "cursor" / "prompt_in" / "prompt.md"
        self.assertTrue(staged.read_text().startswith(marker))
        self.assertEqual(staged.stat().st_size, (self.base / "big-prompt.txt").stat().st_size)
        self.assertEqual(oct(staged.stat().st_mode & 0o777), "0o600")
        # ... and no persisted sink anywhere holds a poison value
        hits = self.scan_sinks(POISON_VALUES, [self.base, Path(self.routing_home), Path(self.xdg)])
        self.assertEqual(hits, [])
        self.audit_profiles()

    def test_usage_launches_no_cursor_process_and_never_reads_another_provider(self):
        config = dict(usage=dict(enabled=True, ttl_seconds=120))
        with SpawnSpy() as spy, patch.dict(os.environ, dict(POISON, ALLOY_USAGE="on")), \
                patch.object(core, "_CONFIG", dict(POISON)), patch.object(usage, "PROVIDERS", ("cursor",)):
            snapshot = usage.get(core, config, force=True)
            self.assertEqual(snapshot["providers"]["cursor"]["status"], "unknown")
            self.assertEqual(snapshot["providers"]["cursor"]["windows"], [])
            with self.assertRaisesRegex(usage.UsageError, "exposes no subscription usage source"):
                usage.fetch(core, "cursor", {})
            with self.assertRaisesRegex(usage.UsageError, "Unknown usage provider"):
                usage.fetch(core, "not-a-provider", {})              # no fall-through to Claude
            with self.assertRaisesRegex(usage.UsageError, "Unknown usage provider"):
                usage.binding(core, "not-a-provider")
            child_env = usage.provider_env(core)
        self.assertEqual(spy.calls, [], "usage started a process: %s" % [c["argv"] for c in spy.calls][:3])
        for name in ("CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
            self.assertNotIn(name, child_env)
        for value in POISON_VALUES[:4]:
            self.assertNotIn(value, json.dumps(child_env))
        # the usage cache persists no poison and no Cursor account state
        self.assertEqual(self.scan_sinks(POISON_VALUES, [Path(self.routing_home)]), [])

    def test_a_boundary_that_is_not_ready_starts_no_cursor_process_at_all(self):
        """Without a validated sandbox every class refuses before any Cursor process starts,
        whatever the reason, and the unsandboxed override never helps."""
        ad = core.ADAPTERS["cursor"]
        reasons = (("no sandbox-exec", lambda: patch.object(core, "SANDBOX_EXEC", "/no/such/sandbox-exec")),
                   ("self-test failure", lambda: patch.dict(os.environ, MOCK_SANDBOX_PREFLIGHT="write_leak")),
                   ("not macOS", lambda: patch.object(core, "CURSOR_PLATFORM", "unsupported-os")))
        for reason, apply in reasons:
            for override in ({}, {"ALLOY_ALLOW_UNSANDBOXED": "1"}):
                with self.subTest(reason=reason, override=override):
                    ad.__dict__.pop("_auth_cache", None)
                    with SpawnSpy() as spy, patch.object(core, "_CURSOR_PREFLIGHT", {}), apply(), \
                            patch.dict(os.environ, override):
                        for kind in ("status", "version", "help", "models"):
                            with self.assertRaises(core.CursorBoundaryError):
                                core.cursor_metadata(kind, ad.resolved_bin())
                        self.assertFalse(ad.cursor_boundary_ready)
                        self.assertFalse(ad.is_authed())
                        result = core.run_panelist(ad, str(self.prompt), str(self.base / "runs" / "refused" / uuid.uuid4().hex),
                                                   30, 1000, "consult", repo=str(self.repo))
                        self.assertEqual(result["status"], "error")
                        self.assertTrue(result["error"].startswith("refused: "), result["error"])
                    started = [self.classify(c) for c in spy.calls]
                    self.assertFalse([k for k in started if k == "inference" or k.startswith("metadata")
                                      or k == "UNWRAPPED-CURSOR"], (reason, started))
                    self.assertEqual(self.cursor_calls(), [])


# ---- no forbidden control survives a rewrite ------------------------------------------------
INJ = "inj-value-9f3a71"     # a distinctive value: a refusal must never echo it


def ins(*tokens):
    """Insert before the trailing instruction: the position an option normally sits."""
    return lambda argv: argv[:-1] + list(tokens) + argv[-1:]


def pre(*tokens):
    return lambda argv: list(tokens) + argv


def post(*tokens):
    return lambda argv: argv + list(tokens)


def swap(flag, value):
    def rewrite(argv):
        argv = list(argv)
        argv[argv.index(flag) + 1] = value
        return argv
    return rewrite


def drop(flag, value=True):
    def rewrite(argv):
        argv = list(argv)
        i = argv.index(flag)
        del argv[i:i + (2 if value else 1)]
        return argv
    return rewrite


FULL_INJECTIONS = (
    # force / auto-approval / plan
    ("--force", ins("--force")), ("-f", ins("-f")), ("--yolo", ins("--yolo")),
    ("--auto-review", ins("--auto-review")), ("--approve-mcps", ins("--approve-mcps")), ("--plan", ins("--plan")),
    # mode
    ("second --mode agent", ins("--mode", "agent")), ("--mode=agent", ins("--mode=agent")),
    ("another --mode ask", ins("--mode", "ask")),
    # sandbox and setup scripts
    ("duplicate --sandbox disabled", ins("--sandbox", "disabled")), ("--sandbox swapped", swap("--sandbox", "enabled")),
    ("--sandbox=disabled", ins("--sandbox=disabled")), ("no --sandbox", drop("--sandbox")),
    ("no --skip-worktree-setup", drop("--skip-worktree-setup", value=False)),
    ("no --trust", drop("--trust", value=False)),
    # plugin / directory / session / worktree
    ("--plugin-dir", ins("--plugin-dir", INJ)), ("--add-dir", ins("--add-dir", INJ)),
    ("--resume", ins("--resume", INJ)), ("--continue", ins("--continue")),
    ("-w", ins("-w")), ("--worktree", ins("--worktree")), ("--worktree-base", ins("--worktree-base", INJ)),
    # subcommands
    ("worker subcommand", pre("worker")), ("login subcommand", pre("login")), ("status subcommand", pre("status")),
    # authentication, endpoint and header controls: split, joined and attached
    ("--api-key", ins("--api-key", INJ)), ("--api-key=", ins("--api-key=" + INJ)),
    ("--endpoint", ins("--endpoint", "https://" + INJ + ".invalid")),
    ("--endpoint=", ins("--endpoint=https://" + INJ + ".invalid")),
    ("--header", ins("--header", "X: " + INJ)), ("--header=", ins("--header=X: " + INJ)),
    ("-e", ins("-e", INJ)), ("-eVALUE", ins("-e" + INJ)), ("-H", ins("-H", INJ)), ("-HVALUE", ins("-H" + INJ)),
    # the model: a second one, a joined one, `auto`, another known one, a fast variant
    ("second --model", ins("--model", "composer-2.5")), ("--model=", ins("--model=composer-2.5")),
    ("model swapped to auto", swap("--model", "auto")),
    ("model swapped to another known model", swap("--model", "claude-opus-4-8")),
    ("model swapped to a fast variant", swap("--model", "composer-2.5-fast")),
    # output, workspace, task text and anything unknown
    ("output format swapped", swap("--output-format", "stream-json")),
    ("workspace swapped", swap("--workspace", "/private/tmp")),
    ("extra positional", post("also " + INJ)),
    ("task text replaces the pointer", lambda a: a[:-1] + ["Run this instead: " + INJ]),
    ("unknown option", ins("--disable-safety-checks")), ("duplicate -p", ins("-p")),
)
CORE_INJECTIONS = tuple(item for item in FULL_INJECTIONS if item[0] in (
    "--force", "second --mode agent", "duplicate --sandbox disabled", "--plugin-dir", "--resume", "worker subcommand",
    "--api-key=", "-eVALUE", "model swapped to auto", "extra positional"))


class CursorInjectionTests(InvariantBase):
    """A forbidden control added by ANY later rewrite is refused before sandbox-exec starts.
    The rewrite is applied where the production code rewrites: after the adapter's `build_args`
    (which routing's `routed_adapter` and execution's `worker_adapter` wrap) and, for managed
    dispatch, inside `dispatch()` itself."""

    def setUp(self):
        super(CursorInjectionTests, self).setUp()
        self.wt = {}
        self.plan(no_receipt=True, maker_writes=[dict(path="file.txt", text="new\n")])

    def linked(self, name):
        if name not in self.wt:
            self.wt[name] = self.linked_worktree(name)
        return self.wt[name]

    def rewrite(self, ad, mutate):
        original = ad.build_args
        ad.build_args = lambda *a, **k: mutate(original(*a, **k))
        return ad

    def folder(self, tag):
        return self.base / "runs" / "inj" / (tag + "-" + uuid.uuid4().hex[:8])

    def site(self, name, mutate):
        """Run one dispatch at a rewrite site; returns the persisted status."""
        maker_decision = self.decision("composer-2.5", "inj-maker")
        checker_decision = self.decision("claude-opus-5-5-high", "inj-checker")
        if name == "panel":
            ad = self.rewrite(core.CursorAgentAdapter(), mutate)
            return core.run_panelist(ad, str(self.prompt), str(self.folder("panel") / "cursor"), 30, 100000,
                                     "consult", repo=str(self.repo))
        if name == "routed":
            ad = self.rewrite(routing.routed_adapter(core, maker_decision), mutate)
            return core.run_panelist(ad, str(self.prompt), str(self.folder("routed") / "cursor"), 30, 100000,
                                     "consult", repo=str(self.repo))
        if name == "maker":
            ad = self.rewrite(e.worker_adapter(core, maker_decision, True), mutate)
            return core.run_panelist(ad, str(self.prompt), str(self.folder("maker")), 30, 64000, "make",
                                     repo=self.linked("maker"), managed_worktree=True)
        if name == "checker":
            ad = self.rewrite(e.worker_adapter(core, checker_decision, False), mutate)
            return core.run_panelist(ad, str(self.prompt), str(self.folder("checker")), 30, 64000, "review",
                                     repo=self.linked("checker"))
        if name in ("dispatch-maker", "dispatch-checker"):
            role = name.split("-")[1]
            real_worker_adapter = e.worker_adapter

            def worker_adapter(core_, decision, write=False):
                return self.rewrite(real_worker_adapter(core_, decision, write), mutate)
            with patch.object(e, "worker_adapter", side_effect=worker_adapter):
                return te.REAL_DISPATCH(core, self.task, role, "Change file.txt to new. Test it.", self.folder(name))
        raise AssertionError(name)

    def refused(self, label, result, spy, before):
        self.assertEqual(result["status"], "error", label)
        self.assertTrue(str(result.get("error", "")).startswith("refused: "), (label, result.get("error")))
        self.assertEqual(len(self.cursor_children(spy)), before, "sandbox-exec or the CLI was started: " + label)
        self.assertNotIn(INJ, json.dumps(result), label)

    def matrix(self, site, injections):
        for label, mutate in injections:
            with self.subTest(site=site, injection=label):
                with SpawnSpy() as spy:
                    before = len(self.cursor_children(spy))
                    result = self.site(site, mutate)
                self.refused("%s at %s" % (label, site), result, spy, before)

    def control(self, site):
        """The same site with an identity rewrite starts a sandboxed process: the refusals
        above are caused by the injection, not by the harness."""
        with SpawnSpy() as spy:
            result = self.site(site, lambda argv: argv)
        self.assertEqual(result["status"], "ok", (site, result.get("error")))
        self.assertEqual(self.audit(spy)["inference"], 1, site)

    def test_a_panel_refuses_every_forbidden_control(self):
        self.control("panel")
        self.matrix("panel", FULL_INJECTIONS)

    def test_a_managed_maker_refuses_every_forbidden_control(self):
        self.control("maker")
        self.matrix("maker", FULL_INJECTIONS)

    def test_the_routing_and_checker_rewrite_sites_refuse_them_too(self):
        for site in ("routed", "checker"):
            self.control(site)
            self.matrix(site, CORE_INJECTIONS)

    def test_dispatch_itself_refuses_them_for_both_managed_roles(self):
        self.plan(maker_writes=[dict(path="file.txt", text="new\n")])      # receipts on: a real, passing task
        with contextlib.redirect_stderr(io.StringIO()):
            code, self.task = self.create()
        self.assertEqual(code, 0, self.task.get("error"))
        self.plan(no_receipt=True)
        for site in ("dispatch-maker", "dispatch-checker"):
            self.control(site)
            self.matrix(site, CORE_INJECTIONS)

    def test_a_refusal_names_the_option_never_its_value(self):
        for label, mutate in (("api key", ins("--api-key", INJ)), ("header", ins("--header=X: " + INJ)),
                              ("attached", ins("-H" + INJ)), ("endpoint", ins("--endpoint=https://" + INJ + ".invalid"))):
            with self.subTest(label):
                result = self.site("panel", mutate)
                self.assertEqual(result["status"], "error")
                text = json.dumps(result) + Path(result["status_path"] if "status_path" in result
                                                 else str(self.base)).name
                self.assertNotIn(INJ, text)
        for status in self.base.glob("runs/inj/*/cursor/status.json"):
            self.assertNotIn(INJ, status.read_text(), str(status))

    def test_the_forbidden_token_detector_can_fail(self):
        for token in ("--force", "-f", "--api-key", "--api-key=x", "--endpoint=https://x", "--header=x", "-eVALUE",
                      "-HVALUE", "--resume", "--plugin-dir", "--worktree-base", "-w", "--yolo", "--plan"):
            self.assertTrue(forbidden_tokens(["-p", token, "x"]), token)
        self.assertEqual(forbidden_tokens(["-p", "--mode", "ask", "--skip-worktree-setup", "--workspace", "/x",
                                           "--trust", "--sandbox", "disabled", "--output-format", "json"]), [])
        good = ["-p", "--mode", "ask", "--output-format", "json", "--workspace", "/x", "--model", "composer-2.5[fast=false]",
                "--trust", "--sandbox", "disabled", "--skip-worktree-setup", 'Read "/x/prompt_in/prompt.md" in full.']
        self.assertEqual(inference_problems(good, maker=False), [])
        self.assertTrue(inference_problems(good, maker=True))                  # a Maker must not set --mode
        self.assertTrue(inference_problems(good + ["extra"], maker=False))
        self.assertTrue(inference_problems([t for t in good if t != "--trust"], maker=False))
        self.assertTrue(inference_problems([t.replace("disabled", "enabled") for t in good], maker=False))
        self.assertTrue(inference_problems([t.replace("composer-2.5[fast=false]", "auto") for t in good], maker=False))


# ---- recognised secrets injected into every Checker packet source ----------------------------------
SHAPES = collections.OrderedDict((
    ("jwt", ("token " + te.GOOD_JWT, te.GOOD_JWT)),
    ("assignment", ("API_KEY=hunter2hunter2hunter2", "hunter2hunter2hunter2")),
    ("bearer header", ("Authorization: Bearer abc123def456ghi789", "abc123def456ghi789")),
    ("basic header", ("Proxy-Authorization: Basic YWJjMTIzZGVmNDU2", "YWJjMTIzZGVmNDU2")),
    ("custom header", ("X-Api-Key: customheader123456", "customheader123456")),
    ("cookie", ("Cookie: session=cookiesecret123456", "cookiesecret123456")),
))
SECRET_TEXT = "; ".join(text for text, _value in SHAPES.values())
SECRET_VALUES = tuple(value for _text, value in SHAPES.values())


class CursorCheckerPacketSecretTests(InvariantBase):
    """Recognised secrets are injected, in every shape, into each source of the Checker packet
    (goal/spec, diff, gate command, gate output, and the changed and allowed paths) and none
    reaches the saved packet, the staged Checker prompt, or any Checker-facing persisted sink.
    The Maker's own inputs are unredacted by design, so the control assertions prove each
    secret really was in its source first."""

    def configure(self, source):
        text = SECRET_TEXT
        maker_text = "new\n"
        tests = ["exit 0"]
        if source in ("spec", "all"):
            self.prompt.write_text("Change file.txt to new. Test it. " + text)
        if source in ("diff", "all"):
            maker_text = "new " + text + "\n"
        if source in ("gate_output", "all"):
            tests = ["echo '%s'" % text]
        if source in ("gate_command", "all"):
            tests = ["exit 0 # " + text]
        self.args.test = tests
        self.plan(maker_writes=[dict(path="file.txt", text=maker_text)])

    def checker_sinks(self, task):
        directory = e.taskdir(core, task["id"])
        sinks = sorted(directory.glob("review-*.json")) + sorted(directory.glob("round-*/checker/**/*"))
        for name in ("status.json", "stdout.txt", "stderr.txt", "result.md"):
            sinks += sorted(directory.glob("round-*/maker/" + name))
        sinks += sorted(directory.glob("round-*/gate-*.log"))
        return [p for p in sinks if p.is_file()]

    def assert_checker_side_is_clean(self, task, label):
        directory = e.taskdir(core, task["id"])
        checker = directory / "round-0" / "checker"
        staged = (checker / "prompt_in" / "prompt.md").read_text()
        self.assertIn("[REDACTED", staged, label)
        self.assertEqual(oct((checker / "prompt_in" / "prompt.md").stat().st_mode & 0o777), "0o600")
        self.assertEqual(staged, (checker / "prompt.txt").read_text())
        sinks = self.checker_sinks(task)
        self.assertGreater(len(sinks), 5, [str(p.relative_to(directory)) for p in sinks])
        for value in SECRET_VALUES:
            for sink in sinks:
                self.assertNotIn(value.encode(), sink.read_bytes(), "%s leaked into %s" % (label, sink.relative_to(directory)))

    def test_every_packet_source_is_redacted_before_it_is_saved_or_staged(self):
        field = {"spec": lambda pk: pk["goal"], "diff": lambda pk: pk["diff"],
                 "gate_output": lambda pk: pk["tests"][0]["output"], "gate_command": lambda pk: pk["tests"][0]["command"],
                 "all": lambda pk: json.dumps(pk)}
        for source in ("spec", "diff", "gate_output", "gate_command", "all"):
            with self.subTest(source=source):
                self.reset()
                self.prompt.write_text("Change file.txt to new. Test it.")
                self.configure(source)
                with contextlib.redirect_stderr(io.StringIO()):
                    code, task = self.create()
                self.assertEqual(code, 0, task.get("error"))
                self.assertEqual(task["state"], "ready")
                directory = e.taskdir(core, task["id"])
                packet = json.loads((directory / "review-0.json").read_text())
                # control: the secret really was in the (unredacted) source, and reached the packet builder
                for value in SECRET_VALUES:
                    if source in ("spec", "all"):
                        self.assertIn(value, (directory / "spec.txt").read_text())
                    if source in ("diff", "all"):
                        self.assertIn(value, (directory / "changes.patch").read_text())
                    if source in ("gate_command", "all"):
                        self.assertIn(value, json.dumps(task["tests"]))
                self.assertIn("[REDACTED", field[source](packet), source)
                self.assert_checker_side_is_clean(task, source)
                # what is sent is what is saved, and the receipt still verifies
                self.assertEqual(task["rounds"][0]["packet"]["id"],
                                 __import__("hashlib").sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest())

    def test_secrets_in_changed_and_allowed_paths_are_redacted_and_never_staged(self):
        """A path is a packet source too (`changed_files`, `allowed_paths`). A Cursor Maker cannot
        produce one -- a file named like a secret makes the scope check fail closed -- so the
        real packet builder and a real sandboxed Checker dispatch are driven directly."""
        self.plan(maker_writes=[dict(path="file.txt", text="new\n")])
        with contextlib.redirect_stderr(io.StringIO()):
            code, task = self.create()
        self.assertEqual(code, 0, task.get("error"))
        names = {"jwt": te.GOOD_JWT + ".txt", "assignment": "API_KEY=hunter2hunter2hunter2.txt",
                 "bearer header": "Authorization: Bearer abc123def456ghi789.txt"}
        worktree = task["worktree"]
        for name in names.values():
            Path(worktree, name).write_text("body\n")
        e.git(worktree, "add", "--all")
        e.git(worktree, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "secret-named files")
        tip = e.git(worktree, "rev-parse", "HEAD")
        task["allow_paths"] = list(task["allow_paths"]) + list(names.values())
        log = self.base / "gate-path.log"
        log.write_text("ok\n")
        record = dict(index=7, gates=[dict(command="true", exit_code=0, log=str(log))])
        encoded, packet_id = e.review_packet(core, task, record, tip, "diff", "goal")
        saved = (e.taskdir(core, task["id"]) / "review-7.json").read_text()
        for value in ("hunter2hunter2hunter2", "abc123def456ghi789", te.GOOD_JWT):
            self.assertNotIn(value, encoded)
            self.assertNotIn(value, saved)
        packet = json.loads(encoded)
        self.assertTrue(any("[REDACTED" in f for f in packet["changed_files"]), packet["changed_files"])
        self.assertTrue(any("[REDACTED" in f for f in packet["allowed_paths"]), packet["allowed_paths"])
        self.assertEqual(json.loads(saved), packet)
        # ... and through a real, sandboxed Checker dispatch: the staged prompt and every sink
        self.plan(no_receipt=True)
        folder = e.taskdir(core, task["id"]) / "round-0" / "checker-paths"
        result = te.REAL_DISPATCH(core, task, "checker", e.checker_prompt(encoded, packet_id, tip), folder)
        self.assertEqual(result["status"], "ok", result.get("error"))
        staged = (folder / "prompt_in" / "prompt.md").read_text()
        self.assertIn("[REDACTED", staged)
        for value in ("hunter2hunter2hunter2", "abc123def456ghi789", te.GOOD_JWT):
            for path in [p for p in folder.rglob("*") if p.is_file()]:
                self.assertNotIn(value.encode(), path.read_bytes(), str(path.relative_to(folder)))

    def test_recognised_secrets_in_the_spec_never_reach_the_cursor_argv_or_environment(self):
        self.prompt.write_text("Change file.txt to new. Test it. " + SECRET_TEXT)
        with SpawnSpy() as spy, contextlib.redirect_stderr(io.StringIO()):
            code, task = self.create()
        self.assertEqual(code, 0, task.get("error"))
        for call in spy.calls:
            if self.classify(call) in ("inference", "metadata:status", "metadata:help"):
                blob = json.dumps(call["argv"]) + json.dumps(call["env"])
                for value in SECRET_VALUES:
                    self.assertNotIn(value, blob)
        self.audit(spy, expect=("inference",))


# =============================================================================================
# 4. The wiring of the two release gates that talk to the real world
# =============================================================================================
def load_by_path(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for inner in flatten(item):
                yield inner
        else:
            yield item


class SandboxGateWiringTests(unittest.TestCase):
    """The real macOS sandbox gate is only a gate if it is run, cannot be skipped by accident and
    cannot pass without the real binary."""

    def run_gate(self, platform, sandbox=None):
        module = load_by_path(GATE, "gate_under_test_" + uuid.uuid4().hex[:8])
        if sandbox is not None:
            module.SANDBOX_EXEC = sandbox
        result = unittest.TestResult()
        with patch.object(sys, "platform", platform), patch.dict(os.environ, {"ALLOY_CURSOR_SANDBOX_GATE": "1", "ALLOY_CURSOR_BUILD_GATE": "1"}):
            unittest.TestLoader().loadTestsFromModule(module).run(result)
        return result

    def test_unittest_discovers_the_gate_by_the_repository_command(self):
        import fnmatch
        self.assertTrue(fnmatch.fnmatch(GATE.name, "test*.py"))
        found = list(flatten(unittest.TestLoader().discover(str(HERE), pattern=GATE.name)))
        ids = [t.id() for t in found]
        self.assertGreaterEqual(len(ids), 15, ids)
        self.assertTrue(all("RealSandboxGate" in i or "_FailedTest" not in i for i in ids), ids)
        self.assertFalse([i for i in ids if "_FailedTest" in i or "ModuleImportFailure" in i], ids)
        # the generic discovery command finds it too (it is a plain test*.py module)
        generic = [t.id() for t in flatten(unittest.TestLoader().discover(str(HERE), pattern="test_cursor_*.py"))]
        self.assertTrue([i for i in generic if "RealSandboxGate" in i])

    def test_off_macos_the_whole_gate_skips_and_only_for_the_platform(self):
        result = self.run_gate("linux")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(len(result.skipped), 2)                # the sandbox class and the real-build class
        for _test, reason in result.skipped:
            self.assertTrue(reason.startswith("platform:"), result.skipped)
        self.assertEqual(result.testsRun, 0)

    def test_on_macos_a_missing_sandbox_exec_is_a_failure_never_a_skip(self):
        result = self.run_gate("darwin", sandbox=os.path.join(tempfile.gettempdir(), "no-such-dir", "sandbox-exec"))
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.errors), 2, result.errors)       # both classes: neither can start anything
        for _test, text in result.errors:
            self.assertIn("is missing", text)
        self.assertFalse(result.wasSuccessful())

    def test_on_macos_a_binary_that_is_not_the_real_sandbox_exec_fails_too(self):
        result = self.run_gate("darwin", sandbox="/dev/null")
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.errors), 2, result.errors)
        self.assertFalse(result.wasSuccessful())

    def test_the_gate_source_has_only_the_platform_skips_and_the_no_cursor_runner_opt_out_and_never_the_mock(self):
        source = GATE.read_text()
        # exactly five skip sites: one platform skip per class, and the opt-out for a runner
        # that has no `cursor-agent` at all
        self.assertEqual(len(re.findall(r"SkipTest\(", source)), 5)
        self.assertEqual(source.count('if sys.platform != "darwin":\n            raise unittest.SkipTest(PLATFORM_SKIP)'), 2)
        self.assertEqual(source.count("raise unittest.SkipTest(NO_BUILD_SKIP)"), 1)
        self.assertIn('if cls.bin_path is None:\n            if os.environ.get(NO_BUILD_FLAG) == "1":\n'
                      '                raise unittest.SkipTest(NO_BUILD_SKIP)', source)
        self.assertIn('NO_BUILD_FLAG = "ALLOY_GATE_NO_CURSOR_BUILD"', source)
        for forbidden in ("skipIf", "skipUnless", "skipTest(", "expectedFailure"):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertIn('SANDBOX_EXEC = "/usr/bin/sandbox-exec"', source)
        self.assertNotIn("mock_panelist", source)
        self.assertNotRegex(source, r"patch\.object\(\s*(?:self\.)?mod\s*,\s*[\"']SANDBOX_EXEC")
        self.assertNotIn("os.environ[\"SANDBOX", source)

    def test_the_macos_ci_job_runs_the_gate_and_fails_on_a_missing_binary(self):
        text = CI.read_text()
        jobs = re.search(r"(?ms)^  test:\n(.*?)^  shellcheck:", text)
        self.assertIsNotNone(jobs, "ci.yml has no `test` job before `shellcheck`")
        job = jobs.group(1)
        self.assertIn("macos-latest", job)                       # the matrix includes macOS ...
        self.assertIn("ubuntu-latest", job)                      # ... and Linux, where the gate skips
        steps = re.split(r"(?m)^      - ", job)[1:]
        gate = [s for s in steps if "test_cursor_sandbox_release_gate.py" in s]
        self.assertEqual(len(gate), 1, "exactly one explicit gate step")
        step = gate[0]
        self.assertRegex(step, r"(?m)^        if: runner\.os == 'macOS'$")
        self.assertRegex(step, r"python3 -m unittest discover -s tests -p 'test_cursor_sandbox_release_gate\.py' -v")
        self.assertIn("test -x /usr/bin/sandbox-exec", step)     # a missing binary fails the step by itself
        self.assertRegex(step, r"test -x /usr/bin/sandbox-exec \|\| \{ echo .*exit 1; \}")
        for weakening in ("continue-on-error", "|| true", "|| :", "set +e", "if: always()", "failure()"):
            self.assertNotIn(weakening, step)
        # it runs after the generic discovery step, which is itself unconditional
        generic = [s for s in steps if "python3 -m unittest discover -s tests -v" in s]
        self.assertEqual(len(generic), 1)
        self.assertNotIn("\n        if:", generic[0])
        self.assertLess(steps.index(generic[0]), steps.index(step))
        # the strict-shell contract GitHub gives `run` steps is not overridden for this step
        self.assertNotIn("shell:", step)
        self.assertNotIn("defaults:", job)

    def test_the_ci_job_declares_the_no_cursor_runner_opt_out_once_at_job_level(self):
        text = CI.read_text()
        job = re.search(r"(?ms)^  test:\n(.*?)^  shellcheck:", text).group(1)
        self.assertRegex(job, r'(?m)^    env:\n(?:      #.*\n)*      ALLOY_GATE_NO_CURSOR_BUILD: "1"\n')
        self.assertEqual(text.count("ALLOY_GATE_NO_CURSOR_BUILD"), 1)      # nowhere else, in particular not per step
        for step in re.split(r"(?m)^      - ", job)[1:]:
            self.assertNotIn("ALLOY_GATE_NO_CURSOR_BUILD", step)

    def test_the_real_build_gate_starts_the_real_runtime_directly_and_can_fail(self):
        source = GATE.read_text()
        klass = source[source.index("class RealCursorBuildGate"):source.index("def stat_is_regular")]
        for needed in ("cursor_resolve_build(cls.bin_path)", 'mod.cursor_command("version", ["--version"]',
                       "[build.node, \"--use-system-ca\", build.script, \"--version\", \"--sandbox\", \"disabled\"]",
                       '"(allow process-exec " + " ".join("(literal %s)" % mod._sb_path(p) for p in allowed) + ")"',
                       'SYSTEM_EXECS = ("/usr/bin/sw_vers",)', "DENIED_EXECS",
                       "test_status_reaches_the_authenticated_state_under_the_production_panel_profile",
                       "test_a_shell_and_the_other_system_tools_are_denied_by_the_real_kernel",
                       "the_bash_launcher_cannot_start", "a_profile_that_allows_only_the_launcher_or_nothing"):
            self.assertIn(needed, klass, needed)
        # the class is not allowed to stand a Python interpreter or a mock in for the runtime
        for forbidden in ("mock", "sys.executable", "real_image", "python_cli_constants_for", "return_value="):
            self.assertNotIn(forbidden, klass, forbidden)

    def run_build_gate(self, flag=None, bin_path=None):
        """The real-build gate class, run in-process on a machine with no `cursor-agent` on PATH
        (or with the given one), and with the opt-out set or not."""
        with patch.dict(os.environ, {"PATH": "/var/empty", "ALLOY_CONFIG": "/dev/null", "ALLOY_CURSOR_BUILD_GATE": "1"}):
            for name in ("ALLOY_BIN_CURSOR", "ALLOY_BIN_CURSOR_AGENT", "ALLOY_GATE_NO_CURSOR_BUILD"):
                os.environ.pop(name, None)
            if flag is not None:
                os.environ["ALLOY_GATE_NO_CURSOR_BUILD"] = flag
            if bin_path:
                os.environ["ALLOY_BIN_CURSOR"] = bin_path
            module = load_by_path(GATE, "gate_build_under_test_" + uuid.uuid4().hex[:8])
            result = unittest.TestResult()
            unittest.TestLoader().loadTestsFromTestCase(module.RealCursorBuildGate).run(result)
        return result

    @unittest.skipUnless(sys.platform == "darwin", "the real-build gate is exercised on macOS only")
    def test_on_macos_no_cursor_at_all_fails_unless_the_runner_says_it_can_have_none(self):
        result = self.run_build_gate()
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.errors), 1, result.errors)
        self.assertIn("no cursor-agent is installed", result.errors[0][1])
        result = self.run_build_gate(flag="1")
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.skipped), 1, result.skipped)
        self.assertIn("ALLOY_GATE_NO_CURSOR_BUILD=1", result.skipped[0][1])
        # only the exact value counts
        for value in ("", "0", "true", "yes", "2", " 1", "1 ", "on"):
            with self.subTest(flag=value):
                result = self.run_build_gate(flag=value)
                self.assertEqual(result.skipped, [], value)
                self.assertEqual(len(result.errors), 1, value)

    @unittest.skipUnless(sys.platform == "darwin", "the real-build gate is exercised on macOS only")
    def test_on_macos_an_installed_cursor_that_cannot_be_started_fails_even_with_the_opt_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(os.path.realpath(tmp)) / "cursor-agent"
            broken.write_bytes(b"\x7fELF not a script and not inside a build directory\n")
            os.chmod(str(broken), 0o755)
            for flag in (None, "1"):
                with self.subTest(flag=flag):
                    result = self.run_build_gate(flag=flag, bin_path=str(broken))
                    self.assertEqual(result.skipped, [])
                    self.assertEqual(len(result.errors), 1, result.errors)
                    self.assertIn("neither inside a Cursor build directory", result.errors[0][1])

    def test_discovery_never_resolves_or_starts_an_installed_cursor_without_opt_in(self):
        module = load_by_path(GATE, "gate_opt_in_" + uuid.uuid4().hex[:8])
        with patch.dict(os.environ, {"ALLOY_CURSOR_BUILD_GATE": "0"}), \
                patch.object(module, "load_alloy", side_effect=AssertionError("resolved live CLI")):
            result = unittest.TestResult()
            with patch.object(sys, "platform", "darwin"):
                unittest.TestLoader().loadTestsFromTestCase(module.RealCursorBuildGate).run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.skipped), 1)
        self.assertIn("ALLOY_CURSOR_BUILD_GATE=1", result.skipped[0][1])

    def test_the_ci_checker_can_fail(self):
        broken = CI.read_text().replace("test -x /usr/bin/sandbox-exec", "true")
        self.assertNotIn("test -x /usr/bin/sandbox-exec", broken)
        weak = CI.read_text().replace("if: runner.os == 'macOS'", "if: runner.os == 'Linux'")
        self.assertNotRegex(weak, r"(?m)^        if: runner\.os == 'macOS'$")


class ReleaseEvidenceTests(unittest.TestCase):
    """Validate operator-supplied evidence with fixtures only, never run either live gate."""
    PROBE = HERE / "live" / "cursor_ask_release.py"
    BUILD_TESTS = (
        "test_the_production_resolver_reaches_a_supported_build_and_its_own_node",
        "test_the_os_version_tool_is_the_real_root_owned_file",
        "test_the_production_boundary_starts_the_real_node_under_the_panel_and_maker_profiles",
        "test_the_real_node_runs_under_the_production_panel_profile_that_allows_only_it",
        "test_status_reaches_the_authenticated_state_under_the_production_panel_profile",
        "test_a_shell_and_the_other_system_tools_are_denied_by_the_real_kernel_and_the_three_are_allowed",
        "test_the_bash_launcher_cannot_start_under_that_profile_which_is_why_it_is_never_used",
        "test_the_gate_can_fail_a_profile_that_allows_only_the_launcher_or_nothing_stops_the_runtime",
    )

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.report = Path(tmp.name)
        self.build = "".join("%s (test_cursor_sandbox_release_gate.RealCursorBuildGate.%s) ... ok\n" %
                             (name, name) for name in self.BUILD_TESTS)
        self.build += "\n----------------------------------------------------------------------\nRan 28 tests in 1.000s\n\nOK\n"
        # Independent expected contract: a missing check must not shrink the verifier's requirements.
        self.record = dict(gate="cursor-ask-release", model="composer-2.5",
                           cursor_version="2026.09.28-64d2043", passed=True, checks={
                               "boundary_ready": True, "supported_build": True, "authenticated": True,
                               "call_ok": True, "workspace_unchanged": True, "outside_unchanged": True,
                               "no_marker_created": True, "alloy_tripwires_clean": True,
                               "process_group_observed": True, "runtime_started_directly": True,
                               "no_unexpected_descendant_process_seen": True, "no_shell_process_seen": True,
                               "no_file_created_outside_runtime": True, "sandbox_denial_log_captured": True,
                               "json_shape_ok": True}, allowed_executables=["/build/node", "/build/rg", "/usr/bin/sw_vers"],
                           executed_descendants=["/build/node", "/build/rg"], attempted_and_denied=["/bin/zsh"],
                           sandbox_denial_log=["Sandbox: node(123) deny(1) process-exec /bin/zsh"])

    def ask_log(self, record=None):
        return ("test_ask_mode_exposes_no_shell_and_changes_no_canary (cursor_ask_release.CursorAskReleaseProbe) ...\n"
                "CURSOR_ASK_RELEASE_RECORD " + json.dumps(self.record if record is None else record) +
                "\nok\n\n----------------------------------------------------------------------\nRan 1 test in 1.000s\n\nOK\n")

    def verify(self, build=None, ask=None):
        (self.report / "build-gate.log").write_text(self.build if build is None else build)
        (self.report / "ask-gate.log").write_text(self.ask_log() if ask is None else ask)
        env = dict(os.environ, ALLOY_LIVE_CURSOR="1", ALLOY_CURSOR_BUILD_GATE="0",
                   ALLOY_CURSOR_SANDBOX_GATE="0", ALLOY_BIN_CURSOR="/no/such/cursor-agent", ALLOY_CONFIG="/dev/null")
        return subprocess.run([sys.executable, "-B", str(self.PROBE), "--verify-report", str(self.report)],
                              env=env, capture_output=True, text=True, timeout=30)

    def test_missing_live_ask_record_cannot_supply_a_passing_release_report(self):
        for ask in ("", "Ran 1 test in 1.000s\n\nOK\n", self.ask_log() * 2):
            with self.subTest(ask=ask[:40]):
                ran = self.verify(ask=ask)
                self.assertNotEqual(ran.returncode, 0)
                self.assertIn("exactly one CURSOR_ASK_RELEASE_RECORD", ran.stderr)
                self.assertEqual(ran.stdout, "")

    def test_partial_failed_or_wrong_model_ask_records_are_refused(self):
        broken = [{}, dict(self.record, executed_descendants=["/bin/sh"]), dict(self.record, sandbox_denial_log=[]), dict(self.record, passed=False), dict(self.record, model="composer-3"),
                  dict(self.record, cursor_version="2026.09.29-unmeasured")]
        for name in self.record["checks"]:
            for value in (None, False, 1):
                checks = dict(self.record["checks"])
                if value is None:
                    del checks[name]
                else:
                    checks[name] = value
                broken.append(dict(self.record, checks=checks))
        for record in broken:
            with self.subTest(record=record):
                ran = self.verify(ask=self.ask_log(record))
                self.assertNotEqual(ran.returncode, 0)
                self.assertIn("ask record is incomplete or failed", ran.stderr)
                self.assertEqual(ran.stdout, "")
        for summary in ("OK (skipped=1)", "FAILED (failures=1)", ""):
            with self.subTest(summary=summary):
                ran = self.verify(ask=self.ask_log().replace("OK\n", summary + "\n"))
                self.assertNotEqual(ran.returncode, 0)
                self.assertIn("ask record is incomplete or failed", ran.stderr)
                self.assertEqual(ran.stdout, "")

    def test_missing_skipped_or_standin_build_evidence_is_refused(self):
        cases = ["", "Ran 28 tests in 1.000s\n\nOK\n", self.build.replace("OK\n", "OK (skipped=1)\n"),
                 self.build.replace("OK\n", "FAILED (failures=1)\n"),
                 self.build.replace("RealCursorBuildGate", "RealSandboxGate")]
        for name in self.BUILD_TESTS:
            cases.append("\n".join(line for line in self.build.split("\n") if not line.startswith(name)))
            cases.append(self.build.replace(name + ") ... ok", name + ") ... skipped 'no Cursor'"))
        for build in cases:
            with self.subTest(build=build[:80]):
                ran = self.verify(build=build)
                self.assertNotEqual(ran.returncode, 0)
                self.assertIn("real-build evidence is incomplete or failed", ran.stderr)
                self.assertEqual(ran.stdout, "")

    def test_complete_evidence_is_attached_to_the_offline_report(self):
        import hashlib
        ran = self.verify()
        self.assertEqual(ran.returncode, 0, ran.stderr)
        report = json.loads(ran.stdout)
        self.assertIs(report["passed"], True)
        self.assertEqual(report["ask_record"], self.record)
        self.assertEqual(report["build_tests"], sorted(self.BUILD_TESTS))
        self.assertEqual(report["build_log_sha256"], hashlib.sha256(self.build.encode()).hexdigest())
        self.assertEqual(report["ask_log_sha256"], hashlib.sha256(self.ask_log().encode()).hexdigest())
        self.assertNotIn("CURSOR_ASK_RELEASE_RECORD", ran.stderr)


class LiveProbeWiringTests(unittest.TestCase):
    PROBE = HERE / "live" / "cursor_ask_release.py"

    @classmethod
    def setUpClass(cls):
        cls.probe = load_by_path(cls.PROBE, "cursor_ask_release_under_test")

    def run_probe(self, **env):
        base = dict((k, v) for k, v in os.environ.items() if not k.startswith(("ALLOY_LIVE", "ALLOY_CURSOR")))
        base.update(ALLOY_CURSOR_BUILD_GATE="0", ALLOY_CURSOR_SANDBOX_GATE="0", ALLOY_BIN_CURSOR="/no/such/cursor-agent", ALLOY_CONFIG="/dev/null")
        base.update(env)
        return subprocess.run([sys.executable, "-B", str(self.PROBE)], capture_output=True, text=True, timeout=120, env=base)

    def test_the_probe_is_never_discovered_and_never_runs_by_accident(self):
        import fnmatch
        self.assertFalse(fnmatch.fnmatch(self.PROBE.name, "test*.py"))
        self.assertFalse((self.PROBE.parent / "__init__.py").exists(), "tests/live must not be a package")
        ids = [t.id() for t in flatten(unittest.TestLoader().discover(str(HERE), pattern="test*.py"))]
        self.assertFalse([i for i in ids if "CursorAskReleaseProbe" in i or "cursor_ask_release" in i])
        for value in (None, "", "0", "true", "yes", "2", " 1", "1 "):
            with self.subTest(flag=value):
                env = {} if value is None else {"ALLOY_LIVE_CURSOR": value}
                ran = self.run_probe(**env)
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertIn("skipped=1", ran.stderr + ran.stdout)
                self.assertNotIn("cursor-agent", ran.stdout)

    def test_the_probe_needs_the_exact_flag_and_the_production_boundary(self):
        source = self.PROBE.read_text()
        self.assertIn('LIVE = os.environ.get(FLAG) == "1"', source)
        self.assertIn('FLAG = "ALLOY_LIVE_CURSOR"', source)
        self.assertIn("@unittest.skipUnless(LIVE", source)
        for needed in ("run_panelist(", "cursor_boundary_ready", "BLOCKED", "canary_changes", "workspace_changes",
                       "SHELL_MARKER", "no_shell_process_seen", "runtime_started_directly",
                       "no_unexpected_descendant_process_seen"):
            self.assertIn(needed, source, needed)
        # it never bypasses the sandbox and never talks to a provider directly
        for forbidden in ("subprocess.Popen([\"cursor", "--force", "--yolo", "ALLOY_ALLOW_UNSANDBOXED", "CURSOR_API_KEY",
                          "--api-key", "security find-", "cursor-agent\", \"-p"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_the_probe_only_ever_uses_a_cursor_native_model(self):
        for good in ("composer-2.5", "composer-2.5[fast=false]", "composer-3", "cursor-grok-4", "cursor-grok-4[effort=high]"):
            self.assertEqual(self.probe.native_model(good), good)
        for bad in ("claude-opus-4-8", "gpt-5.6-sol", "gemini-3.8-flash", "grok-4.7", "auto", "", None, "composer",
                    "Composer-2.5", "xcomposer-2.5", "composer-2.5/../x", " composer-2.5", "kimi-k3"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.probe.native_model(bad)

    def test_release_model_documentation_matches_the_pinned_gate(self):
        self.assertIn("composer-2.5 only", self.probe.__doc__)
        self.assertIn("ALLOY_LIVE_CURSOR_MODEL", self.probe.__doc__)
        self.assertNotIn("overridable", self.probe.__doc__)
        for model in ("composer-3", "cursor-grok-4", "composer-2.5[fast=false]"):
            with self.subTest(model=model):
                ran = self.run_probe(ALLOY_LIVE_CURSOR="1", ALLOY_LIVE_CURSOR_MODEL=model)
                self.assertNotEqual(ran.returncode, 0)
                self.assertIn("composer-2.5 only", ran.stderr)
                self.assertNotIn("BLOCKED", ran.stderr)

    def test_the_probe_refuses_a_non_native_model_before_starting_anything(self):
        ran = self.run_probe(ALLOY_LIVE_CURSOR="1", ALLOY_LIVE_CURSOR_MODEL="claude-opus-4-8")
        self.assertNotEqual(ran.returncode, 0)
        self.assertIn("not Cursor-native", ran.stderr + ran.stdout)
        self.assertNotIn("claude-opus-4-8", json.dumps(ran.stdout))

    def test_the_probe_reports_a_missing_boundary_as_a_failure_not_a_skip(self):
        ran = self.run_probe(ALLOY_LIVE_CURSOR="1")             # the CLI path does not exist: not installed
        self.assertNotEqual(ran.returncode, 0)
        self.assertNotIn("skipped", ran.stderr)
        self.assertIn("BLOCKED", ran.stderr + ran.stdout)
        record = re.findall(r"CURSOR_ASK_RELEASE_RECORD (\{.*\})", ran.stderr)
        self.assertTrue(record, ran.stderr[-400:])
        data = json.loads(record[-1])
        self.assertEqual(data["gate"], "cursor-ask-release")
        self.assertIs(data["passed"], False, "a failed probe must never supply a passing release record")
        self.assertIs(data["checks"]["boundary_ready"], False)
        self.assertEqual(data["model"], "composer-2.5")

    def test_live_effect_check_refuses_any_extra_write_grant(self):
        import types
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o700)
            rt = types.SimpleNamespace(root=tmp, state=tmp + "/state", cache=tmp + "/cache", tmp=tmp + "/tmp")
            mod = types.SimpleNamespace(_sb_path=lambda p: json.dumps(p))
            home = "/fixture/home"
            profile = '\n'.join([
                ';; role=panel', '(deny file-write*)',
                '(allow file-write* (literal "/fixture/home/.cursor/auth.json"))',
                '(allow file-write-mode (literal "/fixture/home/.cursor"))',
                '(allow file-write-data (literal "/dev/null"))',
                '(allow file-write* ' + ' '.join('(subpath %s)' % json.dumps(p)
                                                 for p in (rt.state, rt.cache, rt.tmp)) + ')'])
            self.assertTrue(self.probe.private_write_profile(mod, profile, rt, home))
            self.assertFalse(self.probe.private_write_profile(mod, profile + '\n(allow file-write*)', rt, home))
            self.assertFalse(self.probe.private_write_profile(mod, profile.replace('(deny file-write*)', ''), rt, home))
            self.assertFalse(self.probe.private_write_profile(mod, profile.replace('role=panel', 'role=maker'), rt, home))

    def test_exact_process_detector_fails_off_allowlist_and_unknown_images(self):
        probe = self.probe
        marker = "--workspace /probe-marker-" + uuid.uuid4().hex
        allowed = ("/build/node", "/build/rg", "/usr/bin/sw_vers")
        observer = probe.GroupObserver(marker, allowed)
        rows = [(101, 1, 101, "(node)", "/build/node --use-system-ca /build/index.js " + marker),
                (102, 101, 101, "sh", "/bin/sh -c fixture"),
                (104, 101, 101, "node", "/build/node /build/index.js worker-server"),
                (105, 101, 101, "<defunct>", "<defunct>"),
                (103, 1, 999, "bash", "unrelated shell"),
                (106, 104, 106, "zsh", "/bin/zsh detached-session"),
                (os.getpid(), 1, 101, "python", marker)]
        paths = {101: "/build/node", 102: "/bin/sh", 104: "/build/node", 106: "/bin/zsh"}
        with patch.object(probe, "process_table", return_value=rows), \
                patch.object(probe, "executable_path", side_effect=lambda pid: paths.get(pid, "")):
            observer.sample()
        self.assertTrue(observer.leader_seen)
        self.assertEqual(observer.shells, ["/bin/sh", "/bin/zsh"])
        self.assertEqual(observer.unexpected, ["/bin/sh", "/bin/zsh", "unresolved-pid:105"])
        observer.reconcile(["Sandbox: node(105) deny(1) process-exec /bin/zsh"])
        self.assertIn(105, observer.unknown)       # denied attempts do not prove execution
        observer.reconcile(["Sandbox: rg(105) deny(1) file-write-data /dev/dtracehelper"])
        self.assertNotIn(105, observer.unknown)
        self.assertEqual(observer.descendants, {"/bin/sh", "/bin/zsh", "/build/node", "/build/rg"})
        expected = probe.GroupObserver("--workspace /x", allowed)
        expected.descendants = set(allowed)
        self.assertEqual(expected.unexpected, [])
        for stranger in ("/usr/bin/security", "/bin/sh", "/bin/bash", "/usr/bin/open", "/usr/bin/log", "/usr/bin/git",
                         "/other/build/node", "/other/rg"):
            expected.descendants = {"/build/rg", stranger}
            self.assertEqual(expected.unexpected, [stranger])
        idle = probe.GroupObserver("--workspace /nothing-runs-here-" + uuid.uuid4().hex, allowed)
        with patch.object(probe, "process_table", return_value=[]):
            idle.sample()
        self.assertFalse(idle.leader_seen)
        self.assertEqual(idle.shells, [])
        self.assertFalse(idle.started_directly)
        direct = probe.GroupObserver("--workspace /x", allowed)
        good = "/v/2026.09.28-64d2043/node --use-system-ca /v/2026.09.28-64d2043/index.js -p --workspace /x"
        direct.leader_commands = {good}
        self.assertTrue(direct.started_directly)
        for bad in ("/bin/bash /v/2026.09.28-64d2043/cursor-agent -p --workspace /x",
                    "/usr/bin/env bash /v/cursor-agent -p --workspace /x",
                    "/v/2026.09.28-64d2043/node /v/2026.09.28-64d2043/index.js -p --workspace /x",
                    "/v/2026.09.28-64d2043/node --use-system-ca /v/other.js -p --workspace /x"):
            direct.leader_commands = {good, bad}
            self.assertFalse(direct.started_directly, bad)
        # the tree manifest sees a byte change
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("one")
            before = probe.tree_manifest(tmp)
            Path(tmp, "a.txt").write_text("two")
            self.assertNotEqual(before, probe.tree_manifest(tmp))


if __name__ == "__main__":
    unittest.main()
