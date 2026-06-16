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
    # Point both adapters at the mock and make them look authenticated.
    env["ALLOY_BIN_CODEX"] = MOCK
    env["ALLOY_BIN_GEMINI"] = MOCK
    env["CODEX_API_KEY"] = "test"
    env["GEMINI_API_KEY"] = "test"
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
        for name in ("codex", "gemini"):
            p = by_name(m, name)
            self.assertEqual(p["status"], "ok")
            self.assertTrue(os.path.isfile(p["result_path"]))
            with open(p["result_path"]) as f:
                self.assertIn("MOCK", f.read())

    def test_partial_failure(self):
        # codex ok, gemini fails -> proceed with 1, mark the other failed
        proc, m = panel(self.tmp, env_extra={"MOCK_BEHAVIOR_GEMINI": "fail"})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(m["summary"]["ok"], 1)
        self.assertEqual(by_name(m, "codex")["status"], "ok")
        self.assertEqual(by_name(m, "gemini")["status"], "error")
        self.assertEqual(by_name(m, "gemini")["exit_code"], 3)

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
        # antigravity has no binary and no read-only mode -> always skipped, so
        # this exercises the 0-panelist Claude-only fallback without invoking any
        # real CLI (and without spending tokens).
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
        self.assertEqual({"codex", "gemini", "antigravity"}, names)
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
