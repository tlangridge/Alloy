#!/usr/bin/env python3
"""Frontier CLI adapters: Muse (`muse exec`), Claude effort overrides and agy >= 1.3.4
stream-json input. Every CLI here is a fake script the test writes into a temp dir and
drives through the real dispatch path (run_panelist); no live model is ever called.
Run with:  python3 -m unittest discover -s tests -p test_frontier_adapters.py -v
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOY = os.path.join(os.path.dirname(HERE), "bin", "alloy")


def load_alloy():
    # bin/alloy has no .py extension, so give importlib an explicit loader.
    loader = importlib.machinery.SourceFileLoader("alloy_frontier", ALLOY)
    spec = importlib.util.spec_from_loader("alloy_frontier", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# A fake `muse`: records argv, the kind of stdin it got and two launcher env knobs,
# then prints `exec --json` records -- the prompt echo and FAKE_BULK output deltas
# first, the terminal record last -- the way the real CLI orders them.
FAKE_MUSE = r'''#!%(python)s
import json, os, stat, sys
argv = sys.argv[1:]
if argv == ["--version"]:
    print("Muse Code 9.9.9 (fake)"); sys.exit(0)
mode = os.environ.get("FAKE_MUSE", "ok")
st = os.fstat(0).st_mode
with open(os.environ["FAKE_DUMP"], "w") as fh:
    json.dump({"argv": argv, "stdin_chr": stat.S_ISCHR(st), "stdin_reg": stat.S_ISREG(st),
               "stdin_fifo": stat.S_ISFIFO(st), "stdin_bytes": len(sys.stdin.buffer.read()),
               "env": {k: os.environ.get(k) for k in ("MUSE_NO_AUTO_UPDATE", "MUSE_LOGIN")}}, fh)
if mode == "empty":
    sys.exit(0)
def emit(kind, payload):
    sys.stdout.write(json.dumps({"schema_version": 1, "record_type": "event", "payload_type": kind,
                                 "payload": payload}) + "\n")
prompt = open(argv[argv.index("--prompt-file") + 1], encoding="utf-8").read()
emit("runtime.command.accepted", {"kind": "command_accepted", "command_kind": "turn.submit"})
emit("turn.input.user", {"kind": "turn_input_user", "prompt": prompt})
for _ in range(int(os.environ.get("FAKE_BULK", "0"))):
    emit("run.output.delta", {"kind": "run_output_delta", "text": "D" * 1000})
text = os.environ.get("FAKE_ANSWER", "MUSE ANSWER sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123 end")
terminal = {"ok": ("completed", "completed", None),
            "failed": ("failed", "failed", "provider quota exhausted"),
            "cancelled": ("cancelled", "cancelled", {"code": "user_cancelled"}),
            "mismatch": ("completed", "failed", "inconsistent terminal")}.get(mode)
if terminal:
    kind, state, reason = terminal
    emit("run.terminal." + kind, {"kind": "run_terminal", "terminal": state, "text": text, "reason": reason})
'''

# A fake `agy` for the stream-json path. It reads stdin to EOF before answering, so a
# writer that never closed the pipe would hang the dispatch into its timeout.
FAKE_AGY = r'''#!%(python)s
import json, os, stat, sys
argv = sys.argv[1:]
if argv == ["--version"]:
    print(os.environ.get("FAKE_AGY_VERSION", "1.3.4")); sys.exit(0)
mode = os.environ.get("FAKE_AGY", "ok")
st = os.fstat(0).st_mode
data = sys.stdin.buffer.read()
lines = [ln for ln in data.decode("utf-8").split("\n") if ln]
with open(os.environ["FAKE_DUMP"], "w") as fh:
    json.dump({"argv": argv, "stdin_fifo": stat.S_ISFIFO(st), "stdin_reg": stat.S_ISREG(st),
               "stdin_chr": stat.S_ISCHR(st), "lines": lines, "home": os.environ.get("HOME")}, fh)
if mode == "empty":
    sys.exit(0)
if "-p" in argv:                          # an older agy: plain text print mode
    print("AGY PLAIN ANSWER"); sys.exit(0)
def emit(event):
    sys.stdout.write(json.dumps(event) + "\n"); sys.stdout.flush()
emit({"event": "init", "conversation_id": "c1"})
for _ in range(int(os.environ.get("FAKE_BULK", "0"))):
    emit({"event": "message", "delta": "D" * 1000})
usage = {"input_tokens": 800, "output_tokens": 40, "thinking_tokens": 15,
         "cache_read_tokens": 300, "total_tokens": 840}
result = {"conversation_id": "c1", "status": "SUCCESS", "response": "AGY ANSWER",
          "error": "", "duration_seconds": 1, "num_turns": 3, "usage": usage}
if mode == "error":
    result.update(status="ERROR", response="",
                  error="tool required the write_file permission")
elif mode == "success_with_error":
    result.update(error="model stream interrupted")
elif mode == "agy_error":
    sys.stderr.write('AGY_ERROR: {"status": "UNAVAILABLE", "retryable": true}\n')
if mode != "no_result":
    emit({"event": "result", "result": result})
'''

# A fake `claude` that proves the unchanged stdin path: the prompt FILE itself, byte-exact.
FAKE_CLAUDE = r'''#!%(python)s
import hashlib, json, os, stat, sys
argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.0 (fake)"); sys.exit(0)
st = os.fstat(0).st_mode
data = sys.stdin.buffer.read()
with open(os.environ["FAKE_DUMP"], "w") as fh:
    json.dump({"argv": argv, "stdin_reg": stat.S_ISREG(st), "stdin_fifo": stat.S_ISFIFO(st),
               "sha256": hashlib.sha256(data).hexdigest()}, fh)
sys.stdout.write(json.dumps({"type": "system", "subtype": "init"}) + "\n")
sys.stdout.write(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                             "result": "CLAUDE ANSWER"}) + "\n")
'''

SECRET = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123"
FORBIDDEN_MUSE_FLAGS = ("--yolo", "--disable-approval", "--disable-sandbox", "--trust-workspace",
                        "--approval-mode", "--api-key-stdin", "--enable-shell-tool")


class FrontierCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = load_alloy()

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="alloy-frontier-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dump = os.path.join(self.tmp, "dump.json")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.prompt = os.path.join(self.tmp, "prompt.txt")
        self.prompt_text = 'Review "this"\nline two   café {"event": "x"}\n'
        with open(self.prompt, "w", encoding="utf-8") as fh:
            fh.write(self.prompt_text)
        env = {"ALLOY_CONFIG": "/dev/null", "ALLOY_USAGE": "off", "ALLOY_CAPTURE_USAGE": "",
               "ALLOY_ROUTING_HOME": os.path.join(self.tmp, "routing"), "ALLOY_WEB": "",
               "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
               "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"), "FAKE_DUMP": self.dump,
               "FAKE_BULK": "0", "FAKE_ANSWER": "", "FAKE_MUSE": "ok", "FAKE_AGY": "ok"}
        for key in ("ALLOY_CLAUDE_EFFORT", "ALLOY_CLAUDE_MODEL", "ALLOY_MUSE_MODEL", "ALLOY_MUSE_EFFORT",
                    "ALLOY_ANTIGRAVITY_MODEL", "ALLOY_ANTIGRAVITY_EFFORT", "ALLOY_ANTIGRAVITY_HOME",
                    "ALLOY_CLAUDE_LEAN", "META_API_KEY", "LLAMA_API_KEY", "MUSE_AUTH_PATH",
                    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ALLOY_PANELISTS"):
            env[key] = ""
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("FAKE_ANSWER")       # unset: each fake uses its own default answer
        for target, value in (("_CONFIG", {}), ("log", lambda msg: None)):
            p = mock.patch.object(self.f, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.count = 0

    def fake(self, name, body):
        path = os.path.join(self.tmp, "bin", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(body % {"python": sys.executable})
        os.chmod(path, 0o755)
        return path

    def dispatch(self, adapter, mode="consult", max_chars=1000, timeout_s=30, repo=None, **env):
        self.count += 1
        with mock.patch.dict(os.environ, env):
            return self.f.run_panelist(adapter, self.prompt, os.path.join(self.tmp, "runs", "p%d" % self.count),
                                       timeout_s, max_chars, mode, repo=repo)

    def read(self, st, key):
        with open(st[key], encoding="utf-8") as fh:
            return fh.read()

    def dumped(self):
        with open(self.dump) as fh:
            return json.load(fh)


# --------------------------------------------------------------------------- #
# Muse
# --------------------------------------------------------------------------- #
class MuseAdapterTests(FrontierCase):
    def setUp(self):
        super().setUp()
        os.environ["ALLOY_BIN_MUSE"] = self.fake("muse", FAKE_MUSE)
        self.ad = self.f.MuseAdapter()

    def test_read_only_argv_defaults_and_no_bypass(self):
        args = self.ad.build_args(self.prompt, "", "consult", {"repo": self.repo, "cwd": self.repo})
        self.assertEqual(args, [
            "exec", "--json", "--prompt-file", self.prompt, "--workspace", self.repo,
            "--disable-write", "--disable-shell", "--no-session-log", "--disable-reminders",
            "--no-foreign-personal-context", "--model", "muse-wonder-full-1.0", "--reasoning-effort", "xhigh"])
        for flag in FORBIDDEN_MUSE_FLAGS:
            self.assertNotIn(flag, args)
        self.assertNotIn("line two", " ".join(args))        # the prompt is a file, never argv
        self.assertFalse(self.ad.stdin_from_prompt)
        self.assertFalse(self.ad.stream_input)
        self.assertTrue(self.ad.read_only)
        self.assertFalse(self.ad.experimental)

    def test_no_repo_roots_tools_at_the_run_cwd_and_web_off_disables_web_tools(self):
        cwd = os.path.join(self.tmp, "empty")
        args = self.ad.build_args(self.prompt, "", "consult", {"repo": None, "cwd": cwd})
        self.assertEqual(args[args.index("--workspace") + 1], cwd)
        self.assertNotIn("--disable-web-tools", args)
        with mock.patch.dict(os.environ, {"ALLOY_WEB": "0"}):
            args = self.ad.build_args(self.prompt, "", "consult", {"repo": None, "cwd": cwd})
        self.assertIn("--disable-web-tools", args)
        self.assertIn("--disable-write", args)
        self.assertIn("--disable-shell", args)

    def test_user_model_and_effort_pins_win(self):
        with mock.patch.dict(os.environ, {"ALLOY_MUSE_MODEL": "muse-spark-1.3", "ALLOY_MUSE_EFFORT": "medium"}):
            args = self.ad.build_args(self.prompt, "", "consult", {"cwd": self.tmp})
            self.assertEqual(self.ad.model(), "muse-spark-1.3")
        self.assertEqual(args[args.index("--model") + 1], "muse-spark-1.3")
        self.assertEqual(args[args.index("--reasoning-effort") + 1], "medium")
        for inherit in ("inherit", "default", "Default"):
            with mock.patch.dict(os.environ, {"ALLOY_MUSE_EFFORT": inherit}):
                args = self.ad.build_args(self.prompt, "", "consult", {"cwd": self.tmp})
            self.assertNotIn("--reasoning-effort", args, inherit)
            self.assertNotIn("--effort", args, inherit)

    def test_a_write_capable_role_is_refused_before_spawn(self):
        writer = self.f.MuseAdapter()
        writer.__class__ = type("ManagedMuseAdapter", (self.f.MuseAdapter,), {"read_only": False})
        with self.assertRaises(self.f.CursorBoundaryError):
            writer.build_args(self.prompt, "", "make", {"cwd": self.tmp})
        st = self.dispatch(writer, mode="make")
        self.assertEqual(st["status"], "error")
        self.assertTrue(st["error"].startswith("refused:"), st["error"])
        self.assertFalse(os.path.exists(self.dump))           # nothing was spawned

    def test_registered_for_doctor_and_the_default_panel(self):
        self.assertIs(type(self.f.ADAPTERS["muse"]), self.f.MuseAdapter)
        with mock.patch.dict(self.f.ADAPTERS, {"muse": self.ad}, clear=True):
            self.assertEqual(self.ad.auth_state(), "installed_not_authed")
            self.assertEqual(self.f.default_panel_names(), ["muse"])   # read-only, not experimental
            with mock.patch.dict(os.environ, {"META_API_KEY": "k"}):
                self.assertEqual(self.ad.auth_state(), "ready")
                row = self.f._doctor_rows()[0]
            self.assertEqual((row["name"], row["status"], row["read_only"], row["default_panel"]),
                             ("muse", "ready", True, True))
            self.assertEqual(row["model"], "muse-wonder-full-1.0")
            self.assertEqual(row["cli_version"], "Muse Code 9.9.9 (fake)")
            self.assertEqual(row["auth"], "authenticated")
        auth = os.path.join(os.environ["XDG_CONFIG_HOME"], "muse", "auth.json")
        os.makedirs(os.path.dirname(auth))
        open(auth, "w").close()
        self.assertTrue(self.ad.is_authed())                    # file login evidence, never read
        with mock.patch.dict(os.environ, {"MUSE_AUTH_PATH": os.path.join(self.tmp, "none.json")}):
            self.assertFalse(self.ad.is_authed())

    def test_completed_terminal_is_the_answer_and_only_it_is_persisted(self):
        st = self.dispatch(self.ad, repo=self.repo, FAKE_BULK="20")
        self.assertEqual(st["status"], "ok", st.get("error"))
        self.assertRegex(self.read(st, "result_path"), r"^MUSE ANSWER \[REDACTED[^\]]*\] end$")
        stdout = self.read(st, "stdout_path")
        self.assertEqual([json.loads(ln)["payload_type"] for ln in stdout.strip().split("\n")],
                         ["run.terminal.completed"])                    # no deltas, no prompt echo
        self.assertNotIn("line two", stdout)
        for key in ("stdout_path", "result_path"):
            self.assertNotIn(SECRET, self.read(st, key))
        seen = self.dumped()
        self.assertTrue(seen["stdin_chr"])                     # DEVNULL: the prompt is never on stdin
        self.assertEqual(seen["stdin_bytes"], 0)
        self.assertEqual(seen["env"], {"MUSE_NO_AUTO_UPDATE": "1", "MUSE_LOGIN": "0"})
        self.assertEqual(seen["argv"][seen["argv"].index("--workspace") + 1], self.repo)
        self.assertEqual(st["permissions"]["os_isolation"], False)   # CLI policy, not an OS boundary
        self.assertNotIn("usage", st)                                # no invented usage or quota

    def test_late_terminal_survives_a_transcript_far_beyond_the_head_cap(self):
        st = self.dispatch(self.ad, max_chars=100, FAKE_BULK="200", FAKE_ANSWER="late answer")
        self.assertGreater(st["output_bytes"], 100 * 4 * 100)
        self.assertEqual((st["status"], self.read(st, "result_path")), ("ok", "late answer"))

    def test_failed_and_cancelled_terminals_are_errors_never_analysis(self):
        for mode, needle in (("failed", "Muse run failed: provider quota exhausted"),
                             ("cancelled", 'Muse run cancelled: {"code": "user_cancelled"}'),
                             ("mismatch", "Muse run failed: inconsistent terminal")):
            with self.subTest(mode=mode):
                st = self.dispatch(self.ad, FAKE_MUSE=mode, FAKE_ANSWER="partial analysis")
                self.assertEqual(st["exit_code"], 0)
                self.assertEqual(st["status"], "error")
                self.assertIn(needle, st["error"])
                self.assertEqual(self.read(st, "result_path"), "")

    def test_no_terminal_record_or_no_output_is_empty_never_ok(self):
        # A stream that never reached its terminal record (crash, kill) keeps nothing,
        # exactly as Claude's stream without a `result`: the shared empty classification.
        for mode in ("no_terminal", "empty"):
            with self.subTest(mode=mode):
                st = self.dispatch(self.ad, FAKE_MUSE=mode, FAKE_BULK="3")
                self.assertEqual(st["status"], "empty")
                self.assertEqual(self.read(st, "result_path"), "")

    def test_parse_reads_only_the_final_completed_record(self):
        def rec(kind, **payload):
            return json.dumps({"payload_type": kind, "payload": payload})
        done = rec("run.terminal.completed", terminal="completed", text="  final  ", reason=None)
        failed = rec("run.terminal.failed", terminal="failed", text="partial", reason="boom")
        self.assertEqual(self.ad.parse(done + "\n", "", ""), "final")
        self.assertEqual(self.ad.parse(done + "\n" + failed + "\n", "", ""), "")
        self.assertEqual(self.ad.parse(rec("run.output.delta", text="streamed") + "\n", "", ""), "")
        self.assertEqual(self.ad.parse("plain text answer\n", "", ""), "")
        self.assertEqual(self.ad.output_error("plain text answer\n", ""), "Muse output has no run.terminal record")
        bad = rec("run.terminal.completed", terminal="completed", text=5)
        self.assertEqual(self.ad.output_error(bad, ""), "Muse terminal record has no string text")


# --------------------------------------------------------------------------- #
# Claude effort overrides
# --------------------------------------------------------------------------- #
class ClaudeEffortTests(FrontierCase):
    def effort_args(self, adapter=None, **env):
        with mock.patch.dict(os.environ, env):
            args = (adapter or self.f.ClaudeAdapter()).build_args(self.prompt, "", "consult", {})
        return [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--effort"], args

    def test_override_reaches_effort_verbatim(self):
        for value in ("low", "max", "xhigh", "High"):
            with self.subTest(value=value):
                efforts, args = self.effort_args(ALLOY_CLAUDE_EFFORT=value, ALLOY_CLAUDE_MODEL="opus")
                self.assertEqual(efforts, [value])            # no alias, no lowering, no case change
                self.assertEqual(args[args.index("--model") + 1], "opus")
                self.assertEqual(args[args.index("--permission-mode") + 1], "plan")

    def test_unset_inherit_and_default_send_no_effort(self):
        for value in ("", "inherit", "default", "INHERIT"):
            with self.subTest(value=value):
                self.assertEqual(self.effort_args(ALLOY_CLAUDE_EFFORT=value)[0], [])

    def test_routed_decision_replaces_the_override(self):
        r = self.f.routing
        for decision_effort, expected in (("low", ["low"]), (None, [])):
            with self.subTest(decision_effort=decision_effort):
                ad = r.routed_adapter(self.f, {"cli": "claude", "model": "sonnet", "effort": decision_effort})
                efforts, args = self.effort_args(ad, ALLOY_CLAUDE_EFFORT="max")
                self.assertEqual(efforts, expected)
                self.assertEqual(args[args.index("--model") + 1], "sonnet")

    def test_usage_capture_keeps_the_effort(self):
        with mock.patch.dict(os.environ, {"ALLOY_CLAUDE_EFFORT": "high"}):
            ad = self.f.ClaudeAdapter()
            args = ad.usage_args(ad.build_args(self.prompt, "", "consult", {}))
        self.assertEqual(args[args.index("--effort") + 1], "high")

    def test_prompt_file_is_still_stdin_byte_for_byte(self):
        # The stdin hook leaves non-stream adapters on the prompt FILE itself.
        fake = self.fake("claude", FAKE_CLAUDE)
        st = self.dispatch(self.f.ClaudeAdapter(), ALLOY_BIN_CLAUDE=fake, ALLOY_CLAUDE_EFFORT="medium")
        self.assertEqual(st["status"], "ok", st.get("error"))
        seen = self.dumped()
        self.assertTrue(seen["stdin_reg"])
        self.assertFalse(seen["stdin_fifo"])
        with open(self.prompt, "rb") as fh:
            self.assertEqual(seen["sha256"], hashlib.sha256(fh.read()).hexdigest())
        self.assertEqual(seen["argv"][seen["argv"].index("--effort") + 1], "medium")


# --------------------------------------------------------------------------- #
# Antigravity (agy) >= 1.3.4: stream-json in, stream-json out
# --------------------------------------------------------------------------- #
class AgyCase(FrontierCase):
    VERSION = (1, 3, 4)

    def setUp(self):
        super().setUp()
        os.environ["ALLOY_BIN_ANTIGRAVITY"] = self.fake("agy", FAKE_AGY)
        os.environ["ANTIGRAVITY_API_KEY"] = "fake"
        for target, value in (("_agy_version", lambda _self: self.VERSION),
                              ("_AUTH_LINKS", ()), ("_keychain_plist", lambda _self: None)):
            p = mock.patch.object(self.f.AntigravityAdapter, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.ad = self.f.AntigravityAdapter()

    def settings(self, ctx):
        home = self.ad.prepare_env(ctx)["HOME"]
        with open(os.path.join(home, ".gemini", "antigravity-cli", "settings.json")) as fh:
            return json.load(fh)

    def add_dirs(self, args):
        return [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--add-dir"]


class AgyStreamTests(AgyCase):
    def test_stream_argv_has_no_p_no_staged_prompt_and_canonical_roots(self):
        link = os.path.join(self.tmp, "repo-link")
        os.symlink(self.repo, link)
        pdir = os.path.join(self.tmp, "pdir")
        ctx = {"repo": link, "pdir": pdir, "timeout_s": 30}
        args = self.ad.build_args(self.prompt, "", "consult", ctx)
        self.assertEqual(args[:6], ["--input-format", "stream-json", "--output-format", "stream-json",
                                    "--mode", "plan"])
        self.assertNotIn("-p", args)
        self.assertNotIn("--print", args)
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertNotIn("line two", " ".join(args))
        self.assertFalse(os.path.exists(os.path.join(pdir, "prompt_in")))      # nothing staged
        self.assertEqual(self.add_dirs(args), [self.repo])                     # realpath, prompt dir gone
        self.assertEqual(args[args.index("--print-timeout") + 1], "30s")
        self.assertEqual(args[args.index("--model") + 1], "gemini-4-argon-high")
        self.assertTrue(self.ad.stream_input)
        self.assertFalse(self.ad.stdin_from_prompt)
        with mock.patch.dict(os.environ, {"ALLOY_ANTIGRAVITY_EFFORT": "high",
                                          "ALLOY_ANTIGRAVITY_MODEL": "gemini-4-argon-low"}):
            args = self.ad.build_args(self.prompt, "", "consult", dict(ctx))
        self.assertEqual(args[args.index("--model") + 1], "gemini-4-argon-low")
        self.assertEqual(args[args.index("--effort") + 1], "high")

    def test_stdin_payload_is_one_documented_user_message(self):
        line = self.ad.stdin_payload(self.prompt_text)
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(line.count("\n"), 1)
        self.assertEqual(len(line.splitlines()), 1)                 # U+2028 is escaped, not raw
        self.assertEqual(json.loads(line), {"event": "user", "message": {"content": self.prompt_text}})

    def test_read_only_settings_scope_reads_and_gate_web(self):
        ctx = {"repo": self.repo, "pdir": os.path.join(self.tmp, "pdir")}
        self.ad.build_args(self.prompt, "", "consult", ctx)
        perms = self.settings(ctx)["permissions"]
        self.assertEqual(perms["allow"], ["read_file(%s)" % self.repo, "read_url(*)"])
        self.assertEqual(perms["deny"], ["command(*)", "write_file(*)", "execute_url(*)"])
        with mock.patch.dict(os.environ, {"ALLOY_WEB": "0"}):
            perms = self.settings(ctx)["permissions"]
        self.assertEqual(perms["allow"], ["read_file(%s)" % self.repo])
        self.assertEqual(perms["deny"], ["command(*)", "write_file(*)", "execute_url(*)", "read_url(*)"])
        # Grants are canonical even when a caller hands over a non-canonical root.
        odd = {"agy_add_dirs": [os.path.join(self.repo, "..", "repo"), self.repo]}
        self.assertEqual(self.ad._settings(odd)["permissions"]["allow"][:-1], ["read_file(%s)" % self.repo])
        settings = self.settings(ctx)
        self.assertNotIn("toolPermission", settings)
        self.assertTrue(settings["enableTerminalSandbox"])

    def test_review_roots_add_canonical_gate_logs_and_worktree_metadata(self):
        gate_logs = os.path.join(self.tmp, "gate-logs")
        common = os.path.join(self.tmp, "source.git")
        gitdir = os.path.join(common, "worktrees", "tid")
        os.makedirs(gitdir)
        with open(os.path.join(self.repo, ".git"), "w") as fh:
            fh.write("gitdir: %s\n" % os.path.relpath(gitdir, self.repo))
        ctx = {"repo": self.repo, "pdir": os.path.join(self.tmp, "pdir")}
        with mock.patch.object(self.f, "gate_log_dir", return_value=gate_logs):
            args = self.ad.build_args(self.prompt, "", "review", ctx)
        self.assertEqual(self.add_dirs(args), [self.repo, gate_logs, gitdir, common])
        self.assertEqual(self.settings(ctx)["permissions"]["allow"],
                         ["read_file(%s)" % d for d in (self.repo, gate_logs, gitdir, common)] + ["read_url(*)"])

    def test_usage_capture_keeps_stream_json_and_reads_the_result_usage(self):
        args = self.ad.build_args(self.prompt, "", "consult", {"repo": self.repo, "pdir": self.tmp})
        self.assertEqual(self.ad.usage_args(args), args)
        st = self.dispatch(self.ad, repo=self.repo, ALLOY_CAPTURE_USAGE="1", FAKE_BULK="3")
        self.assertEqual(st["status"], "ok", st.get("error"))
        argv = self.dumped()["argv"]
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertEqual(st["usage"], {"input_tokens": 500, "cache_read_tokens": 300, "cache_write_tokens": 0,
                                       "output_tokens": 40, "reasoning_tokens": 15, "reported_cost_usd": None,
                                       "turns": 3, "source": "agy-stream-json"})

    def test_dispatch_pipes_one_json_line_and_parses_the_success_result(self):
        st = self.dispatch(self.ad, repo=self.repo, FAKE_BULK="5")
        self.assertEqual(st["status"], "ok", st.get("error"))
        self.assertEqual(self.read(st, "result_path"), "AGY ANSWER")
        seen = self.dumped()
        self.assertTrue(seen["stdin_fifo"])                      # a pipe, never a file on stdin
        self.assertFalse(seen["stdin_reg"])
        self.assertEqual(len(seen["lines"]), 1)
        self.assertEqual(json.loads(seen["lines"][0]),
                         {"event": "user", "message": {"content": self.prompt_text}})
        self.assertNotIn("-p", seen["argv"])
        self.assertNotIn("line two", " ".join(st["command"]))
        stdout = self.read(st, "stdout_path")
        self.assertEqual([json.loads(ln)["event"] for ln in stdout.strip().split("\n")], ["result"])
        with open(self.prompt, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.prompt_text)          # the run prompt is untouched

    def test_late_result_survives_a_transcript_far_beyond_the_head_cap(self):
        st = self.dispatch(self.ad, max_chars=100, FAKE_BULK="200")
        self.assertGreater(st["output_bytes"], 100 * 4 * 100)
        self.assertEqual((st["status"], self.read(st, "result_path")), ("ok", "AGY ANSWER"))

    def test_exit_zero_with_an_error_result_is_not_success(self):
        for mode, needle in (("error", "agy result status ERROR: tool required the write_file permission"),
                             ("success_with_error", "agy result reported an error: model stream interrupted"),
                             ("agy_error", "AGY_ERROR")):
            with self.subTest(mode=mode):
                st = self.dispatch(self.ad, FAKE_AGY=mode)
                self.assertEqual(st["exit_code"], 0)
                self.assertEqual(st["status"], "error")
                self.assertIn(needle, st["error"])
                if mode != "agy_error":
                    self.assertEqual(self.read(st, "result_path"), "")
        self.assertIsNone(self.ad.output_error("", ""))
        self.assertEqual(self.ad.output_error("not a stream\n", ""), "agy stream-json output has no result event")
        self.assertEqual(self.ad.parse('{"event": "result", "result": {"status": "SUCCESS"}}\n', "", ""), "")

    def test_no_result_event_or_no_output_is_empty_never_ok(self):
        # As for Claude's stream: no final event (crash, kill) keeps nothing.
        for mode in ("no_result", "empty"):
            with self.subTest(mode=mode):
                st = self.dispatch(self.ad, FAKE_AGY=mode, FAKE_BULK="3")
                self.assertEqual(st["status"], "empty")
                self.assertEqual(self.read(st, "result_path"), "")


class AgyLegacyTests(AgyCase):
    """An agy older than 1.3.4 keeps the staged-prompt invocation, DEVNULL stdin and the
    model it was verified with."""
    VERSION = (1, 2, 12)

    def test_legacy_invocation_is_unchanged(self):
        ctx = {"repo": self.repo, "pdir": os.path.join(self.tmp, "pdir"), "timeout_s": 30}
        args = self.ad.build_args(self.prompt, "", "consult", ctx)
        staged = os.path.join(self.tmp, "pdir", "prompt_in", "prompt.md")
        self.assertEqual(args[0], "-p")
        self.assertIn(staged, args[1])
        self.assertEqual(self.add_dirs(args), [os.path.dirname(staged), self.repo])
        self.assertNotIn("--input-format", args)
        self.assertEqual(args[args.index("--model") + 1], "gemini-3.6-flash-high")
        self.assertFalse(self.ad.stream_input)
        self.assertEqual(self.ad.usage_args(args)[-2:], ["--output-format", "json"])
        self.assertEqual(self.settings(ctx)["permissions"]["deny"], ["command(*)", "write_file(*)"])

    def test_legacy_dispatch_keeps_devnull_stdin_and_plain_output(self):
        st = self.dispatch(self.ad, repo=self.repo)
        seen = self.dumped()
        self.assertTrue(seen["stdin_chr"])                       # DEVNULL, as before
        self.assertEqual(seen["lines"], [])
        self.assertIn("-p", seen["argv"])
        self.assertEqual((st["status"], self.read(st, "result_path")), ("ok", "AGY PLAIN ANSWER"))


if __name__ == "__main__":
    unittest.main()
