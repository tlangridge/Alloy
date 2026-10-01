#!/usr/bin/env python3
"""Release gate for Cursor's OS boundary: the REAL macOS `/usr/bin/sandbox-exec`.

Every other Cursor test in this repository runs against a mock `sandbox-exec` that
merely evaluates the generated profile text. That proves the text says what we mean,
not that the kernel enforces it. This module is the one place where a profile produced
by Alloy's own generator (`cursor_sbpl`, and the spawn gateway `cursor_command` that
calls it) is handed to the real binary and the operations a Cursor role must and must
not be able to perform are attempted for real.

It is discoverable (`python3 -m unittest discover -s tests` picks it up). Both classes skip
when the platform is not macOS or their explicit gate flag is absent. Once opted in, a missing or untrusted
`sandbox-exec`, an operation that could not be exercised, and every unexpected
allow/deny/read result is a test failure. The one exception is a runner that cannot have a
Cursor build at all (`RealCursorBuildGate`, below), and only when it says so explicitly.

`RealSandboxGate` uses a stand-in program for the CLI, so it needs no Cursor install.
`RealCursorBuildGate` starts the REAL pinned build's own node runtime, exactly as production
starts it, under the production panel profile and the real kernel, with `--version` and file-store `status`:
no provider inference call, no login, and keychain access is denied.
HOME is never set or changed.

Run it on its own with:

    ALLOY_CURSOR_SANDBOX_GATE=1 ALLOY_CURSOR_BUILD_GATE=1 python3 -m unittest discover -s tests -p 'test_cursor_sandbox_release_gate.py' -v
"""
import errno
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ALLOY = os.path.join(REPO, "bin", "alloy")
# The one binary the gate accepts. It is never resolved through PATH and there is no
# environment or configuration override.
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PLATFORM_SKIP = "platform: Cursor roles are supported on macOS only (sandbox-exec)"
# A runner that cannot have a Cursor build at all (a hosted CI image) says so with exactly this
# value. It excuses only ABSENCE of any `cursor-agent`; an installed build that is unsupported,
# refused by the resolver or unable to start is always a failure.
NO_BUILD_FLAG = "ALLOY_GATE_NO_CURSOR_BUILD"
NO_BUILD_SKIP = "no Cursor build on this runner: %s=1 was set explicitly" % NO_BUILD_FLAG


def load_alloy():
    """A fresh instance of the production module, untouched by any other test's patches."""
    loader = importlib.machinery.SourceFileLoader("alloy_release_gate_mod", ALLOY)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=gate", "-c", "user.email=gate@example.invalid",
         "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
        env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_OPTIONAL_LOCKS="0")).stdout


def slurp(path, mode="r"):
    with open(path, mode) as handle:
        return handle.read()


def sha(path):
    return hashlib.sha256(slurp(path, "rb")).hexdigest()


def tree_manifest(root):
    """path -> (type, mode, size, sha256 | link target) for everything below root, never
    following a symlink. A byte-level picture, so any leaked write shows up."""
    out = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root)
            st = os.lstat(full)
            if os.path.islink(full):
                out[rel] = ("l", os.readlink(full))
            elif os.path.isdir(full):
                out[rel] = ("d", oct(st.st_mode & 0o777))
            else:
                out[rel] = ("f", oct(st.st_mode & 0o777), st.st_size, sha(full), st.st_nlink)
    return out


# ---------------------------------------------------------------------------------------
# The probes run INSIDE the sandbox. Python is used (rather than shell utilities) so that
# every result is an exact errno: EPERM is the sandbox saying no, anything else (ENOENT,
# EACCES, EEXIST...) means the operation was not really exercised and the gate fails.
# ---------------------------------------------------------------------------------------
_PROBE = r'''
import errno, json, os, subprocess, sys
p = json.loads(sys.argv[1])
ops = sys.argv[2:]
out = {}

def create(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, b"gate")
    os.close(fd)

def append(path):
    with open(path, "ab") as handle:
        handle.write(b"gate")

def read(path):
    with open(path, "rb") as handle:
        handle.read(16)

def nested(path):
    os.mkdir(path)
    create(path + "/inner.txt")

def dotgit_write():
    if p["dotgit_is_file"]:
        append(p["dotgit"])
    else:
        create(p["dotgit"] + "/gate-dotgit-file")

def own_hardlink():
    create(p["tmp"] + "/gate-own")
    os.link(p["tmp"] + "/gate-own", p["tmp"] + "/gate-own-link")

def run_true():
    subprocess.run(["/usr/bin/true"], check=True)

T, W = p["tmp"], p["ws"]
OPS = {
    "control_read": lambda: read(p["control_file"]),
    "tmp_write": lambda: create(T + "/gate-tmp-file"),
    "state_write": lambda: create(p["state"] + "/gate-state-file"),
    "cache_write": lambda: create(p["cache"] + "/gate-cache-file"),
    "ws_modify": lambda: append(p["ws_file"]),
    "ws_create": lambda: create(W + "/gate-new-file.txt"),
    "ws_nested_create": lambda: nested(W + "/gate-new-dir"),
    "dotgit_write": dotgit_write,
    "dotgit_rename": lambda: os.rename(p["dotgit"], p["dotgit"] + ".moved"),
    "gitdir_create": lambda: create(p["gitdir"] + "/gate-gitdir-file"),
    "gitdir_head_append": lambda: append(p["gitdir"] + "/HEAD"),
    "common_create": lambda: create(p["common"] + "/gate-common-file"),
    "common_hook_create": lambda: create(p["common"] + "/hooks/gate-hook"),
    "common_config_append": lambda: append(p["common"] + "/config"),
    "source_write": lambda: append(p["source_file"]),
    "sibling_write": lambda: create(p["sibling"] + "/gate-sibling-file"),
    "home_write": lambda: create(p["home_new"]),
    "system_tmp_write": lambda: create(p["system_tmp_new"]),
    "temp_parent_write": lambda: create(p["temp_parent_new"]),
    "runtime_sibling_write": lambda: create(p["runtime_sibling"]),
    "runtime_root_write": lambda: create(p["runtime_root_new"]),
    "canary_write": lambda: append(p["canary_file"]),
    "outside_canary_write": lambda: append(p["outside_canary_file"]),
    "hardlink_ws_to_tmp": lambda: os.link(p["ws_file"], T + "/gate-hardlink-a"),
    "hardlink_outside_to_tmp": lambda: os.link(p["outside_file"], T + "/gate-hardlink-b"),
    "hardlink_own_in_tmp": own_hardlink,
    "hardlink_ws_to_ws": lambda: os.link(p["ws_file"], W + "/gate-hardlink-c"),
    "symlink_create_tmp_outside": lambda: os.symlink(p["outside_file"], T + "/gate-link-outside"),
    "symlink_create_tmp_outside_dir": lambda: os.symlink(p["outside_dir"], T + "/gate-link-outside-dir"),
    "symlink_create_tmp_source": lambda: os.symlink(p["source_file"], T + "/gate-link-source"),
    "symlink_create_tmp_gitdir": lambda: os.symlink(p["gitdir"] + "/HEAD", T + "/gate-link-head"),
    "symlink_write_outside": lambda: append(T + "/gate-link-outside"),
    "symlink_write_outside_dir": lambda: create(T + "/gate-link-outside-dir/gate-through"),
    "symlink_write_source": lambda: append(T + "/gate-link-source"),
    "symlink_write_gitdir": lambda: append(T + "/gate-link-head"),
    "symlink_create_ws_outside": lambda: os.symlink(p["outside_file"], W + "/gate-ws-link-outside"),
    "symlink_write_ws_outside": lambda: append(W + "/gate-ws-link-outside"),
    "symlink_create_ws_source": lambda: os.symlink(p["source_file"], W + "/gate-ws-link-source"),
    "symlink_write_ws_source": lambda: append(W + "/gate-ws-link-source"),
    "symlink_create_ws_gitdir": lambda: os.symlink(p["gitdir"] + "/HEAD", W + "/gate-ws-link-head"),
    "symlink_write_ws_gitdir": lambda: append(W + "/gate-ws-link-head"),
    "exec": run_true,
    "denied_read": lambda: read(p["sentinel"]),
    "denied_stat": lambda: os.stat(p["sentinel"]),
    "denied_list": lambda: os.listdir(p["denied_root"]),
}

for name in ops:
    try:
        OPS[name]()
        out[name] = "allowed"
    except OSError as exc:
        # EPERM is the sandbox. Anything else means the operation was not truly exercised.
        out[name] = "denied" if exc.errno == errno.EPERM else "error:" + errno.errorcode.get(exc.errno, str(exc.errno))
    except Exception as exc:
        out[name] = "error:" + type(exc).__name__
print(json.dumps(out, sort_keys=True))
'''

# A stand-in CLI: a small non-network program that does what a real CLI must still be able
# to do under the profile (start, read the workspace, write its private runtime, print) while
# the sensitive-read denial holds. It prints one deterministic line.
_FIXTURE_CLI = r'''
import errno, hashlib, json, os, sys
params = json.loads(sys.argv[1])
with open(params["ws_file"], "rb") as handle:
    digest = hashlib.sha256(handle.read()).hexdigest()[:12]
with open(os.path.join(os.environ["TMPDIR"], "fixture-out.txt"), "w") as handle:
    handle.write("written by the fixture CLI\n")
try:
    open(params["sentinel"], "rb").read(1)
    sentinel = "readable"
except OSError as exc:
    sentinel = "denied" if exc.errno == errno.EPERM else "error"
print("FIXTURE-CLI-OK %s ws=%s tmp=written sentinel=%s" % (params["token"], digest, sentinel))
'''

# Reads each path in argv[1:] and reports allowed / denied / error:<errno>.
_READ_PROBE = r'''
import errno, json, os, sys
out = {}
for path in sys.argv[1:]:
    try:
        if os.path.isdir(path):
            os.listdir(path)
        else:
            open(path, "rb").read(16)
        out[path] = "allowed"
    except OSError as exc:
        out[path] = "denied" if exc.errno == errno.EPERM else "error:" + errno.errorcode.get(exc.errno, str(exc.errno))
print(json.dumps(out, sort_keys=True))
'''

# Files (not directories) among the built-in home denials; every other entry is a directory.
_FILE_DENIALS = {".netrc", ".docker/config.json", ".npmrc", ".pypirc", ".git-credentials",
                 ".codex/auth.json", ".claude/.credentials.json"}

_WRITABLE_RUNTIME = ("tmp_write", "state_write", "cache_write")
# The three role shapes: a panel on an ordinary checkout, a Checker on a linked worktree
# (the same read-only profile as a panel) and a Maker on its owned linked worktree.
CASES = ("panel_repo", "checker_worktree", "maker_worktree")

_PANEL_ALLOW = ("control_read", "tmp_write", "state_write", "cache_write",
                "symlink_create_tmp_outside", "symlink_create_tmp_outside_dir",
                "symlink_create_tmp_source", "symlink_create_tmp_gitdir")
_COMMON_DENY = ("dotgit_write", "dotgit_rename", "gitdir_create", "gitdir_head_append", "common_create",
                "common_hook_create", "common_config_append", "sibling_write", "home_write",
                "system_tmp_write", "temp_parent_write", "runtime_sibling_write", "runtime_root_write",
                "canary_write", "outside_canary_write", "hardlink_ws_to_tmp", "hardlink_outside_to_tmp",
                "hardlink_own_in_tmp", "hardlink_ws_to_ws", "symlink_write_outside",
                "symlink_write_outside_dir", "symlink_write_source", "symlink_write_gitdir",
                "denied_read", "denied_stat", "denied_list")
_MAKER_ONLY_ALLOW = ("ws_modify", "ws_create", "ws_nested_create", "exec", "symlink_create_ws_outside",
                     "symlink_create_ws_source", "symlink_create_ws_gitdir")
_MAKER_ONLY_DENY = ("symlink_write_ws_outside", "symlink_write_ws_source", "symlink_write_ws_gitdir")
_PANEL_ONLY_DENY = ("ws_modify", "ws_create", "ws_nested_create", "exec")


def expectations(case):
    """{operation: 'allowed' | 'denied'} for one role shape. The panel/Checker profile allows
    only the private runtime; the Maker profile adds the non-Git contents of its worktree and
    process execution; both deny Git metadata, hard links, everything else and sensitive reads."""
    want = {name: "allowed" for name in _PANEL_ALLOW}
    want.update({name: "denied" for name in _COMMON_DENY})
    if case == "maker_worktree":
        want.update({name: "allowed" for name in _MAKER_ONLY_ALLOW})
        want.update({name: "denied" for name in _MAKER_ONLY_DENY})
        want["source_write"] = "denied"
    else:
        want.update({name: "denied" for name in _PANEL_ONLY_DENY})
        # For a panel on an ordinary checkout the "source checkout" IS the workspace.
        want["source_write"] = "denied"
    return want


def violations(want, got):
    """Every operation whose real result is not the expected one (including missing ones)."""
    return sorted("%s: expected %s, got %s" % (op, want[op], got.get(op, "MISSING"))
                  for op in want if got.get(op) != want[op])


class Case(object):
    """One prepared role shape: fixture tree, private runtime, generated profile."""


SANDBOX_GATE_FLAG = "ALLOY_CURSOR_SANDBOX_GATE"
BUILD_GATE_FLAG = "ALLOY_CURSOR_BUILD_GATE"


class RealSandboxGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "darwin":
            raise unittest.SkipTest(PLATFORM_SKIP)
        if os.environ.get(SANDBOX_GATE_FLAG) != "1":
            raise unittest.SkipTest("real sandbox gate requires %s=1" % SANDBOX_GATE_FLAG)
        # From here on nothing may skip: this explicitly requested gate must pass.
        cls.leaks = []
        cls.cases = {}
        cls.results = {}
        cls.stand_in_root = os.path.realpath(tempfile.mkdtemp(prefix="alloy-gate-standin-"))
        try:
            cls.check_the_binary()
            for name in CASES:
                case = cls.prepare(name)
                cls.cases[name] = case
                cls.results[name] = cls.run_case(case)
        except BaseException:
            cls.cleanup()
            raise

    @classmethod
    def check_the_binary(cls):
        if not os.path.lexists(SANDBOX_EXEC):
            raise AssertionError("%s is missing: the Cursor OS boundary cannot be verified" % SANDBOX_EXEC)
        cls.mod = load_alloy()
        if cls.mod.SANDBOX_EXEC != SANDBOX_EXEC or cls.mod.CURSOR_PLATFORM != "darwin":
            raise AssertionError("the production module does not point at the real sandbox-exec")
        # The production trust check (regular, non-symlink, root-owned, not group/other writable).
        cls.mod._verify_sandbox_exec()
        cls.interpreters = cls.mod._cursor_probe_interpreters()
        cls.launcher = cls.interpreters[0]
        cls.extra_exec = tuple(cls.interpreters[1:])
        cls.home = cls.mod.cursor_login_home()

    @classmethod
    def cleanup(cls):
        shutil.rmtree(getattr(cls, "stand_in_root", ""), True)
        for case in list(getattr(cls, "cases", {}).values()):
            case.rt.close(best_effort=True)
            shutil.rmtree(case.root, True)
        for path in getattr(cls, "leaks", []):
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, True)
            elif os.path.lexists(path):
                os.remove(path)

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    # -- fixtures ---------------------------------------------------------------------------- #
    @classmethod
    def new_root(cls, prefix):
        root = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
        return root

    @classmethod
    def prepare(cls, name):
        mod = cls.mod
        case = Case()
        case.name = name
        case.maker = name == "maker_worktree"
        case.root = cls.new_root("alloy-gate-")
        repo = os.path.join(case.root, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        for fname, body in (("tracked.txt", "tracked\n"), (".gitignore", "ignored.txt\n")):
            with open(os.path.join(repo, fname), "w") as handle:
                handle.write(body)
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "init")
        with open(os.path.join(repo, "ignored.txt"), "w") as handle:
            handle.write("ignored\n")
        case.repo = repo
        if name == "panel_repo":
            case.ws = repo
            case.source_file = os.path.join(repo, "tracked.txt")
        else:
            case.ws = os.path.join(case.root, "worktree")
            git(repo, "worktree", "add", "-q", "-b", "gate-" + name, case.ws)
            case.source_file = os.path.join(repo, "tracked.txt")
        case.ws_file = os.path.join(case.ws, "tracked.txt")
        case.git = mod.cursor_git_locations(case.ws)
        if case.git is None:
            raise AssertionError("the gate fixture is not a Git checkout")
        os.makedirs(os.path.join(case.git["common"], "hooks"), exist_ok=True)
        case.sibling = os.path.join(case.root, "sibling")
        os.makedirs(case.sibling)
        case.outside_dir = os.path.join(case.root, "outside")
        os.makedirs(case.outside_dir)
        case.outside_file = os.path.join(case.outside_dir, "target.txt")
        case.control_file = os.path.join(case.root, "control.txt")
        case.denied_root = os.path.join(case.root, "denied-root")
        os.makedirs(case.denied_root)
        case.sentinel = os.path.join(case.denied_root, "sentinel.txt")
        for path, body in ((case.outside_file, "outside-original\n"), (case.control_file, "control\n"),
                           (case.sentinel, "sentinel\n")):
            with open(path, "w") as handle:
                handle.write(body)
        case.rt = mod.cursor_make_runtime(
            forbidden=[case.root], source=repo, worktree=None if name == "panel_repo" else case.ws,
            git=case.git)
        # Sentinel under a CONFIGURED extra denied-read root, added to the real built-in set.
        case.denials = mod.cursor_denials(extra=case.denied_root)
        role = "maker" if case.maker else "panel"
        case.profile_text = mod.cursor_sbpl(
            role, exe=cls.launcher, runtime=case.rt, denials=case.denials,
            worktree=case.ws if case.maker else None, git=case.git, extra_exec=cls.extra_exec)
        mod._write_profile(case.rt, case.profile_text)
        return case

    @classmethod
    def leak_path(cls, path):
        cls.leaks.append(path)
        return path

    @classmethod
    def params(cls, case):
        tag = uuid.uuid4().hex[:12]
        return {
            "tmp": case.rt.tmp, "state": case.rt.state, "cache": case.rt.cache,
            "ws": case.ws, "ws_file": case.ws_file, "source_file": case.source_file,
            "dotgit": case.git["dotgit"], "dotgit_is_file": bool(case.git["dotgit_is_file"]),
            "gitdir": case.git["gitdir"], "common": case.git["common"],
            "sibling": case.sibling, "outside_dir": case.outside_dir, "outside_file": case.outside_file,
            "control_file": case.control_file, "sentinel": case.sentinel, "denied_root": case.denied_root,
            "home_new": cls.leak_path(os.path.join(cls.home, ".alloy-gate-" + tag)),
            "system_tmp_new": cls.leak_path("/private/tmp/alloy-gate-" + tag),
            "temp_parent_new": cls.leak_path(os.path.join(os.path.dirname(case.rt.root), "alloy-gate-" + tag)),
            "runtime_sibling": os.path.join(case.rt.root, "runtime", "gate-sibling"),
            "runtime_root_new": os.path.join(case.rt.root, "gate-root-file"),
            "canary_file": os.path.join(case.rt.canary, "canary.txt"),
            "outside_canary_file": os.path.join(case.rt.canary_outside, "canary.txt"),
        }

    @classmethod
    def sandboxed(cls, case, args, profile_path=None, timeout=60):
        """Run `<launcher> args...` under the real sandbox-exec and the generated profile."""
        argv = [SANDBOX_EXEC, "-f", profile_path or case.rt.profile, cls.launcher, "-B", "-I", "-S"] + list(args)
        return subprocess.run(argv, cwd=case.rt.tmp, env=cls.mod.cursor_child_env(case.rt, cls.home),
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)

    @classmethod
    def run_probe(cls, case, ops, params=None, profile_path=None):
        params = params if params is not None else cls.params(case)
        ran = cls.sandboxed(case, ["-c", _PROBE, json.dumps(params)] + list(ops), profile_path)
        out = ran.stdout.decode("utf-8", "replace").strip()
        try:
            return json.loads(out)
        except ValueError:
            raise AssertionError("%s: the sandboxed probe did not run (rc=%s): %s" % (
                case.name, ran.returncode, ran.stderr.decode("utf-8", "replace")[:400]))

    @classmethod
    def ops_for(cls, case):
        want = expectations(case.name)
        if not case.maker:
            # a panel cannot create a symlink in its (read-only) worktree, so the ws-symlink
            # probes have nothing to traverse: they are Maker-only operations
            want = {op: v for op, v in want.items() if not op.startswith("symlink_") or "_ws_" not in op}
        return want

    @classmethod
    def run_case(cls, case):
        want = cls.ops_for(case)
        # ordered so that a creation precedes the write through it
        order = [op for op in _OP_ORDER if op in want]
        missing = sorted(set(want) - set(order))
        if missing:
            raise AssertionError("gate operations without an order: %s" % missing)
        before = tree_manifest(case.root)
        case.head_before = slurp(os.path.join(case.git["gitdir"], "HEAD"), "rb")
        params = cls.params(case)
        got = cls.run_probe(case, order, params)
        after = tree_manifest(case.root)
        case.params = params
        case.want = want
        case.before, case.after = before, after
        return got

    # -- the assertions ---------------------------------------------------------------------- #
    def group(self, ops):
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                wanted = {op: v for op, v in case.want.items() if op in ops}
                self.assertTrue(wanted, "%s exercises none of %s" % (name, sorted(ops)))
                self.assertEqual(violations(wanted, self.results[name]), [],
                                 "%s: unexpected real sandbox result" % name)

    def test_sandbox_exec_is_the_real_trusted_binary(self):
        st = os.lstat(SANDBOX_EXEC)
        self.assertTrue(stat_is_regular(st), SANDBOX_EXEC)
        self.assertEqual(st.st_uid, 0)
        self.assertEqual(st.st_mode & 0o022, 0)
        self.assertEqual(self.mod.SANDBOX_EXEC, SANDBOX_EXEC)
        self.assertEqual(self.mod.SANDBOX_TRUSTED_UID, 0)
        for case in self.cases.values():
            self.assertTrue(case.profile_text.startswith("(version 1)"))

    def test_the_private_runtime_is_the_only_writable_place_for_a_panel_or_checker(self):
        self.group(set(_WRITABLE_RUNTIME))
        for name, role in (("panel_repo", "panel"), ("checker_worktree", "checker")):
            case = self.cases[name]
            with self.subTest(role=role):
                for op, child in (("tmp_write", case.rt.tmp), ("state_write", case.rt.state),
                                  ("cache_write", case.rt.cache)):
                    self.assertTrue(any(f.startswith("gate-") for f in os.listdir(child)), (role, op))

    def test_repository_writes_are_denied_for_a_panel_and_a_checker(self):
        for name in ("panel_repo", "checker_worktree"):
            case = self.cases[name]
            with self.subTest(case=name):
                self.assertEqual(violations({op: case.want[op] for op in _PANEL_ONLY_DENY + ("source_write",)},
                                            self.results[name]), [])
                self.assertEqual(sha(case.ws_file), sha_of_text("tracked\n"), "the workspace file changed")
                self.assertFalse(os.path.lexists(os.path.join(case.ws, "gate-new-file.txt")))
                self.assertFalse(os.path.lexists(os.path.join(case.ws, "gate-new-dir")))

    def test_a_maker_can_write_the_non_git_contents_of_its_worktree_only(self):
        case = self.cases["maker_worktree"]
        self.assertEqual(violations({op: case.want[op] for op in ("ws_modify", "ws_create", "ws_nested_create", "exec")},
                                    self.results["maker_worktree"]), [])
        self.assertEqual(slurp(case.ws_file, "rb"), b"tracked\ngate")
        self.assertTrue(os.path.isfile(os.path.join(case.ws, "gate-new-file.txt")))
        self.assertTrue(os.path.isfile(os.path.join(case.ws, "gate-new-dir", "inner.txt")))
        # ... and nothing outside it: the source checkout is not the worktree.
        self.assertEqual(sha(case.source_file), sha_of_text("tracked\n"))
        self.assertEqual(violations({"source_write": "denied", "sibling_write": "denied"},
                                    self.results["maker_worktree"]), [])

    def test_git_metadata_is_write_denied_in_every_role(self):
        self.group({"dotgit_write", "dotgit_rename", "gitdir_create", "gitdir_head_append",
                    "common_create", "common_hook_create", "common_config_append"})
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                self.assertTrue(os.path.lexists(case.git["dotgit"]), ".git entry was moved")
                self.assertFalse(os.path.lexists(case.git["dotgit"] + ".moved"))
                self.assertFalse(os.path.lexists(os.path.join(case.git["gitdir"], "gate-gitdir-file")))
                self.assertFalse(os.path.lexists(os.path.join(case.git["common"], "gate-common-file")))
                self.assertFalse(os.path.lexists(os.path.join(case.git["common"], "hooks", "gate-hook")))
        # the linked worktree's pointer really is a file and the maker's gitdir/common are distinct
        maker = self.cases["maker_worktree"]
        self.assertTrue(maker.git["dotgit_is_file"])
        self.assertNotEqual(maker.git["gitdir"], maker.git["common"])

    def test_nothing_else_under_home_system_temp_or_the_runtime_is_writable(self):
        self.group({"home_write", "system_tmp_write", "temp_parent_write", "sibling_write",
                    "runtime_sibling_write", "runtime_root_write", "canary_write", "outside_canary_write"})
        for name in CASES:
            case = self.cases[name]
            for key in ("home_new", "system_tmp_new", "temp_parent_new"):
                self.assertFalse(os.path.lexists(case.params[key]), "%s leaked %s" % (name, key))
            self.assertEqual(slurp(case.params["canary_file"]), "alloy canary: never written by a Cursor process\n")
            self.assertEqual(slurp(case.params["outside_canary_file"]),
                             "alloy canary: never written by a Cursor process\n")

    def test_hard_links_are_denied_in_every_role(self):
        self.group({"hardlink_ws_to_tmp", "hardlink_outside_to_tmp", "hardlink_own_in_tmp", "hardlink_ws_to_ws"})
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                for leaked in (os.path.join(case.rt.tmp, "gate-hardlink-a"), os.path.join(case.rt.tmp, "gate-hardlink-b"),
                               os.path.join(case.rt.tmp, "gate-own-link"), os.path.join(case.ws, "gate-hardlink-c")):
                    self.assertFalse(os.path.lexists(leaked), leaked)
                self.assertEqual(os.stat(case.outside_file).st_nlink, 1)
                self.assertEqual(os.stat(case.source_file).st_nlink, 1)

    def test_symlink_traversal_cannot_write_its_target(self):
        self.group({"symlink_create_tmp_outside", "symlink_create_tmp_outside_dir", "symlink_create_tmp_source",
                    "symlink_create_tmp_gitdir", "symlink_write_outside", "symlink_write_outside_dir",
                    "symlink_write_source", "symlink_write_gitdir"})
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                self.assertEqual(slurp(case.outside_file), "outside-original\n")
                self.assertFalse(os.path.lexists(os.path.join(case.outside_dir, "gate-through")))
                self.assertEqual(sha(case.source_file), sha_of_text("tracked\n"))
                self.assertEqual(slurp(os.path.join(case.git["gitdir"], "HEAD"), "rb"), case.head_before)
        maker = self.cases["maker_worktree"]
        self.assertEqual(violations({op: maker.want[op] for op in maker.want if "_ws_" in op},
                                    self.results["maker_worktree"]), [])

    def test_process_execution_is_denied_for_a_panel_and_allowed_for_a_maker(self):
        self.group({"exec"})

    def test_no_role_changed_anything_the_profile_did_not_grant(self):
        """The byte-level picture of the fixture tree: a panel or Checker changed NOTHING;
        a Maker changed only non-Git worktree content."""
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                changed = sorted(k for k in set(case.before) | set(case.after) if case.before.get(k) != case.after.get(k))
                if case.maker:
                    wt = os.path.relpath(case.ws, case.root)
                    stray = [k for k in changed
                             if not k.startswith(wt + os.sep) or k == os.path.join(wt, ".git")
                             or k.startswith(os.path.join(wt, ".git") + os.sep)]
                    self.assertEqual(stray, [])
                    self.assertTrue(changed, "the Maker probe changed nothing: it did not exercise the grant")
                else:
                    self.assertEqual(changed, [])

    def test_a_sentinel_under_a_configured_denied_root_is_unreadable_and_the_cli_fixture_still_runs(self):
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                # the parent CAN read it (so the denial is what stops the sandboxed process)
                self.assertEqual(slurp(case.sentinel), "sentinel\n")
                self.assertEqual(violations({op: case.want[op] for op in ("denied_read", "denied_stat", "denied_list",
                                                                          "control_read")}, self.results[name]), [])
                # A working profile with targeted read denials still lets a CLI start and work.
                token = uuid.uuid4().hex[:8]
                fixture = os.path.join(case.root, "fixture_cli.py")
                with open(fixture, "w") as handle:
                    handle.write(_FIXTURE_CLI)
                params = {"ws_file": case.ws_file, "sentinel": case.sentinel, "token": token}
                ran = self.sandboxed(case, [fixture, json.dumps(params)])
                self.assertEqual(ran.returncode, 0, ran.stderr.decode("utf-8", "replace")[:400])
                expected = "FIXTURE-CLI-OK %s ws=%s tmp=written sentinel=denied\n" % (token, sha(case.ws_file)[:12])
                self.assertEqual(ran.stdout.decode("utf-8"), expected)
                self.assertTrue(os.path.isfile(os.path.join(case.rt.tmp, "fixture-out.txt")))

    def test_every_builtin_sensitive_read_is_denied_by_the_real_kernel(self):
        mod = self.mod
        for role in ("panel", "maker"):
            with self.subTest(role=role):
                fake_home = self.new_root("alloy-gate-home-")
                self.addCleanup(shutil.rmtree, fake_home, True)
                targets, controls = [], []
                for rel in mod._CURSOR_HOME_DENIALS:
                    path = os.path.join(fake_home, rel)
                    if rel in _FILE_DENIALS:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "w") as handle:
                            handle.write("credential\n")
                        targets.append(path)
                    else:
                        os.makedirs(path)
                        with open(os.path.join(path, "sentinel.txt"), "w") as handle:
                            handle.write("credential\n")
                        targets.extend([path, os.path.join(path, "sentinel.txt")])
                onepw = os.path.join(fake_home, "Library", "Group Containers", "ABCDE.com.1password.test")
                other = os.path.join(fake_home, "Library", "Group Containers", "group.com.other.test")
                for path in (onepw, other):
                    os.makedirs(path)
                    with open(os.path.join(path, "sentinel.txt"), "w") as handle:
                        handle.write("x\n")
                targets.append(os.path.join(onepw, "sentinel.txt"))
                controls.append(os.path.join(other, "sentinel.txt"))
                secret_tag = uuid.uuid4().hex[:10]
                secret_dir = self.leak_path("/private/tmp/alloy-gate-Secret-" + secret_tag)
                plain_dir = self.leak_path("/private/tmp/alloy-gate-plain-" + secret_tag)
                for path in (secret_dir, plain_dir):
                    os.makedirs(path)
                    with open(os.path.join(path, "sentinel.txt"), "w") as handle:
                        handle.write("x\n")
                self.addCleanup(shutil.rmtree, secret_dir, True)
                self.addCleanup(shutil.rmtree, plain_dir, True)
                targets.extend([secret_dir, os.path.join(secret_dir, "sentinel.txt")])
                controls.extend([os.path.join(plain_dir, "sentinel.txt")])
                control_home = os.path.join(fake_home, "readable.txt")
                with open(control_home, "w") as handle:
                    handle.write("x\n")
                controls.append(control_home)
                case = self.cases["maker_worktree" if role == "maker" else "panel_repo"]
                den = mod.cursor_denials(home=fake_home)
                profile = mod.cursor_sbpl(role, exe=self.launcher, runtime=case.rt, denials=den,
                                          worktree=case.ws if role == "maker" else None,
                                          git=case.git, extra_exec=self.extra_exec)
                path = os.path.join(case.root, "builtin-%s.sb" % role)
                with open(path, "w") as handle:
                    handle.write(profile)
                ran = self.sandboxed(case, ["-c", _READ_PROBE] + targets + controls, profile_path=path)
                self.assertEqual(ran.returncode, 0, ran.stderr.decode("utf-8", "replace")[:400])
                got = json.loads(ran.stdout.decode("utf-8"))
                want = dict((p, "denied") for p in targets)
                want.update(dict((p, "allowed") for p in controls))
                bad = sorted("%s: expected %s, got %s" % (p, want[p], got.get(p, "MISSING")) for p in want
                             if got.get(p) != want[p])
                self.assertEqual(bad, [])
                self.assertGreaterEqual(len(targets), len(mod._CURSOR_HOME_DENIALS))

    def test_the_gateway_profile_is_the_generator_profile_this_gate_verified(self):
        """cursor_command (the spawn gateway) turns a role into cursor_sbpl arguments. With the
        boundary readiness (which needs a real CLI build) supplied by the caller, its profile for
        each role must equal the generator's for the same inputs, so what this gate proves about
        cursor_sbpl is what ships."""
        mod = self.mod
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                pdir = os.path.join(case.root, "gateway-" + name)
                adapter = mod.CursorAgentAdapter()
                if case.maker:
                    adapter.__class__ = type("ManagedCursor", (mod.CursorAgentAdapter,), {"read_only": False})
                ctx = {"repo": case.ws, "pdir": pdir, "cwd": case.ws, "scope": case.rt}
                with mock.patch.dict(os.environ, {"ALLOY_CURSOR_MODEL": "composer-2.5"}):
                    tail = adapter.build_args(self.prompt_file(case), "", "consult", ctx)
                boundary = mod.CursorBoundary(True, "", "gate", self.launcher, self.stand_in_script())
                try:
                    with mock.patch.object(mod, "cursor_boundary", return_value=boundary):
                        argv = mod.cursor_command(
                            "maker" if case.maker else "panel", tail, exe=self.launcher, runtime=case.rt,
                            workspace=case.ws, staged=ctx["cursor_staged"],
                            expected_model=ctx["cursor_expected_model"], managed_worktree=case.maker, cwd=case.ws)
                    with open(case.rt.profile) as handle:
                        gateway_profile = handle.read()
                finally:
                    mod._write_profile(case.rt, case.profile_text)     # the gateway rewrote the file
                # sandbox-exec -f <profile> <runtime binary> <its fixed flag> <entry script> <closed-grammar tail>
                self.assertEqual(argv[:6], [SANDBOX_EXEC, "-f", case.rt.profile, self.launcher,
                                            *mod.CURSOR_NODE_ARGS, self.stand_in_script()])
                self.assertEqual(argv[6:], tail)
                expected = mod.cursor_sbpl("maker" if case.maker else "panel", exe=self.launcher, runtime=case.rt,
                                           denials=mod.cursor_denials(), worktree=case.ws if case.maker else None,
                                           git=case.git)
                self.assertEqual(gateway_profile, expected)

    def test_the_configured_denial_setting_reaches_the_kernel_through_the_gateway(self):
        """ALLOY_CURSOR_DENY_READ_PATHS is the operator-facing setting. Through the real spawn
        gateway it must produce a profile under which the real kernel refuses the sentinel, while a
        neighbouring file stays readable, for every role shape."""
        mod = self.mod
        exe = self.interpreters[-1]              # the interpreter image: the only executable allowed
        for name in CASES:
            case = self.cases[name]
            with self.subTest(case=name):
                pdir = os.path.join(case.root, "setting-" + name)
                adapter = mod.CursorAgentAdapter()
                if case.maker:
                    adapter.__class__ = type("ManagedCursor", (mod.CursorAgentAdapter,), {"read_only": False})
                ctx = {"repo": case.ws, "pdir": pdir, "cwd": case.ws, "scope": case.rt}
                boundary = mod.CursorBoundary(True, "", "gate", exe, self.stand_in_script())
                try:
                    with mock.patch.dict(os.environ, {"ALLOY_CURSOR_MODEL": "composer-2.5",
                                                      "ALLOY_CURSOR_DENY_READ_PATHS": case.denied_root}):
                        tail = adapter.build_args(self.prompt_file(case), "", "consult", ctx)
                        with mock.patch.object(mod, "cursor_boundary", return_value=boundary):
                            argv = mod.cursor_command(
                                "maker" if case.maker else "panel", tail, exe=exe, runtime=case.rt,
                                workspace=case.ws, staged=ctx["cursor_staged"],
                                expected_model=ctx["cursor_expected_model"], managed_worktree=case.maker, cwd=case.ws)
                    self.assertEqual(argv[:6], [SANDBOX_EXEC, "-f", case.rt.profile, exe,
                                                *mod.CURSOR_NODE_ARGS, self.stand_in_script()])
                    ran = subprocess.run(
                        [SANDBOX_EXEC, "-f", case.rt.profile, exe, "-B", "-I", "-S", "-c", _READ_PROBE,
                         case.sentinel, case.denied_root, case.control_file],
                        cwd=case.rt.tmp, env=mod.cursor_child_env(case.rt, self.home), stdin=subprocess.DEVNULL,
                        capture_output=True, timeout=60)
                finally:
                    mod._write_profile(case.rt, case.profile_text)
                self.assertEqual(ran.returncode, 0, ran.stderr.decode("utf-8", "replace")[:400])
                got = json.loads(ran.stdout.decode("utf-8"))
                self.assertEqual(got, {case.sentinel: "denied", case.denied_root: "denied", case.control_file: "allowed"})

    def prompt_file(self, case):
        path = os.path.join(case.root, "gateway-prompt.txt")
        if not os.path.exists(path):
            with open(path, "w") as handle:
                handle.write("gate prompt\n")
        return path

    # -- the gate must be able to fail --------------------------------------------------------- #
    def throwaway(self, name):
        """A private case: what these negative controls do to it never touches the shared ones."""
        case = self.prepare(name)
        self.addCleanup(shutil.rmtree, case.root, True)
        self.addCleanup(case.rt.close, True)
        return case

    def test_the_harness_detects_a_profile_that_does_not_enforce(self):
        """Run the same battery under a profile that allows everything: the expectations must
        report violations. A gate that cannot go red proves nothing."""
        case = self.throwaway("checker_worktree")
        permissive = os.path.join(case.root, "permissive.sb")
        with open(permissive, "w") as handle:
            handle.write("(version 1)\n(allow default)\n")
        ops = [op for op in _OP_ORDER if op in ("ws_create", "hardlink_ws_to_tmp", "symlink_create_tmp_outside",
                                               "symlink_write_outside", "denied_read", "denied_stat", "exec",
                                               "gitdir_create", "control_read")]
        want = dict((op, expectations("checker_worktree")[op]) for op in ops)
        got = self.run_probe(case, ops, self.params(case), profile_path=permissive)
        found = violations(want, got)
        self.assertGreaterEqual(len(found), 7, found)
        self.assertEqual(got["denied_read"], "allowed")
        self.assertEqual(got["hardlink_ws_to_tmp"], "allowed")
        # ... and the real, generated profile passes the very same expectations.
        self.assertEqual(violations(want, self.results["checker_worktree"]), [])

    def test_a_profile_that_prevents_all_useful_execution_fails_the_cli_fixture_check(self):
        case = self.throwaway("panel_repo")
        deny_all = os.path.join(case.root, "deny-all.sb")
        with open(deny_all, "w") as handle:
            handle.write("(version 1)\n(deny default)\n")
        fixture = os.path.join(case.root, "fixture_cli.py")
        with open(fixture, "w") as handle:
            handle.write(_FIXTURE_CLI)
        params = {"ws_file": case.ws_file, "sentinel": case.sentinel, "token": "x"}
        ran = self.sandboxed(case, [fixture, json.dumps(params)], profile_path=deny_all)
        self.assertNotEqual(ran.returncode, 0)
        self.assertNotIn(b"FIXTURE-CLI-OK", ran.stdout)

    # -- the production self-test, on the real sandbox ------------------------------------------- #
    def real_image(self):
        return self.interpreters[-1]

    def test_the_production_self_test_passes_on_the_real_sandbox(self):
        mod = self.fresh_production_module()
        patches = self.python_cli_constants_for(mod)
        with patches[0], patches[1], patches[2], patches[3]:
            boundary = mod.cursor_boundary(self.real_image())
        self.assertTrue(boundary.ready, boundary.reason)
        self.assertEqual(boundary.reason, "")
        self.assertEqual((boundary.exe, boundary.script), (self.real_image(), self.stand_in_script()))

    def fresh_production_module(self):
        return load_alloy()

    @classmethod
    def stand_in_script(cls):
        """The stand-in CLI's entry script: prints the version the stand-in build reports."""
        path = os.path.join(cls.stand_in_root, "index.py")
        if not os.path.exists(path):
            with open(path, "w") as handle:
                handle.write("import sys\nprint('Python %d.%d.%d' % sys.version_info[:3])\n")
        return path

    def python_cli_constants_for(self, mod):
        """The production boundary, with the running Python image standing in for the build's
        node: the resolver returns it, the fixed node arguments become Python's, and its own
        version string is the supported build. Everything else (the sandbox, the profiles, the
        probe, the spawn shape, the version check) is production code."""
        version = "Python %d.%d.%d" % sys.version_info[:3]
        script = self.stand_in_script()
        build = mod.CursorBuild(os.path.dirname(script), self.real_image(), script, version, ("gate", version))
        return (mock.patch.object(mod, "CURSOR_VERSION_RE", re.compile(r"\b(Python \d+\.\d+\.\d+)\b")),
                mock.patch.object(mod, "CURSOR_SUPPORTED_VERSIONS", (version,)),
                mock.patch.object(mod, "cursor_resolve_build", return_value=build),
                mock.patch.object(mod, "CURSOR_NODE_ARGS", ("-B", "-I", "-S")))

    def sabotaged_boundary(self, drop):
        mod = self.fresh_production_module()
        real = mod.cursor_sbpl

        def sbpl(*args, **kwargs):
            text = real(*args, **kwargs)
            return "".join(line for line in text.splitlines(True) if not drop(line))
        patches = self.python_cli_constants_for(mod)
        with patches[0], patches[1], patches[2], patches[3], mock.patch.object(mod, "cursor_sbpl", side_effect=sbpl):
            return mod.cursor_boundary(self.real_image())

    def test_the_production_self_test_refuses_a_profile_without_the_hard_link_denial(self):
        boundary = self.sabotaged_boundary(lambda line: line.strip() == "(deny file-link)")
        self.assertFalse(boundary.ready)
        self.assertIn("link", boundary.reason)

    def test_the_production_self_test_refuses_a_profile_without_the_read_denials(self):
        boundary = self.sabotaged_boundary(lambda line: line.startswith("(deny file-read*"))
        self.assertFalse(boundary.ready)
        self.assertIn("denied_read", boundary.reason)

    def test_the_production_self_test_refuses_a_profile_without_the_write_denial(self):
        boundary = self.sabotaged_boundary(lambda line: line.strip() == "(deny file-write*)")
        self.assertFalse(boundary.ready)
        self.assertIn("outside_write", boundary.reason)


class RealCursorBuildGate(unittest.TestCase):
    """The pinned Cursor build's OWN node runtime, started exactly as production starts it, under
    the production panel profile, on the real kernel sandbox. Version and file-store
    status only: no provider inference call.

    The `cursor-agent` a user runs is a bash launcher, and a panel/Checker profile denies every
    process execution except its three verified CLI binaries. Allowing the launcher made sandbox-exec fail with exit 71 before
    the CLI ever ran, so every Cursor role was unavailable on macOS. Alloy therefore resolves the
    build directory and starts `<dir>/node` directly. Nothing here may be replaced by a stand-in:
    if the real runtime cannot start, this gate fails.

    The build's own code starts `sw_vers` and its bundled `rg`, so the panel profile allows
    exactly three literal executables. File credentials keep security execution denied. This
    class asserts that list from its own copy of it (not from production's), proves `status` reaches the
    authenticated state under the production panel profile (status only: no inference), and proves a
    shell and the other system tools are denied by the real kernel."""

    # The exact allowance, written out here on purpose: production's constants are not the reference.
    SYSTEM_EXECS = ("/usr/bin/sw_vers",)
    DENIED_EXECS = (("/usr/bin/security", ["help"]), ("/bin/sh", ["-c", "exit 0"]), ("/bin/bash", ["-c", "exit 0"]), ("/bin/zsh", ["-c", "exit 0"]),
                    ("/usr/bin/open", ["-h"]), ("/usr/bin/log", ["help"]), ("/usr/bin/true", []),
                    ("/usr/bin/env", ["true"]), ("/usr/bin/git", ["--version"]))

    @classmethod
    def setUpClass(cls):
        if sys.platform != "darwin":
            raise unittest.SkipTest(PLATFORM_SKIP)
        if os.environ.get(BUILD_GATE_FLAG) != "1":
            raise unittest.SkipTest("real Cursor build gate requires %s=1" % BUILD_GATE_FLAG)
        if not os.path.lexists(SANDBOX_EXEC):
            raise AssertionError("%s is missing: the Cursor OS boundary cannot be verified" % SANDBOX_EXEC)
        cls.mod = load_alloy()
        if cls.mod.SANDBOX_EXEC != SANDBOX_EXEC or cls.mod.CURSOR_PLATFORM != "darwin":
            raise AssertionError("the production module does not point at the real sandbox-exec")
        cls.mod._verify_sandbox_exec()
        cls.bin_path = cls.mod.CursorAgentAdapter().resolved_bin()
        if cls.bin_path is None:
            if os.environ.get(NO_BUILD_FLAG) == "1":
                raise unittest.SkipTest(NO_BUILD_SKIP)
            raise AssertionError(
                "no cursor-agent is installed (none on PATH, none in ALLOY_BIN_CURSOR): the real Cursor runtime "
                "cannot be started under the sandbox. Install the supported build, or, on a runner that cannot "
                "have one, set %s=1." % NO_BUILD_FLAG)
        # An installed Cursor: from here on nothing skips. The production resolver must reach the
        # pinned build (following symlinks and past any wrapper) and accept it.
        cls.build = cls.mod.cursor_resolve_build(cls.bin_path)

    def runtime(self):
        rt = self.mod.cursor_make_runtime([self.build.node])
        self.addCleanup(rt.close, True)
        return rt

    def run_in(self, rt, argv):
        return subprocess.run(argv, cwd=rt.tmp, env=self.mod.cursor_child_env(rt), stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=60)

    def test_the_production_resolver_reaches_a_supported_build_and_its_own_node(self):
        mod, build = self.mod, self.build
        self.assertIn(build.build, mod.CURSOR_SUPPORTED_VERSIONS)
        self.assertEqual(os.path.basename(build.dir), build.build)
        self.assertEqual((build.node, build.script), (os.path.join(build.dir, "node"), os.path.join(build.dir, "index.js")))
        self.assertEqual(build.rg, os.path.join(build.dir, "rg"))
        for path in (build.dir, build.node, build.script, build.rg):
            st = os.lstat(path)
            self.assertFalse(stat.S_ISLNK(st.st_mode), path)
            self.assertEqual(st.st_uid, os.getuid(), path)
            self.assertEqual(st.st_mode & 0o022, 0, path)
        for path in (build.node, build.script, build.rg):
            self.assertTrue(stat_is_regular(os.lstat(path)), path)
        for path in (build.node, build.rg):
            self.assertTrue(os.access(path, os.X_OK), path)

    def test_the_os_version_tool_is_the_real_root_owned_file(self):
        for path in self.SYSTEM_EXECS:
            st = os.lstat(path)
            self.assertTrue(stat_is_regular(st), path)                 # regular, not a symlink
            self.assertEqual(st.st_uid, 0, path)                        # root-owned
            self.assertEqual(st.st_mode & 0o022, 0, path)               # not writable by others
            self.assertTrue(os.access(path, os.X_OK), path)

    def test_the_production_boundary_starts_the_real_node_under_the_panel_and_maker_profiles(self):
        # The self-test starts `<dir>/node --use-system-ca <dir>/index.js --version` under the
        # generated panel profile and again under the Maker profile, and requires the pinned build.
        boundary = self.mod.cursor_boundary(self.bin_path)
        self.assertTrue(boundary.ready, boundary.reason)
        self.assertEqual((boundary.exe, boundary.script), (self.build.node, self.build.script))
        self.assertEqual(tuple(boundary.execs), (self.build.rg,) + self.SYSTEM_EXECS)
        self.assertIn(self.build.build, boundary.version)

    def test_the_real_node_runs_under_the_production_panel_profile_that_allows_only_it(self):
        mod, build = self.mod, self.build
        rt = self.runtime()
        argv = mod.cursor_command("version", ["--version"], exe=self.bin_path, runtime=rt)
        self.assertEqual(argv[:2], [SANDBOX_EXEC, "-f"])
        self.assertEqual(argv[3:], [build.node, "--use-system-ca", build.script, "--version", "--sandbox", "disabled"])
        profile = slurp(rt.profile)
        self.assertIn("role=panel", profile)
        # Process execution: denied, then allowed for exactly three literal paths -- the runtime binary,
        # the build's bundled rg and /usr/bin/sw_vers. No shell, no launcher.
        allowed = (build.node, build.rg) + self.SYSTEM_EXECS
        self.assertEqual([ln for ln in profile.splitlines() if "process-exec" in ln],
                         ["(deny process-exec*)",
                          "(allow process-exec " + " ".join("(literal %s)" % mod._sb_path(p) for p in allowed) + ")"])
        ran = self.run_in(rt, argv)
        self.assertEqual(ran.returncode, 0, ran.stderr.decode("utf-8", "replace")[:400])
        self.assertEqual(ran.stdout.decode("utf-8").strip(), build.build)

    def test_status_reaches_the_authenticated_state_under_the_production_panel_profile(self):
        # Status only: file credentials, no inference. Keychain reads and security exec
        # remain denied. The output may name the account, so failure messages mask it.
        hint = ("status did not authenticate under the production panel profile; run "
                "`AGENT_CLI_CREDENTIAL_STORE=file cursor-agent login`. Output: ")
        mod, build = self.mod, self.build
        rt = self.runtime()
        argv = mod.cursor_command("status", ["status"], exe=self.bin_path, runtime=rt)
        self.assertEqual(argv[3:], [build.node, "--use-system-ca", build.script, "status", "--sandbox", "disabled"])
        profile = slurp(rt.profile)
        self.assertIn("role=panel", profile)
        home = mod.cursor_login_home()
        keychains = os.path.join(home, "Library", "Keychains")
        self.assertIn("(deny file-read* (literal %s) (subpath %s))" %
                      (mod._sb_path(keychains), mod._sb_path(keychains)), profile)
        self.assertNotIn('(literal "/usr/bin/security")', profile)
        self.assertEqual(mod.cursor_child_env(rt)["AGENT_CLI_CREDENTIAL_STORE"], "file")
        ran = self.run_in(rt, argv)
        text = mod.strip_ansi((ran.stdout + ran.stderr).decode("utf-8", "replace"))
        shown = re.sub(r"\S+@\S+", "<account>", text)[:300]              # never show an account name
        self.assertEqual(ran.returncode, 0, hint + shown)
        self.assertIsNotNone(mod._CURSOR_LOGGED_IN_RE.search(text), hint + shown)
        self.assertNotIn("EPERM", text)
        # ... and the same through the production adapter: the state doctor and the panel see
        adapter = mod.CursorAgentAdapter()
        self.assertEqual(adapter.auth_state(), "ready")

    def test_a_shell_and_the_other_system_tools_are_denied_by_the_real_kernel_and_the_three_are_allowed(self):
        mod, build = self.mod, self.build
        rt = self.runtime()
        mod.cursor_command("version", ["--version"], exe=self.bin_path, runtime=rt)      # writes the panel profile
        for tool, args in self.DENIED_EXECS:
            with self.subTest(denied=tool):
                self.assertTrue(os.path.exists(tool), tool)
                ran = self.run_in(rt, [SANDBOX_EXEC, "-f", rt.profile, tool] + args)
                self.assertEqual(ran.returncode, 71, tool)                # sandbox-exec: exec refused
                self.assertIn(b"Operation not permitted", ran.stderr)
        for label, cmd in (("node", [build.node, "--version"]), ("rg", [build.rg, "--version"]),
                           ("sw_vers", ["/usr/bin/sw_vers", "-productVersion"])):
            with self.subTest(allowed=label):
                ran = self.run_in(rt, [SANDBOX_EXEC, "-f", rt.profile] + cmd)
                self.assertEqual(ran.returncode, 0, label)
                self.assertTrue(ran.stdout.strip(), label)

    def test_the_bash_launcher_cannot_start_under_that_profile_which_is_why_it_is_never_used(self):
        mod, build = self.mod, self.build
        launcher = os.path.join(build.dir, "cursor-agent")
        self.assertTrue(os.path.isfile(launcher), "the supported build has no launcher to compare against")
        rt = self.runtime()
        mod.cursor_command("version", ["--version"], exe=self.bin_path, runtime=rt)     # writes the panel profile
        ran = self.run_in(rt, [SANDBOX_EXEC, "-f", rt.profile, launcher, "--version"])
        self.assertNotEqual(ran.returncode, 0)                                            # sandbox-exec: exit 71
        self.assertNotIn(build.build.encode(), ran.stdout)

    def test_the_gate_can_fail_a_profile_that_allows_only_the_launcher_or_nothing_stops_the_runtime(self):
        mod, build = self.mod, self.build
        launcher = os.path.join(build.dir, "cursor-agent")
        rt = self.runtime()
        node_argv = [SANDBOX_EXEC, "-f", rt.profile, build.node, *mod.CURSOR_NODE_ARGS, build.script, "--version", "--sandbox", "disabled"]
        for label, exe in (("launcher only", launcher), ("nothing", "/var/empty/nothing")):
            with self.subTest(allowed=label):
                mod._write_profile(rt, mod.cursor_sbpl("panel", exe=exe, runtime=rt, denials=mod.cursor_denials()))
                ran = self.run_in(rt, node_argv)
                self.assertNotEqual(ran.returncode, 0)
                self.assertNotIn(build.build.encode(), ran.stdout)
        mod._write_profile(rt, mod.cursor_sbpl("panel", exe=build.node, runtime=rt, denials=mod.cursor_denials()))
        ran = self.run_in(rt, node_argv)                     # the same command passes when the node is allowed
        self.assertEqual((ran.returncode, ran.stdout.decode("utf-8").strip()), (0, build.build))


def stat_is_regular(st):
    return stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def sha_of_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# One order for the whole battery: a symlink is created before it is written through, and the
# operations that move or replace things come last.
_OP_ORDER = ["control_read", "tmp_write", "state_write", "cache_write",
             "ws_modify", "ws_create", "ws_nested_create",
             "symlink_create_tmp_outside", "symlink_create_tmp_outside_dir", "symlink_create_tmp_source",
             "symlink_create_tmp_gitdir", "symlink_write_outside", "symlink_write_outside_dir",
             "symlink_write_source", "symlink_write_gitdir",
             "symlink_create_ws_outside", "symlink_write_ws_outside", "symlink_create_ws_source",
             "symlink_write_ws_source", "symlink_create_ws_gitdir", "symlink_write_ws_gitdir",
             "hardlink_ws_to_tmp", "hardlink_outside_to_tmp", "hardlink_own_in_tmp", "hardlink_ws_to_ws",
             "gitdir_create", "gitdir_head_append", "common_create", "common_hook_create",
             "common_config_append", "source_write", "sibling_write",
             "home_write", "system_tmp_write", "temp_parent_write", "runtime_sibling_write",
             "runtime_root_write", "canary_write", "outside_canary_write",
             "exec", "denied_read", "denied_stat", "denied_list",
             "dotgit_write", "dotgit_rename"]


if __name__ == "__main__":
    unittest.main()
