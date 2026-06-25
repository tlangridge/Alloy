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


def run_alloy(args, env_extra=None, timeout=60):
    env = dict(os.environ)
    # Hermetic: the default panel is now "all available" adapters, and a dev
    # machine has real grok/claude/etc. installed. Ignore the user config and pin
    # the panel to the two mocked adapters so no real CLI is ever spawned. Tests
    # that exercise another adapter pass --panelists explicitly (the CLI flag
    # overrides this env).
    env["ALLOY_CONFIG"] = "/dev/null"
    env["ALLOY_PANELISTS"] = "codex,claude"
    # Point both adapters at the mock and make them look authenticated.
    env["ALLOY_BIN_CODEX"] = MOCK
    env["ALLOY_BIN_CLAUDE"] = MOCK
    env["CODEX_API_KEY"] = "test"
    env["ANTHROPIC_API_KEY"] = "test"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, ALLOY] + args,
        capture_output=True, text=True, env=env, timeout=timeout,
    )
    return proc


def panel(tmp, env_extra=None, extra_args=None, timeout=60):
    prompt = os.path.join(tmp, "p.txt")
    with open(prompt, "w") as f:
        f.write("Say something useful.")
    args = ["panel", "--prompt-file", prompt, "--run-dir", os.path.join(tmp, "runs")]
    if extra_args:
        args += extra_args
    proc = run_alloy(args, env_extra=env_extra, timeout=timeout)
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
        # antigravity has no read-only mode -> refused/skipped by default (even
        # when listed explicitly, unless ALLOY_ALLOW_UNSANDBOXED=1), so this
        # exercises the 0-panelist Claude-only fallback without invoking any real
        # CLI (and without spending tokens).
        proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"])
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(m["panelists"], [])
        self.assertIn("note", m["summary"])
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

    def test_antigravity_refused_without_unsandboxed(self):
        # agy (`antigravity`) has no read-only mode -> read_only=False, so even
        # when listed explicitly it is skipped unless ALLOY_ALLOW_UNSANDBOXED=1.
        proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                        env_extra={"ALLOY_BIN_ANTIGRAVITY": MOCK,
                                   "ANTIGRAVITY_API_KEY": "x"})
        self.assertEqual(proc.returncode, 3)  # 0 panelists -> Claude-only fallback
        self.assertIsNone(by_name(m, "antigravity"))  # never dispatched
        skipped = {s["name"]: s["reason"] for s in m["summary"]["skipped"]}
        self.assertIn("antigravity", skipped)
        self.assertIn("read-only", skipped["antigravity"])

    def test_antigravity_runs_unsandboxed_print_mode(self):
        # Opt in: it dispatches headless via `-p`, prompt on stdin, and MUST NOT
        # carry the auto-approve bypass flag (the adapter never adds it).
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                         env_extra={"ALLOY_BIN_ANTIGRAVITY": MOCK,
                                    "ANTIGRAVITY_API_KEY": "x",
                                    "ALLOY_ALLOW_UNSANDBOXED": "1"})
        p = by_name(m, "antigravity")
        self.assertEqual(p["status"], "ok")
        cmdlist = p["command"]
        self.assertIn("-p", cmdlist)
        cmd = " ".join(cmdlist)
        self.assertNotIn("--dangerously-skip-permissions", cmd)

    def test_antigravity_model_override(self):
        _proc, m = panel(self.tmp, extra_args=["--panelists", "antigravity"],
                         env_extra={"ALLOY_BIN_ANTIGRAVITY": MOCK,
                                    "ANTIGRAVITY_API_KEY": "x",
                                    "ALLOY_ALLOW_UNSANDBOXED": "1",
                                    "ALLOY_ANTIGRAVITY_MODEL": "gemini-3.1-pro"})
        cmd = " ".join(by_name(m, "antigravity")["command"])
        self.assertIn("--model gemini-3.1-pro", cmd)

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


class RedactionUnitTests(unittest.TestCase):
    """Drive redact_secrets / cap_chars / strip_ansi directly by importing the
    dispatcher as a module."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        import importlib.machinery
        # bin/alloy has no .py extension, so give importlib an explicit loader.
        loader = importlib.machinery.SourceFileLoader("alloy_mod", ALLOY)
        spec = importlib.util.spec_from_loader("alloy_mod", loader)
        cls.f = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.f)

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
