#!/usr/bin/env python3
"""Tests for the fusion dispatcher, driven by a mock panelist CLI so they cost
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
FUSION = os.path.join(REPO, "bin", "fusion")
MOCK = os.path.join(HERE, "mocks", "mock_panelist.py")


def run_fusion(args, env_extra=None, timeout=60):
    env = dict(os.environ)
    # Point both adapters at the mock and make them look authenticated.
    env["FUSION_BIN_CODEX"] = MOCK
    env["FUSION_BIN_GEMINI"] = MOCK
    env["CODEX_API_KEY"] = "test"
    env["GEMINI_API_KEY"] = "test"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, FUSION] + args,
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
    proc = run_fusion(args, env_extra=env_extra, timeout=timeout)
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


class FusionTests(unittest.TestCase):
    def setUp(self):
        os.chmod(MOCK, 0o755)
        self.tmp = tempfile.mkdtemp(prefix="fusiontest-")

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
        proc, m = panel(self.tmp, env_extra={"FUSION_BIN_CODEX": "/no/such/binary"})
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
        proc = run_fusion(["doctor", "--json"])
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        names = {p["name"] for p in data["panelists"]}
        self.assertEqual({"codex", "gemini", "antigravity"}, names)
        codex = next(p for p in data["panelists"] if p["name"] == "codex")
        self.assertEqual(codex["status"], "ready")

    def test_empty_prompt_refused(self):
        empty = os.path.join(self.tmp, "empty.txt")
        open(empty, "w").close()
        proc = run_fusion(["panel", "--prompt-file", empty])
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
