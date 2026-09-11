#!/usr/bin/env python3
"""Tests for the alloy dispatcher, driven by a mock panelist CLI so they cost
no tokens. Run with:  python3 -m unittest discover -s tests -v
"""
import json
import os
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
            {"codex", "grok", "claude", "llm", "opencode", "cursor-agent", "antigravity"},
            names)
        codex = next(p for p in data["panelists"] if p["name"] == "codex")
        self.assertEqual(codex["status"], "ready")

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

    def test_claude_model_override(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "claude"],
                         env_extra={"ALLOY_BIN_CLAUDE": MOCK, "ANTHROPIC_API_KEY": "x",
                                    "ALLOY_CLAUDE_MODEL": "opus"})
        cmd = " ".join(by_name(m, "claude")["command"])
        self.assertIn("--model opus", cmd)

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
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                         env_extra=self._agy_env())
        p = by_name(m, "antigravity")
        staged = os.path.join(os.path.dirname(p["stdout_path"]), "prompt_in", "prompt.md")
        with open(staged) as f:
            self.assertEqual(f.read(), "Say something useful.")
        cmd = " ".join(p["command"])
        self.assertNotIn("Say something useful.", cmd)   # never on argv
        self.assertIn(staged, cmd)                       # pointed at, instead
        # The grant covers the prompt's own directory, not the whole run dir
        # (which holds the other panelists' captured answers).
        self.assertIn("--add-dir " + os.path.dirname(staged), cmd)

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
        self.assertFalse(s["allowNonWorkspaceAccess"])
        # Containment invariant the macOS keychain config leans on: the agy
        # HOME itself (where the generated com.apple.security.plist lives) is
        # never granted as a workspace root, so read tools can't reach it.
        args = by_name(m, "antigravity")["command"]
        add_dirs = [args[i + 1] for i, a in enumerate(args[:-1])
                    if a == "--add-dir"]
        self.assertTrue(add_dirs)
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
        # cursor-agent CAN write -> it must NOT see the real tree; it gets a copy
        # (with .git excluded) so any writes land off your repo.
        repo = self._repo_with_file(name="code.py", body="x = 1")
        os.makedirs(os.path.join(repo, ".git"))
        with open(os.path.join(repo, ".git", "HEAD"), "w") as f:
            f.write("ref: refs/heads/main")
        _proc, m = panel(self.tmp,
                         extra_args=["--panelists", "cursor-agent", "--repo", repo],
                         env_extra={"ALLOY_BIN_CURSOR_AGENT": MOCK,
                                    "CURSOR_API_KEY": "x",
                                    "ALLOY_ALLOW_UNSANDBOXED": "1"})
        p = by_name(m, "cursor-agent")
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


if __name__ == "__main__":
    unittest.main()
