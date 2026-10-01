#!/usr/bin/env python3
"""Tests for the alloy dispatcher, driven by a mock panelist CLI so they cost
no tokens. Run with:  python3 -m unittest discover -s tests -v
"""
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ALLOY = os.path.join(REPO, "bin", "alloy")
MOCK = os.path.join(HERE, "mocks", "mock_panelist.py")
# The fixture Cursor install (versions/<build>/{cursor-agent, node, index.js}) is built by test_execution.
import test_execution as texec  # noqa: E402  (module import only: its test classes are not collected here)


def run_alloy(args, env_extra=None, timeout=60, cwd=None):
    env = dict(os.environ)
    # Hermetic: the default panel is now "all available" adapters, and a dev
    # machine has real grok/claude/etc. installed. Ignore the user config and pin
    # the panel to the two mocked adapters so no real CLI is ever spawned. Tests
    # that exercise another adapter pass --panelists explicitly (the CLI flag
    # overrides this env).
    env["ALLOY_CONFIG"] = "/dev/null"
    env["ALLOY_USAGE"] = "off"  # No real provider reads during mock tests
    env["ALLOY_PANELISTS"] = "codex,claude"
    # Repo access defaults ON (auto-detects the git root) -- but the test process
    # cwd IS a git repo (alloy's own), so pin it OFF by default to stay hermetic.
    # Repo tests opt in with --repo / a cwd inside a tmp git repo + ALLOY_REPO="".
    env["ALLOY_REPO"] = "none"
    # Point both adapters at the mock and make them look authenticated.
    env["ALLOY_BIN_CODEX"] = MOCK
    env["ALLOY_BIN_CLAUDE"] = MOCK
    env["CODEX_API_KEY"] = "test"
    env["ANTHROPIC_API_KEY"] = "test"
    # Cursor must never reach a real cursor-agent or the real sandbox-exec: a path
    # that does not exist is "not installed", so nothing is spawned. Tests that
    # exercise Cursor run in-process (see CursorCase) with the mock CLI.
    env["ALLOY_BIN_CURSOR"] = "/no/such/cursor-agent"
    for legacy in ("ALLOY_BIN_CURSOR_AGENT", "ALLOY_CURSOR_MODEL", "ALLOY_CURSOR_AGENT_MODEL",
                   "ALLOY_CURSOR_EFFORT", "ALLOY_CURSOR_AGENT_EFFORT", "CURSOR_API_KEY",
                   "CURSOR_API_ENDPOINT"):
        env.pop(legacy, None)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, ALLOY] + args,
        capture_output=True, text=True, env=env, timeout=timeout, cwd=cwd,
    )
    return proc


def panel(tmp, env_extra=None, extra_args=None, timeout=60, cwd=None):
    prompt = os.path.join(tmp, "p.txt")
    with open(prompt, "w") as f:
        f.write("Say something useful.")
    args = ["panel", "--prompt-file", prompt, "--run-dir", os.path.join(tmp, "runs")]
    if extra_args:
        args += extra_args
    proc = run_alloy(args, env_extra=env_extra, timeout=timeout, cwd=cwd)
    manifest_path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    manifest = None
    if manifest_path and os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
    return proc, manifest


def by_name(manifest, name):
    for p in manifest["panelists"]:
        if p["name"] == name:
            return p
    return None


class AlloyTests(unittest.TestCase):
    def setUp(self):
        os.chmod(MOCK, 0o755)
        self.tmp = tempfile.mkdtemp(prefix="alloytest-")

    def test_both_ok(self):
        proc, m = panel(self.tmp)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(m["summary"]["ok"], 2)
        for name in ("codex", "claude"):
            p = by_name(m, name)
            self.assertEqual(p["status"], "ok")
            self.assertTrue(os.path.isfile(p["result_path"]))
            with open(p["result_path"]) as f:
                self.assertIn("MOCK", f.read())

    def test_partial_failure(self):
        # codex ok, claude fails -> proceed with 1, mark the other failed
        proc, m = panel(self.tmp, env_extra={"MOCK_BEHAVIOR_CLAUDE": "fail"})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(m["summary"]["ok"], 1)
        self.assertEqual(by_name(m, "codex")["status"], "ok")
        self.assertEqual(by_name(m, "claude")["status"], "error")
        self.assertEqual(by_name(m, "claude")["exit_code"], 3)

    def test_empty_output(self):
        proc, m = panel(self.tmp, env_extra={"MOCK_BEHAVIOR": "empty"})
        self.assertEqual(by_name(m, "codex")["status"], "empty")

    def test_truncation(self):
        proc, m = panel(
            self.tmp,
            env_extra={"MOCK_BEHAVIOR": "huge"},
            extra_args=["--max-chars", "100"],
        )
        p = by_name(m, "codex")
        self.assertTrue(p["truncated"])
        self.assertLessEqual(p["result_chars"], 100 + 120)  # cap + marker

    def test_secret_redaction(self):
        proc, m = panel(self.tmp, env_extra={"MOCK_BEHAVIOR": "secret"})
        p = by_name(m, "codex")
        self.assertGreaterEqual(p["secrets_redacted"], 1)
        with open(p["result_path"]) as f:
            body = f.read()
        self.assertNotIn("sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ", body)
        self.assertIn("REDACTED", body)

    def test_nonutf8_does_not_crash(self):
        proc, m = panel(self.tmp, env_extra={"MOCK_BEHAVIOR": "nonutf8"})
        # manifest must still be valid JSON and the panelist must be classified
        self.assertIsNotNone(m)
        self.assertIn(by_name(m, "codex")["status"], ("ok", "empty"))

    # -- 0.2.1: mode-aware timeouts, run announce, session ids, status ------- #

    def test_consult_default_timeout_unchanged(self):
        _proc, m = panel(self.tmp)
        self.assertEqual(m["timeout_s"], 300)

    def test_make_mode_gets_its_own_larger_default_timeout(self):
        # A Maker explores the repo before it can emit a diff; the consult
        # default (300s) was cutting healthy Makers off mid-read.
        _proc, m = panel(self.tmp, extra_args=["--mode", "make"])
        self.assertEqual(m["mode"], "make")
        self.assertEqual(m["timeout_s"], 1800)

    def test_make_mode_timeout_env_and_flag_precedence(self):
        _proc, m = panel(self.tmp, extra_args=["--mode", "make"],
                         env_extra={"ALLOY_MAKER_TIMEOUT": "77", "ALLOY_TIMEOUT": "5"})
        self.assertEqual(m["timeout_s"], 77)      # maker env beats the consult env
        _proc, m = panel(self.tmp, extra_args=["--mode", "make", "--timeout", "9"],
                         env_extra={"ALLOY_MAKER_TIMEOUT": "77"})
        self.assertEqual(m["timeout_s"], 9)       # explicit flag beats everything

    def test_run_dir_announced_at_dispatch_start(self):
        # So a host that misses the completion can still find the run.
        proc, m = panel(self.tmp)
        self.assertIn("run: " + m["run_dir"], proc.stderr)
        self.assertIn("timeout 300s each", proc.stderr)
        self.assertTrue(os.path.isfile(os.path.join(m["run_dir"], "run.json")))

    def test_estimate_reports_deadlines(self):
        proc = run_alloy(["estimate", "--rounds", "2"])
        est = json.loads(proc.stdout)
        self.assertEqual(est["timeout_s"], 300)
        self.assertEqual(est["maker_timeout_s"], 1800)

    def test_grok_and_claude_get_a_named_session(self):
        # A caller-chosen UUID is passed so the saved CLI session is known before
        # dispatch and can be resumed if alloy has to kill it.
        import uuid as _uuid
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok,claude"],
                         env_extra={"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x"})
        for name in ("grok", "claude"):
            p = by_name(m, name)
            cmd = p["command"]
            self.assertIn("--session-id", cmd)
            sid = cmd[cmd.index("--session-id") + 1]
            self.assertEqual(str(_uuid.UUID(sid)), sid)   # a real UUID
            self.assertEqual(p["session_id"], sid)
            self.assertNotIn("resume_hint", p)            # only offered on a kill

    def test_timeout_records_resume_hint_with_read_only_flags(self):
        _proc, m = panel(
            self.tmp,
            env_extra={"MOCK_BEHAVIOR": "hang"},
            extra_args=["--timeout", "2", "--panelists", "claude"],
        )
        p = by_name(m, "claude")
        self.assertEqual(p["status"], "timeout")
        self.assertIn(p["session_id"], p["resume_hint"])
        self.assertIn("--resume", p["resume_hint"])
        self.assertIn("--permission-mode plan", p["resume_hint"])   # still read-only
        self.assertIn("resume", _proc.stderr)

    def test_status_reads_a_finished_run_from_disk(self):
        _proc, m = panel(self.tmp)
        proc = run_alloy(["status", m["run_dir"]])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("manifest: present", proc.stdout)
        self.assertIn("codex", proc.stdout)
        # a manifest path works too, and --json is machine-readable
        proc = run_alloy(["status", "--json", os.path.join(m["run_dir"], "manifest.json")])
        info = json.loads(proc.stdout)
        self.assertTrue(info["finished"])
        self.assertEqual({r["name"] for r in info["panelists"]}, {"codex", "claude"})
        self.assertEqual({r["status"] for r in info["panelists"]}, {"ok"})

    def test_status_defaults_to_newest_run_under_root(self):
        _proc, m1 = panel(self.tmp)
        time.sleep(0.05)
        _proc, m2 = panel(self.tmp)
        proc = run_alloy(["status", "--run-dir", os.path.join(self.tmp, "runs")])
        self.assertEqual(proc.returncode, 0)
        self.assertIn(m2["run_dir"], proc.stdout)
        self.assertNotIn(m1["run_dir"], proc.stdout)

    def test_status_reports_an_abandoned_run(self):
        # Dispatcher killed before finishing: no manifest, a panelist left
        # "running" with a dead pid -> exit 4 and say so, don't hang or lie.
        rd = os.path.join(self.tmp, "runs", "20260101T000000Z-abc123")
        os.makedirs(os.path.join(rd, "grok"))
        with open(os.path.join(rd, "run.json"), "w") as f:
            json.dump({"dispatcher_pid": 2**22 - 1, "mode": "make", "timeout_s": 1800}, f)
        with open(os.path.join(rd, "grok", "status.json"), "w") as f:
            json.dump({"status": "running", "pid": 2**22 - 1, "session_id": "abc",
                       "name": "grok"}, f)
        with open(os.path.join(rd, "grok", "stdout.txt"), "w") as f:
            f.write("x" * 358)
        proc = run_alloy(["status", rd])
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
        self.assertIn("manifest: absent", proc.stdout)
        self.assertIn("abandoned", proc.stdout)
        self.assertIn("mode: make", proc.stdout)

    def test_status_no_runs(self):
        proc = run_alloy(["status", "--run-dir", os.path.join(self.tmp, "nothing-here")])
        self.assertEqual(proc.returncode, 2)

    def test_timeout_kills_process_group(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        proc, m = panel(
            self.tmp,
            env_extra={"MOCK_BEHAVIOR": "hang", "MOCK_CHILD_PIDFILE": pidfile},
            extra_args=["--timeout", "2", "--panelists", "codex"],
            timeout=60,
        )
        p = by_name(m, "codex")
        self.assertTrue(p["timed_out"])
        self.assertEqual(p["status"], "timeout")
        # the child spawned by the hung mock must have been killed with the group
        self.assertTrue(os.path.isfile(pidfile))
        with open(pidfile) as f:
            child_pid = int(f.read().strip())
        time.sleep(0.5)
        with self.assertRaises(OSError):
            os.kill(child_pid, 0)  # raises if the pid is gone -> group kill worked

    def test_not_installed(self):
        proc, m = panel(self.tmp, env_extra={"ALLOY_BIN_CODEX": "/no/such/binary"})
        self.assertEqual(by_name(m, "codex")["status"], "not_installed")

    def test_no_panelists_fallback(self):
        # opencode has no read-only mode -> refused/skipped by default (even when
        # listed explicitly, unless ALLOY_ALLOW_UNSANDBOXED=1), so this exercises
        # the 0-panelist host-only fallback without invoking any real CLI (and
        # without spending tokens).
        proc, m = panel(self.tmp, extra_args=["--panelists", "opencode"])
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(m["panelists"], [])
        self.assertIn("note", m["summary"])
        self.assertIn("host-only", m["summary"]["note"])
        self.assertTrue(m["summary"]["skipped"])

    def test_doctor_json(self):
        proc = run_alloy(["doctor", "--json"])
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        names = {p["name"] for p in data["panelists"]}
        self.assertEqual(
            {"codex", "grok", "claude", "llm", "opencode", "cursor", "antigravity"},
            names)
        codex = next(p for p in data["panelists"] if p["name"] == "codex")
        self.assertEqual(codex["status"], "ready")
        cursor = next(p for p in data["panelists"] if p["name"] == "cursor")
        self.assertEqual(cursor["status"], "not_installed")   # pinned to a missing binary

    def test_empty_prompt_refused(self):
        empty = os.path.join(self.tmp, "empty.txt")
        open(empty, "w").close()
        proc = run_alloy(["panel", "--prompt-file", empty])
        self.assertEqual(proc.returncode, 2)

    def test_invalid_timeout_rejected(self):
        prompt = os.path.join(self.tmp, "p.txt")
        with open(prompt, "w") as f:
            f.write("hi")
        proc = run_alloy(["panel", "--prompt-file", prompt, "--timeout", "0"])
        self.assertEqual(proc.returncode, 2)

    def test_run_root_has_gitignore(self):
        _proc, _m = panel(self.tmp)
        gi = os.path.join(self.tmp, "runs", ".gitignore")
        self.assertTrue(os.path.isfile(gi))
        with open(gi) as f:
            self.assertEqual(f.read().strip(), "*")

    def test_sidecar_files_are_redacted(self):
        _proc, m = panel(self.tmp, env_extra={"MOCK_BEHAVIOR": "secret"})
        p = by_name(m, "codex")
        with open(p["stdout_path"]) as f:
            raw = f.read()
        # the mock writes the secret to the -o file (codex last_message), so the
        # canonical result is what matters; ensure no raw key leaks anywhere.
        for path in (p["result_path"], p["stdout_path"], p["last_message_path"]):
            if os.path.isfile(path):
                with open(path) as f:
                    self.assertNotIn("sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ", f.read())

    def test_duplicate_panelists_deduped(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "codex,codex"])
        names = [p["name"] for p in m["panelists"]]
        self.assertEqual(names, ["codex"])

    def test_prompt_too_large_rejected(self):
        big = os.path.join(self.tmp, "big.txt")
        with open(big, "w") as f:
            f.write("x" * 50)
        proc = run_alloy(["panel", "--prompt-file", big],
                         env_extra={"ALLOY_MAX_PROMPT_BYTES": "10"})
        self.assertEqual(proc.returncode, 2)

    def test_run_artifacts_have_restrictive_perms(self):
        _proc, m = panel(self.tmp)
        self.assertEqual(os.stat(m["run_dir"]).st_mode & 0o777, 0o700)
        result = by_name(m, "codex")["result_path"]
        self.assertEqual(os.stat(result).st_mode & 0o777, 0o600)

    def test_attach_folds_file_into_prompt(self):
        att = os.path.join(self.tmp, "ctx.txt")
        with open(att, "w") as f:
            f.write("MARKER_CONTEXT_LINE_42")
        _proc, m = panel(self.tmp, extra_args=["--attach", att])
        with open(m["prompt_path"]) as f:
            sent = f.read()
        self.assertIn("MARKER_CONTEXT_LINE_42", sent)
        self.assertIn("ATTACHED FILE", sent)

    def test_attach_missing_file_rejected(self):
        prompt = os.path.join(self.tmp, "p.txt")
        with open(prompt, "w") as f:
            f.write("hi")
        proc = run_alloy(["panel", "--prompt-file", prompt,
                          "--attach", "/no/such/file.txt"])
        self.assertEqual(proc.returncode, 2)

    def test_web_search_flag_default_on_for_codex(self):
        _proc, m = panel(self.tmp)
        cmd = " ".join(by_name(m, "codex")["command"])
        self.assertIn("tools.web_search=true", cmd)

    def test_web_search_flag_off_when_disabled(self):
        _proc, m = panel(self.tmp, env_extra={"ALLOY_WEB": "0"})
        cmd = " ".join(by_name(m, "codex")["command"])
        self.assertNotIn("tools.web_search=true", cmd)

    def test_matrix_printed_on_stderr(self):
        proc, _m = panel(self.tmp)
        self.assertIn("panel matrix", proc.stderr)

    def test_update_check_can_be_disabled(self):
        # A copied installation needs no lock in the checkout's protected .git.
        import shutil
        from unittest import mock
        copied_bin = os.path.join(self.tmp, "copied-install", "bin")
        shutil.copytree(os.path.dirname(ALLOY), copied_bin, ignore=shutil.ignore_patterns("__pycache__"))
        with mock.patch(__name__ + ".ALLOY", os.path.join(copied_bin, "alloy")):
            proc = run_alloy(["update-check"], env_extra={"ALLOY_NO_UPDATE_CHECK": "1"})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("UPDATE_CHECK_DISABLED", proc.stdout)

    def test_codex_effort_pinned_high_by_default(self):
        _proc, m = panel(self.tmp)
        cmd = " ".join(by_name(m, "codex")["command"])
        self.assertIn("model_reasoning_effort=high", cmd)

    def test_codex_effort_overridable(self):
        _proc, m = panel(self.tmp, env_extra={"ALLOY_CODEX_EFFORT": "medium"})
        cmd = " ".join(by_name(m, "codex")["command"])
        self.assertIn("model_reasoning_effort=medium", cmd)

    def test_codex_effort_inherit_skips_flag(self):
        _proc, m = panel(self.tmp, env_extra={"ALLOY_CODEX_EFFORT": "inherit"})
        cmd = " ".join(by_name(m, "codex")["command"])
        self.assertNotIn("model_reasoning_effort", cmd)

    def test_heartbeat_logged_for_slow_panelist(self):
        prompt = os.path.join(self.tmp, "p.txt")
        with open(prompt, "w") as f:
            f.write("hi")
        proc = run_alloy(
            ["panel", "--prompt-file", prompt, "--panelists", "codex",
             "--timeout", "3", "--run-dir", os.path.join(self.tmp, "runs")],
            env_extra={"MOCK_BEHAVIOR": "hang", "ALLOY_HEARTBEAT": "1"})
        self.assertIn("working", proc.stderr)

    def test_stall_timeout_kills_early(self):
        prompt = os.path.join(self.tmp, "p.txt")
        with open(prompt, "w") as f:
            f.write("hi")
        proc = run_alloy(
            ["panel", "--prompt-file", prompt, "--panelists", "codex",
             "--timeout", "30", "--run-dir", os.path.join(self.tmp, "runs")],
            env_extra={"MOCK_BEHAVIOR": "hang", "ALLOY_STALL_TIMEOUT": "1",
                       "ALLOY_HEARTBEAT": "1"}, timeout=20)
        self.assertIn("stalled", proc.stderr)  # killed by stall, not the 30s timeout

    def test_grok_uses_plan_and_prompt_file(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra={"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x"})
        cmd = " ".join(by_name(m, "grok")["command"])
        self.assertIn("--permission-mode plan", cmd)  # read-only
        self.assertIn("--prompt-file", cmd)           # prompt from a real file
        self.assertNotIn("--disable-web-search", cmd)  # web on by default

    def test_grok_panel_offers_only_read_only_tools(self):
        # A tool needing approval cancels grok's whole headless turn.
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra={"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x"})
        args = by_name(m, "grok")["command"]
        self.assertEqual(args[args.index("--tools") + 1], "read_file,list_dir,grep,glob,web_search,web_fetch")
        self.assertIn("WebFetch", args)
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra={"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x", "ALLOY_WEB": "0"})
        args = by_name(m, "grok")["command"]
        self.assertEqual(args[args.index("--tools") + 1], "read_file,list_dir,grep,glob")
        self.assertNotIn("WebFetch", args)

    def test_grok_web_can_be_disabled(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra={"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x",
                                    "ALLOY_WEB": "0"})
        cmd = " ".join(by_name(m, "grok")["command"])
        self.assertIn("--disable-web-search", cmd)

    def test_grok_uses_cli_default_model(self):
        # Unset ALLOY_GROK_MODEL -> no -m flag; the CLI default (currently
        # grok-4.6) is what actually runs.
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra={"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x"})
        cmdlist = by_name(m, "grok")["command"]
        self.assertNotIn("-m", cmdlist)

    def test_grok_model_override(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra={"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x",
                                    "ALLOY_GROK_MODEL": "grok-4.5"})
        cmd = " ".join(by_name(m, "grok")["command"])
        self.assertIn("-m grok-4.5", cmd)

    def test_claude_uses_plan_and_print(self):
        # The host's own model as a panelist: headless (-p), read-only (plan),
        # never a bypass flag.
        _proc, m = panel(self.tmp, extra_args=["--panelists", "claude"],
                         env_extra={"ALLOY_BIN_CLAUDE": MOCK, "ANTHROPIC_API_KEY": "x"})
        cmdlist = by_name(m, "claude")["command"]
        self.assertIn("-p", cmdlist)                       # headless print mode
        cmd = " ".join(cmdlist)
        self.assertIn("--permission-mode plan", cmd)       # read-only
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertNotIn("bypassPermissions", cmd)

    def test_claude_lean_context_by_default(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "claude"])
        cmd = " ".join(by_name(m, "claude")["command"])
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn("--disable-slash-commands", cmd)
        self.assertNotIn("--setting-sources", cmd)  # retain user deny rules and hooks
        _proc, m = panel(self.tmp, extra_args=["--panelists", "claude"], env_extra={"ALLOY_CLAUDE_LEAN": "0"})
        cmd = " ".join(by_name(m, "claude")["command"])
        self.assertNotIn("--strict-mcp-config", cmd)
        self.assertNotIn("--setting-sources", cmd)

    def test_claude_model_override(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "claude"],
                         env_extra={"ALLOY_BIN_CLAUDE": MOCK, "ANTHROPIC_API_KEY": "x",
                                    "ALLOY_CLAUDE_MODEL": "opus"})
        cmd = " ".join(by_name(m, "claude")["command"])
        self.assertIn("--model opus", cmd)

    # -- token usage capture (opt-in) ----------------------------------------- #
    def _usage_panel(self, name, env):
        env = dict(env, ALLOY_CAPTURE_USAGE="1")
        _proc, m = panel(self.tmp, extra_args=["--panelists", name], env_extra=env)
        p = by_name(m, name)
        self.assertEqual(p["status"], "ok")
        with open(p["result_path"]) as f:
            answer = f.read()
        self.assertTrue(answer.startswith("MOCK "), answer)  # text, not raw JSON
        return p, " ".join(p["command"])

    def test_usage_capture_off_by_default(self):
        _proc, m = panel(self.tmp)
        for name in ("codex", "claude"):
            p = by_name(m, name)
            self.assertNotIn("usage", p)
            self.assertNotIn("--json", p["command"])
            if name == "claude":
                # Claude's default output is stream-json (it needs --verbose): the run's own
                # rate_limit_event feeds Claude quota. Capture-off still never asks for the
                # single JSON result object, which is what ALLOY_CAPTURE_USAGE switches to.
                cmd = p["command"]
                self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
                self.assertIn("--verbose", cmd)
                self.assertNotIn("json", cmd)
                self.assertNotIn("text", cmd)
                continue
            self.assertNotIn("json", " ".join(p["command"]))

    def test_usage_capture_codex(self):
        p, cmd = self._usage_panel("codex", {})
        self.assertIn("--json", p["command"])
        self.assertIn("-s read-only", cmd)  # permissions unchanged
        self.assertEqual(p["usage"], {"input_tokens": 600, "cache_read_tokens": 400,
            "cache_write_tokens": 0, "output_tokens": 50, "reasoning_tokens": 20,
            "reported_cost_usd": None, "turns": 1, "source": "codex-jsonl"})

    def test_usage_capture_claude(self):
        p, cmd = self._usage_panel("claude", {})
        self.assertIn("--output-format json", cmd)
        self.assertNotIn("--output-format text", cmd)
        self.assertNotIn("--verbose", cmd)      # json + verbose would print the whole transcript
        self.assertNotIn("stream-json", cmd)
        self.assertIn("--permission-mode plan", cmd)
        self.assertEqual(p["usage"], {"input_tokens": 5, "cache_read_tokens": 2000,
            "cache_write_tokens": 3000, "output_tokens": 60, "reasoning_tokens": 25,
            "reported_cost_usd": 0.05, "turns": 4, "source": "claude-json"})

    def test_usage_capture_grok(self):
        p, cmd = self._usage_panel("grok", {"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x"})
        self.assertIn("--output-format json", cmd)
        self.assertIn("--permission-mode plan", cmd)
        self.assertEqual(p["usage"], {"input_tokens": 900, "cache_read_tokens": 100,
            "cache_write_tokens": 0, "output_tokens": 30, "reasoning_tokens": 10,
            "reported_cost_usd": 0.0123, "turns": 2, "source": "grok-json"})

    def test_usage_capture_antigravity(self):
        p, cmd = self._usage_panel("antigravity", self._agy_env())
        self.assertIn("--output-format json", cmd)
        self.assertIn("--mode plan", cmd)
        self.assertEqual(p["usage"], {"input_tokens": 500, "cache_read_tokens": 300,
            "cache_write_tokens": 0, "output_tokens": 40, "reasoning_tokens": 15,
            "reported_cost_usd": None, "turns": 3, "source": "agy-json"})

    def test_usage_capture_tolerates_plain_output(self):
        # A CLI that ignores the JSON request still yields its plain answer.
        _proc, m = panel(self.tmp, env_extra={"ALLOY_CAPTURE_USAGE": "1",
                                              "MOCK_IGNORE_JSON": "1"})
        for name in ("codex", "claude"):
            p = by_name(m, name)
            self.assertEqual(p["status"], "ok")
            self.assertIsNone(p["usage"])
            with open(p["result_path"]) as f:
                self.assertTrue(f.read().startswith("MOCK "))

    # -- agy / antigravity: read-only is gated on the installed CLI version ---- #
    def _agy_env(self, **extra):
        # MOCK_VERSION >= 1.1.0 => the release whose headless mode auto-DENIES
        # any tool outside permissions.allow, which is what makes agy read-only.
        # XDG_STATE_HOME keeps the (shared, alloy-owned) agy HOME inside the test
        # tmpdir instead of the developer's real ~/.local/state.
        e = {"ALLOY_BIN_ANTIGRAVITY": MOCK, "ANTIGRAVITY_API_KEY": "x",
             "MOCK_VERSION": "1.1.7", "XDG_STATE_HOME": os.path.join(self.tmp, "state")}
        e.update(extra)
        return e

    def _agy_settings(self, home):
        with open(os.path.join(home, ".gemini", "antigravity-cli", "settings.json")) as f:
            return json.load(f)

    def _shared_agy_home(self):
        return os.path.join(self.tmp, "state", "alloy", "agy-home")

    def test_antigravity_refused_on_old_cli(self):
        # agy < 1.1.0 auto-EXECUTES tools in headless mode instead of denying
        # them -> read_only=False, so it is skipped unless ALLOY_ALLOW_UNSANDBOXED=1.
        proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                        env_extra=self._agy_env(MOCK_VERSION="1.0.16"))
        self.assertEqual(proc.returncode, 3)  # 0 panelists -> host-only fallback
        self.assertIsNone(by_name(m, "antigravity"))  # never dispatched
        skipped = {s["name"]: s["reason"] for s in m["summary"]["skipped"]}
        self.assertIn("antigravity", skipped)
        self.assertIn("read-only", skipped["antigravity"])

    def test_antigravity_runs_read_only_on_current_cli(self):
        # On a current agy it joins the panel with no opt-in: headless `-p`, the
        # `--mode plan` intent hint, and never the auto-approve bypass flag
        # (which would disable the allow-list that makes it read-only at all).
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                         env_extra=self._agy_env())
        p = by_name(m, "antigravity")
        self.assertEqual(p["status"], "ok")
        self.assertTrue(p["read_only"])
        cmd = " ".join(p["command"])
        self.assertIn("-p", p["command"])
        self.assertIn("--mode plan", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        # Default model: the latest Gemini family seat (currently 3.6 Flash High).
        self.assertIn("--model gemini-3.6-flash-high", cmd)
        # The engine's deadline is handed to agy so its own 5m print timeout
        # can't cut a longer run short.
        self.assertIn("--print-timeout", cmd)

    def test_antigravity_prompt_goes_in_a_file_not_argv(self):
        # agy ignores stdin in print mode, so the prompt is STAGED AS A FILE and
        # only a pointer reaches argv (no ARG_MAX, no prompt visible in `ps`).
        # A file on stdin is itself a denied read_file on agy 1.2.12.
        stdin_dump = os.path.join(self.tmp, "agy_stdin_len.txt")
        # A private ordinary directory, not REPO: when the suite itself runs in a
        # linked worktree REPO/.git is a pointer file and agy (correctly) also
        # receives the gitdir and common dir, which would make this test depend on
        # where it is checked out. The worktree case is test_antigravity_worktree_*.
        repo = self._repo_with_file()
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity", "--repo", repo],
                         env_extra=self._agy_env(MOCK_VERSION="1.2.12",
                                                 MOCK_STDIN_DUMP=stdin_dump))
        p = by_name(m, "antigravity")
        staged = os.path.join(os.path.dirname(p["stdout_path"]), "prompt_in", "prompt.md")
        with open(staged) as f, open(m["prompt_path"]) as original:
            self.assertEqual(f.read(), original.read())
        cmd = " ".join(p["command"])
        self.assertNotIn("Say something useful.", cmd)   # never on argv
        self.assertIn(staged, cmd)                       # pointed at, instead
        # The grant covers the prompt's own directory, not the whole run dir
        # (which holds the other panelists' captured answers).
        self.assertIn("--add-dir " + os.path.dirname(staged), cmd)
        args = p["command"]
        add_dirs = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--add-dir"]
        self.assertEqual(add_dirs, [os.path.abspath(os.path.dirname(staged)), os.path.abspath(repo)])
        allow = self._agy_settings(self._shared_agy_home())["permissions"]["allow"]
        self.assertEqual(allow, ["read_file(%s)" % d for d in add_dirs])
        deny = self._agy_settings(self._shared_agy_home())["permissions"]["deny"]
        self.assertEqual(deny, ["command(*)", "write_file(*)"])
        with open(stdin_dump) as f:
            self.assertEqual(f.read(), "0")

    def test_antigravity_worktree_metadata_read_roots(self):
        repo = os.path.join(self.tmp, "worktree")
        common = os.path.join(self.tmp, "source.git")
        gitdir = os.path.join(common, "worktrees", "tid")
        os.makedirs(repo)
        os.makedirs(gitdir)
        for target in (gitdir, os.path.relpath(gitdir, repo)):
            with self.subTest(target=target):
                with open(os.path.join(repo, ".git"), "w") as f:
                    f.write("gitdir: %s\n" % target)
                _proc, m = panel(
                    self.tmp, extra_args=["--panelists", "antigravity", "--repo", repo],
                    env_extra=self._agy_env(MOCK_VERSION="1.2.12"))
                p = by_name(m, "antigravity")
                self.assertEqual(p["status"], "ok")
                args = p["command"]
                add_dirs = [args[i + 1] for i, a in enumerate(args[:-1])
                            if a == "--add-dir"]
                pin = os.path.join(os.path.dirname(p["stdout_path"]), "prompt_in")
                self.assertEqual(add_dirs, [os.path.abspath(d)
                                           for d in (pin, repo, gitdir, common)])
                permissions = self._agy_settings(self._shared_agy_home())["permissions"]
                self.assertEqual(permissions["allow"],
                                 ["read_file(%s)" % d for d in add_dirs])
                self.assertEqual(permissions["deny"], ["command(*)", "write_file(*)"])
                self.assertNotIn(self._shared_agy_home(), add_dirs)
                self.assertNotIn("--dangerously-skip-permissions", args)

    def test_antigravity_isolated_home_with_readonly_allowlist(self):
        # The CLI is confined to an alloy-owned HOME holding OUR settings.json, so
        # the user's ~/.gemini is neither read for config nor written to.
        dump = os.path.join(self.tmp, "child_home.txt")
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                         env_extra=self._agy_env(MOCK_ENV_DUMP=dump))
        with open(dump) as f:
            self.assertEqual(f.read(), self._shared_agy_home())
        s = self._agy_settings(self._shared_agy_home())
        self.assertIn("read_file", s["permissions"]["allow"])
        self.assertIn("write_file", s["permissions"]["deny"])
        self.assertIn("command", s["permissions"]["deny"])
        self.assertNotIn("write_file", s["permissions"]["allow"])
        # agy >= 1.2 grammar: bare names are ignored there, so the same posture
        # is also expressed as action(target) grants.
        self.assertIn("command(*)", s["permissions"]["deny"])
        self.assertIn("write_file(*)", s["permissions"]["deny"])
        self.assertEqual(s["permissions"]["allow"][:8], [
            "read_file", "view_file", "view_file_outline", "view_code_item",
            "list_dir", "grep_search", "find_by_name", "codebase_search"])
        self.assertFalse(s["allowNonWorkspaceAccess"])
        # Containment invariant the macOS keychain config leans on: the agy
        # HOME itself (where the generated com.apple.security.plist lives) is
        # never granted as a workspace root, so read tools can't reach it.
        args = by_name(m, "antigravity")["command"]
        add_dirs = [args[i + 1] for i, a in enumerate(args[:-1])
                    if a == "--add-dir"]
        self.assertTrue(add_dirs)
        self.assertEqual(s["permissions"]["allow"][8:],
                         ["read_file(%s)" % d for d in add_dirs])
        for d in add_dirs:
            self.assertFalse(d.startswith(self._shared_agy_home()))
        # toolPermission:"strict" would override the allow-list and deny the READ
        # tools too, leaving a panelist that can never answer. Never set it.
        self.assertNotIn("toolPermission", s)

    def test_antigravity_home_can_be_per_run(self):
        # Opt in to a throwaway HOME inside the run dir (max hygiene, at the cost
        # of agy re-unpacking its ~13MB of binaries every run).
        dump = os.path.join(self.tmp, "child_home.txt")
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                         env_extra=self._agy_env(ALLOY_ANTIGRAVITY_HOME="run",
                                                 MOCK_ENV_DUMP=dump))
        pdir = os.path.dirname(by_name(m, "antigravity")["stdout_path"])
        with open(dump) as f:
            self.assertEqual(f.read(), os.path.join(pdir, "agy_home"))
        self.assertFalse(os.path.exists(self._shared_agy_home()))

    def test_antigravity_web_off_denies_web_tools(self):
        _proc, _m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                          env_extra=self._agy_env(ALLOY_WEB="0"))
        deny = self._agy_settings(self._shared_agy_home())["permissions"]["deny"]
        self.assertIn("search_web", deny)
        self.assertIn("read_url(*)", deny)

    def test_antigravity_model_override(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                         env_extra=self._agy_env(ALLOY_ANTIGRAVITY_MODEL="gemini-3.6-flash-low"))
        cmd = " ".join(by_name(m, "antigravity")["command"])
        self.assertIn("--model gemini-3.6-flash-low", cmd)

    # -- empty/auth classification + single retry (token-refresh race) -------- #
    def _grok_env(self, **extra):
        e = {"ALLOY_BIN_GROK": MOCK, "XAI_API_KEY": "x"}
        e.update(extra)
        return e

    def test_auth_empty_classified_as_auth(self):
        # grok exits 0 with empty stdout + an AuthorizationRequired error on
        # stderr -> must be `auth`, not buried as `empty`. Retry off to observe it.
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra=self._grok_env(MOCK_BEHAVIOR="auth",
                                                  ALLOY_RETRY="0"))
        p = by_name(m, "grok")
        self.assertEqual(p["status"], "auth")
        self.assertIn("Auth", p["error"])
        self.assertNotIn("retried", p)

    def test_plain_empty_surfaces_stderr_tail(self):
        # A genuine blank answer stays `empty`, but the stderr tail is recorded
        # as the reason instead of a silent null.
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra=self._grok_env(MOCK_BEHAVIOR="empty_noisy",
                                                  ALLOY_RETRY="0"))
        p = by_name(m, "grok")
        self.assertEqual(p["status"], "empty")
        self.assertIn("the last stderr line", p["error"])

    def test_retry_recovers_transient_auth(self):
        # Default ALLOY_RETRY includes `auth`: first call fails auth, the single
        # retry lands on the (refreshed) token and succeeds.
        flag = os.path.join(self.tmp, "auth_once.flag")
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra=self._grok_env(MOCK_BEHAVIOR="auth_once",
                                                  MOCK_AUTH_ONCE_FILE=flag))
        p = by_name(m, "grok")
        self.assertEqual(p["status"], "ok")
        self.assertTrue(p["retried"])
        self.assertEqual(p["first_attempt_status"], "auth")

    def test_plain_empty_not_retried_by_default(self):
        # The default retry set is `auth` only -> a genuine empty is NOT
        # re-dispatched (no wasted second call on a blank answer).
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra=self._grok_env(MOCK_BEHAVIOR="empty_noisy"))
        p = by_name(m, "grok")
        self.assertEqual(p["status"], "empty")
        self.assertNotIn("retried", p)

    def test_retry_can_be_disabled(self):
        flag = os.path.join(self.tmp, "auth_once.flag")
        _proc, m = panel(self.tmp, extra_args=["--panelists", "grok"],
                         env_extra=self._grok_env(MOCK_BEHAVIOR="auth_once",
                                                  MOCK_AUTH_ONCE_FILE=flag,
                                                  ALLOY_RETRY="0"))
        p = by_name(m, "grok")
        self.assertEqual(p["status"], "auth")
        self.assertNotIn("retried", p)

    # -- repo access ---------------------------------------------------------- #
    def _repo_with_file(self, name="hello.txt", body="repo content", git=False):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo, exist_ok=True)
        with open(os.path.join(repo, name), "w") as f:
            f.write(body)
        if git:
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        return repo

    def test_read_only_adapter_runs_in_real_repo(self):
        # A read-only adapter's cwd IS the real repo (live read access); the CLI
        # read-only flag is what prevents writes.
        repo = self._repo_with_file()
        _proc, m = panel(self.tmp,
                         extra_args=["--panelists", "codex", "--repo", repo])
        p = by_name(m, "codex")
        self.assertEqual(p["repo_access"], "real")
        self.assertEqual(p["cwd"], repo)
        self.assertEqual(m["summary"]["repo"], repo)

    def test_no_repo_flag_overrides_and_isolates(self):
        # --no-repo wins over ALLOY_REPO -> empty throwaway cwd, no access.
        repo = self._repo_with_file()
        _proc, m = panel(self.tmp,
                         extra_args=["--panelists", "codex", "--no-repo"],
                         env_extra={"ALLOY_REPO": repo})
        p = by_name(m, "codex")
        self.assertEqual(p["repo_access"], "none")
        self.assertTrue(p["cwd"].endswith(os.path.join("codex", "cwd")))
        self.assertIsNone(m["summary"]["repo"])

    def test_write_capable_adapter_gets_disposable_copy(self):
        # A write-capable adapter (opencode) must NOT see the real tree; it gets a
        # copy (with .git excluded) so any writes land off your repo. (Cursor is
        # no longer such an adapter: it runs in the real repo under an OS profile.)
        repo = self._repo_with_file(name="code.py", body="x = 1")
        os.makedirs(os.path.join(repo, ".git"))
        with open(os.path.join(repo, ".git", "HEAD"), "w") as f:
            f.write("ref: refs/heads/main")
        _proc, m = panel(self.tmp,
                         extra_args=["--panelists", "opencode", "--repo", repo],
                         env_extra={"ALLOY_BIN_OPENCODE": MOCK,
                                    "ALLOY_ALLOW_UNSANDBOXED": "1"})
        p = by_name(m, "opencode")
        self.assertEqual(p["repo_access"], "copy")
        self.assertTrue(p["cwd"].endswith("cwd_repo"))
        self.assertTrue(os.path.isfile(os.path.join(p["cwd"], "code.py")))  # copied
        self.assertFalse(os.path.exists(os.path.join(p["cwd"], ".git")))    # excluded

    def test_antigravity_reads_the_real_repo_via_add_dir(self):
        # agy ignores the process cwd, so repo access has to be granted
        # explicitly: read-only adapter -> the REAL tree, handed over as --add-dir.
        repo = self._repo_with_file(name="code.py", body="x = 1")
        _proc, m = panel(self.tmp,
                         extra_args=["--panelists", "antigravity", "--repo", repo],
                         env_extra=self._agy_env())
        p = by_name(m, "antigravity")
        self.assertEqual(p["repo_access"], "real")
        self.assertIn("--add-dir " + repo, " ".join(p["command"]))

    def test_repo_auto_detected_from_git_root(self):
        # Default (ALLOY_REPO unset): auto-detect the git root of the invoking cwd.
        repo = self._repo_with_file(git=True)
        _proc, m = panel(self.tmp, extra_args=["--panelists", "codex"],
                         env_extra={"ALLOY_REPO": ""}, cwd=repo)
        p = by_name(m, "codex")
        self.assertEqual(p["repo_access"], "real")
        self.assertEqual(os.path.realpath(p["cwd"]), os.path.realpath(repo))


def _import_alloy_module():
    import importlib.util
    import importlib.machinery
    # bin/alloy has no .py extension, so give importlib an explicit loader.
    loader = importlib.machinery.SourceFileLoader("alloy_mod", ALLOY)
    spec = importlib.util.spec_from_loader("alloy_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class AntigravityKeychainFreeAuthTests(unittest.TestCase):
    """AntigravityAdapter's login check runs WITHOUT the macOS keychain (operator policy
    2026-09-29: Alloy never reads it and never runs `security`). A fresh agy login on
    macOS lives only in the login keychain, so with no key and no agy token file the
    login is UNKNOWN: agy stays `ready` (routing and execute gate on that) and `doctor`
    reports auth `unknown`; the first real dispatch reports `auth` if the login is bad.
    Hermetic on every platform: `~` maps to a fixture dir through os.path.expanduser
    (HOME is never set), config/env auth is cleared, sys.platform is faked and every
    subprocess call is recorded, never run."""

    @classmethod
    def setUpClass(cls):
        cls.f = _import_alloy_module()

    def _run_check(self, check, fake_run=None, platform="darwin", token_file=False, api_key=""):
        from unittest import mock
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return fake_run(cmd, **kw) if fake_run else subprocess.CompletedProcess(cmd, 0, "", "")

        def popen(cmd, *a, **kw):
            calls.append(cmd)
            raise AssertionError("no process may be spawned: %r" % (cmd,))

        with tempfile.TemporaryDirectory() as home:
            if token_file:
                d = os.path.join(home, ".gemini", "antigravity-cli")
                os.makedirs(d)
                open(os.path.join(d, "antigravity-oauth-token"), "w").close()
            env = {"ANTIGRAVITY_API_KEY": api_key, "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(self.f, "_CONFIG", {}), \
                 mock.patch.object(self.f.os.path, "expanduser",
                                   lambda p: home + p[1:] if p.startswith("~") else p), \
                 mock.patch.object(self.f.sys, "platform", platform), \
                 mock.patch.object(self.f.subprocess, "run", run), \
                 mock.patch.object(self.f.subprocess, "Popen", popen):
                result = check(self.f.AntigravityAdapter())
        return result, calls

    def _is_authed_with(self, fake_run, platform="darwin", token_file=False):
        result, _calls = self._run_check(lambda ad: ad.is_authed(), fake_run, platform, token_file)
        return result

    def test_unknown_login_counts_as_usable_and_no_command_runs(self):
        seen, calls = self._run_check(lambda ad: (ad._auth_evidence(), ad.is_authed(), ad.auth_status("ready")))
        self.assertEqual(seen, (None, True, "unknown"))
        self.assertEqual(calls, [])

    def test_what_the_keychain_would_say_is_never_asked(self):
        # Whatever a keychain lookup would have returned (found, not found, wedged, missing
        # binary), the answer is identical and nothing is run: there is no lookup any more.
        def not_found(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 44)

        def timeout(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 5)

        def missing(cmd, **kw):
            raise FileNotFoundError(cmd[0])

        for fake in (not_found, timeout, missing):
            with self.subTest(fake.__name__):
                seen, calls = self._run_check(lambda ad: (ad.is_authed(), ad.auth_status("ready")), fake)
                self.assertEqual(seen, (True, "unknown"))
                self.assertEqual(calls, [])

    def test_agy_token_file_or_key_is_real_evidence(self):
        for kwargs in ({"token_file": True}, {"api_key": "k"}):
            with self.subTest(kwargs):
                seen, calls = self._run_check(
                    lambda ad: (ad._auth_evidence(), ad.is_authed(), ad.auth_status("ready")), **kwargs)
                self.assertEqual(seen, (True, True, "authenticated"))
                self.assertEqual(calls, [])

    def test_non_darwin_never_probes_keychain(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        self.assertFalse(self._is_authed_with(fake_run, platform="linux"))
        self.assertEqual(calls, [])
        # Off macOS nothing else can hold the login, so "no evidence" is a definite no.
        seen, _calls = self._run_check(lambda ad: (ad._auth_evidence(), ad.auth_status("installed_not_authed")),
                                       platform="linux")
        self.assertEqual(seen, (False, "not_authenticated"))

    def test_file_auth_short_circuits_keychain_probe(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        self.assertTrue(self._is_authed_with(fake_run, token_file=True))
        self.assertEqual(calls, [])  # no subprocess when a token file exists

    def test_unknown_login_keeps_agy_ready_for_routing_and_execute(self):
        from unittest import mock
        with mock.patch.object(self.f.AntigravityAdapter, "resolved_bin", return_value="/fake/agy"):
            state, calls = self._run_check(lambda ad: ad.auth_state())
            self.assertEqual(state, "ready")   # alloy_routing/alloy_execution require exactly this
            self.assertEqual(calls, [])
            state, _calls = self._run_check(lambda ad: ad.auth_state(), platform="linux")
            self.assertEqual(state, "installed_not_authed")

    def test_doctor_reports_auth_unknown_in_json_and_text(self):
        import argparse
        import contextlib
        import io
        from unittest import mock

        def doctor(as_json):
            def check(ad):
                # doctor may run the CLI's own --version (never `security`); answer it here.
                ad_row = self.f.ADAPTERS
                with mock.patch.dict(ad_row, {"antigravity": ad}, clear=True), \
                     mock.patch.object(self.f.AntigravityAdapter, "resolved_bin", return_value="/fake/agy"), \
                     mock.patch.object(self.f.AntigravityAdapter, "cli_version", return_value="agy 1.2.12"):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        self.f.cmd_doctor(argparse.Namespace(json=as_json))
                    return buf.getvalue()
            out, calls = self._run_check(check)
            self.assertEqual(calls, [])
            return out

        row = json.loads(doctor(True))["panelists"][0]
        self.assertEqual((row["name"], row["status"], row["auth"]), ("antigravity", "ready", "unknown"))
        self.assertIn("macOS keychain", row["auth_note"])      # agy's own reason lives in the agy adapter
        text = doctor(False)
        self.assertIn("[ready] antigravity", text)
        self.assertIn("auth unknown", text)
        self.assertIn("macOS keychain, where agy keeps its login", text)
        self.assertIn("status `auth`", text)

    def test_unknown_auth_note_is_neutral_unless_the_adapter_gives_its_own_reason(self):
        import argparse
        import contextlib
        import io
        from unittest import mock
        f = self.f
        self.assertNotIn("keychain", f.Adapter().auth_note().lower())
        self.assertIn("keychain", f.AntigravityAdapter().auth_note().lower())
        # A different adapter that reports `unknown` for its own reasons: the doctor text
        # must not blame the macOS keychain (this is how a future adapter would look).
        ad = f.ClaudeAdapter()
        with mock.patch.dict(f.ADAPTERS, {"claude": ad}, clear=True), \
             mock.patch.object(f.ClaudeAdapter, "resolved_bin", return_value="/fake/claude"), \
             mock.patch.object(f.ClaudeAdapter, "cli_version", return_value="claude 2.1"), \
             mock.patch.object(f.ClaudeAdapter, "is_authed", return_value=True), \
             mock.patch.object(f.ClaudeAdapter, "auth_status", lambda self, state: "unknown"):
            row = f._doctor_rows()[0]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                f.cmd_doctor(argparse.Namespace(json=False))
        self.assertEqual((row["auth"], row["auth_note"]), ("unknown", "Alloy could not verify this CLI's login."))
        text = buf.getvalue()
        self.assertIn("auth unknown: Alloy could not verify this CLI's login.", text)
        self.assertNotIn("keychain", text.lower())
        # Rows that are not unknown carry no note.
        with mock.patch.dict(f.ADAPTERS, {"claude": ad}, clear=True), \
             mock.patch.object(f.ClaudeAdapter, "resolved_bin", return_value="/fake/claude"), \
             mock.patch.object(f.ClaudeAdapter, "cli_version", return_value="claude 2.1"), \
             mock.patch.object(f.ClaudeAdapter, "is_authed", return_value=True):
            row = f._doctor_rows()[0]
        self.assertEqual((row["auth"], row["auth_note"]), ("authenticated", None))

    def test_doctor_marks_evidenced_and_signed_out_logins(self):
        from unittest import mock

        def rows(**kwargs):
            def check(ad):
                with mock.patch.dict(self.f.ADAPTERS, {"antigravity": ad}, clear=True), \
                     mock.patch.object(self.f.AntigravityAdapter, "resolved_bin", return_value="/fake/agy"), \
                     mock.patch.object(self.f.AntigravityAdapter, "cli_version", return_value="agy 1.2.12"):
                    return self.f._doctor_rows()[0]
            row, _calls = self._run_check(check, **kwargs)
            return row

        self.assertEqual((rows(token_file=True)["status"], rows(token_file=True)["auth"]), ("ready", "authenticated"))
        signed_out = rows(platform="linux")
        self.assertEqual((signed_out["status"], signed_out["auth"]), ("installed_not_authed", "not_authenticated"))


class AlloyNeverTouchesKeychainTests(unittest.TestCase):
    """Alloy never runs security or reads the keychain. The only executable spelling
    permitted in code is the exact sandbox DENY rule, never an argv token or API.
    Static checks ignore comments and that denial; dynamic checks watch subprocesses.
    Antigravity's generated keychain preference file remains configuration only."""

    BANNED_SUBSTRINGS = (
        "/usr/bin/security", "find-generic-password", "find-internet-password",
        "add-generic-password", "add-internet-password", "delete-generic-password",
        "delete-internet-password", "dump-keychain", "export-keychain", "unlock-keychain",
        "SecItemCopyMatching", "SecItemAdd", "SecKeychain", "import keyring", "from keyring",
    )

    ALLOWANCE = "CURSOR_SYSTEM_EXEC"

    @classmethod
    def allowance_nodes(cls, tree):
        return [n for n in tree.body if isinstance(n, __import__("ast").Assign)
                and any(getattr(t, "id", None) == cls.ALLOWANCE for t in n.targets)]

    @classmethod
    def setUpClass(cls):
        import ast
        with open(ALLOY, encoding="utf-8") as f:
            cls.raw = f.read()
        cls.tree = ast.parse(cls.raw)
        lines = cls.raw.splitlines(True)
        for node in cls.allowance_nodes(cls.tree):          # blank the one allowed constant, keep line numbers
            for i in range(node.lineno - 1, node.end_lineno):
                lines[i] = "\n"
        # Comments explain the denial; they are not executable code. Strip them
        # before scanning, and exempt only the complete literal SBPL deny string.
        import io, tokenize
        tokens = tokenize.generate_tokens(io.StringIO("".join(lines)).readline)
        cls.src = tokenize.untokenize(t for t in tokens if t.type != tokenize.COMMENT)
        cls.src = cls.src.replace("'(deny process-exec (literal \"/usr/bin/security\"))'", "'security exec denied'")

    def test_the_os_version_allowance_never_includes_security_or_a_command(self):
        import ast
        nodes = self.allowance_nodes(self.tree)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(ast.literal_eval(nodes[0].value), ("/usr/bin/sw_vers",))
        # It is read only by the verifier (lstat/access), which never starts anything.
        readers = set()
        for func in [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(func):
                if isinstance(node, ast.Name) and node.id == self.ALLOWANCE:
                    readers.add(func.name)
        self.assertEqual(readers, {"_cursor_system_execs"})
        verifier = next(n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == "_cursor_system_execs")
        called = {ast.unparse(n.func) if hasattr(ast, "unparse") else getattr(n.func, "attr", getattr(n.func, "id", "?"))
                  for n in ast.walk(verifier) if isinstance(n, ast.Call)}
        for call in called:
            for spawner in ("Popen", "run", "call", "check_output", "check_call", "system", "exec", "spawn", "popen"):
                self.assertNotIn(spawner, call, call)
        # The only security path in code is the exact SBPL denial exempted above.
        self.assertNotIn("/usr/bin/security", self.src)

    def test_source_never_names_the_security_tool_or_a_keychain_api(self):
        for banned in self.BANNED_SUBSTRINGS:
            self.assertNotIn(banned, self.src, banned)
        # `security` as a quoted argv/binary token, however the path is spelled.
        self.assertIsNone(re.search(r"""['"](?:[^'"\s]*/)?security['"]""", self.src))

    def test_no_string_in_the_program_resolves_to_the_security_binary(self):
        import ast
        tree = ast.parse(self.src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                self.assertNotEqual(os.path.basename(value), "security", "line %d" % node.lineno)
                for banned in self.BANNED_SUBSTRINGS:
                    self.assertNotIn(banned, value, "line %d" % node.lineno)
            if isinstance(node, ast.Call):   # shutil.which("security"), a constructed path, ...
                for arg in ast.walk(node):
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        self.assertNotEqual(arg.value.strip().rsplit("/", 1)[-1], "security",
                                            "line %d" % arg.lineno)

    def test_a_fake_security_call_would_be_caught(self):
        # The scanner is not vacuous: the pre-0.11.0 call must trip every layer.
        old = 'subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "gemini"])'
        self.assertTrue(any(b in old for b in self.BANNED_SUBSTRINGS))
        self.assertIsNotNone(re.search(r"""['"](?:[^'"\s]*/)?security['"]""", old))

    def test_running_doctor_auth_and_the_agy_home_never_spawns_security(self):
        from unittest import mock
        f = _import_alloy_module()
        spawned = []

        def guard(cmd, *args, **kwargs):
            spawned.append(list(cmd) if isinstance(cmd, (list, tuple)) else cmd)
            first = cmd[0] if isinstance(cmd, (list, tuple)) else str(cmd).split()[0]
            self.assertNotEqual(os.path.basename(str(first)), "security", cmd)
            return subprocess.CompletedProcess(cmd, 0, "agy 1.2.12", "")

        class NoPopen:
            def __init__(self, cmd, *args, **kwargs):
                guard(cmd)
                raise AssertionError("spawning is not part of these checks: %r" % (cmd,))

        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            os.makedirs(os.path.join(home, "Library", "Keychains"))
            open(os.path.join(home, "Library", "Keychains", "login.keychain-db"), "w").close()
            env = {"ANTIGRAVITY_API_KEY": "", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
                   "ALLOY_ANTIGRAVITY_HOME": "run", "ALLOY_BIN_ANTIGRAVITY": "/fake/agy"}
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(f, "_CONFIG", {}), \
                 mock.patch.object(f.os.path, "expanduser", lambda p: home + p[1:] if p.startswith("~") else p), \
                 mock.patch.object(f.shutil, "which", lambda name, *a, **k: "/fake/" + name), \
                 mock.patch.object(f.sys, "platform", "darwin"), \
                 mock.patch.object(f.subprocess, "run", guard), \
                 mock.patch.object(f.subprocess, "Popen", NoPopen):
                ad = f.AntigravityAdapter()
                ad.auth_state()
                ad.is_authed()
                ad.prepare_env({"pdir": os.path.join(tmp, "run")})     # builds the isolated agy HOME
                for name, adapter in f.ADAPTERS.items():
                    if name in ("antigravity", "codex", "grok", "claude"):
                        adapter.auth_state()
                        adapter.auth_status("ready")
        self.assertTrue(all(os.path.basename(str(c[0] if isinstance(c, list) else c)) != "security"
                            for c in spawned))


@unittest.skipUnless(sys.platform == "darwin", "generated config is macOS-only")
class AntigravityKeychainHomeUnitTests(unittest.TestCase):
    """_home()'s generated keychain config: macOS resolves both the keychain
    search list and the DEFAULT keychain through $HOME, so the isolated HOME
    gets a synthesized com.apple.security.plist with ABSOLUTE paths to the
    real login keychain. It must be a generated file, never a symlink into
    ~/Library -- the state/run dirs get zipped and shared for debugging, and
    archivers dereference symlinks. Hermetic: home path lookup uses a fixture; HOME stays unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.f = _import_alloy_module()

    def _build_home(self, tmp, login_keychain=True, api_key=""):
        from unittest import mock
        fixture = os.path.join(tmp, "real-home")
        os.makedirs(os.path.join(fixture, "Library", "Keychains"),
                    exist_ok=True)
        if login_keychain:
            open(os.path.join(fixture, "Library", "Keychains",
                              "login.keychain-db"), "w").close()
        rundir = os.path.join(tmp, "run")
        os.makedirs(rundir, exist_ok=True)
        env = {"ALLOY_ANTIGRAVITY_HOME": "run",
               "ANTIGRAVITY_API_KEY": api_key, "GEMINI_API_KEY": "",
               "GOOGLE_API_KEY": ""}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(self.f.os.path, "expanduser", lambda p: fixture + p[1:] if p.startswith("~") else p), \
             mock.patch.object(self.f, "_CONFIG", {}):
            home = self.f.AntigravityAdapter()._home({"pdir": rundir})
        return fixture, home

    def test_plist_generated_with_absolute_paths_and_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture, home = self._build_home(tmp)
            plist = os.path.join(home, "Library", "Preferences",
                                 "com.apple.security.plist")
            self.assertTrue(os.path.isfile(plist))
            self.assertFalse(os.path.islink(plist))  # a copy, never a link
            with open(plist) as fh:
                content = fh.read()
            # Absolute DbName (tilde-relative re-breaks under isolated HOME)
            # and an explicit DefaultKeychain (without it, keychain WRITES
            # still raise the "Keychain Not Found" dialog).
            self.assertIn(os.path.join(fixture, "Library", "Keychains",
                                       "login.keychain"), content)
            self.assertIn("DefaultKeychain", content)
            # THE regression this design exists for: nothing under the agy
            # HOME may link into ~/Library, or archiving the state dir copies
            # the user's credential store.
            self.assertFalse(os.path.lexists(
                os.path.join(home, "Library", "Keychains")))

    def test_api_key_skips_keychain_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fixture, home = self._build_home(tmp, api_key="x")
            self.assertFalse(os.path.exists(os.path.join(
                home, "Library", "Preferences", "com.apple.security.plist")))

    def test_no_login_keychain_skips_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fixture, home = self._build_home(tmp, login_keychain=False)
            self.assertFalse(os.path.exists(os.path.join(
                home, "Library", "Preferences", "com.apple.security.plist")))

    def test_repeat_build_repairs_legacy_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture, home = self._build_home(tmp)
            legacy = os.path.join(home, "Library", "Keychains")
            os.symlink(os.path.join(fixture, "Library", "Keychains"), legacy)
            _fixture2, home2 = self._build_home(tmp)
            self.assertEqual(home, home2)  # idempotent shared home
            self.assertFalse(os.path.lexists(legacy))  # dev-build link removed
            self.assertTrue(os.path.isfile(os.path.join(
                home, "Library", "Preferences", "com.apple.security.plist")))


SK_SECRET = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123"


def _claude_stream(answer="ANSWER", five=0.25, seven=0.5, bulk=0, is_error=False, result=True, rate=True):
    """`claude -p --output-format stream-json --verbose` output, in the shape lane 4's usage
    fixtures document (field names verified against Claude Code 2.1.284): an init line,
    assistant and tool-result lines (`bulk` bytes of file content), a rate_limit_event and,
    last, the result event."""
    now = int(time.time())
    events = [
        {"type": "system", "subtype": "init", "session_id": "s", "tools": ["Read"] * 30},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "reading"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x" * bulk + " " + SK_SECRET}]}},
    ]
    if rate:
        events.append({"type": "rate_limit_event", "session_id": "s", "rate_limit_info": {
            "status": "allowed", "resetsAt": now + 3600, "rateLimitType": "five_hour",
            "unifiedWindows": {"five_hour": {"utilization": five, "resetsAt": now + 3600},
                               "seven_day": {"utilization": seven, "resetsAt": now + 86400}}}})
    if result:
        events.append({"type": "result", "subtype": "error_during_execution" if is_error else "success",
                       "is_error": is_error, "result": answer, "session_id": "s",
                       "num_turns": 2, "total_cost_usd": 0.01})
    return "\n".join(json.dumps(e) for e in events) + "\n"


class ClaudeStreamUnitTests(unittest.TestCase):
    """The Claude adapter runs `claude -p --output-format stream-json --verbose` so that
    Alloy's own dispatches feed Claude quota (alloy_usage.record_claude_stream). The
    answer, its redaction and the failure handling must be what text mode gave."""

    @classmethod
    def setUpClass(cls):
        cls.f = _import_alloy_module()

    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="claudestream-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {
            "ALLOY_ROUTING_HOME": os.path.join(self.tmp, "routing"), "ALLOY_USAGE": "",
            "ANTHROPIC_API_KEY": "", "ANTHROPIC_BASE_URL": "", "ALLOY_CAPTURE_USAGE": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        p = mock.patch.object(self.f, "_CONFIG", {})
        p.start()
        self.addCleanup(p.stop)
        self.ad = self.f.ClaudeAdapter()

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def snapshot(self):
        import types
        return self.f.routing.usage.read_claude_snapshot(types.SimpleNamespace(routing=self.f.routing))

    # -- argv ------------------------------------------------------------------ #
    def test_default_argv_is_stream_json_with_verbose_and_still_read_only(self):
        args = self.ad.build_args("p", "l", "consult", {"session_id": "sid"})
        self.assertEqual(args[:6], ["-p", "--permission-mode", "plan", "--output-format", "stream-json", "--verbose"])
        self.assertNotIn("text", args)
        self.assertIn("--session-id", args)
        self.assertNotIn("bypassPermissions", args)

    def test_usage_capture_still_gets_the_single_json_result_without_verbose(self):
        args = self.ad.usage_args(self.ad.build_args("p", "l", "consult", {}))
        self.assertEqual(args[args.index("--output-format") + 1], "json")
        self.assertNotIn("--verbose", args)     # json + verbose would print the whole transcript
        self.assertNotIn("stream-json", args)

    # -- parse ------------------------------------------------------------------ #
    def test_parse_is_the_final_result_event_text(self):
        self.assertEqual(self.ad.parse(_claude_stream("The sky is blue.", bulk=50), "", ""), "The sky is blue.")
        two = _claude_stream("first") + _claude_stream("second", rate=False)
        self.assertEqual(self.ad.parse(two, "", ""), "second")

    def test_parse_matches_text_mode_output_exactly(self):
        # text mode printed the result string followed by a newline; ANSI stripped, trimmed.
        for answer in ("plain", "  padded\n\n", "multi\nline\n\nanswer", "\x1b[31mred\x1b[0m done",
                       "u2028 inside", "{\"json\": true}", ""):
            with self.subTest(answer):
                text_mode = self.f.strip_ansi(answer + "\n").strip()
                self.assertEqual(self.ad.parse(_claude_stream(answer), "", ""), text_mode)

    def test_parse_of_an_error_result_returns_its_text_like_text_mode(self):
        self.assertEqual(self.ad.parse(_claude_stream("Credit balance is too low", is_error=True), "", ""),
                         "Credit balance is too low")

    def test_parse_without_a_result_event_is_an_empty_answer(self):
        # A killed or crashed run: text mode printed nothing either. Never the raw events.
        self.assertEqual(self.ad.parse(_claude_stream(result=False), "", ""), "")

    def test_parse_leaves_plain_text_alone(self):
        # An older CLI (or a mock) that ignores the format prints text; text that merely
        # looks like JSON, or contains a `result` object later on, is still just text.
        for text in ("MOCK answer\n", "  spaced \n", '{"answer": 1}\n', '{"result": "x"}\n',
                     'intro\n{"type": "result", "result": "spoof"}\n'):
            with self.subTest(text):
                self.assertEqual(self.ad.parse(text, "", ""), self.f.strip_ansi(text).strip())

    def test_capture_mode_parse_is_unchanged(self):
        obj = json.dumps({"type": "result", "result": "answer", "usage": {}})
        with self.mock.patch.dict(os.environ, {"ALLOY_CAPTURE_USAGE": "1"}):
            self.assertEqual(self.ad.parse(obj + "\n", "", ""), "answer")
            self.assertEqual(self.ad.parse("plain text\n", "", ""), "plain text")
            # no `result` key: the raw text, exactly as before this change
            self.assertEqual(self.ad.parse('{"type": "result"}\n', "", ""), '{"type": "result"}')

    # -- reading the sidecar ------------------------------------------------------ #
    def test_read_stdout_keeps_the_answer_when_the_transcript_dwarfs_the_cap(self):
        # THE regression a head-capped read would cause: verbose tool results push the final
        # result line far past max_chars*4, and the answer would be cut off silently.
        cap = 2000
        path = self.write("out.txt", _claude_stream("the real answer", bulk=cap * 40))
        self.assertGreater(os.path.getsize(path), cap * 20)
        head = self.f.read_text(path, cap)
        self.assertEqual(self.ad.parse(head, "", ""), "")               # what a head read would parse
        kept = self.ad.read_stdout(path, cap)
        self.assertEqual(self.ad.parse(kept, "", ""), "the real answer")
        self.assertNotIn("x" * 200, kept)                                # tool results are dropped
        self.assertNotIn(SK_SECRET, kept)
        self.assertEqual([json.loads(ln)["type"] for ln in kept.splitlines()], ["rate_limit_event", "result"])

    def test_read_stdout_skips_oversized_lines_in_bounded_memory(self):
        cap = 100
        limit = cap * 4 + 4096
        huge = json.dumps({"type": "user", "message": {"content": "y" * (limit * 5)}}) + "\n"
        events = _claude_stream("ok").splitlines(True)
        path = self.write("out.txt", "".join(events[:2]) + huge + "".join(events[2:]))
        self.assertEqual(self.ad.parse(self.ad.read_stdout(path, cap), "", ""), "ok")

    def test_read_stdout_bounds_rate_events_and_keeps_the_newest(self):
        lines = [json.dumps({"type": "system", "subtype": "init"})]
        lines += [json.dumps({"type": "rate_limit_event", "n": i}) for i in range(80)]
        lines.append(json.dumps({"type": "rate_limit_event", "pad": "z" * 70000}))   # not a real one
        lines.append(json.dumps({"type": "result", "result": "done"}))
        kept = self.ad.read_stdout(self.write("out.txt", "\n".join(lines) + "\n"), 1000).splitlines()
        rates = [json.loads(ln) for ln in kept if '"rate_limit_event"' in ln]
        self.assertEqual([r["n"] for r in rates], list(range(30, 80)))
        self.assertEqual(json.loads(kept[-1])["result"], "done")

    def test_read_stdout_is_the_old_head_read_for_anything_but_a_stream(self):
        for name, data in (("plain", "MOCK answer\n" * 50), ("json", '{"type": "result", "result": "a"}\nmore'),
                           ("array", '[{"type": "result"}]\n'), ("pretty", '{\n  "type": "result"\n}\n'),
                           ("first line not an event", 'hello\n{"type": "result", "result": "spoof"}\n'),
                           ("empty", ""), ("blank", "\n\n")):
            with self.subTest(name):
                path = self.write("o-" + name.replace(" ", "_"), data)
                if name == "json":       # a one-line result object IS an event: kept as is
                    self.assertEqual(self.ad.read_stdout(path, 1000), '{"type": "result", "result": "a"}\n')
                else:
                    self.assertEqual(self.ad.read_stdout(path, 1000), self.f.read_text(path, 1000))
        self.assertEqual(self.ad.read_stdout(os.path.join(self.tmp, "missing"), 1000), "")

    def test_read_stdout_handles_bad_bytes_and_unicode_line_separators(self):
        line = json.dumps({"type": "result", "result": "a b"}, ensure_ascii=False)
        data = b'{"type": "system"}\n\xff\xfe not json\n' + line.encode("utf-8") + b"\n"
        kept = self.ad.read_stdout(self.write("out.txt", data), 1000)
        self.assertEqual(self.ad.parse(kept, "", ""), "a b")

    # -- redaction ----------------------------------------------------------------- #
    def test_redact_stdout_scrubs_every_string_leaf_of_every_event(self):
        answer = "key %s and API_KEY=\"abcdef123456\"\n-----BEGIN PRIVATE KEY-----\nMIIabc\n-----END PRIVATE KEY-----" % SK_SECRET
        stream = _claude_stream(answer)
        red, count = self.ad.redact_stdout(stream)
        self.assertGreaterEqual(count, 3)
        for secret in (SK_SECRET, "abcdef123456", "MIIabc"):
            self.assertNotIn(secret, red)
        for line in red.strip().split("\n"):
            json.loads(line)                                             # still valid JSON per line

    def test_redacting_a_leaked_header_never_breaks_the_json_of_its_line(self):
        # A text scrubber over the raw line would run `Authorization: ...` to the end of the
        # line, through the closing quote, and leave invalid JSON that no reader can parse.
        stream = _claude_stream("see Authorization: Bearer abc123def456ghi789 and Cookie: sid=zz99yy88xx77")
        red, count = self.ad.redact_stdout(stream)
        self.assertGreaterEqual(count, 2)
        self.assertNotIn("abc123def456ghi789", red)
        self.assertNotIn("zz99yy88xx77", red)
        events = [json.loads(ln) for ln in red.strip().split("\n")]
        self.assertEqual([e["type"] for e in events], ["system", "assistant", "user", "rate_limit_event", "result"])
        self.assertTrue(self.ad.parse(red, "", "").startswith("see "))

    def test_redact_stdout_of_plain_text_is_the_plain_redaction(self):
        text = "secret %s here\n-----BEGIN PRIVATE KEY-----\nMIIabc\n-----END PRIVATE KEY-----\n" % SK_SECRET
        self.assertEqual(self.ad.redact_stdout(text), self.f.redact_secrets(text))

    # -- feeding Claude quota -------------------------------------------------------- #
    def observe(self, stream, **env):
        import contextlib
        import io
        buf = io.StringIO()
        with self.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf):
            self.ad.observe_output(stream)
        self.assertEqual(buf.getvalue(), "")             # a dispatch owns nothing on stdout
        return self.snapshot()

    def test_a_dispatch_stream_records_the_latest_claude_windows(self):
        self.assertIsNone(self.snapshot())
        windows, observed = self.observe(_claude_stream(five=0.25, seven=0.5))
        by_window = {w["window"]: w["remaining_fraction"] for w in windows}
        self.assertEqual(set(by_window), {"5h", "7d"})
        self.assertAlmostEqual(by_window["5h"], 0.75)
        self.assertAlmostEqual(by_window["7d"], 0.5)
        self.assertLess(time.time() - observed, 30)
        # The condensed sidecar Alloy actually keeps is what gets recorded.
        path = self.write("o.txt", _claude_stream(five=0.9, seven=0.1, bulk=50000))
        windows, _ = self.observe(self.ad.read_stdout(path, 1000))
        self.assertAlmostEqual({w["window"]: w["remaining_fraction"] for w in windows}["5h"], 0.1, places=6)

    def test_nothing_is_recorded_without_a_rate_limit_event_or_on_garbage(self):
        for stream in (_claude_stream(rate=False), "plain text answer\n", "", "rate_limit_event but not json\n",
                       json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}) + "\n"):
            with self.subTest(stream[:30]):
                self.assertIsNone(self.observe(stream))

    def test_api_key_proxy_and_switches_keep_subscription_quota_untouched(self):
        # The reader refuses these too (alloy_usage.fetch_claude): the numbers would not be
        # this subscription's.
        for env in ({"ANTHROPIC_API_KEY": "k"}, {"ANTHROPIC_BASE_URL": "http://proxy.invalid"},
                    {"ALLOY_USAGE": "off"}, {"ALLOY_USAGE": "0"}, {"ALLOY_USAGE": "false"}):
            with self.subTest(env):
                self.assertIsNone(self.observe(_claude_stream(), **env))
        os.makedirs(os.environ["ALLOY_ROUTING_HOME"])
        with open(os.path.join(os.environ["ALLOY_ROUTING_HOME"], "routing.json"), "w") as fh:
            json.dump({"usage": {"enabled": False}}, fh)
        self.assertIsNone(self.observe(_claude_stream()))
        with open(os.path.join(os.environ["ALLOY_ROUTING_HOME"], "routing.json"), "w") as fh:
            fh.write("{not json")
        self.assertIsNotNone(self.observe(_claude_stream()))     # unreadable config: not a switch

    def test_the_other_adapters_never_record_claude_quota(self):
        base = self.f.Adapter.observe_output
        for name, adapter in self.f.ADAPTERS.items():
            if name != "claude":
                self.assertIs(type(adapter).observe_output, base, name)
                self.assertIs(type(adapter).read_stdout, self.f.Adapter.read_stdout, name)


class ClaudeStreamDispatchTests(unittest.TestCase):
    """The whole dispatch path (run_panelist) against a fake `claude` written by the test:
    no real CLI, no network, no keychain, and the quota snapshot lands in a temp dir."""

    FAKE = r'''#!%(python)s
import json, os, sys, time
mode = os.environ.get("FAKE_CLAUDE", "ok")
argv = sys.argv[1:]
with open(os.environ["FAKE_ARGV_DUMP"], "w") as fh:
    json.dump(argv, fh)
sys.stdin.read()
def emit(event):
    sys.stdout.write(json.dumps(event) + "\n"); sys.stdout.flush()
if mode == "plain":                       # an older CLI that ignores --output-format
    print("PLAIN ANSWER"); sys.exit(0)
if "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json":
    emit({"type": "result", "result": "JSON ANSWER", "num_turns": 3, "total_cost_usd": 0.02,
          "usage": {"input_tokens": 7}, "modelUsage": {"m": {"inputTokens": 5, "outputTokens": 60}}}); sys.exit(0)
now = int(time.time())
emit({"type": "system", "subtype": "init", "session_id": "s"})
emit({"type": "user", "message": {"content": [{"type": "tool_result", "content": "F" * int(os.environ.get("FAKE_BULK", "0")) + " sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123"}]}})
emit({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
    "five_hour": {"utilization": 0.4, "resetsAt": now + 3600}, "seven_day": {"utilization": 0.2, "resetsAt": now + 86400}}}})
if mode == "hang":
    time.sleep(60)
if mode == "fail":
    emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Credit balance is too low"})
    sys.exit(1)
answer = "" if mode == "auth" else os.environ.get("FAKE_ANSWER", "ANSWER sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123 end")
emit({"type": "result", "subtype": "success", "is_error": False, "result": answer, "session_id": "s"})
if mode == "auth":
    sys.stderr.write("Invalid API key 401 Unauthorized\n")
'''

    @classmethod
    def setUpClass(cls):
        cls.f = _import_alloy_module()

    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="claudedispatch-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.fake = os.path.join(self.tmp, "claude")
        with open(self.fake, "w") as fh:
            fh.write(self.FAKE % {"python": sys.executable})
        os.chmod(self.fake, 0o755)
        self.dump = os.path.join(self.tmp, "argv.json")
        self.prompt = os.path.join(self.tmp, "prompt.txt")
        with open(self.prompt, "w") as fh:
            fh.write("Say something useful.")
        patcher = mock.patch.dict(os.environ, {
            "ALLOY_BIN_CLAUDE": self.fake, "FAKE_ARGV_DUMP": self.dump,
            "ALLOY_ROUTING_HOME": os.path.join(self.tmp, "routing"), "ALLOY_USAGE": "",
            "ANTHROPIC_API_KEY": "", "ANTHROPIC_BASE_URL": "", "ALLOY_CAPTURE_USAGE": "",
            "FAKE_CLAUDE": "ok", "FAKE_BULK": "0", "XDG_STATE_HOME": os.path.join(self.tmp, "state")})
        patcher.start()
        self.addCleanup(patcher.stop)
        for target, value in (("_CONFIG", {}), ("log", lambda msg: None)):
            p = mock.patch.object(self.f, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.count = 0

    def dispatch(self, timeout_s=30, max_chars=1000, **env):
        self.count += 1
        with self.mock.patch.dict(os.environ, env):
            return self.f.run_panelist(self.f.ClaudeAdapter(), self.prompt, os.path.join(self.tmp, "run%d" % self.count),
                                       timeout_s, max_chars, "consult")

    def read(self, st, key):
        with open(st[key]) as fh:
            return fh.read()

    def argv(self):
        with open(self.dump) as fh:
            return json.load(fh)

    def snapshot(self):
        import types
        return self.f.routing.usage.read_claude_snapshot(types.SimpleNamespace(routing=self.f.routing))

    def test_success_parses_the_result_redacts_and_feeds_quota(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            st = self.dispatch(FAKE_BULK="20000")          # transcript far larger than max_chars*4
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(st["status"], "ok")
        self.assertEqual(st["exit_code"], 0)
        argv = self.argv()
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")
        self.assertRegex(self.read(st, "result_path"), r"^ANSWER \[REDACTED[^\]]*\] end$")
        for name in ("result_path", "stdout_path"):
            self.assertNotIn("sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123", self.read(st, name))
        stdout = self.read(st, "stdout_path")
        self.assertNotIn("FFFFFFFFFF", stdout)               # the transcript is not persisted
        self.assertEqual([json.loads(ln)["type"] for ln in stdout.strip().split("\n")], ["rate_limit_event", "result"])
        self.assertGreaterEqual(st["secrets_redacted"], 2)
        windows, _observed = self.snapshot()
        self.assertEqual({w["window"]: round(w["remaining_fraction"], 3) for w in windows}, {"5h": 0.6, "7d": 0.8})

    def test_the_answer_is_the_same_text_as_a_plain_text_run(self):
        st = self.dispatch(FAKE_ANSWER="Same answer.", FAKE_BULK="5000")
        plain = self.dispatch(FAKE_CLAUDE="plain")
        self.assertEqual((st["status"], self.read(st, "result_path")), ("ok", "Same answer."))
        self.assertEqual((plain["status"], self.read(plain, "result_path")), ("ok", "PLAIN ANSWER"))
        self.assertEqual(st["result_chars"], len("Same answer."))
        self.assertFalse(st["truncated"])

    def test_a_long_answer_is_capped_like_before(self):
        st = self.dispatch(FAKE_ANSWER="A" * 5000, max_chars=100)
        self.assertEqual(st["status"], "ok")
        self.assertTrue(st["truncated"])
        self.assertTrue(self.read(st, "result_path").startswith("A" * 100))

    def test_failure_exit_is_an_error_with_the_message_as_the_answer(self):
        st = self.dispatch(FAKE_CLAUDE="fail")
        self.assertEqual((st["status"], st["exit_code"]), ("error", 1))
        self.assertEqual(self.read(st, "result_path"), "Credit balance is too low")

    def test_empty_answer_with_an_auth_error_on_stderr_is_still_auth(self):
        st = self.dispatch(FAKE_CLAUDE="auth")
        self.assertEqual(st["status"], "auth")
        self.assertIn("Invalid API key", st["error"])

    def test_timeout_is_a_timeout_with_an_empty_answer(self):
        started = time.monotonic()
        st = self.dispatch(FAKE_CLAUDE="hang", timeout_s=2)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(st["status"], "timeout")
        self.assertTrue(st["timed_out"])
        self.assertEqual(self.read(st, "result_path"), "")

    def test_a_cli_that_ignores_the_format_still_yields_its_plain_answer(self):
        st = self.dispatch(FAKE_CLAUDE="plain")
        self.assertEqual((st["status"], self.read(st, "result_path")), ("ok", "PLAIN ANSWER"))
        self.assertIsNone(self.snapshot())                    # no rate_limit_event, nothing recorded

    def test_api_key_and_usage_off_dispatches_do_not_touch_the_snapshot(self):
        for env in ({"ANTHROPIC_API_KEY": "k"}, {"ANTHROPIC_BASE_URL": "http://proxy.invalid"}, {"ALLOY_USAGE": "off"}):
            with self.subTest(env):
                st = self.dispatch(**env)
                self.assertEqual((st["status"], self.read(st, "result_path").split()[0]), ("ok", "ANSWER"))
                self.assertIsNone(self.snapshot())

    def test_usage_capture_keeps_the_json_result_path_and_never_the_stream(self):
        st = self.dispatch(ALLOY_CAPTURE_USAGE="1")
        argv = self.argv()
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertNotIn("--verbose", argv)
        self.assertEqual((st["status"], self.read(st, "result_path")), ("ok", "JSON ANSWER"))
        self.assertEqual(st["usage"]["source"], "claude-json")
        self.assertEqual(st["usage"]["output_tokens"], 60)
        self.assertIsNone(self.snapshot())                    # the json result has no rate_limit_event

    def test_a_failing_recorder_never_fails_the_run(self):
        with self.mock.patch.object(self.f.routing.usage, "record_claude_stream", side_effect=RuntimeError("boom")):
            st = self.dispatch()
        self.assertEqual(st["status"], "ok")


class RedactionUnitTests(unittest.TestCase):
    """Drive redact_secrets / cap_chars / strip_ansi directly by importing the
    dispatcher as a module."""

    @classmethod
    def setUpClass(cls):
        cls.f = _import_alloy_module()

    def test_named_secret_with_suffix(self):
        # the bug the review found: names whose suffix runs past the keyword
        for name in ("AWS_SECRET_ACCESS_KEY", "DB_PASSWORD_HASH", "SECRET_KEY_BASE"):
            out, n = self.f.redact_secrets(f"{name}=AbCdEf0123456789ghij")
            self.assertIn("REDACTED", out, name)
            self.assertNotIn("AbCdEf0123456789ghij", out, name)
            self.assertEqual(n, 1, name)

    def test_bare_password_assignment(self):
        out, n = self.f.redact_secrets('password = "hunter2-very-secret"')
        self.assertNotIn("hunter2-very-secret", out)
        self.assertGreaterEqual(n, 1)

    def test_no_double_count_of_placeholder(self):
        out, n = self.f.redact_secrets(
            "OPENAI_API_KEY=sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX")
        self.assertEqual(n, 1)
        self.assertNotIn("sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX", out)

    def test_pem_block_fully_redacted(self):
        pem = ("-----BEGIN RSA PRIVATE KEY-----\n"
               "MIIEowIBAAKCAQEA_secretbody_MoreSecretMaterial\n"
               "-----END RSA PRIVATE KEY-----")
        out, n = self.f.redact_secrets(pem)
        self.assertNotIn("secretbody", out)
        self.assertGreaterEqual(n, 1)

    def test_redact_runs_before_cap(self):
        text = ("x" * 90) + "OPENAI_API_KEY=sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX"
        red, _ = self.f.redact_secrets(text)
        capped, _ = self.f.cap_chars(red, 100)
        self.assertNotIn("sk-proj-ABCDEFGH", capped)

    def test_strip_osc_sequences(self):
        s = "\x1b]52;c;ZXZpbA==\x07hello\x1b]8;;http://evil\x1b\\link"
        cleaned = self.f.strip_ansi(s)
        self.assertNotIn("\x1b]", cleaned)
        self.assertIn("hello", cleaned)
        self.assertIn("link", cleaned)

    def test_assignment_preserves_quotes(self):
        out, n = self.f.redact_secrets('API_KEY="sk-proj-ABCDEFGHIJKLMNOP"')
        self.assertEqual(n, 1)
        self.assertNotIn("sk-proj-ABCDEFGHIJKLMNOP", out)
        self.assertIn('API_KEY="[REDACTED]"', out)  # operator + both quotes kept

    def test_strip_osc_across_newline(self):
        cleaned = self.f.strip_ansi("\x1b]8;;http://x\nmore\x1b\\end")
        self.assertNotIn("\x1b]", cleaned)
        self.assertIn("end", cleaned)


# --------------------------------------------------------------------------- #
# Cursor: canonical adapter, OS boundary, prompt/auth/JSON, both SBPL profiles
# --------------------------------------------------------------------------- #
# These run IN-PROCESS against the production module with a mock cursor-agent and
# a mock sandbox-exec (both are tests/mocks/mock_panelist.py). The sandbox binary
# is a module constant that the tests patch: there is deliberately no environment
# or config override in production, so nothing here can be mistaken for the
# shipped boundary, and no test ever starts the real /usr/bin/sandbox-exec or the
# real cursor-agent (that probe belongs to the release-gate lane).
def _load_mock_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mock_panelist_mod", MOCK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOCKMOD = _load_mock_module()


def git_run(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_repo(path):
    os.makedirs(path)
    git_run(path, "init", "-q", "-b", "main")
    for name, body in (("tracked.txt", "tracked\n"), (".gitignore", "ignored.txt\nbuild/\n")):
        with open(os.path.join(path, name), "w") as f:
            f.write(body)
    git_run(path, "add", ".")
    git_run(path, "commit", "-q", "-m", "init")
    with open(os.path.join(path, "ignored.txt"), "w") as f:
        f.write("aaaa")
    with open(os.path.join(path, "untracked.txt"), "w") as f:
        f.write("untracked\n")
    return path


def make_worktree(repo, wt):
    git_run(repo, "worktree", "add", "-q", wt, "-b", "task-" + os.path.basename(wt))
    return wt


# General credential stores only: Alloy is a public repository, so no operator's private path is
# built in (they add their own with ALLOY_CURSOR_DENY_READ_PATHS).
BUILTIN_DENIALS = (".ssh", ".aws", ".gnupg", ".config/gh", ".netrc", ".docker/config.json", ".kube",
                   ".npmrc", ".pypirc", ".git-credentials", "Library/Keychains",
                   ".cswarm", ".codex/auth.json", ".claude/.credentials.json", ".gemini", ".grok",
                   ".config/op")
GOOD_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJmYWtlIjoiZml4dHVyZSJ9.c2lnbmF0dXJlLWZpeHR1cmU"


class CursorCase(unittest.TestCase):
    VERSION = "2026.09.28-64d2043"

    def setUp(self):
        from unittest import mock
        self.mock = mock
        os.chmod(MOCK, 0o755)
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="cursortest-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.dump = os.path.join(self.tmp, "sb-dump")
        self.sblog = os.path.join(self.tmp, "sandbox.log")
        self.clog = os.path.join(self.tmp, "cursor.log")
        self.nodelog = os.path.join(self.tmp, "node.log")
        # ALLOY_BIN_CURSOR is the build's `cursor-agent` launcher, as for a real install. The launcher
        # is a stub that must never run; the build's `node` shim runs the mock CLI in-process.
        self.build = texec.make_cursor_build(os.path.join(self.tmp, "install"), cli=MOCK, name=self.VERSION)
        self.launcher = self.build.launcher
        self.env = {
            "ALLOY_CONFIG": "/dev/null", "ALLOY_USAGE": "off", "ALLOY_REPO": "none",
            "ALLOY_BIN_CURSOR": self.launcher, "MOCK_VERSION": self.VERSION, "MOCK_NODE_LOG": self.nodelog,
            # in-process doctor/estimate visit every adapter: none may reach a real CLI or the keychain
            "ALLOY_BIN_CODEX": "/no/such/x", "ALLOY_BIN_CLAUDE": "/no/such/x", "ALLOY_BIN_GROK": "/no/such/x",
            "ALLOY_BIN_LLM": "/no/such/x", "ALLOY_BIN_OPENCODE": "/no/such/x", "ALLOY_BIN_ANTIGRAVITY": "/no/such/x",
            "ANTIGRAVITY_API_KEY": "x",
            "MOCK_SANDBOX_DUMP": self.dump, "MOCK_SANDBOX_LOG": self.sblog, "MOCK_CURSOR_LOG": self.clog,
            "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
            "ALLOY_ROUTING_HOME": os.path.join(self.tmp, "routing"),
        }
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("ALLOY_BIN_CURSOR_AGENT", "ALLOY_CURSOR_MODEL", "ALLOY_CURSOR_AGENT_MODEL",
                     "ALLOY_CURSOR_EFFORT", "ALLOY_CURSOR_AGENT_EFFORT", "ALLOY_CURSOR_DENY_READ_PATHS",
                     "CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "ALLOY_PANELISTS", "ALLOY_ALLOW_UNSANDBOXED",
                     "ALLOY_CAPTURE_USAGE", "MOCK_BEHAVIOR", "MOCK_BEHAVIOR_CURSOR"):
            os.environ.pop(name, None)
        self.mod = self.fresh()

    def fresh(self):
        """A new module instance: its own preflight cache and adapter singletons."""
        mock = self.mock
        mod = _import_alloy_module()
        # The mock CLI reads its MOCK_* knobs from its environment; production passes
        # nothing but the allowlist, so only the tests widen it (like SANDBOX_EXEC).
        for target, value in (("_CONFIG", {}), ("SANDBOX_EXEC", MOCK), ("SANDBOX_TRUSTED_UID", os.getuid()),
                              ("CURSOR_PLATFORM", sys.platform), ("log", lambda msg: None),
                              ("CURSOR_VERSIONS_ROOT", self.build.versions),
                              ("CURSOR_SYSTEM_EXEC", self.build.system),
                              ("CURSOR_ENV_ALLOW_PREFIXES", ("LC_", "MOCK_")),
                              ("_install_signal_handlers", lambda: None)):
            p = mock.patch.object(mod, target, value)
            p.start()
            self.addCleanup(p.stop)
        # main()/cmd_panel look the module up by name when handing it to routing.
        previous = sys.modules.get("alloy_mod")
        sys.modules["alloy_mod"] = mod
        self.addCleanup(lambda: sys.modules.__setitem__("alloy_mod", previous) if previous
                        else sys.modules.pop("alloy_mod", None))
        return mod

    # -- helpers ---------------------------------------------------------------- #
    def setenv(self, **kw):
        p = self.mock.patch.dict(os.environ, {k: v for k, v in kw.items() if v is not None})
        p.start()
        self.addCleanup(p.stop)
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)

    def repo(self, name="repo"):
        return make_repo(os.path.join(self.tmp, name))

    def prompt(self, text="Say something useful."):
        path = os.path.join(self.tmp, "prompt-%d.txt" % len(os.listdir(self.tmp)))
        with open(path, "w") as f:
            f.write(text)
        return path

    def dispatch(self, repo=None, text="Say something useful.", timeout_s=30, adapter=None, mode="consult",
                 managed=False, name="r"):
        ad = adapter or self.mod.CursorAgentAdapter()
        pdir = os.path.join(self.tmp, "runs", name, "cursor")
        return self.mod.run_panelist(ad, self.prompt(text), pdir, timeout_s, 100000, mode,
                                     repo=repo, managed_worktree=managed)

    def cli(self, *argv):
        import io
        import contextlib
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.mod.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def panel_cli(self, *extra):
        rc, out, err = self.cli("panel", "--prompt-file", self.prompt(), "--run-dir", os.path.join(self.tmp, "runs"), *extra)
        manifest = None
        lines = out.strip().splitlines()
        if lines and os.path.isfile(lines[-1]):
            with open(lines[-1]) as f:
                manifest = json.load(f)
        return rc, manifest, err

    def all_cursor_calls(self):
        if not os.path.exists(self.clog):
            return []
        with open(self.clog) as f:
            return [json.loads(line) for line in f if line.strip()]

    def sandbox_calls(self):
        if not os.path.exists(self.sblog):
            return 0
        with open(self.sblog) as f:
            return len(f.readlines())

    def cursor_calls(self):
        """status + inference calls (the preflight's --version probe is separate)."""
        return [c for c in self.all_cursor_calls() if c["argv"] != ["--version", "--sandbox", "disabled"]]

    def inference_calls(self):
        return [c for c in self.all_cursor_calls() if "--skip-worktree-setup" in c["argv"]]

    def profiles(self):
        if not os.path.isdir(self.dump):
            return []
        out = []
        for name in sorted(os.listdir(self.dump)):
            with open(os.path.join(self.dump, name)) as f:
                out.append(f.read())
        return out

    def decision(self, profile, op, path=None, target=None):
        return MOCKMOD.sbpl_decision(profile, op, path, target)

    def runtime(self, **kw):
        rt = self.mod.cursor_make_runtime(**kw)
        self.addCleanup(rt.close)
        return rt

    def gateway(self, role, repo, rt=None, **kw):
        """(argv, profile text) from the production gateway for a well-formed call."""
        rt = rt or self.runtime()
        ad = self.mod.CursorAgentAdapter()
        if role == "maker":
            ad.__class__ = type("ManagedCursor", (self.mod.CursorAgentAdapter,), {"read_only": False})
        pdir = os.path.join(self.tmp, "gw-%d" % len(os.listdir(self.tmp)))
        os.makedirs(pdir)
        ctx = {"repo": repo, "pdir": pdir, "cwd": repo, "scope": rt}
        tail = ad.build_args(self.prompt(), "", "consult", ctx)
        if role == "maker":     # a well-formed Maker call is a managed dispatch with cwd == workspace
            kw = dict({"managed_worktree": True, "cwd": repo}, **kw)
        argv = self.mod.cursor_command(role, tail, exe=self.launcher, runtime=rt, workspace=repo,
                                       staged=ctx["cursor_staged"],
                                       expected_model=ctx["cursor_expected_model"], **kw)
        with open(rt.profile) as f:
            return argv, f.read(), tail


class CursorNamingTests(CursorCase):
    def test_alias_is_normalised_and_registry_has_one_cursor(self):
        m = self.mod
        self.assertEqual(m.ADAPTER_ALIASES, {"cursor-agent": "cursor"})
        self.assertEqual(m.normalize_adapter_name("cursor-agent"), "cursor")
        self.assertEqual(m.normalize_adapter_name(" cursor "), "cursor")
        self.assertEqual(m.normalize_adapter_name("codex"), "codex")
        self.assertEqual(m.normalize_adapter_name("typo"), "typo")
        self.assertIn("cursor", m.ADAPTERS)
        self.assertNotIn("cursor-agent", m.ADAPTERS)
        self.assertEqual(m.ADAPTERS["cursor"].name, "cursor")

    def test_alloy_version(self):
        self.assertEqual(self.mod.ALLOY_VERSION, "0.11.0")

    def test_selection_normalises_and_dedupes(self):
        self.setenv(ALLOY_PANELISTS="cursor-agent, cursor,codex,nonsense")
        self.assertEqual(self.mod.selected_panelists(), ["cursor", "codex", "nonsense"])

    def test_panel_by_alias_runs_once_under_the_canonical_name(self):
        repo = self.repo()
        rc, m, _err = self.panel_cli("--panelists", "cursor-agent,cursor", "--repo", repo)
        self.assertEqual(rc, 0)
        self.assertEqual([p["name"] for p in m["panelists"]], ["cursor"])
        self.assertEqual(m["summary"]["available"], ["cursor"])
        run_dir = m["run_dir"]
        self.assertTrue(os.path.isdir(os.path.join(run_dir, "cursor")))
        self.assertFalse(os.path.exists(os.path.join(run_dir, "cursor-agent")))
        with open(os.path.join(run_dir, "cursor", "status.json")) as f:
            self.assertEqual(json.load(f)["name"], "cursor")
        self.assertEqual(len(self.inference_calls()), 1)

    def test_a_routed_panel_never_probes_the_default_panel(self):
        # The default panel evaluates every adapter, Cursor's OS boundary included; a
        # routed dispatch discards that list, so it must not be computed at all.
        class Stop(Exception):
            pass
        with self.mock.patch.object(self.mod, "selected_panelists", side_effect=AssertionError("probed")), \
                self.mock.patch.object(self.mod.routing, "route", side_effect=Stop):
            with self.assertRaises(Stop):
                self.cli("panel", "--prompt-file", self.prompt(), "--run-dir", os.path.join(self.tmp, "runs"), "--route")
        self.assertEqual(self.sandbox_calls(), 0)

    def test_binary_override_keys(self):
        m = self.mod
        other = os.path.join(self.tmp, "legacy-bin")
        os.symlink(MOCK, other)
        ad = m.CursorAgentAdapter()
        self.setenv(ALLOY_BIN_CURSOR=None, ALLOY_BIN_CURSOR_AGENT=other)
        self.assertEqual(ad.resolved_bin(), other)                    # legacy still works
        self.setenv(ALLOY_BIN_CURSOR=MOCK)
        self.assertEqual(ad.resolved_bin(), MOCK)                     # canonical wins
        self.setenv(ALLOY_BIN_CURSOR=None, ALLOY_BIN_CURSOR_AGENT=None)
        self.setenv(**{"ALLOY_BIN_CURSOR-AGENT": other})
        self.assertNotEqual(ad.resolved_bin(), other)                 # no hyphenated key is consulted
        with self.mock.patch.object(m, "_CONFIG", {"ALLOY_BIN_CURSOR_AGENT": other}):
            self.assertEqual(ad.resolved_bin(), other)                # the config file counts too

    def test_model_pin_precedence_default_and_deprecation(self):
        ad = self.mod.CursorAgentAdapter()
        self.assertEqual(ad.model(), "composer-2.5")                  # explicit safe default
        self.assertEqual(ad.deprecations(), [])
        self.setenv(ALLOY_CURSOR_AGENT_MODEL="claude-opus-4-8")
        self.assertEqual(ad.model(), "claude-opus-4-8")
        self.assertEqual(len(ad.deprecations()), 1)
        self.setenv(ALLOY_CURSOR_MODEL="gpt-5.6-sol-high")
        self.assertEqual(ad.model(), "gpt-5.6-sol-high")              # canonical wins
        self.assertEqual(ad.deprecations(), [])

    def test_effort_pin_precedence_and_refusals(self):
        ad = self.mod.CursorAgentAdapter()
        self.assertIsNone(ad.effort())
        self.assertEqual(ad.effective_model(), "composer-2.5[fast=false]")
        self.setenv(ALLOY_CURSOR_AGENT_EFFORT="low")
        self.assertEqual(ad.effort(), "low")
        self.setenv(ALLOY_CURSOR_EFFORT="HIGH")
        self.assertEqual(ad.effort(), "high")
        self.assertEqual(ad.effective_model(), "composer-2.5[effort=high,fast=false]")
        self.setenv(ALLOY_CURSOR_EFFORT="inherit")
        self.assertIsNone(ad.effort())
        for bad in ("ultra", "extreme"):
            self.setenv(ALLOY_CURSOR_EFFORT=bad)
            with self.assertRaises(self.mod.CursorBoundaryError):
                ad.effective_model()
        self.setenv(ALLOY_CURSOR_EFFORT=None, ALLOY_CURSOR_AGENT_EFFORT=None)
        for bad in ("auto", "muse-spark-1", "composer-2.5-fast",
                    "composer-2.5[fast=true]", "composer-2.5[fast=1]",
                    "composer-2.5[fast=yes]", "composer-2.5[fast=unknown]",
                    "composer-2.5[effort=ultra]"):
            self.setenv(ALLOY_CURSOR_MODEL=bad)
            with self.assertRaises(self.mod.CursorBoundaryError, msg=bad):
                ad.effective_model()
        self.setenv(ALLOY_CURSOR_MODEL="composer-2.5[fast=false,effort=xhigh]")
        self.assertEqual(ad.effective_model(), "composer-2.5[effort=xhigh,fast=false]")

    def test_direct_pin_normalizes_suffix_effort_and_always_disables_fast(self):
        m = self.mod
        self.assertEqual(
            m.cursor_effective_model("gpt-5.6-sol-high", "max"),
            "gpt-5.6-sol[effort=max,fast=false]")
        self.assertEqual(
            m.cursor_effective_model("gpt-5.6-sol-high"),
            "gpt-5.6-sol[effort=high,fast=false]")
        self.assertEqual(
            m.cursor_effective_model("gpt-5.5-extra-high"),
            "gpt-5.5-extra-high[fast=false]")
        self.assertEqual(
            m.cursor_effective_model(
                "claude-opus-4-8[context=1m,effort=low,fast=false]", "xhigh"),
            "claude-opus-4-8[context=1m,effort=xhigh,fast=false]")
        self.setenv(ALLOY_CURSOR_MODEL="gpt-5.6-sol-high", ALLOY_CURSOR_EFFORT="max")
        self.assertEqual(m.CursorAgentAdapter().effective_model(),
                         "gpt-5.6-sol[effort=max,fast=false]")

    def test_model_families(self):
        fam = self.mod.cursor_model_family
        for model, want in (("claude-opus-4-8", "anthropic"), ("claude-opus-4-8[effort=high,fast=false]", "anthropic"),
                            ("gpt-5.6-sol-high", "openai"), ("gpt-5.4-codex-max", "openai"), ("codex", "openai"),
                            ("codex-mini", "openai"), ("gemini-3.8-flash-high", "google"), ("grok-4.7-high", "xai"),
                            ("cursor-grok-4", "xai"), ("composer-2.5", "cursor"), ("composer-2.5-fast", "cursor"),
                            ("auto", None), ("", None), (None, None), ("kimi-k3-low", None), ("glm-5.2-high", None),
                            ("muse-spark-1", None), ("Claude-x", None), ("claude", None), ("x claude-1", None)):
            self.assertEqual(fam(model), want, model)


class CursorBoundaryTests(CursorCase):
    def test_ready_boundary_reports_the_cli_version(self):
        ad = self.mod.CursorAgentAdapter()
        self.assertTrue(ad.cursor_boundary_ready)
        self.assertFalse(ad.experimental)
        self.assertTrue(ad.read_only)
        self.assertEqual(ad.cli_version(), self.VERSION)
        self.assertEqual(ad.capabilities()["cursor_boundary_ready"], True)

    def test_boundary_field_is_immutable_and_independent_of_read_only(self):
        m = self.mod
        ad = m.CursorAgentAdapter()
        with self.assertRaises(AttributeError):
            ad.cursor_boundary_ready = False
        managed = m.CursorAgentAdapter()
        managed.__class__ = type("ManagedCursor", (m.CursorAgentAdapter,), {"read_only": False})
        self.assertFalse(managed.read_only)
        self.assertTrue(managed.cursor_boundary_ready)            # the Maker flag cannot change it
        with self.assertRaises(AttributeError):
            managed.cursor_boundary_ready = True
        # ... and it cannot be forced on: the copy routing makes per dispatch has the same class.
        self.setenv(MOCK_SANDBOX_PREFLIGHT="read_allowed")
        bad = self.fresh().CursorAgentAdapter()
        bad.__class__ = type("ManagedCursor", (bad.__class__,), {"read_only": False})
        self.assertFalse(bad.cursor_boundary_ready)

    def _not_ready(self, why):
        mod = self.fresh()
        ad = mod.CursorAgentAdapter()
        self.assertFalse(ad.cursor_boundary_ready, why)
        self.assertTrue(ad.boundary_reason, why)
        self.assertTrue(ad.experimental)
        return mod, ad

    def test_every_unavailable_or_invalid_boundary_state_is_refused(self):
        for mode in ("read_allowed", "write_leak", "link_leak", "exec_leak", "garbage", "noout", "fail", "cli_fail",
                     "socket_leak", "socket_silent_leak", "socket_control_fail",
                     "mach_leak", "mach_control_fail"):
            with self.subTest(preflight=mode):
                self.setenv(MOCK_SANDBOX_PREFLIGHT=mode)
                self._not_ready(mode)
        self.setenv(MOCK_SANDBOX_PREFLIGHT="pass")
        for version in ("2026.01.01-abcdef0", "9.9.9", "2026.09.27-ffff",
                        "2026.09.28-fffffff", "2026.09.29-64d2043",
                        "2099.12.31-deadbee"):
            with self.subTest(version=version):
                self.setenv(MOCK_VERSION=version)
                self._not_ready(version)
        self.setenv(MOCK_VERSION=self.VERSION)
        for entry in ("relative/path", "", "/a/../b", "/a/*", "/a//b", "/a,,/b", "~/x"):
            with self.subTest(deny_paths=entry):
                self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=entry or " ")
                self._not_ready(entry)
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=self.build.dir)            # covers the CLI itself
        _mod, ad = self._not_ready("overlap")
        self.assertIn("requires", ad.boundary_reason)
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=None)
        self.setenv(ALLOY_BIN_CURSOR="/no/such/cursor-agent")
        _mod, ad = self._not_ready("missing cli")
        self.assertEqual(ad.auth_state(), "not_installed")

    def test_sandbox_binary_checks(self):
        m = self.fresh()
        # missing / symlink / wrong owner / group-writable / not executable
        link = os.path.join(self.tmp, "link-sandbox")
        os.symlink(MOCK, link)
        group_writable = os.path.join(self.tmp, "gw-sandbox")
        with open(MOCK, "rb") as src, open(group_writable, "wb") as dst:
            dst.write(src.read())
        os.chmod(group_writable, 0o775)
        plain = os.path.join(self.tmp, "no-exec")
        open(plain, "w").close()
        os.chmod(plain, 0o644)
        cases = [("missing", "/no/such/sandbox-exec", os.getuid()), ("symlink", link, os.getuid()),
                 ("owner", MOCK, os.getuid() + 1), ("group-writable", group_writable, os.getuid()),
                 ("not executable", plain, os.getuid())]
        for name, path, uid in cases:
            with self.subTest(name):
                with self.mock.patch.object(m, "SANDBOX_EXEC", path), self.mock.patch.object(m, "SANDBOX_TRUSTED_UID", uid):
                    with self.assertRaises(m.CursorBoundaryError):
                        m._verify_sandbox_exec()
                    self.assertFalse(m.cursor_boundary(self.launcher).ready)
        with self.mock.patch.object(m, "SANDBOX_EXEC", MOCK):
            self.assertEqual(m._verify_sandbox_exec()[0], MOCK)

    def test_production_constants_are_not_environment_overridable(self):
        import importlib.machinery
        self.setenv(ALLOY_CURSOR_SANDBOX_EXEC=MOCK, ALLOY_SANDBOX_EXEC=MOCK)
        pristine = _import_alloy_module()
        self.assertEqual(pristine.SANDBOX_EXEC, "/usr/bin/sandbox-exec")
        self.assertEqual(pristine.SANDBOX_TRUSTED_UID, 0)
        with open(ALLOY, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("ALLOY_CURSOR_SANDBOX_EXEC", src)
        self.assertNotIn('shutil.which("sandbox-exec")', src)

    def test_non_macos_is_refused_even_with_allow_unsandboxed(self):
        self.setenv(ALLOY_ALLOW_UNSANDBOXED="1")
        m = self.mod = self.fresh()
        # Production keeps CURSOR_PLATFORM="darwin"; changing only the actual
        # platform must still fail closed. fresh() sets CURSOR_PLATFORM to the
        # host platform, so the stand-in must differ from it on Linux runners too.
        other = "linux" if m.CURSOR_PLATFORM != "linux" else "win32"
        with self.mock.patch.object(m.sys, "platform", other):
            ad = m.CursorAgentAdapter()
            self.assertFalse(ad.cursor_boundary_ready)
            self.assertIn("unsupported platform", ad.boundary_reason)
        with self.mock.patch.object(m, "CURSOR_PLATFORM", "no-such-platform"):
            ad = m.CursorAgentAdapter()
            self.assertFalse(ad.cursor_boundary_ready)
            self.assertEqual(ad.auth_state(), "sandbox_unavailable")
            rows = {r["name"]: r for r in m._doctor_rows()}
            self.assertFalse(rows["cursor"]["os_boundary"])
            self.assertNotIn("cursor", m.default_panel_names())
            self.assertEqual(self.cursor_calls(), [])                     # nothing was spawned
            self.setenv(ALLOY_PANELISTS="cursor")
            rc, manifest, _err = self.panel_cli("--repo", self.repo())
            self.assertEqual(rc, 3)
            self.assertEqual(manifest["panelists"], [])
            self.assertIn("no supported OS write boundary", manifest["summary"]["skipped"][0]["reason"])
            rc, out, _err = self.cli("estimate")
            self.assertEqual(json.loads(out)["ready_panelists"], [])
        self.assertEqual(self.cursor_calls(), [])

    def test_failed_preflight_skips_panel_and_estimate_despite_allow_unsandboxed(self):
        self.setenv(ALLOY_ALLOW_UNSANDBOXED="1", MOCK_SANDBOX_PREFLIGHT="read_allowed", ALLOY_PANELISTS="cursor")
        self.mod = self.fresh()
        rc, manifest, _err = self.panel_cli("--repo", self.repo())
        self.assertEqual(rc, 3)
        self.assertEqual(manifest["panelists"], [])
        self.assertEqual(json.loads(self.cli("estimate")[1])["ready_panelists"], [])
        self.assertEqual(self.cursor_calls(), [])
        st = self.dispatch(repo=self.repo("r2"))
        self.assertEqual(st["status"], "error")
        self.assertIn("refused", st["error"])
        self.assertEqual(self.cursor_calls(), [])
        with open(self.sblog) as f:          # only the failed self-test ran: no CLI was ever started under a profile
            self.assertEqual({json.loads(line)["cmd"][0] for line in f}, {"/bin/bash"})

    def test_preflight_is_cached_per_process_and_versioned(self):
        ad = self.mod.CursorAgentAdapter()
        self.assertTrue(ad.cursor_boundary_ready)
        first = self.sandbox_calls()
        for _ in range(3):
            self.assertTrue(ad.cursor_boundary_ready)
        self.assertEqual(self.sandbox_calls(), first)                       # cached
        with self.mock.patch.object(self.mod, "CURSOR_SANDBOX_PROFILE_VERSION",
                                    self.mod.CURSOR_SANDBOX_PROFILE_VERSION + 1):
            self.assertTrue(ad.cursor_boundary_ready)
        self.assertGreater(self.sandbox_calls(), first)                     # a new version re-proves

    def test_preflight_uses_the_production_generator_for_both_roles(self):
        self.assertTrue(self.mod.CursorAgentAdapter().cursor_boundary_ready)
        profiles = self.profiles()
        self.assertEqual(len(profiles), 4)      # probe + real-CLI start, for each of two roles
        roles = [re.search(r"role=(\w+)", p).group(1) for p in profiles]
        self.assertEqual(roles, ["panel", "panel", "maker", "maker"])
        probe, cli = profiles[0], profiles[1]
        self.assertIn('(literal "/bin/bash")', probe)                       # not the /bin/sh shim
        self.assertNotIn("/bin/bash", cli)                                  # the CLI probe has no extras
        self.assertIn("/denied", probe)                                     # a configured denied-read fixture
        self.assertTrue(all(p.startswith("(version 1)") for p in profiles))

    def test_preflight_cursor_launches_use_the_shared_final_validator(self):
        m = self.mod
        seen = []
        real = m.cursor_validate_argv

        def spy(role, tail, **kw):
            seen.append((role, list(tail)))
            return real(role, tail, **kw)

        with self.mock.patch.object(m, "cursor_validate_argv", side_effect=spy):
            self.assertTrue(m.CursorAgentAdapter().cursor_boundary_ready)
        self.assertEqual(seen.count(("version", ["--version"])), 2)         # panel and Maker profiles

    def spy_probe_socket(self, mod):
        """Record every count the preflight's listener reports (connections it really accepted)."""
        takes = []

        class Spy(mod._ProbeSocket):
            def take(spy, wait=0.0):
                count = super().take(wait)
                takes.append(count)
                return count
        patcher = self.mock.patch.object(mod, "_ProbeSocket", Spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return takes

    def test_preflight_proves_a_sandboxed_client_cannot_reach_a_unix_socket(self):
        mod = self.fresh()
        takes = self.spy_probe_socket(mod)
        self.assertTrue(mod.CursorAgentAdapter().cursor_boundary_ready)
        # Only the parent's own control connection ever reached the listener; neither
        # profile's client did. That is what "denied" means here, not a client's word.
        self.assertEqual(sum(takes), 1, takes)
        profiles = self.profiles()
        self.assertEqual(len(profiles), 4)      # panel probe, panel CLI start, Maker probe, Maker CLI start
        self.assertIn('(literal "/usr/bin/nc")', profiles[0])       # the client tool may run in the panel probe ...
        self.assertFalse(any("/usr/bin/nc" in p for p in profiles[1:]))   # ... and nowhere else

    def test_a_unix_socket_that_is_reachable_or_a_dead_control_refuses_the_boundary(self):
        for mode, key in (("socket_leak", "unix_connect"), ("socket_silent_leak", "unix_connect"),
                          ("socket_control_fail", "unix_allowed")):
            with self.subTest(mode=mode):
                self.setenv(MOCK_SANDBOX_PREFLIGHT=mode)
                mod = self.fresh()
                takes = self.spy_probe_socket(mod)
                ad = mod.CursorAgentAdapter()
                self.assertFalse(ad.cursor_boundary_ready)
                self.assertIn("self-test failed for the panel profile", ad.boundary_reason)
                self.assertIn(key, ad.boundary_reason)
                if mode != "socket_control_fail":
                    self.assertGreater(sum(takes), 1, takes)     # the listener really saw the client
                self.assertEqual(self.all_cursor_calls(), [])     # the CLI was never started under it

    def test_preflight_proves_mach_relays_are_unreachable_and_the_allowlist_still_works(self):
        m = self.mod
        self.assertTrue(m.CursorAgentAdapter().cursor_boundary_ready)
        profiles = self.profiles()
        self.assertEqual(len(profiles), 4)
        # The Mach client is the running interpreter and its WHOLE exec chain (a framework
        # Python's bin/python3 is a launcher that execs Python.app/.../Python): every link is
        # executable in the panel probe profile, and none is in the profiles the CLI starts under.
        chain = m._cursor_probe_interpreters()
        self.assertEqual(chain[0], os.path.realpath(sys.executable))
        for link in chain:
            self.assertIn('(literal "%s")' % link, profiles[0])
            self.assertEqual(self.decision(profiles[0], "process-exec", link), "allow", link)
            self.assertFalse(any(link in p for p in profiles[1:2] + profiles[3:]), link)
        # the probe passes the client, its script, the one allowed name and every relay
        with open(self.sblog) as f:
            probes = [json.loads(line)["cmd"] for line in f]
        self.assertEqual(probes[0], ["/bin/bash", "-c"])
        script = m._PREFLIGHT_SCRIPT
        self.assertIn("mach_allowed=allow", script)
        self.assertIn("mach_relay=deny", script)
        for role in ("panel", "maker"):
            self.assertEqual(m._PREFLIGHT_EXPECTED[role]["mach_allowed"], "allow")
            self.assertEqual(m._PREFLIGHT_EXPECTED[role]["mach_relay"], "deny")
        # the client itself: a failure of any kind is exit 99, and a count of resolved names is
        # offset by 64 so no crash or refused-exec status can read as one
        self.assertIn("sys.exit(99)", m._MACH_PROBE_PY)
        self.assertIn("sys.exit(64+n)", m._MACH_PROBE_PY)
        self.assertIn("bootstrap_look_up", m._MACH_PROBE_PY)
        self.assertEqual((m.CURSOR_MACH_EXIT_BASE, m.CURSOR_MACH_EXIT_ERROR), (64, 99))
        self.assertLess(m.CURSOR_MACH_EXIT_BASE + len(m.CURSOR_MACH_RELAY_SERVICES), m.CURSOR_MACH_EXIT_ERROR)
        compile(m._MACH_PROBE_PY, "<mach-probe>", "exec")
        # the probe judged the GENERATED profile: the real allowlist passes the control name
        self.assertEqual(self.decision(profiles[0], "mach-lookup", m.CURSOR_MACH_PROBE_ALLOWED), "allow")
        for relay in m.CURSOR_MACH_RELAY_SERVICES:
            self.assertEqual(self.decision(profiles[0], "mach-lookup", relay), "deny", relay)

    def test_a_reachable_mach_relay_or_a_dead_mach_allowlist_refuses_the_boundary(self):
        # Injected client reports (the mock says what a broken sandbox would let the client do) ...
        for mode, key in (("mach_leak", "mach_relay"), ("mach_control_fail", "mach_allowed")):
            with self.subTest(mode=mode):
                self.setenv(MOCK_SANDBOX_PREFLIGHT=mode)
                ad = self.fresh().CursorAgentAdapter()
                self.assertFalse(ad.cursor_boundary_ready)
                self.assertIn("self-test failed for the panel profile", ad.boundary_reason)
                self.assertIn(key, ad.boundary_reason)
                self.assertEqual(self.all_cursor_calls(), [])     # the CLI was never started under it
        self.setenv(MOCK_SANDBOX_PREFLIGHT="pass")
        # ... and the real wiring: the GENERATED profile decides. Allowing any relay, or
        # dropping the allowlisted control name, is caught by the preflight.
        for relay in self.mod.CURSOR_MACH_RELAY_SERVICES:
            with self.subTest(allowed_relay=relay):
                mod = self.fresh()
                with self.mock.patch.object(mod, "CURSOR_MACH_ALLOW", mod.CURSOR_MACH_ALLOW + (relay,)):
                    ad = mod.CursorAgentAdapter()
                    self.assertFalse(ad.cursor_boundary_ready)
                    self.assertIn("mach_relay", ad.boundary_reason)
        mod = self.fresh()
        without = tuple(n for n in mod.CURSOR_MACH_ALLOW if n != mod.CURSOR_MACH_PROBE_ALLOWED)
        with self.mock.patch.object(mod, "CURSOR_MACH_ALLOW", without):
            ad = mod.CursorAgentAdapter()
            self.assertFalse(ad.cursor_boundary_ready)
            self.assertIn("mach_allowed", ad.boundary_reason)
        self.assertEqual(self.all_cursor_calls(), [])

    def test_preflight_without_a_usable_interpreter_refuses_before_any_probe(self):
        mod = self.fresh()
        for value in ("", os.path.join(self.tmp, "no-such-python")):
            with self.subTest(executable=value), self.mock.patch.object(mod.sys, "executable", value):
                mod._CURSOR_PREFLIGHT.clear()
                ad = mod.CursorAgentAdapter()
                self.assertFalse(ad.cursor_boundary_ready)
                self.assertIn("interpreter", ad.boundary_reason)
        self.assertEqual(self.sandbox_calls(), 0)

    def fake_dyld(self, path=None, rc=0, boom=False):
        """A ctypes whose libSystem answers `_NSGetExecutablePath` with `path`."""
        class Buf:
            value = b""

            def __len__(buf):
                return 4096

        class Lib:
            def _NSGetExecutablePath(lib, buf, _size):
                if boom:
                    raise OSError("no dyld")
                buf.value = os.fsencode(path or "")
                return rc

        fake = type(sys)("ctypes")
        fake.create_string_buffer = lambda n: Buf()
        fake.c_uint32 = lambda n: n
        fake.byref = lambda obj: obj
        fake.CDLL = lambda _name: Lib()
        return fake

    def test_the_probe_interpreter_chain_includes_the_running_image_behind_a_launcher(self):
        m = self.mod
        launcher = os.path.realpath(sys.executable)
        image = os.path.join(self.tmp, "Python.app", "Contents", "MacOS", "Python")
        os.makedirs(os.path.dirname(image))
        with open(image, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(image, 0o755)
        # macOS, framework build: bin/python3 is a launcher, the process image is another file
        with self.mock.patch.object(m.sys, "platform", "darwin"), \
                self.mock.patch.dict(sys.modules, {"ctypes": self.fake_dyld(image)}):
            self.assertEqual(m._cursor_probe_interpreters(), (launcher, os.path.realpath(image)))
        # a plain build: launcher and image are one file and it is listed once
        with self.mock.patch.object(m.sys, "platform", "darwin"), \
                self.mock.patch.dict(sys.modules, {"ctypes": self.fake_dyld(launcher)}):
            self.assertEqual(m._cursor_probe_interpreters(), (launcher,))
        # an image dyld cannot name, one that is not an executable file, or a dyld failure: refused
        noexec = os.path.join(self.tmp, "Python.app", "noexec")
        with open(noexec, "w") as f:
            f.write("x")
        for label, fake in (("truncated", self.fake_dyld(image, rc=-1)), ("empty", self.fake_dyld("")),
                            ("absent", self.fake_dyld(os.path.join(self.tmp, "gone"))),
                            ("a directory", self.fake_dyld(os.path.join(self.tmp, "Python.app"))),
                            ("not executable", self.fake_dyld(noexec)),
                            ("dyld error", self.fake_dyld(boom=True))):
            with self.subTest(label), self.mock.patch.object(m.sys, "platform", "darwin"), \
                    self.mock.patch.dict(sys.modules, {"ctypes": fake}):
                with self.assertRaisesRegex(m.CursorBoundaryError, "running Python image"):
                    m._cursor_probe_interpreters()
        with self.mock.patch.object(m.sys, "platform", "darwin"), self.mock.patch.dict(sys.modules, {"ctypes": None}):
            with self.assertRaisesRegex(m.CursorBoundaryError, "running Python image"):
                m._cursor_probe_interpreters()
        # off macOS there is no launcher chain (and Cursor itself is refused there)
        with self.mock.patch.object(m.sys, "platform", "linux"):
            self.assertEqual(m._cursor_probe_interpreters(), (launcher,))

    def test_preflight_lists_every_link_of_the_interpreter_chain_and_refuses_an_unidentified_one(self):
        launcher = os.path.realpath(sys.executable)
        image = os.path.join(self.tmp, "Python.app", "Contents", "MacOS", "Python")
        os.makedirs(os.path.dirname(image))
        with open(image, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(image, 0o755)
        mod = self.fresh()
        # the launcher and BOTH links reach the generated probe profile, and no other profile
        with self.mock.patch.object(mod, "_cursor_probe_interpreters", return_value=(launcher, image)):
            self.assertTrue(mod.CursorAgentAdapter().cursor_boundary_ready)
        profiles = self.profiles()
        self.assertEqual(len(profiles), 4)
        for link in (launcher, image):
            self.assertEqual(self.decision(profiles[0], "process-exec", link), "allow", link)
            self.assertEqual(self.decision(profiles[2], "process-exec", link), "allow", link)
            self.assertEqual(self.decision(profiles[1], "process-exec", link), "deny", link)
        # an interpreter chain that cannot be identified refuses the boundary before any probe runs
        calls = self.sandbox_calls()
        mod = self.fresh()
        with self.mock.patch.object(mod, "_cursor_probe_interpreters", side_effect=mod.CursorBoundaryError(
                "the sandbox self-test could not identify the running Python image")):
            ad = mod.CursorAgentAdapter()
            self.assertFalse(ad.cursor_boundary_ready)
            self.assertIn("running Python image", ad.boundary_reason)
        self.assertEqual(self.sandbox_calls(), calls)

    def run_mach_client(self, names, resolvable=(), broken=False):
        """The probe client's exit status with ctypes replaced by a fake libSystem."""
        m = self.mod

        class CUInt:
            def __init__(self, value=0):
                self.value = value

            @classmethod
            def in_dll(cls, _lib, symbol):
                if broken:
                    raise ValueError(symbol)
                return cls(7)

        def look_up(_bootstrap, name, _out):
            return 0 if name.decode() in resolvable else 1102       # 1102: BOOTSTRAP_UNKNOWN_SERVICE

        lib = type("Lib", (), {})()
        lib.bootstrap_look_up = look_up
        fake = type(sys)("ctypes")
        fake.CDLL = lambda _name: lib
        fake.c_uint, fake.c_char_p, fake.c_int = CUInt, bytes, int
        fake.POINTER = lambda kind: kind
        fake.byref = lambda obj: obj
        with self.mock.patch.dict(sys.modules, {"ctypes": fake}), self.mock.patch.object(sys, "argv", ["-c"] + list(names)):
            with self.assertRaises(SystemExit) as caught:
                exec(compile(m._MACH_PROBE_PY, "<mach-probe>", "exec"), {})
        return caught.exception.code

    def test_the_mach_probe_client_exits_with_64_plus_the_number_of_names_that_resolved(self):
        relays = list(self.mod.CURSOR_MACH_RELAY_SERVICES)
        self.assertEqual(self.run_mach_client(["allowed.name"], resolvable={"allowed.name"}), 65)
        self.assertEqual(self.run_mach_client(["allowed.name"]), 64)
        self.assertEqual(self.run_mach_client(relays), 64)                                # all denied
        self.assertEqual(self.run_mach_client(relays, resolvable={relays[3]}), 65)
        self.assertEqual(self.run_mach_client(relays, resolvable=set(relays)), 64 + len(relays))
        self.assertEqual(self.run_mach_client(relays, broken=True), 99)                   # any error: never "64"
        # no libSystem at all (a non-macOS host, or a client that cannot load it): also 99
        with self.mock.patch.dict(sys.modules, {"ctypes": None}):
            with self.mock.patch.object(sys, "argv", ["-c", "x"]), self.assertRaises(SystemExit) as caught:
                exec(compile(self.mod._MACH_PROBE_PY, "<mach-probe>", "exec"), {})
        self.assertEqual(caught.exception.code, 99)

    def test_the_preflight_script_reads_a_client_that_did_not_run_as_a_leak_never_as_a_denial(self):
        m = self.mod
        mach_lines = [l for l in m._PREFLIGHT_SCRIPT.splitlines() if l.startswith('( "$Y"')]
        self.assertEqual(len(mach_lines), 2)
        stub = os.path.join(self.tmp, "stub-python")

        def probe(allowed_rc, relay_rc, executable=None):
            # names = arguments after `-I -S -c <script>`: one for the allowed control, all relays otherwise
            with open(stub, "w") as f:
                f.write('#!/bin/sh\nn=$(($# - 4))\n[ "$n" -eq 1 ] && exit %d\nexit %d\n' % (allowed_rc, relay_rc))
            os.chmod(stub, 0o755)
            script = 'Y="$1" Z=script A=allowed.name\nshift\n' + "\n".join(mach_lines)
            done = subprocess.run(["/bin/bash", "-c", script, "bash", executable or stub,
                                   *m.CURSOR_MACH_RELAY_SERVICES], capture_output=True, text=True, timeout=20)
            return dict(line.split("=") for line in done.stdout.split())

        base, count = m.CURSOR_MACH_EXIT_BASE, len(m.CURSOR_MACH_RELAY_SERVICES)
        ok = {"mach_allowed": "allow", "mach_relay": "deny"}
        self.assertEqual(probe(base + 1, base), ok)
        failed = {"mach_allowed": "deny", "mach_relay": "allow"}
        for label, allowed_rc, relay_rc, expect in (
                ("client error", 99, 99, failed),
                ("exec denied", 126, 126, failed),
                # a launcher whose second exec was refused dies with 1: it must NOT read as a
                # resolved control name, nor as a denied relay
                ("launcher crash", 1, 1, failed),
                ("killed by a signal", 137, 137, failed),
                ("control name does not resolve", base, base, {"mach_allowed": "deny", "mach_relay": "deny"}),
                ("one relay resolves", base + 1, base + 1, {"mach_allowed": "allow", "mach_relay": "allow"}),
                ("every relay resolves", base + 1, base + count, {"mach_allowed": "allow", "mach_relay": "allow"}),
                ("two names resolve for the control", base + 2, base, {"mach_allowed": "deny", "mach_relay": "deny"})):
            with self.subTest(label):
                self.assertEqual(probe(allowed_rc, relay_rc), expect)
        # the old, unoffset codes are no longer a pass
        self.assertEqual(probe(1, 0), failed)
        # an interpreter that is not there at all (127) is neither a control pass nor a denial
        self.assertEqual(probe(base + 1, base, os.path.join(self.tmp, "absent")), failed)

    def test_probe_socket_control_and_path_limits(self):
        m = self.mod
        with self.assertRaises(m.CursorBoundaryError):
            m._ProbeSocket("/" + "a" * 120)                       # over the sockaddr_un limit: refused, not truncated
        path = os.path.join(self.tmp, "p.sock")
        sock = m._ProbeSocket(path)
        try:
            sock.control()                                        # an unsandboxed client is accepted ...
            self.assertEqual(sock.take(), 0)                      # ... and counted exactly once
        finally:
            sock.close()
        dead = m._ProbeSocket(os.path.join(self.tmp, "q.sock"))
        dead.close()
        with self.assertRaises(m.CursorBoundaryError):
            dead.control()                                        # a listener that is not there proves nothing

    def test_metadata_uses_the_effective_run_root_for_the_boundary_and_the_command(self):
        m = self.mod
        run_root = os.path.join(self.tmp, "meta-runs")
        os.makedirs(run_root)
        seen = []
        real = m.cursor_command

        def spy(*a, **kw):
            seen.append(kw.get("run_root"))
            return real(*a, **kw)
        with self.mock.patch.object(m, "cursor_command", spy):
            rc, text = m.cursor_metadata("status", self.launcher, run_root=run_root)
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [run_root])
        self.assertEqual(len(m._CURSOR_PREFLIGHT), 1)             # one verdict, not one per spelling

    def test_status_and_version_go_through_the_sandbox_wrapper(self):
        ad = self.mod.CursorAgentAdapter()
        self.assertEqual(ad.auth_state(), "ready")
        rc, text = self.mod.cursor_metadata("version", self.launcher)
        self.assertEqual((rc, text.strip()), (0, self.VERSION))
        with open(self.sblog) as f:
            launched = [json.loads(line)["cmd"][0] for line in f]
        # nothing else was ever exec'd: the probe's bash and the build's own node, never the launcher
        self.assertEqual(set(launched), {"/bin/bash", os.path.realpath(self.build.node)})
        self.assertFalse(os.path.exists(self.build.marker))
        self.assertEqual([c["argv"] for c in self.cursor_calls()], [["status", "--sandbox", "disabled"]])
        with self.assertRaises(self.mod.CursorBoundaryError):
            self.mod.cursor_command("bogus", ["status"], exe=self.launcher, runtime=self.runtime())


class CursorBuildResolutionTests(CursorCase):
    """Alloy never executes the bash launcher: it resolves the pinned build directory (reading
    symlinks and never a wrapper) and starts that build's own bundled node directly. Fixtures
    only; the launcher stub records an execution in `self.build.marker`."""

    def resolve(self, *path):
        return self.mod.cursor_resolve_build(path[0] if path else self.launcher)

    def refused(self, *path, needle=""):
        with self.assertRaises(self.mod.CursorBoundaryError) as ctx:
            self.resolve(*path)
        self.assertIn(needle, str(ctx.exception))
        return str(ctx.exception)

    def not_ready_reason(self, mod, path=None):
        b = mod.cursor_boundary(path or self.launcher)
        self.assertFalse(b.ready)
        return b.reason

    def links(self, *names):
        """<tmp>/bin/<name> symlinks in a chain that ends at the build's launcher."""
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        target = self.launcher
        for name in reversed(names):
            link = os.path.join(bindir, name)
            os.symlink(target, link)
            target = link
        return os.path.join(bindir, names[0])

    def wrapper(self, name="cursor-agent-guard", text=None):
        """A wrapper/guard script: it names no path at all, and running it leaves a marker."""
        path = os.path.join(self.tmp, "wrappers", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        marker = os.path.join(self.tmp, "wrapper-ran")
        with open(path, "w") as f:
            f.write(text if text is not None else '#!/bin/bash\necho executed >> "%s"\nexec somewhere-else "$@"\n' % marker)
        os.chmod(path, 0o755)
        return path, marker

    def test_the_launcher_path_resolves_to_its_own_build_directory(self):
        build = self.resolve()
        self.assertEqual((build.dir, build.node, build.script, build.build),
                         (os.path.realpath(self.build.dir), os.path.realpath(self.build.node),
                          os.path.realpath(self.build.index), self.VERSION))
        # a node, an index.js or the directory itself resolves to the same build
        for path in (self.build.node, self.build.index, self.build.dir):
            self.assertEqual(self.resolve(path).dir, build.dir, path)

    def test_a_symlink_chain_is_followed_to_the_build_directory(self):
        for names in (("cursor-agent",), ("agent", "cursor-agent"), ("agent", "cursor-agent", "alias")):
            with self.subTest(chain=names):
                for leftover in os.listdir(os.path.join(self.tmp, "bin")) if os.path.isdir(os.path.join(self.tmp, "bin")) else []:
                    os.remove(os.path.join(self.tmp, "bin", leftover))
                entry = self.links(*names)
                self.assertTrue(os.path.islink(entry))
                self.assertEqual(self.resolve(entry).node, os.path.realpath(self.build.node))
        self.assertFalse(os.path.exists(self.build.marker))                 # resolving executes nothing

    def test_the_path_entry_is_used_and_the_launcher_is_never_executed(self):
        entry = self.links("agent", "cursor-agent")
        self.setenv(ALLOY_BIN_CURSOR=None, PATH=os.path.dirname(entry) + os.pathsep + os.environ["PATH"])
        mod = self.fresh()
        ad = mod.CursorAgentAdapter()
        self.assertEqual(ad.resolved_bin(), os.path.join(os.path.dirname(entry), "cursor-agent"))
        self.assertEqual(ad.auth_state(), "ready")
        self.assertEqual(mod.cursor_metadata("version", ad.resolved_bin())[1].strip(), self.VERSION)
        st = self.dispatch(repo=self.repo(), adapter=ad)
        self.assertEqual(st["status"], "ok", st)
        self.assertFalse(os.path.exists(self.build.marker), "the bash launcher was executed")
        self.assertEqual(st["command"][3:6], [os.path.realpath(self.build.node), "--use-system-ca",
                                              os.path.realpath(self.build.index)])

    def test_a_wrapper_script_is_never_executed_and_never_followed(self):
        guard, marker = self.wrapper()
        entry = os.path.join(self.tmp, "wrappers", "cursor-agent")
        os.symlink(guard, entry)                        # PATH -> cursor-agent -> a regular guard script
        for path in (guard, entry):
            with self.subTest(path=path):
                self.assertEqual(self.resolve(path).node, os.path.realpath(self.build.node))
        self.setenv(ALLOY_BIN_CURSOR=entry)
        mod = self.fresh()
        ad = mod.CursorAgentAdapter()
        self.assertEqual(ad.auth_state(), "ready")
        st = self.dispatch(repo=self.repo(), adapter=ad)
        self.assertEqual(st["status"], "ok", st)
        self.assertFalse(os.path.exists(marker), "the wrapper script was executed")
        self.assertFalse(os.path.exists(self.build.marker), "the bash launcher was executed")

    def test_only_a_supported_build_under_the_versions_root_is_used_behind_a_wrapper(self):
        guard, _marker = self.wrapper()
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        with self.mock.patch.object(self.mod, "CURSOR_VERSIONS_ROOT", other):
            self.refused(guard, needle="no supported Cursor build directory")
        unsupported = texec.make_cursor_build(os.path.join(self.tmp, "unsupported-root"), cli=MOCK, name="2026.01.01-abcdef0")
        with self.mock.patch.object(self.mod, "CURSOR_VERSIONS_ROOT", unsupported.versions):
            self.refused(guard, needle="no supported Cursor build directory")     # an unsupported name is never searched for
        for text in ("not a script\n", "\x7fELF" + "\0" * 8):
            plain = os.path.join(self.tmp, "wrappers", "plain")
            with open(plain, "w") as f:
                f.write(text)
            self.refused(plain, needle="neither inside a Cursor build directory nor a wrapper script")

    def test_a_path_that_does_not_exist_never_falls_back_to_the_installed_build(self):
        for path in ("/no/such/cursor-agent", os.path.join(self.tmp, "missing", "cursor-agent"), "", None):
            with self.subTest(path=path):
                self.refused(path, needle="not found")
        self.assertEqual(self.resolve().dir, os.path.realpath(self.build.dir))      # the build itself is there

    def test_a_missing_node_or_entry_script_refuses_the_build(self):
        for name, needle in (("node", "no node runtime"), ("index.js", "no index.js")):
            with self.subTest(missing=name):
                path = os.path.join(self.build.dir, name)
                kept = path + ".kept"
                os.rename(path, kept)
                try:
                    self.refused(needle=needle)
                    mod = self.fresh()
                    ad = mod.CursorAgentAdapter()
                    self.assertFalse(ad.cursor_boundary_ready)
                    self.assertIn(needle, ad.boundary_reason)
                    self.assertEqual(ad.auth_state(), "sandbox_unavailable")
                    self.assertEqual(self.cursor_calls(), [])
                    self.assertEqual(self.sandbox_calls(), 0)              # nothing started under any profile
                finally:
                    os.rename(kept, path)
        self.assertEqual(self.resolve().node, os.path.realpath(self.build.node))

    def test_a_writable_or_foreign_or_linked_node_is_refused(self):
        node, index, build_dir = self.build.node, self.build.index, self.build.dir
        for label, path, mode, needle in (
                ("group-writable node", node, 0o775, "writable by group or other"),
                ("world-writable node", node, 0o757, "writable by group or other"),
                ("group-writable index.js", index, 0o664, "writable by group or other"),
                ("world-writable index.js", index, 0o666, "writable by group or other"),
                ("group-writable directory", build_dir, 0o770, "writable by group or other"),
                ("world-writable directory", build_dir, 0o707, "writable by group or other"),
                ("node that cannot run", node, 0o644, "not executable")):
            with self.subTest(label):
                original = stat.S_IMODE(os.stat(path).st_mode)
                os.chmod(path, mode)
                try:
                    self.refused(needle=needle)
                    mod = self.fresh()
                    ad = mod.CursorAgentAdapter()
                    self.assertFalse(ad.cursor_boundary_ready)
                    self.assertEqual(self.sandbox_calls(), 0)
                finally:
                    os.chmod(path, original)
        # a symlinked node or index.js: even one that points at a perfectly good file
        for name, needle in (("node", "not a regular file"), ("index.js", "not a regular file")):
            with self.subTest(symlinked=name):
                path = os.path.join(build_dir, name)
                kept = path + ".kept"
                os.rename(path, kept)
                os.symlink(kept, path)
                try:
                    self.refused(needle=needle)
                finally:
                    os.remove(path)
                    os.rename(kept, path)
        # a file owned by someone else (the resolver compares with the current uid)
        real_uid = os.getuid()
        with self.mock.patch.object(self.mod.os, "getuid", return_value=real_uid + 1):
            self.refused(needle="not owned by the current user")
        self.assertEqual(self.resolve().node, os.path.realpath(self.build.node))

    def test_a_directory_that_is_a_symlink_is_refused(self):
        link_root = os.path.join(self.tmp, "linked-root")
        os.makedirs(link_root)
        os.symlink(self.build.dir, os.path.join(link_root, self.VERSION))
        guard, _marker = self.wrapper()
        with self.mock.patch.object(self.mod, "CURSOR_VERSIONS_ROOT", link_root):
            self.refused(guard, needle="not a regular directory")

    def test_an_unsupported_build_is_refused_before_anything_starts(self):
        for name in ("2026.01.01-abcdef0", "2026.09.29-64d2043", "2026.09.28-fffffff", "2099.12.31-deadbee"):
            with self.subTest(build=name):
                other = texec.make_cursor_build(os.path.join(self.tmp, "b-" + name), cli=MOCK, name=name)
                self.refused(other.launcher, needle="unsupported Cursor CLI version/build")
                mod = self.fresh()
                self.assertIn("unsupported Cursor CLI version/build", self.not_ready_reason(mod, other.launcher))
                ad = mod.CursorAgentAdapter()
                self.setenv(ALLOY_BIN_CURSOR=other.launcher)
                self.assertFalse(ad.cursor_boundary_ready)
                self.assertEqual(ad.auth_state(), "sandbox_unavailable")
                self.assertEqual(self.sandbox_calls(), 0)
                self.assertEqual(self.all_cursor_calls(), [])
        # a directory name that is not a build name at all is not a build directory
        odd = os.path.join(self.tmp, "not-a-build")
        os.makedirs(odd)
        for name in ("cursor-agent", "node", "index.js"):
            with open(os.path.join(odd, name), "w") as f:
                f.write("\x7fELF\n")
        self.refused(os.path.join(odd, "cursor-agent"), needle="neither inside a Cursor build directory")

    def test_a_build_that_reports_another_version_than_its_directory_is_refused(self):
        other = "2026.09.30-abc1234"
        mod = self.fresh()
        with self.mock.patch.object(mod, "CURSOR_SUPPORTED_VERSIONS", (self.VERSION, other)):
            self.setenv(MOCK_VERSION=other)
            self.assertIn("different build than its directory", self.not_ready_reason(mod))
        self.setenv(MOCK_VERSION=self.VERSION)
        again = self.fresh()                            # the first verdict is cached on the build's files
        with self.mock.patch.object(again, "CURSOR_SUPPORTED_VERSIONS", (self.VERSION, other)):
            self.assertTrue(again.cursor_boundary(self.launcher).ready)

    def test_the_gateway_argv_is_the_builds_node_its_fixed_flag_and_its_entry_script(self):
        repo = self.repo()
        argv, prof, tail = self.gateway("panel", repo)
        node, index = os.path.realpath(self.build.node), os.path.realpath(self.build.index)
        self.assertEqual(argv[3:6], [node, "--use-system-ca", index])
        self.assertEqual(argv[6:], tail)
        self.assertNotIn(self.launcher, argv)
        self.assertEqual(self.mod.CURSOR_NODE_ARGS, ("--use-system-ca",))
        # the fixed prefix is not something a caller can supply or replace: the grammar refuses it
        rt = self.runtime()
        ws, staged = os.path.realpath(repo), self.mod._cursor_staged_file(argv[-1].split('"')[1])
        for injected in (["--use-system-ca"], [index], ["--experimental-permission"], ["--require", "x.js"], [node]):
            with self.subTest(injected=injected), self.assertRaises(self.mod.CursorBoundaryError):
                self.mod.cursor_command("panel", injected + tail, exe=self.launcher, runtime=rt, workspace=ws,
                                        staged=staged, expected_model="composer-2.5[fast=false]")

    def test_every_cursor_process_sees_the_clis_name_and_a_compile_cache_inside_its_runtime(self):
        self.setenv(CURSOR_INVOKED_AS="agent", NODE_COMPILE_CACHE="/private/var/poison-compile-cache")
        mod = self.fresh()
        ad = mod.CursorAgentAdapter()
        self.assertEqual(ad.auth_state(), "ready")
        st = self.dispatch(repo=self.repo(), adapter=ad)
        self.assertEqual(st["status"], "ok", st)
        with open(self.nodelog) as f:
            starts = [json.loads(line) for line in f]
        self.assertGreaterEqual(len(starts), 4)         # both preflight probes, status and the panel call
        node, index = os.path.realpath(self.build.node), os.path.realpath(self.build.index)
        for start in starts:
            self.assertEqual(start["argv"][:3], [node, "--use-system-ca", index])
            self.assertEqual(start["invoked_as"], "cursor-agent")                    # not the ambient value
            self.assertTrue(start["compile_cache"].endswith(os.path.join("runtime", "cache", "cursor-compile-cache")))
            self.assertNotIn("poison", start["compile_cache"])
        self.assertFalse(os.path.exists(self.build.marker))
        self.assertIn("CURSOR_INVOKED_AS", self.mod.CURSOR_ENV_ALLOW)
        self.assertNotIn("NODE_COMPILE_CACHE", self.mod.CURSOR_ENV_ALLOW)    # provided by the runtime, never inherited

    def test_the_verdict_is_reproved_when_the_runtime_or_entry_script_changes(self):
        mod = self.fresh()
        self.assertTrue(mod.cursor_boundary(self.launcher).ready)
        first = self.sandbox_calls()
        self.assertTrue(mod.cursor_boundary(self.launcher).ready)
        self.assertEqual(self.sandbox_calls(), first)                       # cached on the build's files
        with open(self.build.index, "a") as f:
            f.write("// changed\n")
        self.assertTrue(mod.cursor_boundary(self.launcher).ready)
        self.assertGreater(self.sandbox_calls(), first)                     # a changed entry script re-proves


class CursorExecAllowListTests(CursorCase):
    """A panel/Checker profile allows exactly three literal executables: the build's node, its
    bundled rg and /usr/bin/sw_vers. The OS-version tool stand in as fixtures
    here (a unit test never starts the real ones); the real gate asserts the real paths."""

    def fixture_tool(self, name, mode=0o755):
        path = os.path.join(self.tmp, "tools", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, mode)
        return path

    def not_ready(self, mod):
        b = mod.cursor_boundary(self.launcher)
        self.assertFalse(b.ready)
        return b.reason

    def test_the_boundary_reports_exactly_the_three_executables_and_the_profile_allows_them(self):
        b = self.mod.cursor_boundary(self.launcher)
        self.assertTrue(b.ready, b.reason)
        want = (os.path.realpath(self.build.node), os.path.realpath(self.build.rg)) + tuple(self.build.system)
        self.assertEqual((b.exe,) + tuple(b.execs), want)
        self.assertEqual(len(self.build.system), 1)
        self.assertEqual(self.mod.CURSOR_SYSTEM_EXEC, self.build.system)              # the patched constant
        pristine = _import_alloy_module()
        self.assertEqual(pristine.CURSOR_SYSTEM_EXEC, ("/usr/bin/sw_vers",))
        # the profile the CLI is started under (the preflight's panel start, then the gateway's)
        panel_cli = self.profiles()[1]
        self.assertIn("role=panel", panel_cli)
        self.assertEqual([l for l in panel_cli.splitlines() if "process-exec" in l],
                         ["(deny process-exec*)",
                          "(allow process-exec " + " ".join('(literal "%s")' % p for p in want) + ")"])
        for path in want:
            self.assertEqual(self.decision(panel_cli, "process-exec", path), "allow", path)
        for path in ("/bin/sh", "/bin/bash", "/usr/bin/open", "/usr/bin/log", "/usr/bin/env", "/usr/bin/true",
                     "/usr/bin/security", "/usr/bin/sw_vers", os.path.realpath(self.launcher)):
            self.assertEqual(self.decision(panel_cli, "process-exec", path), "deny", path)   # the real system paths are not the fixtures

    def test_a_bundled_rg_that_is_missing_writable_linked_or_not_executable_refuses_the_build(self):
        rg = self.build.rg
        kept = rg + ".kept"
        os.rename(rg, kept)
        try:
            with self.assertRaises(self.mod.CursorBoundaryError) as ctx:
                self.mod.cursor_resolve_build(self.launcher)
            self.assertIn("no bundled rg", str(ctx.exception))
            os.symlink(kept, rg)
            with self.assertRaises(self.mod.CursorBoundaryError) as ctx:
                self.mod.cursor_resolve_build(self.launcher)
            self.assertIn("not a regular file", str(ctx.exception))
        finally:
            if os.path.lexists(rg):
                os.remove(rg)
            os.rename(kept, rg)
        for mode, needle in ((0o775, "writable by group or other"), (0o757, "writable by group or other"),
                             (0o644, "not executable")):
            with self.subTest(mode=oct(mode)):
                os.chmod(rg, mode)
                try:
                    with self.assertRaises(self.mod.CursorBoundaryError) as ctx:
                        self.mod.cursor_resolve_build(self.launcher)
                    self.assertIn(needle, str(ctx.exception))
                    mod = self.fresh()
                    self.assertIn(needle, self.not_ready(mod))
                    self.assertEqual(self.sandbox_calls(), 0)
                finally:
                    os.chmod(rg, 0o755)
        with self.mock.patch.object(self.mod.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(self.mod.CursorBoundaryError) as ctx:
                self.mod.cursor_resolve_build(self.launcher)
            self.assertIn("not owned by the current user", str(ctx.exception))
        self.assertEqual(self.mod.cursor_resolve_build(self.launcher).rg, os.path.realpath(self.build.rg))

    def test_the_system_tools_are_verified_like_sandbox_exec_before_anything_starts(self):
        good_sw_vers, = self.build.system
        link = os.path.join(self.tmp, "tools", "linked-sw-vers")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(good_sw_vers, link)
        directory = os.path.join(self.tmp, "tools", "a-directory")
        os.makedirs(directory)
        cases = (("missing", os.path.join(self.tmp, "tools", "no-such-tool"), "is missing"),
                 ("symlink", link, "not a regular, non-symlink file"),
                 ("directory", directory, "not a regular, non-symlink file"),
                 ("group-writable", self.fixture_tool("gw", 0o775), "writable by group or other"),
                 ("world-writable", self.fixture_tool("ww", 0o757), "writable by group or other"),
                 ("not executable", self.fixture_tool("nx", 0o644), "not executable"))
        for label, bad, needle in cases:
            for position in (0,):                       # the OS-version tool is verified
                with self.subTest(case=label, position=position):
                    tools = [good_sw_vers]
                    tools[position] = bad
                    mod = self.mod = self.fresh()
                    with self.mock.patch.object(mod, "CURSOR_SYSTEM_EXEC", tuple(tools)):
                        reason = self.not_ready(mod)
                        self.assertIn(needle, reason)
                        ad = mod.CursorAgentAdapter()
                        self.assertFalse(ad.cursor_boundary_ready)
                        self.assertEqual(ad.auth_state(), "sandbox_unavailable")
                        self.assertEqual(self.dispatch(repo=self.repo("r-%s-%d" % (label, position)), adapter=ad,
                                                 name="d-%s-%d" % (label, position))["status"], "error")
                    self.assertEqual(self.sandbox_calls(), 0)             # no profile was ever run
                    self.assertEqual(self.all_cursor_calls(), [])
        # owned by someone other than the trusted user (root in production)
        mod = self.fresh()
        with self.mock.patch.object(mod, "SANDBOX_TRUSTED_UID", os.getuid() + 1):
            self.assertIn("not owned by the trusted user", self.not_ready(mod))
        self.assertEqual(self.sandbox_calls(), 0)
        # and a good pair is accepted
        self.assertTrue(self.fresh().cursor_boundary(self.launcher).ready)

    def test_a_denial_that_covers_a_system_tool_makes_cursor_refuse_instead_of_dropping_it(self):
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=self.build.system[0])
        self.assertIn("requires", self.not_ready(self.fresh()))

    def test_the_verdict_is_reproved_when_a_system_tool_changes(self):
        mod = self.fresh()
        self.assertTrue(mod.cursor_boundary(self.launcher).ready)
        first = self.sandbox_calls()
        self.assertTrue(mod.cursor_boundary(self.launcher).ready)
        self.assertEqual(self.sandbox_calls(), first)
        with open(self.build.system[0], "a") as f:
            f.write("# changed\n")
        self.assertTrue(mod.cursor_boundary(self.launcher).ready)
        self.assertGreater(self.sandbox_calls(), first)

    def test_alloy_itself_never_runs_security_or_any_system_tool(self):
        spawned = []
        real = subprocess.Popen

        def spy(argv, *a, **k):
            spawned.append(list(argv))
            return real(argv, *a, **k)
        with self.mock.patch.object(self.mod.subprocess, "Popen", spy):
            ad = self.mod.CursorAgentAdapter()
            self.assertEqual(ad.auth_state(), "ready")
            self.dispatch(repo=self.repo(), adapter=ad)
        names = {os.path.basename(a) for argv in spawned for a in argv if isinstance(a, str)}
        for tool in ("security", "sw_vers", "rg", "sh", "open", "log"):
            self.assertNotIn(tool, names, tool)
        self.assertFalse(any(a in self.build.system for argv in spawned for a in argv))


class CursorProfileTests(CursorCase):
    def test_every_profile_allows_only_the_file_login_refresh_and_denies_keychains(self):
        home = os.path.join(self.tmp, "login-home")
        os.makedirs(os.path.join(home, ".cursor"))
        rt = self.runtime()
        den = self.mod.cursor_denials(home=home)
        auth_dir = os.path.join(home, ".cursor")
        auth = os.path.join(auth_dir, "auth.json")
        for role in ("panel", "maker"):
            with self.subTest(role=role), self.mock.patch.object(self.mod, "cursor_login_home", return_value=home):
                prof = self.mod.cursor_sbpl(role, exe=self.build.node, runtime=rt, denials=den,
                                            worktree=os.path.join(self.tmp, "owned-wt") if role == "maker" else None)
                for op in ("file-read-data", "file-write-data", "file-write-create", "file-write-mode"):
                    self.assertEqual(self.decision(prof, op, auth), "allow", op)
                self.assertEqual(self.decision(prof, "file-write-mode", auth_dir), "allow")
                for path in (auth_dir, auth + ".tmp", auth_dir + "/settings.json", auth + "/child"):
                    self.assertEqual(self.decision(prof, "file-write-data", path), "deny", path)
                keychain = os.path.join(home, "Library", "Keychains", "login.keychain-db")
                for op in ("file-read-data", "file-read-metadata"):
                    self.assertEqual(self.decision(prof, op, keychain), "deny", op)
                self.assertEqual(self.decision(prof, "process-exec", "/usr/bin/security"), "deny")
                for service in ("com.apple.SecurityServer", "com.apple.securityd.xpc"):
                    self.assertEqual(self.decision(prof, "mach-lookup", service), "deny")
        # A link must never turn a credential write grant into access to another path.
        target = os.path.join(self.tmp, "elsewhere")
        with open(target, "w") as handle:
            handle.write("untouched")
        os.symlink(target, auth)
        with self.mock.patch.object(self.mod, "cursor_login_home", return_value=home):
            with self.assertRaisesRegex(self.mod.CursorBoundaryError, "credential file is a symlink"):
                self.mod.cursor_sbpl("panel", exe=self.build.node, runtime=rt, denials=den)
        os.unlink(auth)
        os.link(target, auth)
        os.chmod(target, 0o600)
        with self.mock.patch.object(self.mod, "cursor_login_home", return_value=home):
            with self.assertRaisesRegex(self.mod.CursorBoundaryError, "no hard links"):
                self.mod.cursor_sbpl("panel", exe=self.build.node, runtime=rt, denials=den)
        os.unlink(auth)
        os.rmdir(auth_dir)
        os.symlink(self.tmp, auth_dir)
        with self.mock.patch.object(self.mod, "cursor_login_home", return_value=home):
            with self.assertRaisesRegex(self.mod.CursorBoundaryError, "credential directory is a symlink"):
                self.mod.cursor_sbpl("panel", exe=self.build.node, runtime=rt, denials=den)

    def test_panel_profile_allows_only_the_private_runtime(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        rt = self.runtime()
        argv, prof, _ = self.gateway("panel", wt, rt)
        home = self.mod.cursor_login_home()
        d = lambda op, path: self.decision(prof, op, path)
        self.assertEqual(argv[:3], [MOCK, "-f", rt.profile])
        # the build's own node, started directly with the CLI's fixed prefix: never the bash launcher
        self.assertEqual(argv[3:6], [os.path.realpath(self.build.node), "--use-system-ca",
                                     os.path.realpath(self.build.index)])
        for base in (rt.state, rt.cache, rt.tmp):
            self.assertEqual(d("file-write-create", base + "/x"), "allow", base)
            self.assertEqual(d("file-write-data", base + "/a/b"), "allow", base)
        self.assertEqual(d("file-write-data", "/dev/null"), "allow")
        denied = [wt + "/tracked.txt", wt + "/new.txt", wt + "/.git", repo + "/x", repo + "/.git/config",
                  home + "/x", home + "/.cursor/x", home + "/.local/share/cursor-agent/versions/x",
                  home + "/Library/Caches/x", home + "/.config/x", os.path.dirname(MOCK) + "/x",
                  self.build.dir + "/x", self.build.dir + "/.running/x", self.build.dir + "/index.js",
                  os.path.join(self.tmp, "runs", "x"), rt.root + "/x", rt.root + "/runtime/x", rt.root + "/profile.sb",
                  rt.canary + "/canary.txt", rt.canary_outside + "/canary.txt", tempfile.gettempdir() + "/x",
                  "/tmp/x", "/private/tmp/x", "/etc/x", "/usr/local/x"]
        for path in denied:
            for op in ("file-write-create", "file-write-data", "file-write-unlink"):
                self.assertEqual(d(op, path), "deny", (op, path))
        # Git metadata: the pointer file, the worktree gitdir and the common dir
        gitdir = os.path.join(repo, ".git", "worktrees", os.path.basename(wt))
        for path in (wt + "/.git", gitdir + "/HEAD", gitdir + "/hooks/x", repo + "/.git/hooks/x", repo + "/.git/config"):
            self.assertEqual(d("file-write-create", path), "deny", path)
        self.assertEqual(d("file-link", rt.tmp + "/link"), "deny")          # even into a writable root
        self.assertEqual(d("file-link", wt + "/link"), "deny")
        # Process execution is denied except exactly three literal paths: the build's own node, its
        # bundled rg and sw_vers (a fixture stands in for the OS-version tool here; the real
        # gate asserts /usr/bin/sw_vers). One allow rule, in this order. Not the
        # launcher, not the entry script, no shell, no open, no log, no coreutils.
        allowed = [os.path.realpath(self.build.node), os.path.realpath(self.build.rg)] + list(self.build.system)
        for path in allowed:
            self.assertEqual(d("process-exec", path), "allow", path)
        exec_rules = [line for line in prof.splitlines() if line.startswith("(allow process-exec")]
        self.assertEqual(exec_rules, ["(allow process-exec " + " ".join('(literal "%s")' % p for p in allowed) + ")"])
        self.assertEqual([line for line in prof.splitlines() if "process-exec" in line],
                         ["(deny process-exec*)"] + exec_rules)
        for tool in (self.launcher, self.build.index, "/usr/bin/true", "/bin/bash", "/bin/sh", "/usr/bin/env",
                     "/usr/bin/git", "/usr/bin/open", "/usr/bin/log", "/usr/bin/security", "/usr/bin/sw_vers",
                     "/usr/bin/basename", "/usr/bin/dirname", "/bin/realpath", "/usr/bin/realpath",
                     "/usr/bin/rg", self.build.dir + "/spawn-helper", self.build.dir + "/cursorsandbox"):
            self.assertEqual(d("process-exec", tool), "deny", tool)     # the fixture tools are not the real ones
        self.assertEqual(d("file-read-data", wt + "/tracked.txt"), "allow")      # reads of the repo stay possible
        self.assertEqual(d("file-read-data", self.build.node), "allow")
        self.assertEqual(d("file-read-data", self.build.index), "allow")
        self.assertEqual(d("network-outbound", "api2.cursor.sh:443"), "allow")  # the provider network is needed
        # ... but a path is a Unix-domain socket, and only the resolver's is reachable
        self.assertEqual(d("network-outbound", "/x"), "deny")
        self.assertEqual(d("network-outbound", "/private/var/run/mDNSResponder"), "allow")

    def test_maker_profile_allows_only_non_git_worktree_content_and_runtime(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        sibling = make_worktree(repo, os.path.join(self.tmp, "sibling"))
        rt = self.runtime()
        _argv, prof, _ = self.gateway("maker", wt, rt)
        home = self.mod.cursor_login_home()
        d = lambda op, path: self.decision(prof, op, path)
        for path in (wt + "/src/new.py", wt + "/tracked.txt", wt + "/ignored.txt", wt + "/.gitignore",
                     wt + "/.gitattributes", rt.state + "/x", rt.cache + "/x", rt.tmp + "/x"):
            self.assertEqual(d("file-write-create", path), "allow", path)
            self.assertEqual(d("file-write-unlink", path), "allow", path)
        gitdir = os.path.join(repo, ".git", "worktrees", os.path.basename(wt))
        for path in (wt + "/.git", gitdir + "/HEAD", gitdir + "/index", gitdir + "/commondir", gitdir + "/hooks/pre-commit",
                     repo + "/.git/config", repo + "/.git/hooks/x", repo + "/.git/refs/heads/x", repo + "/.git/objects/x",
                     repo + "/tracked.txt", sibling + "/tracked.txt", sibling + "/.git", home + "/x", home + "/.cursor/x",
                     home + "/.local/share/cursor-agent/x", home + "/Library/Caches/x", rt.root + "/profile.sb",
                     rt.canary + "/canary.txt", "/tmp/x", tempfile.gettempdir() + "/x"):
            self.assertEqual(d("file-write-create", path), "deny", path)
        self.assertEqual(d("file-link", wt + "/link"), "deny")
        self.assertEqual(d("file-link", rt.tmp + "/link"), "deny")
        self.assertEqual(d("process-exec", "/usr/bin/true"), "allow")       # repository commands run
        self.assertEqual(d("process-exec", "/bin/bash"), "allow")
        self.assertIn('(deny process-exec (literal "/usr/bin/security"))', prof)
        self.assertEqual(d("process-exec", "/usr/bin/security"), "deny")
        # A Maker allows the three executables a panel/Checker is limited to (it allows everything)
        for path in [os.path.realpath(self.build.node), os.path.realpath(self.build.rg), *self.build.system,
                     "/usr/bin/sw_vers"]:
            self.assertEqual(d("process-exec", path), "allow", path)
        # The Git denials come after the broader worktree grant, or they would not win.
        lines = prof.splitlines()
        grant = next(i for i, l in enumerate(lines) if l.startswith("(allow file-write*") and wt in l)
        gitdeny = next(i for i, l in enumerate(lines) if l.startswith("(deny file-write*") and "/.git" in l)
        self.assertGreater(gitdeny, grant)

    def test_both_profiles_deny_unsandboxed_write_delegation_channels(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        for role, workspace in (("panel", repo), ("maker", wt)):
            with self.subTest(role=role):
                _argv, profile, _tail = self.gateway(role, workspace)
                for operation in ("job-creation", "lsopen", "appleevent-send",
                                  "user-preference-write"):
                    self.assertIn("(deny %s)" % operation, profile)
                    self.assertEqual(self.decision(profile, operation, ""), "deny")

    def test_both_profiles_deny_local_ipc_relays_and_other_process_access(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        home = self.mod.cursor_login_home()
        for role, workspace in (("panel", repo), ("maker", wt)):
            with self.subTest(role=role):
                rt = self.runtime()
                _argv, prof, _tail = self.gateway(role, workspace, rt)
                d = lambda op, path=None, target=None: self.decision(prof, op, path, target)
                # Unix-domain sockets: tmux, Docker (both spellings), an ssh agent, an IDE's
                # command-line hook and sockets inside the writable roots are unreachable ...
                for sock in ("/private/tmp/tmux-501/default", "/private/var/run/docker.sock",
                             home + "/.docker/run/docker.sock", "/private/tmp/com.apple.launchd.AbC/Listeners",
                             "/private/var/folders/xx/T/vscode-ipc-1.sock", workspace + "/dev.sock",
                             rt.tmp + "/agent.sock", "/private/var/run/mDNSResponder2"):
                    self.assertEqual(d("network-outbound", sock), "deny", sock)
                    self.assertEqual(d("network-bind", sock), "deny", sock)
                # ... except the one resolver socket name resolution needs, and only to connect
                self.assertEqual(d("network-outbound", "/private/var/run/mDNSResponder"), "allow")
                self.assertEqual(d("network-bind", "/private/var/run/mDNSResponder"), "deny")
                # the provider network (TCP/UDP endpoints are not paths) is untouched
                for endpoint in ("api2.cursor.sh:443", "127.0.0.1:8080", "[::1]:8080"):
                    self.assertEqual(d("network-outbound", endpoint), "allow", endpoint)
                self.assertEqual(d("network-bind", "127.0.0.1:0"), "allow")
                lines = prof.splitlines()
                self.assertEqual([l for l in lines if l.startswith("(allow network")],
                                 ['(allow network-outbound (literal "/private/var/run/mDNSResponder"))'])
                # inspecting or reading the task port of any process but itself and its children
                for op in ("process-info-pidinfo", "process-info-rusage", "process-info-setcontrol"):
                    self.assertEqual(d(op, target="others"), "deny", op)
                    self.assertEqual(d(op, target="self"), "allow", op)
                    self.assertEqual(d(op, target="children"), "allow", op)
                self.assertEqual(d("process-info-listpids"), "deny")
                self.assertEqual(d("process-info-codesignature"), "allow")
                self.assertEqual(d("mach-task-read", target="others"), "deny")
                self.assertEqual(d("mach-task-read", target="self"), "allow")
                # Mach services that act for a caller outside its sandbox: every lookup is
                # denied unless it is on the exact allowlist. TLS and name resolution stay
                # reachable; file credentials are used and keychain services stay denied.
                # An UNLISTED service is unreachable too.
                for service in self.mod.CURSOR_MACH_RELAY_SERVICES:
                    self.assertEqual(d("mach-lookup", service), "deny", service)
                for service in ("com.apple.trustd", "com.apple.system.opendirectoryd.libinfo"):
                    self.assertEqual(d("mach-lookup", service), "allow", service)
                for service in self.mod.CURSOR_MACH_ALLOW:
                    self.assertEqual(d("mach-lookup", service), "allow", service)
                for unlisted in ("com.apple.SecurityServer", "com.apple.securityd.xpc", "com.example.relay", "com.apple.some.unlisted.service", "org.tmux.relay",
                                 "com.docker.socket", "com.apple.coreservices.uiagent",
                                 "com.apple.SecurityServer.extra", "com.apple.trustd2", ""):
                    self.assertEqual(d("mach-lookup", unlisted), "deny", unlisted)
                # ordering: all of it precedes the write rules, so no role grant can undo it
                first_write = next(i for i, l in enumerate(lines) if l.startswith("(deny file-write*)"))
                for needle in ("(deny network-outbound", "(deny network-bind", "(deny process-info*)",
                               "(deny mach-task-read", "(deny mach-lookup"):
                    self.assertLess(next(i for i, l in enumerate(lines) if l.startswith(needle)), first_write, needle)
                self.assertLess(lines.index("(deny mach-lookup)"),
                                next(i for i, l in enumerate(lines) if l.startswith("(allow mach-lookup")))

    def test_the_mach_lookup_allowlist_is_exact_default_deny_and_never_holds_a_relay(self):
        m = self.mod
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        # the constants: no relay is allowed, the probe's control name is allowed, no duplicates
        self.assertEqual(set(m.CURSOR_MACH_ALLOW) & set(m.CURSOR_MACH_RELAY_SERVICES), set())
        self.assertIn(m.CURSOR_MACH_PROBE_ALLOWED, m.CURSOR_MACH_ALLOW)
        self.assertEqual(len(set(m.CURSOR_MACH_ALLOW)), len(m.CURSOR_MACH_ALLOW))
        self.assertTrue(m.CURSOR_MACH_RELAY_SERVICES)
        for role, workspace in (("panel", repo), ("maker", wt)):
            with self.subTest(role=role):
                _argv, profile, _tail = self.gateway(role, workspace)
                mach = [l for l in profile.splitlines() if "mach-lookup" in l]
                # exactly two rules: a filterless deny, then the allow of exact global names
                self.assertEqual(len(mach), 2, mach)
                self.assertEqual(mach[0], "(deny mach-lookup)")
                self.assertEqual(mach[1], "(allow mach-lookup " + " ".join(
                    '(global-name "%s")' % n for n in m.CURSOR_MACH_ALLOW) + ")")
                # no bare/regex/prefix allow that would reopen the gap, and no deny-list of relays
                self.assertNotIn("(allow mach-lookup)", profile)
                self.assertNotIn("global-name-prefix", profile)
                self.assertNotIn("global-name-regex", profile)
                self.assertNotIn("xpc-service-name", profile)
                self.assertNotRegex(profile, r"\(deny mach-lookup \(")
                for relay in m.CURSOR_MACH_RELAY_SERVICES:
                    self.assertNotIn('"%s"' % relay, profile, relay)
        # a name that could break out of the SBPL literal is refused, not escaped
        for bad in ('x") (allow mach-lookup', "a b", "", "a\nb", "com.apple.x\\"):
            with self.subTest(name=bad), self.mock.patch.object(m, "CURSOR_MACH_ALLOW", m.CURSOR_MACH_ALLOW + (bad,)):
                with self.assertRaises(m.CursorBoundaryError):
                    self.gateway("panel", repo)

    def test_the_mock_evaluator_models_target_and_path_filters_faithfully(self):
        # A parser that dropped a filter it did not understand would turn `(allow ... (target
        # self))` into an unconditional allow and make every check above pass vacuously.
        prof = "\n".join(["(version 1)", "(deny process-info*)",
                          "(allow process-info* (target self) (target children))",
                          '(deny network-outbound (subpath "/"))',
                          '(allow network-outbound (literal "/r"))',
                          '(deny mach-lookup (global-name "svc.a") (global-name "svc.b"))'])
        d = self.decision
        self.assertEqual(d(prof, "process-info-pidinfo", target="others"), "deny")
        self.assertEqual(d(prof, "process-info-pidinfo", target="self"), "allow")
        self.assertEqual(d(prof, "process-info-pidinfo"), "deny")             # no target: not a self/child rule
        self.assertEqual(d(prof, "network-outbound", "/x"), "deny")
        self.assertEqual(d(prof, "network-outbound", "/r"), "allow")
        self.assertEqual(d(prof, "network-outbound", "host:1"), "deny")       # no allow-default in this snippet
        self.assertEqual(d("(version 1)\n(allow default)\n" + "\n".join(prof.splitlines()[1:]),
                           "network-outbound", "host:1"), "allow")
        # (evaluator semantics only: a filtered deny leaves other names to the default. The
        # production profile is default-deny for Mach lookups; see the allowlist tests.)
        self.assertEqual(d("(version 1)\n(allow default)\n" + prof.splitlines()[-1], "mach-lookup", "svc.b"), "deny")
        self.assertEqual(d("(version 1)\n(allow default)\n" + prof.splitlines()[-1], "mach-lookup", "svc.c"), "allow")
        # the allowlist shape: a filterless deny, then an allow of exact names; later wins
        allow = "\n".join(["(version 1)", "(allow default)", "(deny mach-lookup)",
                           '(allow mach-lookup (global-name "svc.a") (global-name "svc.b"))'])
        self.assertEqual(d(allow, "mach-lookup", "svc.a"), "allow")
        self.assertEqual(d(allow, "mach-lookup", "svc.b"), "allow")
        self.assertEqual(d(allow, "mach-lookup", "svc.c"), "deny")               # unlisted
        self.assertEqual(d(allow, "mach-lookup", "svc.a.sub"), "deny")           # exact, not a prefix
        self.assertEqual(d(allow, "mach-lookup", "svc"), "deny")
        self.assertEqual(d(allow, "mach-lookup"), "deny")                        # no name: not an allowed one
        self.assertEqual(d(allow, "network-outbound", "host:1"), "allow")        # other operations unaffected
        reversed_order = "\n".join(["(version 1)", "(allow default)",
                                    '(allow mach-lookup (global-name "svc.a"))', "(deny mach-lookup)"])
        self.assertEqual(d(reversed_order, "mach-lookup", "svc.a"), "deny")      # order is what makes it work

    def test_maker_refuses_plain_dirs_and_subdirectories(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        os.makedirs(os.path.join(wt, "sub"))
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        for target in (plain, os.path.join(wt, "sub")):
            with self.subTest(target=target), self.assertRaises(self.mod.CursorBoundaryError):
                self.gateway("maker", target)

    def test_profile_ordering_puts_denials_last(self):
        repo = self.repo()
        _a, prof, _ = self.gateway("panel", repo)
        lines = [l for l in prof.splitlines() if l.startswith("(")]
        first_read_deny = next(i for i, l in enumerate(lines) if l.startswith("(deny file-read*"))
        self.assertTrue(all(l.startswith("(deny file-read*") for l in lines[first_read_deny:]))
        self.assertEqual(lines[first_read_deny - 1], "(deny file-link)")
        last_grant = max(i for i, l in enumerate(lines) if l.startswith("(allow file-write"))
        self.assertLess(last_grant, first_read_deny)
        self.assertEqual(lines[1], "(allow default)")

    def test_every_builtin_sensitive_read_is_denied_in_every_role_and_discovery(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        home = self.mod.cursor_login_home()
        seen = []
        for role, target in (("panel", repo), ("maker", wt)):
            _a, prof, _ = self.gateway(role, target)
            seen.append(prof)
        rt = self.runtime()
        for kind in ("status", "version", "help", "models"):      # discovery/metadata use the panel profile
            self.mod.cursor_command(kind, self.mod._CURSOR_METADATA[kind], exe=self.launcher, runtime=rt)
            with open(rt.profile) as f:
                seen.append(f.read())
        self.assertEqual(len(seen), 6)
        for prof in seen:
            for rel in BUILTIN_DENIALS:
                for op in ("file-read-data", "file-read-metadata"):
                    self.assertEqual(self.decision(prof, op, os.path.join(home, rel)), "deny", rel)
                    self.assertEqual(self.decision(prof, op, os.path.join(home, rel, "child", "x")), "deny", rel)
            self.assertEqual(self.decision(prof, "file-read-data", home + "/Library/Group Containers/2BUA8C4S2C.com.1password.x/y"), "deny")
            self.assertEqual(self.decision(prof, "file-read-data", home + "/Library/Group Containers/group.com.other/y"), "allow")
            # Secret-staging places: anything DIRECTLY under the shared temp roots whose name
            # contains "secret" (any case), and everything beneath it -- a pattern, because
            # ALLOY_CURSOR_DENY_READ_PATHS refuses globs.
            for root in ("/private/tmp", "/tmp"):
                for name in ("my-secrets", "tool-secret.abc123", "SECRETS", "db_Secret.txt", "secret", "x-SeCrEt-y"):
                    for op in ("file-read-data", "file-read-metadata"):
                        self.assertEqual(self.decision(prof, op, "%s/%s" % (root, name)), "deny", (root, name))
                    self.assertEqual(self.decision(prof, "file-read-data", "%s/%s/child/x" % (root, name)), "deny")
                for name in ("other", "secre", "sec/ret", "x/secret", "x/y-secrets/z", "se-cret", "secrecy"):
                    self.assertEqual(self.decision(prof, "file-read-data", "%s/%s" % (root, name)), "allow", (root, name))
            self.assertEqual(self.decision(prof, "file-read-data", "/private/tmp2/secret"), "allow")
            self.assertEqual(self.decision(prof, "file-read-data", "/private/tmpsecret"), "allow")
            self.assertEqual(self.decision(prof, "file-read-data", "/private/var/secret"), "allow")
            # Public repository: no operator-specific path is named in the built-in profile.
            self.assertNotIn("exampletool", prof.lower())
            self.assertNotIn("exampleops", prof.lower())
            # Alloy's own secrets root and the future `alloy secrets` store
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "routing", "jev-key")), "deny")
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "state", "alloy", "secrets", "k")), "deny")
            # ... while the run state Cursor must read (staged prompt, worktrees) stays readable
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "state", "alloy", "runs", "x")), "allow")
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "state", "alloy", "execution", "worktrees", "x")), "allow")

    def test_operator_specific_paths_are_not_built_in_and_operators_add_their_own(self):
        with open(ALLOY, encoding="utf-8") as f:
            src = f.read().lower()
        for name in ("exampletool", "exampleops"):
            self.assertNotIn(name, src)
        self.assertNotIn(".exampletool/secrets", self.mod._CURSOR_HOME_DENIALS)
        home = self.mod.cursor_login_home()
        private = os.path.join(home, ".exampletool", "secrets")
        repo = self.repo()
        _a, prof, _ = self.gateway("panel", repo)
        self.assertEqual(self.decision(prof, "file-read-data", private), "allow")     # not built in
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=private)                              # the operator's own
        _a, prof, _ = self.gateway("panel", repo)
        for path in (private, os.path.join(private, "k")):
            self.assertEqual(self.decision(prof, "file-read-data", path), "deny")
        with self.assertRaises(self.mod.CursorBoundaryError):                          # globs stay refused
            self.mod.cursor_denials(extra="/private/tmp/tool-secret.*")

    def test_configured_denials_are_additive_and_cannot_remove_builtins(self):
        extra = os.path.join(self.tmp, "extra-denied")
        os.makedirs(extra)
        later = os.path.join(self.tmp, "created-later")
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS="%s, %s" % (extra, later))
        _a, prof, _ = self.gateway("panel", self.repo())
        home = self.mod.cursor_login_home()
        for path in (extra, extra + "/sentinel", later, later + "/x/y"):     # a missing path stays denied
            self.assertEqual(self.decision(prof, "file-read-data", path), "deny", path)
        self.assertEqual(self.decision(prof, "file-read-data", home + "/.ssh/id_ed25519"), "deny")
        self.assertIn(extra, self.mod.cursor_denials(home=home, extra=extra).paths)

    def test_denials_are_read_from_the_config_file_too(self):
        extra = os.path.join(self.tmp, "config-denied")
        with self.mock.patch.object(self.mod, "_CONFIG", {"ALLOY_CURSOR_DENY_READ_PATHS": extra}):
            _a, prof, _ = self.gateway("panel", self.repo())
        self.assertEqual(self.decision(prof, "file-read-data", extra + "/x"), "deny")

    def test_denial_that_covers_a_required_path_fails_closed(self):
        repo = self.repo()
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=self.tmp)                   # covers the repo, prompt and run dirs
        self.mod = self.fresh()
        st = self.dispatch(repo=repo)
        self.assertEqual(st["status"], "error")
        self.assertIn("requires", st["error"])
        self.assertEqual(self.inference_calls(), [])
        # built-ins are checked the same way: a repository under a denied credential dir
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=None)
        fake_home = os.path.join(self.tmp, "fake-home")
        inside = os.path.join(fake_home, ".ssh", "proj")
        os.makedirs(inside)
        with self.mock.patch.object(self.mod, "cursor_login_home", lambda: os.path.realpath(fake_home)):
            with self.assertRaises(self.mod.CursorBoundaryError):
                self.mod._check_overlap(self.mod.cursor_denials(), [os.path.realpath(inside)])

    def test_fingerprint_root_containing_a_denial_is_refused_before_any_walk(self):
        m = self.mod
        root = os.path.join(self.tmp, "fake-home")
        denied = os.path.join(root, "Library", "Keychains")
        os.makedirs(denied)
        denials = m.CursorDenials((denied,), ())
        with self.mock.patch.object(m, "cursor_git_locations",
                                    side_effect=AssertionError("must refuse before Git inspection")), \
                self.mock.patch.object(m, "_fp_walk",
                                       side_effect=AssertionError("must not walk denied roots")):
            with self.assertRaises(m.CursorBoundaryError):
                m.cursor_fingerprint(root, denials=denials)

    def test_denial_parsing_and_escaping(self):
        m = self.mod
        home = m.cursor_login_home()
        tricky = os.path.join(self.tmp, 'we"ird\\dir')
        self.assertEqual(m._sb_path(tricky), '"' + self.tmp + '/we\\"ird\\\\dir"')
        rt = self.runtime()
        prof = m.cursor_sbpl("panel", exe=self.build.node, runtime=rt, denials=m.CursorDenials((tricky,), ()))
        self.assertEqual(self.decision(prof, "file-read-data", tricky + "/f"), "deny")      # the literal round-trips
        self.assertEqual(self.decision(prof, "file-read-data", self.tmp + "/weird/f"), "allow")
        for bad in ("relative", "/a/../b", "/a/*", "/a/b/", "", "/x\ny", tricky):
            with self.subTest(bad=bad), self.assertRaises(m.CursorBoundaryError):
                m.cursor_denials(home=home, extra=bad)
        for path in ("relative", "/x\ny", "/x\x00y"):
            with self.subTest(sb=path), self.assertRaises(m.CursorBoundaryError):
                m._sb_path(path)

    def test_a_final_symlink_denial_covers_the_link_and_its_target(self):
        m = self.mod
        home = os.path.join(self.tmp, "fixture-home")
        os.makedirs(os.path.join(home, "dotfiles-ssh"))
        os.symlink(os.path.join(home, "dotfiles-ssh"), os.path.join(home, ".ssh"))
        with self.mock.patch.object(m, "cursor_login_home", lambda: home):
            den = m.cursor_denials()
            rt = self.runtime()
            prof = m.cursor_sbpl("panel", exe=self.build.node, runtime=rt, denials=den)
        self.assertEqual(self.decision(prof, "file-read-data", home + "/.ssh/id"), "deny")
        self.assertEqual(self.decision(prof, "file-read-data", home + "/dotfiles-ssh/id"), "deny")

    def test_login_home_comes_from_the_account_database(self):
        import pwd
        self.assertEqual(self.mod.cursor_login_home(), os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir))

    def test_missing_account_database_home_fails_without_expanduser_fallback(self):
        m = self.mod
        with self.mock.patch.object(m.pwd, "getpwuid", side_effect=KeyError("missing")), \
                self.mock.patch.object(m.os.path, "expanduser",
                                       side_effect=AssertionError("must not consult HOME")):
            with self.assertRaises(m.CursorBoundaryError):
                m.cursor_login_home()
            self.assertFalse(m.cursor_boundary(self.launcher).ready)

    def test_dispatch_records_a_refusal_when_login_home_disappears(self):
        m = self.mod
        ad = m.CursorAgentAdapter()
        self.assertTrue(ad.cursor_boundary_ready)
        before = len(self.inference_calls())
        with self.mock.patch.object(m.pwd, "getpwuid", side_effect=KeyError("missing")):
            st = self.dispatch(repo=self.repo(), adapter=ad)
        self.assertEqual(st["status"], "error")
        self.assertTrue(st["error"].startswith("refused: "), st)
        self.assertIn("account database", st["error"])
        self.assertEqual(len(self.inference_calls()), before)
        with open(os.path.join(self.tmp, "runs", "r", "cursor", "status.json")) as f:
            self.assertEqual(json.load(f)["error"], st["error"])

    def test_write_grants_refuse_symlinks_and_uncertain_paths(self):
        m = self.mod
        real = os.path.join(self.tmp, "real")
        os.makedirs(real)
        link = os.path.join(self.tmp, "linkdir")
        os.symlink(real, link)
        with self.assertRaises(m.CursorBoundaryError):
            m._canon_grant(link, "the workspace")
        with self.assertRaises(m.CursorBoundaryError):
            m._canon_grant("relative", "the workspace")
        self.assertEqual(m._canon_grant(real, "x"), real)
        rt = self.runtime()
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_sbpl("maker", exe=self.build.node, runtime=rt, denials=m.cursor_denials(), worktree=None)
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_sbpl("nonsense", exe=self.build.node, runtime=rt, denials=m.cursor_denials())

    def test_runtime_is_private_outside_every_repository_and_removed(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        st = self.dispatch(repo=wt)
        self.assertEqual(st["status"], "ok", st)
        call = self.inference_calls()[-1]
        state, cache, tmpdir = (call["env"][k] for k in ("XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"))
        root = os.path.dirname(os.path.dirname(tmpdir))
        self.assertEqual({os.path.basename(p) for p in (state, cache, tmpdir)}, {"state", "cache", "tmp"})
        self.assertTrue(os.path.basename(root).startswith("alloy-cursor-"))
        for protected in (repo, wt, self.tmp, os.path.join(self.tmp, "runs")):
            self.assertFalse(root.startswith(protected.rstrip("/") + "/"), protected)
        self.assertFalse(os.path.exists(root))                       # removed once the group is dead
        self.assertEqual(call["env"]["HOME"], self.mod.cursor_login_home())
        rt = self.runtime()
        self.assertEqual(os.stat(rt.root).st_mode & 0o777, 0o700)
        for d in (rt.state, rt.cache, rt.tmp):
            self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        self.assertIsNone(self.mod._git_toplevel(rt.tmp))

    def test_runtime_inside_a_repository_or_over_a_protected_path_is_refused(self):
        m = self.mod
        repo = self.repo()
        inside = os.path.join(repo, "tmpdir")
        os.makedirs(inside)
        with self.mock.patch.object(tempfile, "tempdir", inside):
            with self.assertRaises(m.CursorBoundaryError):
                m.cursor_make_runtime()
        self.assertEqual(os.listdir(inside), [])                      # nothing left behind
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_make_runtime(forbidden=[tempfile.gettempdir()])
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_make_runtime(forbidden=["/"])

    def test_runtime_always_protects_configured_and_default_run_roots(self):
        m = self.mod
        configured = os.path.join(self.tmp, "configured-runs")
        default = os.path.join(self.tmp, "state", "alloy", "runs")
        for run_root, configured_value in ((configured, configured), (default, None)):
            os.makedirs(run_root, exist_ok=True)
            self.setenv(ALLOY_RUN_ROOT=configured_value)
            with self.subTest(run_root=run_root), self.mock.patch.object(tempfile, "tempdir", run_root):
                with self.assertRaises(m.CursorBoundaryError):
                    m.cursor_make_runtime()
                self.assertEqual(os.listdir(run_root), [])

    def test_tmpdir_environment_cannot_place_runtime_beneath_the_run_root(self):
        m = self.mod
        run_root = os.path.join(self.tmp, "environment-runs")
        os.makedirs(run_root)
        self.setenv(ALLOY_RUN_ROOT=run_root)
        with self.mock.patch.dict(os.environ, {"TMPDIR": run_root}), \
                self.mock.patch.object(tempfile, "tempdir", None):
            with self.assertRaises(m.CursorBoundaryError):
                m.cursor_make_runtime()
        self.assertEqual(os.listdir(run_root), [])

    def test_explicit_cli_run_root_is_protected_during_preflight_and_dispatch(self):
        m = self.mod
        repo = self.repo()
        run_root = os.path.join(self.tmp, "argument-runs")
        os.makedirs(run_root)
        with self.mock.patch.object(tempfile, "tempdir", run_root):
            with self.assertRaises(m.CursorBoundaryError):
                m.cursor_make_runtime(run_root=run_root)
            with self.assertRaises(m.CursorBoundaryError):
                m.cursor_metadata("status", self.launcher, run_root=run_root)
            rc, out, _err = self.cli(
                "panel", "--prompt-file", self.prompt(), "--run-dir", run_root,
                "--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 3)
        with open(out.strip().splitlines()[-1]) as f:
            manifest = json.load(f)
        self.assertEqual(manifest["panelists"], [])
        self.assertIn("no supported OS write boundary",
                      manifest["summary"]["skipped"][0]["reason"])
        self.assertFalse([n for n in os.listdir(run_root) if n.startswith("alloy-cursor-")])

    def test_retry_pdir_is_protected_without_parent_depth_inference(self):
        m = self.mod
        run_root = os.path.join(self.tmp, "runs-root")
        retry = os.path.join(run_root, "stamp", "cursor", "_retry")
        os.makedirs(retry)
        with self.mock.patch.object(tempfile, "tempdir", retry):
            with self.assertRaises(m.CursorBoundaryError):
                m.cursor_make_runtime(pdir=retry)
        self.assertEqual(os.listdir(retry), [])

    def test_cleanup_uncertainty_turns_a_completed_dispatch_into_failure(self):
        m = self.mod
        ad = m.CursorAgentAdapter()
        self.assertTrue(ad.cursor_boundary_ready)       # warm preflight before intercepting dispatch cleanup
        real_run = m.subprocess.run
        retained = []

        def leave_private_tree(argv, *args, **kwargs):
            if isinstance(argv, list) and argv[:3] == ["rm", "-r", "--"]:
                retained.append(argv[-1])
                return __import__("subprocess").CompletedProcess(argv, 0, "", "")
            return real_run(argv, *args, **kwargs)

        try:
            with self.mock.patch.object(m.subprocess, "run", side_effect=leave_private_tree):
                st = self.dispatch(repo=self.repo(), adapter=ad)
            self.assertEqual(len(self.inference_calls()), 1)
            self.assertEqual(st["status"], "error")
            self.assertIn("cleanup could not be verified", st["error"])
            with open(os.path.join(self.tmp, "runs", "r", "cursor", "status.json")) as f:
                self.assertEqual(json.load(f)["status"], "error")
        finally:
            for path in set(retained):
                if os.path.lexists(path):
                    real_run(["rm", "-r", "--", path], check=True, capture_output=True)



class CursorGrammarTests(CursorCase):
    def good(self, role="panel", ws=None):
        ws = ws or os.path.join(self.tmp, "ws")
        os.makedirs(ws, exist_ok=True)
        staged = os.path.join(self.tmp, "prompt_in", "prompt.md")
        os.makedirs(os.path.dirname(staged), exist_ok=True)
        with open(staged, "w") as f:
            f.write("fixture")
        instr = self.mod.cursor_instruction(role, staged, os.path.realpath(ws))
        argv = ["-p"] + (["--mode", "ask"] if role == "panel" else []) + [
            "--output-format", "json", "--workspace", ws, "--model", "composer-2.5", "--trust",
            "--sandbox", "disabled", "--skip-worktree-setup", instr]
        return argv, ws, staged

    def check(self, role, argv, ws, staged):
        self.mod.cursor_validate_argv(role, argv, workspace=ws, staged=staged,
                                      expected_model="composer-2.5")

    def test_the_two_closed_role_grammars_accept_exactly_their_own_form(self):
        for role in ("panel", "maker"):
            argv, ws, staged = self.good(role)
            self.check(role, argv, ws, staged)
        argv, ws, staged = self.good("panel")
        with self.assertRaises(self.mod.CursorBoundaryError):
            self.check("maker", argv, ws, staged)
        argv, ws, staged = self.good("maker")
        with self.assertRaises(self.mod.CursorBoundaryError):
            self.check("panel", argv, ws, staged)

    def test_forbidden_and_unknown_controls_are_refused_for_both_roles(self):
        bad_tails = [
            ["--api-key", "SUPERSECRETVALUE"], ["--api-key=SUPERSECRETVALUE"], ["-eSUPERSECRETVALUE"],
            ["-HSUPERSECRETVALUE"], ["-e", "https://x.invalid"], ["-H", "X: y"], ["--endpoint", "https://x.invalid"],
            ["--endpoint=https://x.invalid"], ["--header", "Authorization: x"], ["--header=Authorization: x"],
            ["--force"], ["-f"], ["--yolo"], ["--auto-review"], ["--approve-mcps"], ["--plan"],
            ["--plugin-dir", "/x"], ["--add-dir", "/x"], ["--resume"], ["--resume", "abc"], ["--continue"],
            ["-w"], ["--worktree"], ["--worktree", "n"], ["--worktree-base", "main"], ["--effort", "high"],
            ["--stream-partial-output"], ["--mode", "plan"], ["--mode", "agent"], ["--mode", "ask"],
            ["--sandbox", "disabled"], ["--sandbox", "disabled"], ["--output-format", "text"],
            ["--output-format", "json"], ["--model", "auto"], ["--model", "gpt-5"], ["--model=gpt-5.6-sol-high"],
            ["--workspace", "/elsewhere"], ["--trust"], ["-p"], ["--skip-worktree-setup"],
            ["worker"], ["login"], ["status"], ["--list-models"], ["extra positional"], ["-pFOO"], ["--"],
        ]
        for role in ("panel", "maker"):
            for tail in bad_tails:
                argv, ws, staged = self.good(role)
                for mutated in (argv[:-1] + tail + argv[-1:], tail + argv):
                    with self.subTest(role=role, tail=tail):
                        with self.assertRaises(self.mod.CursorBoundaryError) as cm:
                            self.check(role, mutated, ws, staged)
                        self.assertNotIn("SUPERSECRETVALUE", str(cm.exception))
                        self.assertNotIn("x.invalid", str(cm.exception))

    def test_auth_endpoint_and_header_controls_are_named_in_every_spelling(self):
        forms = (["--api-key", "V"], ["--api-key=V"], ["-e", "V"], ["-eV"], ["-H", "V"], ["-HV"], ["--endpoint", "V"],
                 ["--endpoint=V"], ["--header", "V"], ["--header=V"])
        for role in ("panel", "maker"):
            for form in forms:
                argv, ws, staged = self.good(role)
                with self.subTest(role=role, form=form), self.assertRaises(self.mod.CursorBoundaryError) as cm:
                    self.check(role, argv[:-1] + form + argv[-1:], ws, staged)
                self.assertIn("authentication, endpoint and header controls are forbidden", str(cm.exception))

    def test_specific_structural_refusals(self):
        m = self.mod
        for role in ("panel", "maker"):
            argv, ws, staged = self.good(role)
            variants = {
                "missing model": [a for i, a in enumerate(argv) if not (a == "--model" or argv[i - 1] == "--model")],
                "missing sandbox": [a for i, a in enumerate(argv) if not (a == "--sandbox" or argv[i - 1] == "--sandbox")],
                "missing setup skip": [a for a in argv if a != "--skip-worktree-setup"],
                "missing trust": [a for a in argv if a != "--trust"],
                "missing print": [a for a in argv if a != "-p"],
                "missing instruction": argv[:-1],
                "flag as value": [("--force" if a == "composer-2.5" else a) for a in argv],
                "auto model": [("auto" if a == "composer-2.5" else a) for a in argv],
                "unknown model": [("muse-spark-1" if a == "composer-2.5" else a) for a in argv],
                "known model replacement": [("gpt-5.6-sol-high" if a == "composer-2.5" else a) for a in argv],
                "empty model": [("" if a == "composer-2.5" else a) for a in argv],
                "bracketed unknown": [("kimi-k3[effort=low]" if a == "composer-2.5" else a) for a in argv],
                "sandbox enabled": [("enabled" if a == "disabled" else a) for a in argv],
                "text output": [("text" if a == "json" else a) for a in argv],
                "task text on argv": argv[:-1] + [argv[-1] + " Also do this task: " + "x" * 3000],
                "other instruction": argv[:-1] + ["Please do the task described here."],
                "instruction other path": argv[:-1] + [argv[-1].replace("prompt.md", "other.md")],
                "instruction newline": argv[:-1] + [argv[-1] + "\nmore"],
                "duplicate model": argv[:-1] + ["--model", "composer-2.5", argv[-1]],
                "duplicate trust": argv[:-1] + ["--trust", argv[-1]],
                "duplicate skip": argv[:-1] + ["--skip-worktree-setup", argv[-1]],
                "positional before flag": [argv[-1]] + argv[:-1],
                "non-string": argv[:-1] + [5],
            }
            if role == "panel":
                variants["duplicate mode"] = argv[:-1] + ["--mode", "ask", argv[-1]]
                variants["no mode"] = [a for i, a in enumerate(argv) if not (a == "--mode" or argv[i - 1] == "--mode")]
            for name, mutated in variants.items():
                with self.subTest(role=role, case=name), self.assertRaises(m.CursorBoundaryError):
                    self.check(role, mutated, ws, staged)
        # the Maker instruction embeds the verified worktree: another path in it is refused
        argv, ws, staged = self.good("maker")
        with self.assertRaises(m.CursorBoundaryError):
            self.check("maker", argv[:-1] + [argv[-1].replace(json.dumps(os.path.realpath(ws)), json.dumps("/elsewhere"))], ws, staged)

    def test_workspace_staged_and_model_identity_are_exact(self):
        m = self.mod
        argv, ws, staged = self.good("panel")
        alias = os.path.join(self.tmp, "workspace-alias")
        os.symlink(ws, alias)
        aliased = list(argv)
        aliased[aliased.index("--workspace") + 1] = alias
        with self.assertRaises(m.CursorBoundaryError):
            self.check("panel", aliased, ws, staged)
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_validate_argv("panel", argv, workspace=ws, staged=None,
                                   expected_model="composer-2.5")
        for duplicate in ("composer-2.5[fast=false,fast=true]",
                          "composer-2.5[effort=low,effort=high]"):
            with self.subTest(model=duplicate), self.assertRaises(m.CursorBoundaryError):
                m.cursor_validate_model(duplicate)

    def test_exact_staged_file_denial_and_symlink_are_refused_before_spawn(self):
        m = self.mod
        repo = self.repo()
        rt = self.runtime()
        ad = m.CursorAgentAdapter()
        pdir = os.path.join(self.tmp, "staged-check")
        os.makedirs(pdir)
        ctx = {"repo": repo, "pdir": pdir, "cwd": repo, "scope": rt}
        tail = ad.build_args(self.prompt(), "", "consult", ctx)
        staged = ctx["cursor_staged"]
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=staged)
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_command("panel", tail, exe=self.launcher, runtime=rt, workspace=repo,
                             staged=staged, expected_model=ctx["cursor_expected_model"])
        target = os.path.join(self.tmp, "other-prompt")
        with open(target, "w") as f:
            f.write("x")
        os.remove(staged)
        os.symlink(target, staged)
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=None)
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_command("panel", tail, exe=self.launcher, runtime=rt, workspace=repo,
                             staged=staged, expected_model=ctx["cursor_expected_model"])

    def test_metadata_roles_have_exact_grammars(self):
        m = self.mod
        for role, tail in m._CURSOR_METADATA.items():
            m.cursor_validate_argv(role, list(tail))
            for bad in (tail + ["--force"], ["-p"] + tail, [], tail + tail, ["--api-key", "x"] + tail, ["-eX"], ["--model", "auto"]):
                with self.subTest(role=role, bad=bad), self.assertRaises(m.CursorBoundaryError):
                    m.cursor_validate_argv(role, bad)
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_validate_argv("status", ["--version"])
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_validate_argv("bogus", ["status"])

    def test_refused_argv_never_reaches_sandbox_exec(self):
        repo = self.repo()
        rt = self.runtime()
        argv, ws, staged = self.good("panel", ws=repo)
        self.assertTrue(self.mod.CursorAgentAdapter().cursor_boundary_ready)
        spawned = self.sandbox_calls()
        with self.assertRaises(self.mod.CursorBoundaryError):
            self.mod.cursor_command("panel", argv[:-1] + ["--force", argv[-1]], exe=self.launcher,
                                    runtime=rt, workspace=ws, staged=staged,
                                    expected_model="composer-2.5")
        self.assertFalse(os.path.exists(rt.profile))                  # no profile was even written
        self.assertEqual(self.sandbox_calls(), spawned)                # and nothing was spawned

    def test_rewrites_after_build_args_are_caught_at_the_final_spawn(self):
        """The gateway validates the argv AFTER routing/managed rewrites. These mimic
        routed_adapter (--effort), worker_adapter (mode/sandbox edits) and dispatch()."""
        repo = self.repo()
        self.assertTrue(self.mod.CursorAgentAdapter().cursor_boundary_ready)
        preflight_calls = self.sandbox_calls()

        def rewriter(edit):
            ad = self.mod.CursorAgentAdapter()
            original = ad.build_args
            ad.build_args = lambda *a, **k: edit(original(*a, **k))
            return ad

        def set_value(flag, value):
            def edit(argv):
                argv = list(argv)
                argv[argv.index(flag) + 1] = value
                return argv
            return edit
        edits = {
            "effort appended": lambda a: a[:-1] + ["--effort", "high", a[-1]],
            "mode edited": set_value("--mode", "accept-edits"),
            "mode plan": set_value("--mode", "plan"),
            "sandbox enabled": set_value("--sandbox", "enabled"),
            "model auto": set_value("--model", "auto"),
            "known model swapped": set_value("--model", "gpt-5.6-sol-high"),
            "force appended": lambda a: a[:-1] + ["--force", a[-1]],
            "yolo appended": lambda a: a + ["--yolo"],
            "endpoint appended": lambda a: a[:-1] + ["--endpoint=https://x.invalid", a[-1]],
            "header short": lambda a: a[:-1] + ["-HX-A: b", a[-1]],
            "api key": lambda a: a[:-1] + ["--api-key", "k", a[-1]],
            "plugin dir": lambda a: a[:-1] + ["--plugin-dir", "/x", a[-1]],
            "add dir": lambda a: a[:-1] + ["--add-dir", "/x", a[-1]],
            "resume": lambda a: a[:-1] + ["--resume", "abc", a[-1]],
            "worktree": lambda a: a[:-1] + ["--worktree", a[-1]],
            "subcommand": lambda a: ["worker"] + a,
            "workspace swapped": set_value("--workspace", "/"),
            "session id": lambda a: a[:-1] + ["--session-id", "x", a[-1]],
        }
        for name, edit in edits.items():
            with self.subTest(name):
                st = self.dispatch(repo=repo, adapter=rewriter(edit), name=name.replace(" ", "-"))
                self.assertEqual(st["status"], "error")
                self.assertTrue(st["error"].startswith("refused: "), st["error"])
                self.assertEqual(st["exit_code"], None)
        self.assertEqual(self.cursor_calls(), [])
        self.assertEqual(self.sandbox_calls(), preflight_calls)                # never reached sandbox-exec

    def test_poisoned_environment_and_config_never_reach_any_cursor_process(self):
        repo = self.repo()
        self.setenv(CURSOR_API_KEY="env-poison-not-a-secret", CURSOR_API_ENDPOINT="https://env-poison.invalid",
                    TYPESAFE_API_KEY="router-poison", OPENROUTER_API_KEY="router-poison-2")
        with self.mock.patch.object(self.mod, "_CONFIG", {"CURSOR_API_KEY": "cfg-poison-not-a-secret",
                                                          "CURSOR_API_ENDPOINT": "https://cfg-poison.invalid",
                                                          "OTHER_PROVIDER_TOKEN": "unrelated-config-secret"}):
            ad = self.mod.CursorAgentAdapter()
            self.assertEqual(ad.auth_state(), "ready")                  # status
            self.mod.cursor_metadata("version", self.launcher)               # version
            st = self.dispatch(repo=repo, adapter=ad)                   # panel
        self.assertEqual(st["status"], "ok", st)
        calls = self.all_cursor_calls()
        self.assertEqual({tuple(c["argv"][:1]) for c in calls if "--skip-worktree-setup" not in c["argv"]},
                         {("status",), ("--version",)})                    # status, version (preflight) ... and:
        self.assertEqual(len(self.inference_calls()), 1)                    # ... the panel call
        for call in calls:
            for name in ("CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY",
                         "OPENROUTER_API_KEY", "OTHER_PROVIDER_TOKEN"):
                self.assertIsNone(call["env"][name], (call["argv"][:1], name))
            joined = " ".join(call["argv"])
            for flag in ("--api-key", "--endpoint", "--header", "-e ", "-H ", "--force", "--yolo"):
                self.assertNotIn(flag, joined)
        blob = json.dumps(st)
        self.assertNotIn("poison", blob)
        with open(os.path.join(self.tmp, "runs", "r", "cursor", "status.json")) as f:
            self.assertNotIn("poison", f.read())
        for name in ("stdout.txt", "stderr.txt", "result.md"):
            with open(os.path.join(self.tmp, "runs", "r", "cursor", name)) as f:
                self.assertNotIn("poison", f.read())
        with open(self.sblog) as f:
            self.assertNotIn("poison", f.read())


class CursorEnvironmentTests(CursorCase):
    # Names an ambient shell exports that must never reach any Cursor process: IPC
    # hooks (each a route to an unsandboxed server), cloud/VCS/provider credentials,
    # code-injection knobs and a proxy URL that embeds a password.
    AMBIENT = {
        "SSH_AUTH_SOCK": "/private/tmp/agent.sock", "TMUX": "/private/tmp/tmux-501/default,1,0",
        "TMUX_PANE": "%1", "STY": "1234.pts-0", "DOCKER_HOST": "unix:///var/run/docker.sock",
        "VSCODE_IPC_HOOK_CLI": "/private/tmp/vscode-ipc.sock", "VSCODE_IPC_HOOK": "/private/tmp/vscode.sock",
        "AWS_ACCESS_KEY_ID": "poison-aws-id", "AWS_SECRET_ACCESS_KEY": "poison-aws-secret",
        "AWS_SESSION_TOKEN": "poison-aws-session", "AWS_PROFILE": "poison-profile",
        "GITHUB_TOKEN": "poison-github", "GH_TOKEN": "poison-gh", "OPENAI_API_KEY": "poison-openai",
        "ANTHROPIC_API_KEY": "poison-anthropic", "NPM_TOKEN": "poison-npm", "NODE_OPTIONS": "--require=/x.js",
        "HTTPS_PROXY": "http://user:poison-proxy-pass@proxy.invalid:3128",
    }
    KEPT = {"NO_PROXY": "localhost", "LC_ALL": "C", "TZ": "UTC"}

    def maker(self):
        ad = self.mod.CursorAgentAdapter()
        ad.__class__ = type("ManagedCursor", (self.mod.CursorAgentAdapter,), {"read_only": False})
        return ad

    def test_every_cursor_process_gets_only_allowlisted_environment(self):
        m = self.mod
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        self.setenv(**self.AMBIENT, **self.KEPT, AGENT_CLI_CREDENTIAL_STORE="default")
        ad = m.CursorAgentAdapter()
        self.assertEqual(ad.auth_state(), "ready")                          # status
        self.assertEqual(m.cursor_metadata("version", self.launcher)[0], 0)      # version (and the preflight's own launches)
        self.assertEqual(self.dispatch(repo=repo, adapter=ad)["status"], "ok")            # panel
        self.assertEqual(self.dispatch(repo=wt, adapter=self.maker(), managed=True,
                                       mode="make", name="mk")["status"], "ok")            # Maker
        calls = self.all_cursor_calls()
        self.assertEqual(len(calls), 6)         # preflight --version x2, status, metadata --version, panel, Maker
        with open(self.nodelog) as handle:
            node_calls = [json.loads(line) for line in handle]
        self.assertEqual(len(node_calls), len(calls))
        self.assertEqual(len({c["env"]["CURSOR_DATA_DIR"] for c in calls}), len(calls))
        for call in node_calls:
            self.assertEqual(call["credential_store"], "file")
        # what the private runtime provides (the CLI's name and its compile cache inside the runtime)
        runtime_names = {"HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR", "CURSOR_INVOKED_AS", "NODE_COMPILE_CACHE", "AGENT_CLI_CREDENTIAL_STORE", "CURSOR_DATA_DIR", "CURSOR_CONFIG_DIR"}
        # The mock runs under /usr/bin/python3, whose Xcode shim re-exports these itself (in the
        # test process too); they are not something Alloy passes, so they say nothing here.
        interpreter_shim = {"SDKROOT", "CPATH", "LIBRARY_PATH", "MANPATH"}
        ambient = {n for n in os.environ
                   if not (n in m.CURSOR_ENV_ALLOW or n.startswith(m.CURSOR_ENV_ALLOW_PREFIXES)
                           or n in runtime_names or n in interpreter_shim or n.startswith("__"))}
        self.assertTrue(set(self.AMBIENT) - {"HTTPS_PROXY"} <= ambient)
        for call in calls:
            names = set(call["env_names"])
            for name in ambient | {"HTTPS_PROXY"}:       # nothing outside the allowlist; a credentialed proxy URL is dropped
                self.assertNotIn(name, names, (call["argv"][:1], name))
            self.assertTrue({"PATH", "NO_PROXY", "LC_ALL", "TZ"} <= names, (call["argv"][:1], sorted(names)))
            self.assertTrue(runtime_names <= names)
            self.assertEqual(call["env"]["HOME"], m.cursor_login_home())
            self.assertEqual(call["env"]["CURSOR_DATA_DIR"], call["env"]["XDG_STATE_HOME"])
            self.assertEqual(call["env"]["CURSOR_CONFIG_DIR"], call["env"]["XDG_STATE_HOME"])
            self.assertFalse(os.path.exists(call["env"]["CURSOR_DATA_DIR"]))
            for name in ("CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
                self.assertNotIn(name, names)
        for call in calls[-2:]:                                              # panel and Maker: the private runtime only
            self.assertEqual(os.path.basename(call["env"]["TMPDIR"]), "tmp")

    def test_allowlist_is_explicit_and_proxy_credentials_are_never_forwarded(self):
        pristine = _import_alloy_module()               # production constants, no test patching
        self.assertEqual(pristine.CURSOR_ENV_ALLOW_PREFIXES, ("LC_",))
        banned = tuple(n for n in self.AMBIENT if n != "HTTPS_PROXY") + (
            "CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS", "AZURE_CLIENT_SECRET", "MOCK_BEHAVIOR", "HOME", "TMPDIR")
        for name in banned:
            self.assertNotIn(name, pristine.CURSOR_ENV_ALLOW, name)
        self.assertEqual(pristine.cursor_base_env({n: "x" for n in banned}), {})
        env = pristine.cursor_base_env({
            "PATH": "/usr/bin", "LC_ALL": "C", "LC_CTYPE": "UTF-8", "LANG": "C", "TERM": "xterm", "TZ": "UTC",
            "HTTPS_PROXY": "http://proxy.invalid:3128", "https_proxy": "https://user:secret@proxy.invalid",
            "ALL_PROXY": "socks5://:tokenonly@proxy.invalid", "NO_PROXY": "localhost,.internal",
            "SSL_CERT_FILE": "/etc/ssl/cert.pem", "LCX": "not-a-locale", "MOCK_X": "not-allowed-in-production",
            "PYTHONPATH": "/x", "DYLD_INSERT_LIBRARIES": "/x", "BAD": 5})
        self.assertEqual(env, {"PATH": "/usr/bin", "LC_ALL": "C", "LC_CTYPE": "UTF-8", "LANG": "C", "TERM": "xterm",
                               "TZ": "UTC", "HTTPS_PROXY": "http://proxy.invalid:3128",
                               "NO_PROXY": "localhost,.internal", "SSL_CERT_FILE": "/etc/ssl/cert.pem"})

    def test_dispatch_does_not_start_from_the_full_process_environment(self):
        self.setenv(**self.AMBIENT)
        st = self.dispatch(repo=self.repo())
        self.assertEqual(st["status"], "ok", st)
        call = self.inference_calls()[-1]
        self.assertTrue(set(call["env_names"]).isdisjoint(self.AMBIENT))
        self.assertNotIn("poison", json.dumps(st))


class CursorPromptTests(CursorCase):
    def test_huge_prompt_is_staged_privately_and_never_on_argv_stdin_or_status(self):
        repo = self.repo()
        marker = "TASKTEXT-9f3c1a-"
        text = (marker + "x" * 1000 + "\n") * 3000        # ~3 MB, past ARG_MAX territory
        dump = os.path.join(self.tmp, "prompt-dump.json")
        self.setenv(MOCK_PROMPT_DUMP=dump)
        st = self.dispatch(repo=repo, text=text)
        self.assertEqual(st["status"], "ok", st)
        staged = os.path.join(self.tmp, "runs", "r", "cursor", "prompt_in", "prompt.md")
        with open(staged, "rb") as f:
            self.assertEqual(f.read(), text.encode())                         # complete
        import stat as _stat
        self.assertEqual(_stat.S_IMODE(os.stat(staged).st_mode), 0o600)
        self.assertEqual(_stat.S_IMODE(os.stat(os.path.dirname(staged)).st_mode), 0o700)
        with open(dump) as f:
            self.assertEqual(json.load(f)["bytes"], len(text.encode()))       # the CLI read all of it
        call = self.inference_calls()[-1]
        self.assertEqual(call["stdin_bytes"], 0)                              # stdin is DEVNULL
        self.assertLess(sum(len(a) for a in call["argv"]), 2000)
        self.assertNotIn(marker, " ".join(call["argv"]))
        self.assertNotIn(marker, json.dumps(st["command"]))
        with open(os.path.join(os.path.dirname(staged), "..", "status.json")) as f:
            self.assertNotIn(marker, f.read())
        self.assertIn(json.dumps(staged), call["argv"][-1])                   # only a pointer to the file
        self.assertTrue(call["argv"][-1].startswith("Read "))

    def test_symlinked_run_root_stages_the_canonical_prompt_and_dispatches(self):
        repo = self.repo()
        real_root = os.path.join(self.tmp, "real-runs")
        linked_root = os.path.join(self.tmp, "linked-runs")
        os.makedirs(real_root)
        os.symlink(real_root, linked_root)
        self.setenv(ALLOY_RUN_ROOT=linked_root)
        rc, out, _err = self.cli(
            "panel", "--prompt-file", self.prompt(), "--panelists", "cursor",
            "--repo", repo)
        self.assertEqual(rc, 0)
        with open(out.strip().splitlines()[-1]) as f:
            manifest = json.load(f)
        self.assertEqual(manifest["panelists"][0]["status"], "ok")
        staged = os.path.realpath(os.path.join(
            manifest["run_dir"], "cursor", "prompt_in", "prompt.md"))
        call = self.inference_calls()[-1]
        self.assertIn(json.dumps(staged), call["argv"][-1])
        self.assertTrue(os.path.isfile(staged))

    def test_existing_staged_symlinks_are_refused_without_writing_the_target(self):
        m = self.mod
        pdir = os.path.join(self.tmp, "staging")
        pin = os.path.join(pdir, "prompt_in")
        os.makedirs(pin)
        target = os.path.join(self.tmp, "outside-prompt")
        with open(target, "w") as f:
            f.write("unchanged")
        os.symlink(target, os.path.join(pin, "prompt.md"))
        ctx = {"repo": self.repo(), "cwd": self.tmp, "pdir": pdir}
        with self.assertRaises(m.CursorBoundaryError):
            m.CursorAgentAdapter().build_args(self.prompt("secret prompt"), "", "consult", ctx)
        with open(target) as f:
            self.assertEqual(f.read(), "unchanged")

    def test_stdin_hook_is_generalised(self):
        m = self.mod
        self.assertFalse(m.AntigravityAdapter.stdin_from_prompt)
        self.assertFalse(m.CursorAgentAdapter.stdin_from_prompt)
        for cls in (m.CodexAdapter, m.ClaudeAdapter, m.GrokAdapter, m.LlmAdapter, m.OpenCodeAdapter):
            self.assertTrue(cls.stdin_from_prompt, cls)

    def test_panel_argv_shape(self):
        repo = self.repo()
        st = self.dispatch(repo=repo)
        cmd = st["command"]
        # sandbox-exec -f <profile> <build>/node --use-system-ca <build>/index.js <tail>
        self.assertEqual(cmd[3:6], [os.path.realpath(self.build.node), "--use-system-ca", os.path.realpath(self.build.index)])
        tail = cmd[6:]
        self.assertEqual(tail[:2], ["-p", "--mode"])
        self.assertEqual(tail.count("--mode"), 1)
        self.assertEqual(tail[tail.index("--mode") + 1], "ask")
        self.assertEqual(tail[tail.index("--output-format") + 1], "json")
        self.assertEqual(tail[tail.index("--model") + 1], "composer-2.5[fast=false]")
        self.assertEqual(tail[tail.index("--sandbox") + 1], "disabled")
        self.assertEqual(tail[tail.index("--workspace") + 1], os.path.realpath(repo))
        self.assertIn("--trust", tail)
        self.assertIn("--skip-worktree-setup", tail)
        for forbidden in ("--force", "-f", "--yolo", "--auto-review", "--approve-mcps", "--plan", "--resume",
                          "--continue", "-w", "--worktree", "--worktree-base", "--plugin-dir", "--add-dir",
                          "--api-key", "--endpoint", "--header", "-e", "-H", "worker", "--effort", "--session-id"):
            self.assertNotIn(forbidden, tail)
        self.assertEqual(cmd[1], "-f")                                        # wrapped by sandbox-exec
        self.assertEqual(st["read_only"], True)
        self.assertTrue(st["permissions"]["os_isolation"])
        self.assertEqual(st["permissions"]["enforcement"], "macos_sandbox_exec")
        self.assertEqual(st["repo_access"], "real")
        self.assertEqual(os.path.realpath(st["cwd"]), os.path.realpath(repo))

    def test_no_repo_panel_runs_in_an_empty_throwaway_directory(self):
        st = self.dispatch(repo=None)
        self.assertEqual(st["status"], "ok", st)
        self.assertEqual(st["repo_access"], "none")
        self.assertTrue(st["cwd"].endswith(os.path.join("cursor", "cwd")))

    def test_pin_is_reflected_in_the_final_model_argument(self):
        repo = self.repo()
        self.setenv(ALLOY_CURSOR_MODEL="gpt-5.6-sol-high", ALLOY_CURSOR_EFFORT="max")
        st = self.dispatch(repo=repo)
        self.assertEqual(st["status"], "ok", st)
        self.assertEqual(st["command"][st["command"].index("--model") + 1],
                         "gpt-5.6-sol[effort=max,fast=false]")
        self.assertEqual(st["model"], "gpt-5.6-sol-high")

    def test_status_records_the_model_value_actually_sent(self):
        repo = self.repo()
        for pin, effort, sent in ((None, None, "composer-2.5[fast=false]"),
                                  ("gpt-5.6-sol-high", "max", "gpt-5.6-sol[effort=max,fast=false]")):
            with self.subTest(pin=pin):
                self.setenv(ALLOY_CURSOR_MODEL=pin, ALLOY_CURSOR_EFFORT=effort)
                st = self.dispatch(repo=repo, name="m-%s" % (pin or "default"))
                self.assertEqual(st["status"], "ok", st)
                self.assertEqual(st["effective_model"], sent)
                self.assertEqual(st["command"][st["command"].index("--model") + 1], st["effective_model"])
                self.assertEqual(st["model"], pin or "composer-2.5")            # the configured pin is kept as well
                with open(os.path.join(self.tmp, "runs", "m-%s" % (pin or "default"), "cursor", "status.json")) as f:
                    self.assertEqual(json.load(f)["effective_model"], sent)
        self.setenv(ALLOY_CURSOR_MODEL="auto")                                  # refused before any model value exists
        st = self.dispatch(repo=repo, name="m-refused")
        self.assertNotIn("effective_model", st)

    def test_unknown_pin_is_refused_without_spawning_the_cli(self):
        for bad in ("auto", "muse-spark-1"):
            with self.subTest(bad):
                self.setenv(ALLOY_CURSOR_MODEL=bad)
                st = self.dispatch(repo=self.repo(bad))
                self.assertEqual(st["status"], "error")
                self.assertTrue(st["error"].startswith("refused: "))
        self.assertEqual(self.inference_calls(), [])


class CursorAuthAndDoctorTests(CursorCase):
    def doctor_row(self, **kw):
        rc, out, _err = self.cli("doctor", "--json")
        self.assertEqual(rc, 0)
        return next(r for r in json.loads(out)["panelists"] if r["name"] == "cursor"), out

    def test_ready_row_with_masked_account(self):
        row, out = self.doctor_row()
        self.assertEqual(row["status"], "ready")
        self.assertIs(row["os_boundary"], True)
        self.assertTrue(row["read_only"])
        self.assertFalse(row["experimental"])
        self.assertTrue(row["default_panel"])
        self.assertEqual(row["auth_detail"], "t***@***.com")
        self.assertIsNone(row["reason"])
        self.assertEqual(row["cli_version"], self.VERSION)
        self.assertEqual(row["model"], "composer-2.5")
        self.assertNotIn("tl***", out)                      # the CLI's own (already partial) text is not echoed
        self.assertNotIn("gmail", out)
        self.assertEqual(self.mod.default_panel_names().count("cursor"), 1)
        self.assertEqual(sum(1 for r in json.loads(out)["panelists"] if r["name"] == "cursor"), 1)

    def test_status_uses_the_gateway_with_the_exact_status_grammar(self):
        self.mod.CursorAgentAdapter().auth_state()
        calls = self.cursor_calls()
        self.assertEqual([c["argv"] for c in calls], [["status", "--sandbox", "disabled"]])
        with open(self.sblog) as f:
            self.assertTrue(any('"status"' in line for line in f))
        self.assertEqual(calls[0]["stdin_bytes"], 0)

    def test_logged_out_unknown_and_failed_status_fail_closed(self):
        for mode, reason in (("logged_out", "not_logged_in"), ("garbage", "auth_unknown"), ("error", "auth_unknown")):
            with self.subTest(mode):
                self.setenv(MOCK_CURSOR_STATUS=mode)
                self.mod = self.fresh()
                row, _out = self.doctor_row()
                self.assertEqual(row["status"], "installed_not_authed")
                self.assertEqual(row["reason"], reason)
                self.assertIsNone(row["auth_detail"])
                rc, out, _err = self.cli("doctor")
                self.assertIn("cursor-agent login", out)
                self.setenv(ALLOY_PANELISTS="cursor")
                self.assertEqual(json.loads(self.cli("estimate")[1])["ready_panelists"], [])
        self.assertEqual(self.mod.mask_account(""), "")

    def test_masking(self):
        mask = self.mod.mask_account
        self.assertEqual(mask("tl***@gmail.com"), "t***@***.com")
        self.assertEqual(mask("alice@example.org"), "a***@***.org")
        self.assertEqual(mask("plainname"), "p***")
        self.assertEqual(mask("  "), "")
        for raw in ("tl***@gmail.com", "alice@example.org"):
            self.assertNotIn(raw.split("@")[0][1:], mask(raw).replace("***", ""))

    def test_unavailable_boundary_shows_the_required_sentence_and_a_reason(self):
        self.setenv(MOCK_SANDBOX_PREFLIGHT="read_allowed")
        self.mod = self.fresh()
        row, _out = self.doctor_row()
        self.assertEqual(row["status"], "sandbox_unavailable")
        self.assertIs(row["os_boundary"], False)
        self.assertIn("denied_read", row["reason"])
        self.assertFalse(row["default_panel"])
        rc, out, _err = self.cli("doctor")
        self.assertIn("Cursor installed/authenticated, but no supported OS write sandbox is available; "
                      "Cursor roles are refused.", out)
        self.assertEqual(self.cursor_calls(), [])                 # not even `status` was spawned

    def test_not_installed_shows_the_install_hint(self):
        self.setenv(ALLOY_BIN_CURSOR="/no/such/cursor-agent")
        self.mod = self.fresh()
        row, _ = self.doctor_row()
        self.assertEqual(row["status"], "not_installed")
        rc, out, _err = self.cli("doctor")
        self.assertIn("cursor.com/cli", out)

    def test_deprecated_model_key_is_warned_in_doctor_json_and_text(self):
        self.setenv(ALLOY_CURSOR_AGENT_MODEL="composer-2.5")
        row, _ = self.doctor_row()
        self.assertEqual(row["warnings"], ["ALLOY_CURSOR_AGENT_MODEL is deprecated; use ALLOY_CURSOR_MODEL"])
        self.assertIn("deprecated", self.cli("doctor")[1])
        self.setenv(ALLOY_CURSOR_MODEL="composer-2.5")
        self.assertEqual(self.doctor_row()[0]["warnings"], [])

    def test_estimate_counts_cursor_only_with_boundary_and_a_known_model(self):
        self.setenv(ALLOY_PANELISTS="cursor")
        self.assertEqual(json.loads(self.cli("estimate")[1])["ready_panelists"], ["cursor"])
        self.setenv(ALLOY_CURSOR_MODEL="auto")
        self.mod = self.fresh()
        self.assertEqual(json.loads(self.cli("estimate")[1])["ready_panelists"], [])
        self.setenv(ALLOY_CURSOR_MODEL=None, ALLOY_ALLOW_UNSANDBOXED="1", MOCK_SANDBOX_PREFLIGHT="write_leak")
        self.mod = self.fresh()
        self.assertEqual(json.loads(self.cli("estimate")[1])["ready_panelists"], [])

    def test_estimate_uses_the_effective_model_validator(self):
        self.setenv(ALLOY_PANELISTS="cursor")
        for bad in ("composer-2.5[fast=1]", "composer-2.5[fast=yes]",
                    "composer-2.5[effort=ultra]"):
            with self.subTest(model=bad):
                self.setenv(ALLOY_CURSOR_MODEL=bad)
                self.mod = self.fresh()
                self.assertEqual(json.loads(self.cli("estimate")[1])["ready_panelists"], [])

    def test_estimate_boundary_predicate_ignores_allow_unsandboxed(self):
        # The status column already gates this in practice; the predicate is the second lock.
        self.setenv(ALLOY_PANELISTS="cursor", ALLOY_ALLOW_UNSANDBOXED="1")
        base = {"name": "cursor", "status": "ready", "read_only": True, "os_boundary": True, "model": "composer-2.5"}
        for override, expected in (({}, ["cursor"]), ({"os_boundary": False}, []), ({"model": "auto"}, []),
                                   ({"model": ""}, []), ({"model": "kimi-k3-low"}, []), ({"read_only": False}, [])):
            with self.subTest(override=override):
                with self.mock.patch.object(self.mod, "_doctor_rows", lambda o=override: [dict(base, **o)]):
                    self.assertEqual(json.loads(self.cli("estimate")[1])["ready_panelists"], expected)

    def test_version_command_marks_cursor_experimental_until_the_boundary_is_ready(self):
        self.assertIn("cursor,", self.cli("version")[1] + ",")
        self.assertNotIn("cursor*", self.cli("version")[1])
        self.setenv(MOCK_SANDBOX_PREFLIGHT="read_allowed")
        self.mod = self.fresh()
        self.assertIn("cursor*", self.cli("version")[1])

    def test_alloy_never_invokes_security_or_touches_keychains(self):
        spawned = []
        real = subprocess.Popen

        def spy(argv, *a, **k):
            spawned.append(list(argv))
            return real(argv, *a, **k)
        repo = self.repo()
        with self.mock.patch.object(self.mod.subprocess, "Popen", spy):
            ad = self.mod.CursorAgentAdapter()
            self.assertEqual(ad.auth_state(), "ready")
            ad.doctor_extra("ready")
            self.dispatch(repo=repo)
        flat = [a for argv in spawned for a in argv if isinstance(a, str)]
        self.assertFalse([a for a in flat if os.path.basename(a) == "security"])
        self.assertFalse([a for a in flat if "Keychains" in a])
        # Cursor starts through the sandbox wrapper; the parent also runs Git and guarded cleanup.
        self.assertEqual({os.path.basename(argv[0]) for argv in spawned}, {"mock_panelist.py", "git", "rm"})



class CursorJsonTests(CursorCase):
    def read(self, st, name):
        with open(os.path.join(os.path.dirname(st["result_path"]), name)) as f:
            return f.read()

    def test_success_records_result_usage_and_provider_session(self):
        st = self.dispatch(repo=self.repo())
        self.assertEqual(st["status"], "ok")
        self.assertIn("MOCK cursor answer", self.read(st, "result.md"))
        self.assertEqual(st["usage"], {"input_tokens": 800, "cache_read_tokens": 300, "cache_write_tokens": 20,
                                       "output_tokens": 40, "reasoning_tokens": 0, "reported_cost_usd": None,
                                       "turns": None, "source": "cursor-json"})
        self.assertEqual(st["provider_session_id"], "mock-provider-session-1")
        self.assertNotEqual(st["session_id"], st["provider_session_id"])       # Alloy's own id is untouched
        import uuid as _uuid
        self.assertEqual(str(_uuid.UUID(st["session_id"])), st["session_id"])
        self.assertEqual(st["exit_code"], 0)
        for name in ("stdout.txt", "stderr.txt", "result.md", "status.json"):
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(st["result_path"]), name)), name)

    def test_provider_failure_cannot_be_turned_into_success(self):
        repo = self.repo()
        cases = [("is_error", {}, "is_error"), ("is_error", {"MOCK_CURSOR_EXIT": "2"}, None),
                 ("is_error_int", {}, "is_error"), ("is_error_string", {}, "is_error"),
                 ("malformed", {}, "JSON"), ("no_result", {}, "result"), ("nonstring", {}, "result"),
                 ("nonobject", {}, "JSON"), ("ok", {"MOCK_CURSOR_EXIT": "3"}, "Cursor exited 3")]
        for i, (mode, extra, needle) in enumerate(cases):
            with self.subTest(mode=mode, extra=extra):
                self.setenv(MOCK_CURSOR_JSON=mode, MOCK_CURSOR_EXIT=extra.get("MOCK_CURSOR_EXIT", "0"))
                st = self.dispatch(repo=repo, name="c%d" % i)
                self.assertEqual(st["status"], "error")
                if needle:
                    self.assertIn(needle, st["error"])
                if mode.startswith("is_error"):
                    self.assertIn("boom", self.read(st, "result.md"))          # a non-empty result did not win
                if mode == "ok":
                    self.assertEqual(st["exit_code"], 3)
                    self.assertIn("MOCK cursor answer", self.read(st, "result.md"))
        self.setenv(MOCK_CURSOR_JSON="ok", MOCK_CURSOR_EXIT="0")

    def test_usage_shapes(self):
        repo = self.repo()
        for i, mode in enumerate(("usage_unknown", "usage_bad", "usage_missing")):
            with self.subTest(mode):
                self.setenv(MOCK_CURSOR_JSON=mode)
                st = self.dispatch(repo=repo, name="u%d" % i)
                self.assertEqual(st["status"], "ok")
                self.assertIn("usage", st)
                self.assertIsNone(st["usage"])
        ad = self.mod.CursorAgentAdapter()
        self.assertEqual(ad.usage(json.dumps({"usage": {"input_tokens": 5}}))["input_tokens"], 5)
        self.assertIsNone(ad.usage("not json"))
        self.assertIsNone(ad.usage(json.dumps({"usage": []})))
        partial = ad.usage(json.dumps({"usage": {"inputTokens": 7, "outputTokens": -1, "cacheReadTokens": "x"}}))
        self.assertEqual((partial["input_tokens"], partial["output_tokens"], partial["cache_read_tokens"]), (7, 0, 0))

    def test_secret_shaped_output_is_absent_from_every_persisted_sink(self):
        repo = self.repo()
        cases = {
            "jwt": [GOOD_JWT],
            "assignment": ["hunter2hunter2hunter2"],
            "assignment_quoted": ["quotedhunter2hunter2"],
            "header": ["abc123def456ghi789"],
            "header_basic": ["YWJjMTIzZGVmNDU2"],
            "header_api_key": ["customheader123456"],
            "header_schemes": ["schemevalue123456", "secondvalue123456"],
            "cookie": ["cookiesecret123456", "cookierefresh123456"],
        }
        for i, (mode, secrets) in enumerate(cases.items()):
            with self.subTest(mode):
                self.setenv(MOCK_CURSOR_JSON=mode)
                st = self.dispatch(repo=repo, name="s%d" % i)
                sinks = {name: self.read(st, name) for name in ("result.md", "stdout.txt", "stderr.txt", "status.json")}
                for name, body in sinks.items():
                    for secret in secrets:
                        self.assertNotIn(secret, body, (mode, name))
                self.assertIn("REDACTED", sinks["result.md"])
                self.assertIn("REDACTED", sinks["stdout.txt"])
                self.assertIn("REDACTED", sinks["stderr.txt"])
                self.assertIn("REDACTED", sinks["status.json"])
                self.assertGreaterEqual(st["secrets_redacted"], 3)
                self.assertGreaterEqual(json.loads(sinks["status.json"])["secrets_redacted"], 3)
                self.assertNotIn(secrets[0], json.dumps(st))                    # nor the value returned for the manifest

    def test_secret_in_stderr_tail_is_absent_from_status_json_error(self):
        repo = self.repo()
        for exit_code, expected in (("0", "empty"), ("4", "error")):
            with self.subTest(exit_code=exit_code):
                self.setenv(MOCK_CURSOR_JSON="jwt_empty", MOCK_CURSOR_EXIT=exit_code)
                st = self.dispatch(repo=repo, name="stderr-" + exit_code)
                self.assertEqual(st["status"], expected)
                self.assertIn("warning: leaked", st["error"])
                self.assertIn("REDACTED", st["error"])
                body = self.read(st, "status.json")
                self.assertNotIn(GOOD_JWT, body)
                self.assertIn("REDACTED", body)

    def test_every_status_write_is_redacted_including_the_first_and_every_command_element(self):
        m = self.mod
        writes = []
        real = m.write_atomic

        def spy(path, data):
            if os.path.basename(path) == "status.json":
                writes.append(data)
            return real(path, data)
        secret = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        self.setenv(ALLOY_CODEX_MODEL=secret, ALLOY_BIN_CODEX=MOCK, CODEX_API_KEY="x")
        pdir = os.path.join(self.tmp, "runs", "x", "codex")
        with self.mock.patch.object(m, "write_atomic", spy):
            st = m.run_panelist(m.ADAPTERS["codex"], self.prompt(), pdir, 30, 100000, "consult")
        self.assertGreaterEqual(len(writes), 2)                      # the "running" write and the final one
        for data in writes:
            self.assertNotIn(secret, data)
            json.loads(data)                                          # still valid JSON
        self.assertNotIn(secret, json.dumps(st))
        self.assertTrue(any("REDACTED" in a for a in st["command"]))
        red, n = m.redact_tree({"a": ["x", {"b": "OPENAI_API_KEY=sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX"}], "n": 3})
        self.assertEqual(n, 1)
        self.assertEqual(red["n"], 3)

    def test_output_is_captured_in_memory_and_sidecars_appear_only_redacted(self):
        m = self.mod
        while_running = []
        real = m.write_atomic

        def spy(path, data):
            if os.path.basename(path) == "status.json" and json.loads(data)["status"] == "running":
                pdir = os.path.dirname(path)
                while_running.append([os.path.exists(os.path.join(pdir, n)) for n in ("stdout.txt", "stderr.txt")])
            return real(path, data)
        self.setenv(MOCK_CURSOR_JSON="jwt")
        with self.mock.patch.object(m, "write_atomic", spy):
            st = self.dispatch(repo=self.repo())
        self.assertEqual(while_running, [[False, False]])             # the child was never handed a sidecar file
        for name in ("stdout.txt", "stderr.txt"):                     # created atomically, already redacted
            self.assertNotIn(GOOD_JWT, self.read(st, name))
            self.assertIn("REDACTED", self.read(st, name))

    def test_capture_usage_flag_leaves_the_argv_alone_and_still_reports_usage(self):
        repo = self.repo()
        plain = self.dispatch(repo=repo, name="plain")
        self.setenv(ALLOY_CAPTURE_USAGE="1")
        captured = self.dispatch(repo=repo, name="captured")
        self.assertEqual(captured["status"], "ok")
        self.assertEqual(captured["usage"], plain["usage"])
        self.assertEqual(captured["command"][4:-1], plain["command"][4:-1])        # already JSON: no rewrite

    def test_timeout_kills_the_group_and_reports_it(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        self.setenv(MOCK_BEHAVIOR="hang", MOCK_CHILD_PIDFILE=pidfile)
        st = self.dispatch(repo=self.repo(), timeout_s=2)
        self.assertEqual(st["status"], "timeout")
        self.assertTrue(st["timed_out"])
        time.sleep(0.3)
        with open(pidfile) as f:
            with self.assertRaises(OSError):
                os.kill(int(f.read()), 0)                              # the descendant is gone too

    def test_other_mock_behaviours_flow_through_the_json_path(self):
        repo = self.repo()
        for i, (behavior, status) in enumerate((("empty", "empty"), ("fail", "error"), ("auth", "auth"))):
            with self.subTest(behavior):
                self.setenv(MOCK_BEHAVIOR=behavior)
                st = self.dispatch(repo=repo, name="b%d" % i)
                self.assertEqual(st["status"], status)


class CursorTripwireTests(CursorCase):
    def fp(self, path):
        return self.mod.cursor_fingerprint(path)

    def moves(self, path, mutate):
        before = self.fp(path)
        mutate()
        after = self.fp(path)
        self.assertNotEqual(before.digest, after.digest)
        return self.mod.cursor_fingerprint_changes(before, after)

    def test_unrelated_sibling_activity_does_not_refuse_a_canary_snapshot(self):
        rt = self.runtime()
        before = rt.snapshot()
        sibling = os.path.join(os.path.dirname(rt.canary_outside), "canary-neighbour-" + str(os.getpid()))
        self.addCleanup(lambda: os.path.exists(sibling) and os.unlink(sibling))
        original = self.mod._fp_entry_at
        def racing_entry(fd, name, display, *args, **kwargs):
            entry = original(fd, name, display, *args, **kwargs)
            if display == rt.canary_outside:
                with open(sibling, "w") as handle:
                    handle.write("unrelated temporary file")
            return entry
        with self.mock.patch.object(self.mod, "_fp_entry_at", side_effect=racing_entry):
            self.assertEqual(rt.snapshot(), before)

    def test_worktree_bytes_are_hashed_for_tracked_untracked_and_ignored_files(self):
        repo = self.repo()
        a, b = self.fp(repo), self.fp(repo)
        self.assertEqual(a.digest, b.digest)                                     # deterministic
        def write(name, body):
            with open(os.path.join(repo, name), "w") as f:
                f.write(body)
        self.assertIn("tree:ignored.txt", self.moves(repo, lambda: write("ignored.txt", "bbbb")))   # same name, same size
        self.assertIn("tree:untracked.txt", self.moves(repo, lambda: write("untracked.txt", "UNTRACKED\n")))
        self.assertIn("tree:tracked.txt", self.moves(repo, lambda: write("tracked.txt", "TRACKED\n")))
        self.moves(repo, lambda: write("brand-new.txt", "x"))
        self.moves(repo, lambda: os.remove(os.path.join(repo, "brand-new.txt")))
        self.moves(repo, lambda: os.chmod(os.path.join(repo, "tracked.txt"), 0o755))
        os.makedirs(os.path.join(repo, "build"))
        self.moves(repo, lambda: write("build/artifact.o", "obj"))
        # git status and HEAD do not move for the ignored file: the old tripwire missed it
        status_before = git_run(repo, "status", "--porcelain")
        write("ignored.txt", "cccc")
        self.assertEqual(git_run(repo, "status", "--porcelain"), status_before)

    def test_symlinks_and_special_files_are_recorded_not_followed(self):
        repo = self.repo()
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w") as f:
            f.write("one")
        os.symlink(outside, os.path.join(repo, "link"))
        os.symlink("/no/such/target", os.path.join(repo, "dangling"))
        os.mkfifo(os.path.join(repo, "fifo"))
        first = self.fp(repo)                                                    # must not block on the FIFO
        with open(outside, "w") as f:
            f.write("TWO")
        self.assertEqual(first.digest, self.fp(repo).digest)                      # the target's bytes are not hashed
        self.assertEqual(first.entries["tree:link"][0], "l")
        self.assertEqual(first.entries["tree:fifo"][0], "o")
        def retarget():
            os.remove(os.path.join(repo, "link"))
            os.symlink(os.path.join(self.tmp, "elsewhere"), os.path.join(repo, "link"))
        self.assertIn("tree:link", self.moves(repo, retarget))

        def swap():
            os.remove(os.path.join(repo, "tracked.txt"))
            os.mkdir(os.path.join(repo, "tracked.txt"))
        self.assertIn("tree:tracked.txt", self.moves(repo, swap))                 # a path changing type

    def test_directory_swap_to_symlink_during_walk_is_refused(self):
        repo = self.repo()
        nested = os.path.join(repo, "nested")
        parked = os.path.join(repo, "nested-original")
        outside = os.path.join(self.tmp, "outside-tree")
        os.makedirs(nested)
        os.makedirs(outside)
        with open(os.path.join(nested, "inside.txt"), "w") as f:
            f.write("inside")
        with open(os.path.join(outside, "secret.txt"), "w") as f:
            f.write("must not be followed")
        real_open = os.open
        swapped = {"done": False}

        def racing_open(path, flags, *a, **kw):
            if path == "nested" and kw.get("dir_fd") is not None and not swapped["done"]:
                swapped["done"] = True
                os.rename(nested, parked)
                os.symlink(outside, nested)
            return real_open(path, flags, *a, **kw)

        with self.mock.patch.object(os, "open", racing_open):
            with self.assertRaises(self.mod.CursorBoundaryError):
                self.fp(repo)
        self.assertTrue(swapped["done"])

    def test_directory_mutation_during_enumeration_is_refused(self):
        repo = self.repo()
        real_listdir = os.listdir
        state = {"done": False}

        def racing_listdir(path="."):
            names = real_listdir(path)           # the directory changes right after it was listed
            if isinstance(path, int) and not state["done"]:
                state["done"] = True
                with open(os.path.join(repo, "enumeration-race.txt"), "w") as f:
                    f.write("changed")
            return names

        with self.mock.patch.object(os, "listdir", racing_listdir):
            with self.assertRaises(self.mod.CursorBoundaryError):
                self.fp(repo)
        self.assertTrue(state["done"])

    def test_unreadable_entries_and_races_refuse(self):
        if os.getuid() == 0:
            self.skipTest("root can read everything")
        repo = self.repo()
        os.chmod(os.path.join(repo, "untracked.txt"), 0)
        self.addCleanup(os.chmod, os.path.join(repo, "untracked.txt"), 0o644)
        with self.assertRaises(self.mod.CursorBoundaryError):
            self.fp(repo)
        os.chmod(os.path.join(repo, "untracked.txt"), 0o644)
        with self.mock.patch.object(self.mod, "CURSOR_FP_MAX_ENTRIES", 3), self.assertRaises(self.mod.CursorBoundaryError):
            self.fp(repo)
        # a file that grows while it is read is a race
        real_open, real_read = os.open, os.read
        opened, state = {}, {"done": False}

        def recording_open(path, flags, *a, **k):
            fd = real_open(path, flags, *a, **k)
            if os.path.basename(path) == "untracked.txt":
                opened[fd] = os.path.join(repo, "untracked.txt")
            return fd

        def racing_read(fd, n):
            data = real_read(fd, n)
            if data and fd in opened and not state["done"]:
                state["done"] = True
                with open(opened[fd], "a") as f:          # the very file being hashed grows underneath it
                    f.write("more")
            return data
        with self.mock.patch.object(os, "open", recording_open), self.mock.patch.object(os, "read", racing_read):
            with self.assertRaises(self.mod.CursorBoundaryError):
                self.fp(repo)
        self.assertTrue(state["done"])

    def _git_internal_classes(self, repo, wt):
        common = os.path.join(repo, ".git")
        gitdir = os.path.join(common, "worktrees", os.path.basename(wt))
        sha = git_run(repo, "rev-parse", "HEAD").strip()
        pointer = os.path.join(wt, ".git")

        def put(path, body, mode="a"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, mode) as f:
                f.write(body)

        def unterminate():                       # same target, different bytes: no trailing newline
            with open(pointer) as f:
                body = f.read()
            put(pointer, body.rstrip("\n"), "w")
        packed = "# pack-refs with: peeled fully-peeled sorted \n"
        return {
            "linked pointer": unterminate,
            "gitdir commondir": lambda: put(os.path.join(gitdir, "commondir"), "\n"),
            "gitdir HEAD": lambda: put(os.path.join(gitdir, "HEAD"), "ref: refs/heads/main\n", "w"),
            "gitdir config.worktree": lambda: put(os.path.join(gitdir, "config.worktree"), "[core]\n"),
            "gitdir info/exclude": lambda: put(os.path.join(gitdir, "info", "exclude"), "x\n"),
            "gitdir info/attributes": lambda: put(os.path.join(gitdir, "info", "attributes"), "* filter=x\n"),
            "gitdir info/sparse-checkout": lambda: put(os.path.join(gitdir, "info", "sparse-checkout"), "/x\n"),
            "gitdir hooks": lambda: put(os.path.join(gitdir, "hooks", "post-checkout"), "#!/bin/sh\n"),
            "gitdir refs": lambda: put(os.path.join(gitdir, "refs", "bisect", "bad"), sha + "\n"),
            "gitdir packed-refs": lambda: put(os.path.join(gitdir, "packed-refs"), packed),
            "common config": lambda: put(os.path.join(common, "config"), "[alias]\n\tx = y\n"),
            "common config.worktree": lambda: put(os.path.join(common, "config.worktree"), "[core]\n"),
            "common HEAD": lambda: put(os.path.join(common, "HEAD"), "ref: refs/heads/main\n\n", "w"),
            "common packed-refs": lambda: put(os.path.join(common, "packed-refs"), packed),
            "common info/exclude": lambda: put(os.path.join(common, "info", "exclude"), "x\n"),
            "common info/attributes": lambda: put(os.path.join(common, "info", "attributes"), "* filter=x\n"),
            "common info/sparse-checkout": lambda: put(os.path.join(common, "info", "sparse-checkout"), "/x\n"),
            "common hooks new": lambda: put(os.path.join(common, "hooks", "pre-commit"), "#!/bin/sh\n"),
            "common refs": lambda: put(os.path.join(common, "refs", "heads", "evil"), sha + "\n"),
        }

    def test_every_protected_git_internal_class_moves_the_fingerprint(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        for name, mutate in self._git_internal_classes(repo, wt).items():
            with self.subTest(name):
                changes = self.moves(wt, mutate)
                self.assertTrue(any(k.startswith("git:") for k in changes), (name, changes))
        # deletion of a present entry moves it too (present/missing is part of the digest)
        common = os.path.join(repo, ".git")
        self.moves(wt, lambda: os.remove(os.path.join(common, "packed-refs")))

    def test_ordinary_checkout_git_internals_move_the_fingerprint(self):
        repo = self.repo()
        gitdir = os.path.join(repo, ".git")
        sha = git_run(repo, "rev-parse", "HEAD").strip()
        git_run(repo, "branch", "other")
        for rel, body, mode in (("config", "[x]\n", "a"), ("HEAD", "ref: refs/heads/other\n", "w"),
                                ("info/exclude", "x\n", "a"), ("hooks/post-commit", "#!/bin/sh\n", "a"),
                                ("refs/heads/evil", sha + "\n", "a"), ("info/attributes", "* x\n", "a"),
                                ("info/sparse-checkout", "/\n", "a"), ("config.worktree", "[x]\n", "a"),
                                ("packed-refs", "# pack-refs with: peeled fully-peeled sorted \n", "a")):
            with self.subTest(rel):
                path = os.path.join(gitdir, rel)

                def mutate(path=path, body=body, mode=mode):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, mode) as f:
                        f.write(body)
                self.assertTrue(any(k.startswith("git:") for k in self.moves(repo, mutate)))

    def test_git_locations(self):
        m = self.mod
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        ordinary = m.cursor_git_locations(repo)
        self.assertEqual((ordinary["top"], ordinary["dotgit"], ordinary["gitdir"], ordinary["common"], ordinary["dotgit_is_file"]),
                         (repo, repo + "/.git", repo + "/.git", repo + "/.git", False))
        linked = m.cursor_git_locations(wt)
        self.assertTrue(linked["dotgit_is_file"])
        self.assertEqual(linked["dotgit"], wt + "/.git")
        self.assertEqual(linked["common"], repo + "/.git")
        self.assertEqual(linked["gitdir"], repo + "/.git/worktrees/" + os.path.basename(wt))
        os.makedirs(os.path.join(repo, "sub"))
        self.assertEqual(m.cursor_git_locations(os.path.join(repo, "sub"))["top"], repo)     # found from a subdirectory
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assertIsNone(m.cursor_git_locations(plain))
        # nonstandard / ambiguous layouts refuse
        bad = os.path.join(self.tmp, "bad")
        os.makedirs(bad)
        for body in ("gitdir: /no/such/dir\n", "garbage\n", "gitdir: %s/.git/worktrees/x\ngitdir: y\n" % repo, ""):
            with open(os.path.join(bad, ".git"), "w") as f:
                f.write(body)
            with self.subTest(pointer=body), self.assertRaises(m.CursorBoundaryError):
                m.cursor_git_locations(bad)
        os.remove(os.path.join(bad, ".git"))
        os.symlink(repo + "/.git", os.path.join(bad, ".git"))
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_git_locations(bad)

    def test_a_clean_run_passes_and_tampering_fails_the_call(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        self.assertEqual(self.dispatch(repo=wt, name="clean")["status"], "ok")
        common = os.path.join(repo, ".git")
        with open(os.path.join(common, "config")) as f:
            config = f.read()
        cases = {
            "ignored file same name": [[os.path.join(wt, "ignored.txt"), "zzzz"]],
            "tracked file": [[os.path.join(wt, "tracked.txt"), "changed\n"]],
            "new untracked file": [[os.path.join(wt, "dropped.txt"), "x"]],
            "common config": [[os.path.join(common, "config"), config + "[alias]\n\tx = y\n"]],
            "hook": [[os.path.join(common, "hooks", "pre-commit.sample"), "x"]],
            "common info/exclude": [[os.path.join(common, "info", "exclude"), "x\n"]],
        }
        for i, (name, writes) in enumerate(cases.items()):
            with self.subTest(name):
                self.setenv(MOCK_TAMPER_WRITE=json.dumps(writes))
                st = self.dispatch(repo=wt, name="t%d" % i)
                self.assertEqual(st["status"], "error")
                self.assertIn("sandbox tripwire", st["error"])
        self.setenv(MOCK_TAMPER_WRITE=None)
        self.assertEqual(self.dispatch(repo=wt, name="after")["status"], "ok")

    def test_manifest_uses_the_cursor_content_tripwire_for_repo_tamper(self):
        repo = self.repo()
        before = self.mod._repo_fingerprint(repo)
        ignored = os.path.join(repo, "ignored.txt")
        self.setenv(MOCK_TAMPER_WRITE=json.dumps([[ignored, "zzzz"]]))
        rc, manifest, _err = self.panel_cli("--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 3)
        self.assertEqual(self.mod._repo_fingerprint(repo), before)  # the legacy signal misses it
        self.assertTrue(manifest["summary"]["repo_tamper"])
        row = manifest["panelists"][0]
        self.assertIn("tree:ignored.txt", row["workspace_changes"])
        self.assertIn("sandbox tripwire", row["error"])

    def test_canary_mutation_outside_the_runtime_fails_the_call(self):
        self.setenv(MOCK_TAMPER_CANARY="1")
        st = self.dispatch(repo=self.repo())
        self.assertEqual(st["status"], "error")
        self.assertIn("sandbox tripwire", st["error"])
        self.assertIn("1 canary", st["error"])

    def test_manifest_reports_repo_tamper_for_a_canary_only_tripwire(self):
        # Only the outside canary moves: the workspace fingerprint is untouched, yet the
        # run failed on the tripwire, so the manifest must not say the tree is clean.
        repo = self.repo()
        self.setenv(MOCK_TAMPER_CANARY="1")
        rc, manifest, _err = self.panel_cli("--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 3)
        row = manifest["panelists"][0]
        self.assertEqual(row["status"], "error")
        self.assertIn("sandbox tripwire", row["error"])
        self.assertEqual(row["workspace_changes"], [])
        self.assertTrue(row["canary_changes"])
        self.assertTrue(manifest["summary"]["repo_tamper"])
        self.assertEqual(manifest["summary"]["repo_tamper_check"], "checked")
        # and a clean run still reports no tamper
        self.setenv(MOCK_TAMPER_CANARY=None)
        os.environ.pop("MOCK_TAMPER_CANARY", None)
        rc, manifest, _err = self.panel_cli("--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 0)
        self.assertFalse(manifest["summary"]["repo_tamper"])
        self.assertEqual(manifest["panelists"][0]["canary_changes"], [])

    def test_uncertain_fingerprint_refuses_before_any_process_starts(self):
        if os.getuid() == 0:
            self.skipTest("root can read everything")
        repo = self.repo()
        path = os.path.join(repo, "untracked.txt")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        st = self.dispatch(repo=repo)
        self.assertEqual(st["status"], "error")
        self.assertTrue(st["error"].startswith("refused: "))
        self.assertEqual(self.inference_calls(), [])

    def test_the_tripwire_runs_only_after_the_whole_process_group_is_dead(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        self.setenv(MOCK_BEHAVIOR="hang", MOCK_CHILD_PIDFILE=pidfile)
        observed = []

        class Probe(self.mod.CursorAgentAdapter):
            def after_exit(probe, ctx):
                with open(pidfile) as f:
                    pid = int(f.read())
                try:
                    os.kill(pid, 0)
                    observed.append("alive")
                except OSError:
                    observed.append("dead")
                return super().after_exit(ctx)
        st = self.dispatch(repo=self.repo(), timeout_s=2, adapter=Probe())
        self.assertEqual(st["status"], "timeout")
        self.assertEqual(observed, ["dead"])

    def run_in(self, pdir, repo, **kw):
        return self.mod.run_panelist(self.mod.CursorAgentAdapter(), self.prompt(), pdir, 30, 100000,
                                     "consult", repo=repo, **kw)

    def test_a_run_directory_inside_the_workspace_is_refused_not_misreported_as_tamper(self):
        repo = self.repo()
        link = os.path.join(self.tmp, "run-link")
        os.symlink(os.path.join(repo, "sub"), link)
        os.makedirs(os.path.join(repo, "sub"))
        for name, pdir, kw in (
                ("pdir below the repo", os.path.join(repo, ".runs", "r", "cursor"), {}),
                ("pdir is the repo", repo, {}),
                ("run root below the repo", os.path.join(self.tmp, "elsewhere", "cursor"),
                 {"run_root": os.path.join(repo, "runs")}),
                ("pdir reached through a symlink", os.path.join(link, "cursor"), {})):
            with self.subTest(name):
                st = self.run_in(pdir, repo, **kw)
                self.assertEqual(st["status"], "error")
                self.assertTrue(st["error"].startswith("refused: "), st["error"])
                self.assertIn("run directory is inside the workspace", st["error"])
                self.assertIn("--run-dir", st["error"])              # says what to do about it
                self.assertNotIn("tripwire", st["error"])
        self.assertEqual(self.inference_calls(), [])
        # a sibling that merely shares the repository's name as a prefix is NOT inside it
        st = self.run_in(os.path.join(self.tmp, "repo-runs", "r", "cursor"), repo)
        self.assertEqual(st["status"], "ok", st)
        self.assertEqual(len(self.inference_calls()), 1)

    def test_panel_with_a_run_dir_inside_the_repo_reports_the_real_cause(self):
        repo = self.repo()
        rc, out, _err = self.cli("panel", "--prompt-file", self.prompt(), "--run-dir", os.path.join(repo, ".alloy-runs"),
                                 "--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 3)
        with open(out.strip().splitlines()[-1]) as f:
            manifest = json.load(f)
        row = manifest["panelists"][0]
        self.assertEqual(row["status"], "error")
        self.assertIn("run directory is inside the workspace", row["error"])
        self.assertFalse(manifest["summary"]["repo_tamper"])         # Cursor never ran and wrote nothing
        self.assertEqual(self.inference_calls(), [])

    def test_directory_enumeration_needs_descriptor_support_and_refuses_without_it(self):
        self.assertIn(os.listdir, os.supports_fd)                      # documented POSIX API since Python 3.3
        self.assertTrue(self.mod._LISTDIR_BY_FD)
        repo = self.repo()
        with self.mock.patch.object(self.mod, "_LISTDIR_BY_FD", False):
            with self.assertRaisesRegex(self.mod.CursorBoundaryError, "descriptor"):
                self.fp(repo)
            st = self.dispatch(repo=repo)                              # and a dispatch refuses instead of skipping the walk
        self.assertEqual(st["status"], "error")
        self.assertTrue(st["error"].startswith("refused: "))
        self.assertEqual(self.inference_calls(), [])

    def test_enumeration_lists_by_descriptor_and_never_depends_on_scandir_of_a_descriptor(self):
        # os.scandir has no dir_fd parameter, and scandir(fd) is a 3.7+ form: the walk uses only
        # os.listdir(fd). Every listing during a fingerprint is by an open descriptor (a path
        # listing could be redirected by a rename), and scandir is never reached.
        repo = self.repo()
        os.makedirs(os.path.join(repo, "deep", "er"))
        with open(os.path.join(repo, "deep", "er", "f.txt"), "w") as f:
            f.write("x")
        baseline = self.fp(repo)
        real_listdir = os.listdir
        listed = []

        def spy_listdir(path="."):
            listed.append(path)
            return real_listdir(path)

        def no_scandir(*_a, **_k):
            raise AssertionError("os.scandir must not be used for the fingerprint")

        with self.mock.patch.object(os, "listdir", spy_listdir), self.mock.patch.object(os, "scandir", no_scandir):
            self.assertEqual(self.fp(repo), baseline)
        self.assertGreaterEqual(len(listed), 3)                       # root, deep and deep/er at least
        self.assertTrue(all(isinstance(p, int) for p in listed), listed)
        self.assertIn("tree:deep/er/f.txt", baseline.entries)
        with self.assertRaises(TypeError):                            # the API the review asked for does not exist
            os.scandir(".", dir_fd=0)


class CursorGitHardeningTests(CursorCase):
    def spy_popen(self):
        calls = []
        real = subprocess.Popen

        def spy(argv, *a, **k):
            calls.append((list(argv), dict(k)))
            return real(argv, *a, **k)
        p = self.mock.patch.object(self.mod.subprocess, "Popen", spy)
        p.start()
        self.addCleanup(p.stop)
        return calls

    def assert_hardened(self, calls):
        gits = [(a, k) for a, k in calls if a and a[0] == "git"]
        self.assertTrue(gits)
        for argv, kw in gits:
            pairs = [(argv[i], argv[i + 1]) for i in range(len(argv) - 1) if argv[i] == "-c"]
            self.assertIn(("-c", "core.hooksPath=/dev/null"), pairs, argv)
            self.assertIn(("-c", "core.fsmonitor=false"), pairs, argv)
            self.assertEqual(kw["env"]["GIT_CONFIG_NOSYSTEM"], "1", argv)
            self.assertEqual(kw["env"]["GIT_OPTIONAL_LOCKS"], "0", argv)
            self.assertIs(kw["stdin"], subprocess.DEVNULL, argv)
            for stripped in ("GIT_DIR", "GIT_WORK_TREE", "GIT_EXTERNAL_DIFF"):
                self.assertNotIn(stripped, kw["env"])
        return gits

    def test_every_parent_git_call_has_the_full_contract(self):
        m = self.mod
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        self.setenv(GIT_DIR="/nonexistent-git-dir", GIT_EXTERNAL_DIFF="/bin/false")
        calls = self.spy_popen()
        m._git(repo, "rev-parse", "--show-toplevel")
        m._git_toplevel(repo)
        m._repo_fingerprint(repo)
        m.cursor_git_locations(wt)
        m.cursor_fingerprint(wt)
        rt = self.runtime()
        self.dispatch(repo=wt)
        gits = self.assert_hardened(calls)
        self.assertGreaterEqual(len(gits), 12)

    def test_a_panel_run_uses_only_hardened_git(self):
        repo = self.repo()
        calls = self.spy_popen()
        rc, manifest, _err = self.panel_cli("--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 0)
        self.assert_hardened(calls)

    def test_hooks_and_command_valued_fsmonitor_never_run(self):
        m = self.mod
        repo = self.repo()
        marker = os.path.join(self.tmp, "fsmonitor-ran")
        script = os.path.join(self.tmp, "fsm.sh")
        with open(script, "w") as f:
            f.write("#!/bin/sh\ntouch %s\nprintf '\\0'\n" % marker)
        os.chmod(script, 0o755)
        git_run(repo, "config", "core.fsmonitor", script)
        # control: an unhardened `git status` does run the configured fsmonitor command
        subprocess.run(["git", "-C", repo, "status", "--porcelain"], capture_output=True)
        self.assertTrue(os.path.exists(marker), "control failed: this git did not run core.fsmonitor")
        os.remove(marker)
        m._repo_fingerprint(repo)
        m._git_toplevel(repo)
        m.cursor_fingerprint(repo)
        m.cursor_git_locations(repo)
        self.assertFalse(os.path.exists(marker))

    def test_git_output_and_time_are_bounded(self):
        m = self.mod
        repo = self.repo()
        self.assertIsNone(m._git(repo, "config", "--list", cap=5))                       # output over the cap
        ran = m._run_bounded(["sleep", "5"], env=dict(os.environ), timeout=0.3)
        self.assertIsNone(ran["rc"])
        self.assertTrue(ran["group_dead"])
        self.assertEqual(m._git(repo, "rev-parse", "--show-toplevel").returncode, 0)
        self.assertNotEqual(m._git(os.path.join(self.tmp, "no-such-dir"), "status").returncode, 0)

    def test_streamed_digest_is_exact_and_not_limited_by_the_output_cap(self):
        m = self.mod
        repo = self.repo()
        blob = os.urandom(5 << 20)                                                # larger than the 4 MB output cap
        path = os.path.join(self.tmp, "big.bin")
        with open(path, "wb") as f:
            f.write(blob)
        sha = git_run(repo, "hash-object", "-w", path).strip()
        self.assertIsNone(m._git(repo, "cat-file", "blob", sha))                  # the buffered helper gives up ...
        rc, digest = m._git_digest(repo, "cat-file", "blob", sha)                 # ... the streaming one does not
        self.assertEqual((rc, digest), (0, hashlib.sha256(blob).hexdigest()))
        self.assertEqual(m._git_digest(repo, "cat-file", "blob", "0" * 40)[0], 128)   # a git failure keeps its code

    def test_a_large_status_no_longer_silently_disables_the_repo_tamper_check(self):
        m = self.mod
        repo = self.repo()
        status = ("status", "--porcelain=v1", "--untracked-files=all")
        with self.mock.patch.object(m, "_GIT_OUTPUT_CAP", 16):
            self.assertIsNone(m._git(repo, *status))          # what used to turn the check off without a word
            before = m._repo_fingerprint(repo)
            self.assertIsNotNone(before)
            self.assertEqual(m._repo_fingerprint(repo), before)                 # deterministic
            with open(os.path.join(repo, "added-by-a-panelist.txt"), "w") as f:
                f.write("x")
            self.assertNotEqual(m._repo_fingerprint(repo), before)              # and still detects the change
        self.assertIsNone(m._repo_fingerprint(os.path.join(self.tmp, "no-such-dir")))

    def test_an_unavailable_tamper_check_is_recorded_in_the_manifest(self):
        repo = self.repo()
        rc, manifest, err = self.panel_cli("--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 0)
        self.assertEqual(manifest["summary"]["repo_tamper_check"], "checked")
        self.assertFalse(manifest["summary"]["repo_tamper"])
        with self.mock.patch.object(self.mod, "_git_digest", return_value=None):      # Git did not complete
            rc, manifest, err = self.panel_cli("--panelists", "cursor", "--repo", repo)
        self.assertEqual(rc, 0)
        self.assertEqual(manifest["summary"]["repo_tamper_check"], "unavailable")
        self.assertIn("tamper check was unavailable", err)                      # visible on the matrix too
        self.assertFalse(manifest["summary"]["repo_tamper"])                     # never reported as "clean" evidence
        rc, manifest, err = self.panel_cli("--panelists", "cursor")              # ALLOY_REPO=none: nothing to check
        self.assertEqual(manifest["summary"]["repo_tamper_check"], "no_repo")
        self.assertNotIn("unavailable", err)


class CursorManagedMakerTests(CursorCase):
    def maker(self):
        ad = self.mod.CursorAgentAdapter()
        ad.__class__ = type("ManagedCursor", (self.mod.CursorAgentAdapter,), {"read_only": False})
        return ad

    def test_maker_form_omits_mode_and_uses_the_maker_profile(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        ad = self.maker()
        self.assertFalse(ad.read_only)
        self.assertTrue(ad.cursor_boundary_ready)
        st = self.dispatch(repo=wt, adapter=ad, managed=True, mode="make")
        self.assertEqual(st["status"], "ok", st)
        tail = st["command"][4:]
        self.assertNotIn("--mode", tail)
        for required in ("-p", "--trust", "--skip-worktree-setup"):
            self.assertIn(required, tail)
        self.assertEqual(tail[tail.index("--sandbox") + 1], "disabled")
        for forbidden in ("--force", "-f", "--yolo", "--auto-review", "--approve-mcps", "--mode", "--plan"):
            self.assertNotIn(forbidden, tail)
        self.assertIn(json.dumps(os.path.realpath(wt)), tail[-1])            # owned worktree in the reminder, no task text
        maker_profiles = [p for p in self.profiles() if "role=maker" in p]
        prof = maker_profiles[-1]
        self.assertEqual(self.decision(prof, "file-write-create", wt + "/src/x.py"), "allow")
        self.assertEqual(self.decision(prof, "file-write-create", wt + "/.git"), "deny")
        self.assertFalse(st["read_only"])
        self.assertEqual(st["permissions"]["command_execution"], "allowed_in_worktree")
        self.assertEqual(st["permissions"]["enforcement"], "macos_sandbox_exec")

    def test_maker_worktree_edits_are_exposed_for_allow_path_classification(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        changed = os.path.join(wt, "tracked.txt")
        self.setenv(MOCK_TAMPER_WRITE=json.dumps([[changed, "maker edit\n"]]))
        st = self.dispatch(repo=wt, adapter=self.maker(), managed=True, mode="make")
        self.assertEqual(st["status"], "ok", st)
        self.assertEqual(st["changed_paths"], ["tracked.txt"])
        self.assertIn("tree:tracked.txt", st["workspace_changes"])
        with open(st["result_path"].replace("result.md", "status.json")) as f:
            persisted = json.load(f)
        self.assertEqual(persisted["changed_paths"], ["tracked.txt"])

    def test_maker_with_boundary_down_never_spawns_even_though_read_only_is_false(self):
        self.setenv(MOCK_SANDBOX_PREFLIGHT="exec_leak", ALLOY_ALLOW_UNSANDBOXED="1")
        self.mod = self.fresh()
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        st = self.dispatch(repo=wt, adapter=self.maker(), managed=True, mode="make")
        self.assertEqual(st["status"], "error")
        self.assertTrue(st["error"].startswith("refused: "))
        self.assertEqual(self.cursor_calls(), [])

    def test_a_read_only_adapter_cannot_be_dispatched_as_a_managed_maker(self):
        wt = make_worktree(self.repo(), os.path.join(self.tmp, "wt"))
        with self.assertRaises(self.mod.execution.ExecutionError):
            self.dispatch(repo=wt, managed=True, mode="make")

    def test_maker_in_a_plain_directory_is_refused(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        st = self.dispatch(repo=plain, adapter=self.maker(), managed=True, mode="make")
        self.assertEqual(st["status"], "error")
        self.assertIn("refused", st["error"])
        self.assertEqual(self.cursor_calls(), [])

    def test_maker_gateway_requires_a_managed_linked_worktree_and_a_matching_cwd(self):
        m = self.mod
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        separate = os.path.join(self.tmp, "separate")
        os.makedirs(separate)
        git_run(separate, "init", "-q", "-b", "main", "--separate-git-dir", os.path.join(self.tmp, "separate.gitdir"))
        self.assertTrue(os.path.isfile(os.path.join(separate, ".git")))       # a .git pointer that is NOT a linked worktree
        self.gateway("maker", wt)                                              # the well-formed call is accepted
        cases = {
            "not a managed dispatch": (wt, {"managed_worktree": False}),
            "managed flag unset": (wt, {"managed_worktree": None}),
            "cwd is another directory": (wt, {"cwd": self.tmp}),
            "cwd is the source checkout": (wt, {"cwd": repo}),
            "cwd missing": (wt, {"cwd": None}),
            "the user's main checkout": (repo, {}),
            "a pointer-file checkout that is not a linked worktree": (separate, {}),
        }
        for name, (workspace, kw) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(m.CursorBoundaryError, "Maker"):
                self.gateway("maker", workspace, **kw)
        self.assertEqual(self.inference_calls(), [])
        # the same gates are not imposed on the read-only panel role
        self.gateway("panel", repo)

    def test_a_maker_outside_managed_mode_never_gets_a_write_grant_or_a_process(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        # write-capable but not managed: it would otherwise run in a disposable copy while the
        # profile and instruction granted the REAL repository
        st = self.dispatch(repo=wt, adapter=self.maker(), managed=False, mode="make", name="unmanaged")
        self.assertEqual(st["status"], "error")
        self.assertTrue(st["error"].startswith("refused: "), st["error"])
        self.assertIn("managed", st["error"])
        # a managed dispatch whose workspace is the ordinary checkout is refused as well
        st = self.dispatch(repo=repo, adapter=self.maker(), managed=True, mode="make", name="main-checkout")
        self.assertEqual(st["status"], "error")
        self.assertTrue(st["error"].startswith("refused: "), st["error"])
        self.assertIn("linked Git worktree", st["error"])
        self.assertEqual(self.cursor_calls(), [])
        # no profile ever named either directory: only the preflight's fixtures were profiled
        self.assertFalse(any(wt in p or repo in p for p in self.profiles()))


if __name__ == "__main__":
    unittest.main()
