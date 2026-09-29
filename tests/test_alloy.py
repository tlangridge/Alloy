#!/usr/bin/env python3
"""Tests for the alloy dispatcher, driven by a mock panelist CLI so they cost
no tokens. Run with:  python3 -m unittest discover -s tests -v
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ALLOY = os.path.join(REPO, "bin", "alloy")
MOCK = os.path.join(HERE, "mocks", "mock_panelist.py")


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


class AntigravityKeychainAuthUnitTests(unittest.TestCase):
    """The keychain fallback in AntigravityAdapter.is_authed: a fresh agy login
    stores the token ONLY in the login keychain (the token file is written just
    when a keyring save fails), so file checks alone report a healthy install
    as unauthenticated. Hermetic on every platform: HOME points at a fixture
    dir, config/env auth is cleared, sys.platform and the `security` subprocess
    are faked."""

    @classmethod
    def setUpClass(cls):
        cls.f = _import_alloy_module()

    def _is_authed_with(self, fake_run, platform="darwin", token_file=False):
        from unittest import mock
        with tempfile.TemporaryDirectory() as home:
            if token_file:
                d = os.path.join(home, ".gemini", "antigravity-cli")
                os.makedirs(d)
                open(os.path.join(d, "antigravity-oauth-token"), "w").close()
            env = {"HOME": home, "ANTIGRAVITY_API_KEY": "", "GEMINI_API_KEY": "",
                   "GOOGLE_API_KEY": ""}
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(self.f, "_CONFIG", {}), \
                 mock.patch.object(self.f.sys, "platform", platform), \
                 mock.patch.object(self.f.subprocess, "run", fake_run):
                return self.f.AntigravityAdapter().is_authed()

    def test_keychain_item_present_counts_as_authed(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw))
            return subprocess.CompletedProcess(cmd, 0)

        self.assertTrue(self._is_authed_with(fake_run))
        # Metadata-only existence check: never -w, so the secret is never read
        # and no keychain ACL dialog can appear. stdin is detached so an
        # interactive-capable `security` can never consume the caller's input.
        self.assertEqual(len(calls), 1)
        cmd, kw = calls[0]
        self.assertIn("find-generic-password", cmd)
        self.assertNotIn("-w", cmd)
        self.assertEqual(kw.get("stdin"), subprocess.DEVNULL)

    def test_no_keychain_item_means_not_authed(self):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 44)  # errSecItemNotFound

        self.assertFalse(self._is_authed_with(fake_run))

    def test_security_timeout_means_not_authed(self):
        def fake_run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 5)

        self.assertFalse(self._is_authed_with(fake_run))

    def test_security_oserror_means_not_authed(self):
        def fake_run(cmd, **kw):
            raise FileNotFoundError("/usr/bin/security")

        self.assertFalse(self._is_authed_with(fake_run))

    def test_non_darwin_never_probes_keychain(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        self.assertFalse(self._is_authed_with(fake_run, platform="linux"))
        self.assertEqual(calls, [])

    def test_file_auth_short_circuits_keychain_probe(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        self.assertTrue(self._is_authed_with(fake_run, token_file=True))
        self.assertEqual(calls, [])  # no subprocess when a token file exists


@unittest.skipUnless(sys.platform == "darwin", "generated config is macOS-only")
class AntigravityKeychainHomeUnitTests(unittest.TestCase):
    """_home()'s generated keychain config: macOS resolves both the keychain
    search list and the DEFAULT keychain through $HOME, so the isolated HOME
    gets a synthesized com.apple.security.plist with ABSOLUTE paths to the
    real login keychain. It must be a generated file, never a symlink into
    ~/Library -- the state/run dirs get zipped and shared for debugging, and
    archivers dereference symlinks. Hermetic: HOME is a fixture dir."""

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
        env = {"HOME": fixture, "ALLOY_ANTIGRAVITY_HOME": "run",
               "ANTIGRAVITY_API_KEY": api_key, "GEMINI_API_KEY": "",
               "GOOGLE_API_KEY": ""}
        with mock.patch.dict(os.environ, env), \
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


BUILTIN_DENIALS = (".ssh", ".aws", ".gnupg", ".config/gh", ".netrc", ".docker/config.json", ".kube",
                   ".npmrc", ".pypirc", ".git-credentials", "Library/Keychains", ".openclaw/secrets",
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
        self.env = {
            "ALLOY_CONFIG": "/dev/null", "ALLOY_USAGE": "off", "ALLOY_REPO": "none",
            "ALLOY_BIN_CURSOR": MOCK, "MOCK_VERSION": self.VERSION,
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
        for target, value in (("_CONFIG", {}), ("SANDBOX_EXEC", MOCK), ("SANDBOX_TRUSTED_UID", os.getuid()),
                              ("CURSOR_PLATFORM", sys.platform), ("log", lambda msg: None),
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
        return [c for c in self.all_cursor_calls() if c["argv"] != ["--version"]]

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

    def decision(self, profile, op, path):
        return MOCKMOD.sbpl_decision(profile, op, path)

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
        argv = self.mod.cursor_command(role, tail, exe=MOCK, runtime=rt, workspace=repo,
                                       staged=ctx["cursor_staged"], **kw)
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
        self.assertEqual(ad.effective_model(), "composer-2.5")
        self.setenv(ALLOY_CURSOR_AGENT_EFFORT="low")
        self.assertEqual(ad.effort(), "low")
        self.setenv(ALLOY_CURSOR_EFFORT="HIGH")
        self.assertEqual(ad.effort(), "high")
        self.assertEqual(ad.effective_model(), "composer-2.5[effort=high]")
        self.setenv(ALLOY_CURSOR_EFFORT="inherit")
        self.assertIsNone(ad.effort())
        for bad in ("ultra", "extreme"):
            self.setenv(ALLOY_CURSOR_EFFORT=bad)
            with self.assertRaises(self.mod.CursorBoundaryError):
                ad.effective_model()
        self.setenv(ALLOY_CURSOR_EFFORT=None, ALLOY_CURSOR_AGENT_EFFORT=None)
        for bad in ("auto", "muse-spark-1", "composer-2.5-fast", "composer-2.5[fast=true]"):
            self.setenv(ALLOY_CURSOR_MODEL=bad)
            with self.assertRaises(self.mod.CursorBoundaryError, msg=bad):
                ad.effective_model()

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
        for mode in ("read_allowed", "write_leak", "link_leak", "exec_leak", "garbage", "noout", "fail", "cli_fail"):
            with self.subTest(preflight=mode):
                self.setenv(MOCK_SANDBOX_PREFLIGHT=mode)
                self._not_ready(mode)
        self.setenv(MOCK_SANDBOX_PREFLIGHT="pass")
        for version in ("2026.01.01-abcdef0", "9.9.9", "2026.09.27-ffff"):
            with self.subTest(version=version):
                self.setenv(MOCK_VERSION=version)
                self._not_ready(version)
        self.setenv(MOCK_VERSION=self.VERSION)
        for entry in ("relative/path", "", "/a/../b", "/a/*", "/a//b", "/a,,/b", "~/x"):
            with self.subTest(deny_paths=entry):
                self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=entry or " ")
                self._not_ready(entry)
        self.setenv(ALLOY_CURSOR_DENY_READ_PATHS=os.path.dirname(MOCK))     # covers the CLI itself
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
                    self.assertFalse(m.cursor_boundary(MOCK).ready)
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
        with self.mock.patch.object(self.mod, "CURSOR_SANDBOX_PROFILE_VERSION", 2):
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

    def test_status_and_version_go_through_the_sandbox_wrapper(self):
        ad = self.mod.CursorAgentAdapter()
        self.assertEqual(ad.auth_state(), "ready")
        rc, text = self.mod.cursor_metadata("version", MOCK)
        self.assertEqual((rc, text.strip()), (0, self.VERSION))
        with open(self.sblog) as f:
            launched = [json.loads(line)["cmd"][0] for line in f]
        self.assertEqual(set(launched), {"/bin/bash", os.path.realpath(MOCK)})       # nothing else was ever exec'd
        self.assertEqual([c["argv"] for c in self.cursor_calls()], [["status"]])
        with self.assertRaises(self.mod.CursorBoundaryError):
            self.mod.cursor_command("bogus", ["status"], exe=MOCK, runtime=self.runtime())


class CursorProfileTests(CursorCase):
    def test_panel_profile_allows_only_the_private_runtime(self):
        repo = self.repo()
        wt = make_worktree(repo, os.path.join(self.tmp, "wt"))
        rt = self.runtime()
        argv, prof, _ = self.gateway("panel", wt, rt)
        home = self.mod.cursor_login_home()
        d = lambda op, path: self.decision(prof, op, path)
        self.assertEqual(argv[:3], [MOCK, "-f", rt.profile])
        for base in (rt.state, rt.cache, rt.tmp):
            self.assertEqual(d("file-write-create", base + "/x"), "allow", base)
            self.assertEqual(d("file-write-data", base + "/a/b"), "allow", base)
        self.assertEqual(d("file-write-data", "/dev/null"), "allow")
        denied = [wt + "/tracked.txt", wt + "/new.txt", wt + "/.git", repo + "/x", repo + "/.git/config",
                  home + "/x", home + "/.cursor/x", home + "/.local/share/cursor-agent/versions/x",
                  home + "/Library/Caches/x", home + "/.config/x", os.path.dirname(MOCK) + "/x",
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
        self.assertEqual(d("process-exec", MOCK), "allow")                  # the resolved CLI only
        for tool in ("/usr/bin/true", "/bin/bash", "/bin/sh", "/usr/bin/env", "/usr/bin/git", "/usr/bin/security"):
            self.assertEqual(d("process-exec", tool), "deny", tool)
        self.assertEqual(d("file-read-data", wt + "/tracked.txt"), "allow")      # reads of the repo stay possible
        self.assertEqual(d("file-read-data", MOCK), "allow")
        self.assertEqual(d("network-outbound", "/x"), "allow")                  # the provider network is needed

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
        self.assertNotIn("(deny process-exec", prof)
        # The Git denials come after the broader worktree grant, or they would not win.
        lines = prof.splitlines()
        grant = next(i for i, l in enumerate(lines) if l.startswith("(allow file-write*") and wt in l)
        gitdeny = next(i for i, l in enumerate(lines) if l.startswith("(deny file-write*") and "/.git" in l)
        self.assertGreater(gitdeny, grant)

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
            self.mod.cursor_command(kind, self.mod._CURSOR_METADATA[kind], exe=MOCK, runtime=rt)
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
            self.assertEqual(self.decision(prof, "file-read-data", "/private/tmp/anvil-secret.abc123"), "deny")
            self.assertEqual(self.decision(prof, "file-read-data", "/private/tmp/anvil-secret.abc/x"), "deny")
            self.assertEqual(self.decision(prof, "file-read-data", "/private/tmp/other"), "allow")
            # Alloy's own secrets root and the future `alloy secrets` store
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "routing", "jev-key")), "deny")
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "state", "alloy", "secrets", "k")), "deny")
            # ... while the run state Cursor must read (staged prompt, worktrees) stays readable
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "state", "alloy", "runs", "x")), "allow")
            self.assertEqual(self.decision(prof, "file-read-data", os.path.join(self.tmp, "state", "alloy", "execution", "worktrees", "x")), "allow")

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

    def test_denial_parsing_and_escaping(self):
        m = self.mod
        home = m.cursor_login_home()
        tricky = os.path.join(self.tmp, 'we"ird\\dir')
        self.assertEqual(m._sb_path(tricky), '"' + self.tmp + '/we\\"ird\\\\dir"')
        rt = self.runtime()
        prof = m.cursor_sbpl("panel", exe=MOCK, runtime=rt, denials=m.CursorDenials((tricky,), ()))
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
            prof = m.cursor_sbpl("panel", exe=MOCK, runtime=rt, denials=den)
        self.assertEqual(self.decision(prof, "file-read-data", home + "/.ssh/id"), "deny")
        self.assertEqual(self.decision(prof, "file-read-data", home + "/dotfiles-ssh/id"), "deny")

    def test_login_home_is_never_taken_from_the_environment(self):
        import pwd
        self.setenv(HOME=self.tmp)
        self.assertEqual(self.mod.cursor_login_home(), os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir))

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
            m.cursor_sbpl("maker", exe=MOCK, runtime=rt, denials=m.cursor_denials(), worktree=None)
        with self.assertRaises(m.CursorBoundaryError):
            m.cursor_sbpl("nonsense", exe=MOCK, runtime=rt, denials=m.cursor_denials())

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


class CursorGrammarTests(CursorCase):
    def good(self, role="panel", ws=None):
        ws = ws or os.path.join(self.tmp, "ws")
        os.makedirs(ws, exist_ok=True)
        staged = os.path.join(self.tmp, "prompt_in", "prompt.md")
        instr = self.mod.cursor_instruction(role, staged, os.path.realpath(ws))
        argv = ["-p"] + (["--mode", "ask"] if role == "panel" else []) + [
            "--output-format", "json", "--workspace", ws, "--model", "composer-2.5", "--trust",
            "--sandbox", "enabled", "--skip-worktree-setup", instr]
        return argv, ws, staged

    def check(self, role, argv, ws, staged):
        self.mod.cursor_validate_argv(role, argv, workspace=ws, staged=staged)

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
            ["--sandbox", "disabled"], ["--sandbox", "enabled"], ["--output-format", "text"],
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
                "empty model": [("" if a == "composer-2.5" else a) for a in argv],
                "bracketed unknown": [("kimi-k3[effort=low]" if a == "composer-2.5" else a) for a in argv],
                "sandbox disabled": [("disabled" if a == "enabled" else a) for a in argv],
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
            self.mod.cursor_command("panel", argv[:-1] + ["--force", argv[-1]], exe=MOCK, runtime=rt, workspace=ws, staged=staged)
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
            "sandbox disabled": set_value("--sandbox", "disabled"),
            "model auto": set_value("--model", "auto"),
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
                                                          "CURSOR_API_ENDPOINT": "https://cfg-poison.invalid"}):
            ad = self.mod.CursorAgentAdapter()
            self.assertEqual(ad.auth_state(), "ready")                  # status
            self.mod.cursor_metadata("version", MOCK)                   # version
            st = self.dispatch(repo=repo, adapter=ad)                   # panel
        self.assertEqual(st["status"], "ok", st)
        calls = self.all_cursor_calls()
        self.assertEqual({tuple(c["argv"][:1]) for c in calls if "--skip-worktree-setup" not in c["argv"]},
                         {("status",), ("--version",)})                    # status, version (preflight) ... and:
        self.assertEqual(len(self.inference_calls()), 1)                    # ... the panel call
        for call in calls:
            for name in ("CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
                self.assertIsNone(call["env"][name], (call["argv"][:1], name))
            joined = " ".join(call["argv"])
            for flag in ("--api-key", "--endpoint", "--header", "-e ", "-H ", "--force", "--yolo"):
                self.assertNotIn(flag, joined)
        blob = json.dumps(st)
        self.assertNotIn("poison", blob)
        with open(os.path.join(self.tmp, "runs", "r", "cursor", "status.json")) as f:
            self.assertNotIn("poison", f.read())
        for name in ("stdout.txt", "result.md"):
            with open(os.path.join(self.tmp, "runs", "r", "cursor", name)) as f:
                self.assertNotIn("poison", f.read())
        with open(self.sblog) as f:
            self.assertNotIn("poison", f.read())


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
        tail = cmd[4:]                                                        # sandbox-exec -f <profile> <exe> <tail>
        self.assertEqual(tail[:2], ["-p", "--mode"])
        self.assertEqual(tail.count("--mode"), 1)
        self.assertEqual(tail[tail.index("--mode") + 1], "ask")
        self.assertEqual(tail[tail.index("--output-format") + 1], "json")
        self.assertEqual(tail[tail.index("--model") + 1], "composer-2.5")
        self.assertEqual(tail[tail.index("--sandbox") + 1], "enabled")
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
        self.assertEqual(st["command"][st["command"].index("--model") + 1], "gpt-5.6-sol-high[effort=max]")
        self.assertEqual(st["model"], "gpt-5.6-sol-high")

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
        self.assertEqual([c["argv"] for c in calls], [["status"]])
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
        # the only executables Alloy starts for Cursor are the sandbox wrapper and git
        self.assertEqual({os.path.basename(argv[0]) for argv in spawned}, {"mock_panelist.py", "git"})



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
                 ("malformed", {}, "JSON"), ("no_result", {}, "result"), ("nonstring", {}, "result"),
                 ("nonobject", {}, "JSON"), ("ok", {"MOCK_CURSOR_EXIT": "3"}, None)]
        for i, (mode, extra, needle) in enumerate(cases):
            with self.subTest(mode=mode, extra=extra):
                self.setenv(MOCK_CURSOR_JSON=mode, MOCK_CURSOR_EXIT=extra.get("MOCK_CURSOR_EXIT", "0"))
                st = self.dispatch(repo=repo, name="c%d" % i)
                self.assertEqual(st["status"], "error")
                if needle:
                    self.assertIn(needle, st["error"])
                if mode == "is_error":
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
        cases = {"jwt": [GOOD_JWT], "assignment": ["hunter2hunter2hunter2"], "header": ["abc123def456ghi789"]}
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
                self.assertGreaterEqual(st["secrets_redacted"], 3)
                self.assertNotIn(secrets[0], json.dumps(st))                    # nor the value returned for the manifest

    def test_secret_in_stderr_tail_is_absent_from_status_json_error(self):
        self.setenv(MOCK_CURSOR_JSON="jwt_empty")
        st = self.dispatch(repo=self.repo())
        self.assertEqual(st["status"], "empty")
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
            opened[fd] = path
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

    def test_canary_mutation_outside_the_runtime_fails_the_call(self):
        self.setenv(MOCK_TAMPER_CANARY="1")
        st = self.dispatch(repo=self.repo())
        self.assertEqual(st["status"], "error")
        self.assertIn("sandbox tripwire", st["error"])
        self.assertIn("1 canary", st["error"])

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
        self.assertEqual(tail[tail.index("--sandbox") + 1], "enabled")
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


if __name__ == "__main__":
    unittest.main()
