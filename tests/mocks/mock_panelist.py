#!/usr/bin/env python3
"""A fake panelist CLI for alloy's tests.

It impersonates both codex and claude closely enough to exercise the dispatcher
without spending tokens, and can be told to misbehave via env vars so we can test
every failure mode (timeout, nonzero exit, empty/huge/non-UTF-8 output, leaked
secret).

Role is inferred from argv: codex passes `exec` (+ `-o <file>`), the stdin/stdout
adapters (claude) pass `-p`. Behavior is read from MOCK_BEHAVIOR_<ROLE> then
MOCK_BEHAVIOR (default ok):

Two env knobs sit outside the behavior switch: MOCK_VERSION overrides what
`--version` prints, and MOCK_ENV_DUMP names a file to write the child's $HOME to.

The same file also impersonates two Cursor-related executables:

  sandbox-exec   argv[0] == "-f": `<profile> <cmd...>`. It validates and copies the
                 profile ($MOCK_SANDBOX_DUMP/<n>.sb), logs the call ($MOCK_SANDBOX_LOG),
                 answers Alloy's preflight probe by evaluating the generated profile
                 with a last-match-wins SBPL evaluator (sbpl_decision), and otherwise
                 execs <cmd>. MOCK_SANDBOX_PREFLIGHT injects failures: read_allowed,
                 write_leak, link_leak, exec_leak, socket_leak (the client reports and makes
                 the Unix-socket connect), socket_silent_leak (it connects but reports deny),
                 socket_control_fail (the allowed resolver socket does not connect), mach_leak
                 (a relay service resolves), mach_control_fail (the allowlisted service does
                 not resolve), garbage, noout, fail, cli_fail. The probe's Mach lines are
                 decided by evaluating `mach-lookup` and the client's `process-exec` against
                 the generated profile. MOCK_CURSOR_LOG also records the child's env names.
  cursor-agent   `status`, `--version` and the print-mode inference call (recognised by
                 --skip-worktree-setup). MOCK_CURSOR_STATUS: ok|logged_out|garbage|error.
                 MOCK_CURSOR_JSON: ok|is_error|malformed|no_result|nonstring|nonobject|
                 jwt|jwt_empty|assignment|assignment_quoted|header|header_basic|
                 header_api_key|header_schemes|cookie|is_error_int|is_error_string|
                 usage_unknown|usage_bad|usage_missing. MOCK_CURSOR_EXIT
                 sets the exit code. MOCK_CURSOR_LOG records argv/env/stdin per call,
                 MOCK_PROMPT_DUMP the staged prompt's size and hash, MOCK_TAMPER_WRITE
                 (JSON [[path, text], ...]) and MOCK_TAMPER_CANARY simulate a sandbox escape.

  ok        read stdin, emit a canned answer
  empty     emit nothing
  fail      print to stderr and exit 3
  auth      emit an AuthorizationRequired error on stderr, empty stdout, exit 0
  auth_once auth on the first call, ok thereafter (state via $MOCK_AUTH_ONCE_FILE)
  hang      spawn a child `sleep` (pid -> $MOCK_CHILD_PIDFILE), then sleep forever
  huge      emit a large answer (to test output capping)
  secret    emit a fake API key (to test redaction)
  nonutf8   emit invalid UTF-8 bytes (to test decode safety)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time


# -- a small last-match-wins SBPL evaluator for the profiles Alloy generates -------- #
def _sbpl_tokens(line):
    toks, i = [], 0
    while i < len(line):
        c = line[i]
        if c in " \t":
            i += 1
        elif c in "()":
            toks.append(c)
            i += 1
        elif c == '"' or line.startswith('#"', i):
            regex = c == "#"
            i += 2 if regex else 1
            buf = []
            while line[i] != '"':
                if line[i] == "\\":
                    nxt = line[i + 1]
                    buf.append(nxt if (not regex or nxt == '"') else line[i:i + 2])
                    i += 2
                else:
                    buf.append(line[i])
                    i += 1
            i += 1
            toks.append(("re" if regex else "str", "".join(buf)))
        else:
            j = i
            while j < len(line) and line[j] not in ' \t()"':
                j += 1
            toks.append(line[i:j])
            i = j
    return toks


def sbpl_rules(profile):
    """[(allow|deny, [ops], [(kind, value)])] from a one-rule-per-line profile."""
    rules = []
    for line in profile.splitlines():
        line = line.strip()
        if not (line.startswith("(allow") or line.startswith("(deny")):
            continue
        toks = _sbpl_tokens(line)
        kind, ops, filters, i = toks[1], [], [], 2
        while i < len(toks) and toks[i] not in ("(", ")"):
            ops.append(toks[i])
            i += 1
        while i < len(toks):
            if toks[i] == "(" and isinstance(toks[i + 2], tuple):
                filters.append((toks[i + 1], toks[i + 2][1]))
                i += 4
            elif toks[i] == "(" and toks[i + 1] == "target":
                # `(target self|children|others)`: a process filter, not a path filter. A
                # parser that skipped it would turn the rule into an unconditional one.
                filters.append(("target", toks[i + 2]))
                i += 4
            else:
                i += 1
        rules.append((kind, ops, filters))
    return rules


def _sbpl_filter_hit(name, value, path, target):
    if name == "target":
        return target == value
    if path is None:
        return False
    return ((name in ("literal", "global-name") and path == value)
            or (name == "subpath" and (path == value or path.startswith(value.rstrip("/") + "/")))
            or (name == "regex" and re.search(value, path)))


def sbpl_decision(profile, op, path=None, target=None):
    """'allow' or 'deny' for one operation. Later rules win. `path` is the file path,
    the Unix-domain socket path (network-bind/-outbound; a TCP endpoint is any
    non-absolute string such as "127.0.0.1:443") or the Mach service name; `target`
    is the process relation (self, children, others) for process-info/task-port ops."""
    result = "deny"
    for kind, ops, filters in sbpl_rules(profile):
        if not any(o == "default" or (o.endswith("*") and op.startswith(o[:-1])) or o == op for o in ops):
            continue
        if filters and not any(_sbpl_filter_hit(name, v, path, target) for name, v in filters):
            continue
        result = kind
    return result


def _connect_unix(path):
    """What an allowed sandboxed client's connect does: reach the listener for real."""
    import socket
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(2)
        client.connect(path)
    except OSError:
        pass
    finally:
        client.close()


def _sandbox_probe(profile, cmd, mode):
    """Answer Alloy's preflight probe the way a working sandbox would."""
    t, w, o, d, l, g, c, p, s, n, m, y, _script, a = cmd[4:18]
    relays = cmd[18:]
    dec = lambda op, path: sbpl_decision(profile, op, path)
    res = {"tmp_write": dec("file-write-create", t + "/probe"),
           "workspace_write": dec("file-write-create", w + "/probe"),
           "outside_write": dec("file-write-create", o + "/probe"),
           "gitdir_write": dec("file-write-create", g + "/probe"),
           "common_write": dec("file-write-create", c + "/probe"),
           "dotgit_write": dec("file-write-create", p),
           "denied_read": dec("file-read-data", d),
           "link": dec("file-link", t + "/link") if dec("process-exec", "/bin/ln") == "allow" else "deny",
           "exec": dec("process-exec", "/usr/bin/true")}
    # The socket client must itself be executable under the profile; then the connect
    # is decided by the network rules on the socket's path.
    client = dec("process-exec", n) == "allow"
    res["unix_allowed"] = dec("network-outbound", m) if client else "deny"
    res["unix_connect"] = dec("network-outbound", s) if client else "deny"
    # The Mach client is the interpreter. Its exit status is the number of names that
    # resolved: the script reads "exactly one" as the allowed control and "none" as every
    # relay denied, so a client that cannot run yields deny / allow (fail closed).
    py = dec("process-exec", y) == "allow"
    res["mach_allowed"] = dec("mach-lookup", a) if py else "deny"
    res["mach_relay"] = ("deny" if py and all(dec("mach-lookup", r) == "deny" for r in relays)
                         else "allow")
    if dec("file-write-data", "/dev/null") != "allow":      # the probe's own 2>/dev/null
        res = {k: ("allow" if k == "mach_relay" else "deny") for k in res}
    res.update({"read_allowed": {"denied_read": "allow"}, "write_leak": {"workspace_write": "allow"},
                "link_leak": {"link": "allow"}, "exec_leak": {"exec": "allow"},
                "socket_leak": {"unix_connect": "allow"},
                "socket_silent_leak": {"unix_connect": "deny"},      # reports deny yet connects
                "socket_control_fail": {"unix_allowed": "deny"},
                "mach_leak": {"mach_relay": "allow"},
                "mach_control_fail": {"mach_allowed": "deny"}}.get(mode, {}))
    if res["unix_connect"] == "allow" or mode == "socket_silent_leak":
        _connect_unix(s)                                            # the listener really sees it
    if mode == "garbage":
        sys.stdout.write("not a probe result\n")
    elif mode != "noout":
        sys.stdout.write("".join("%s=%s\n" % kv for kv in res.items()))
    return 9 if mode == "fail" else 0


def sandbox_exec(argv):
    profile_path, cmd = argv[1], argv[2:]
    try:
        with open(profile_path, encoding="utf-8") as f:
            profile = f.read()
    except OSError:
        sys.stderr.write("sandbox-exec: cannot read the profile\n")
        return 71
    if not profile.startswith("(version 1)"):
        sys.stderr.write("sandbox-exec: invalid profile\n")
        return 65
    dump = os.environ.get("MOCK_SANDBOX_DUMP")
    if dump:
        os.makedirs(dump, exist_ok=True)
        with open(os.path.join(dump, "%03d.sb" % len(os.listdir(dump))), "w", encoding="utf-8") as f:
            f.write(profile)
    log = os.environ.get("MOCK_SANDBOX_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"cmd": cmd[:2] if "ALLOY_PREFLIGHT_PROBE" in " ".join(cmd) else cmd}) + "\n")
    mode = os.environ.get("MOCK_SANDBOX_PREFLIGHT", "pass")
    if cmd[:2] == ["/bin/bash", "-c"] and len(cmd) > 14 and "ALLOY_PREFLIGHT_PROBE" in cmd[2]:
        return _sandbox_probe(profile, cmd, mode)
    if mode == "cli_fail" and cmd[-1:] == ["--version"]:
        return 7
    os.execv(cmd[0], cmd)


# -- cursor-agent ------------------------------------------------------------------ #
_FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJmYWtlIjoiZml4dHVyZSJ9.c2lnbmF0dXJlLWZpeHR1cmU"


def _cursor_log(argv, stdin_len):
    log = os.environ.get("MOCK_CURSOR_LOG")
    if not log:
        return
    names = ("CURSOR_API_KEY", "CURSOR_API_ENDPOINT", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY",
             "OTHER_PROVIDER_TOKEN", "HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR")
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "stdin_bytes": stdin_len,
                            "env": {n: os.environ.get(n) for n in names},
                            "env_names": sorted(os.environ)}) + "\n")


def _cursor_status():
    mode = os.environ.get("MOCK_CURSOR_STATUS", "ok")
    if mode == "ok":
        sys.stdout.write("\u2713 Logged in as tl***@gmail.com\n")
    elif mode == "logged_out":
        sys.stdout.write("\u2717 Not logged in\n")
    elif mode == "garbage":
        sys.stdout.write("something unexpected\n")
    else:
        sys.stderr.write("status: simulated failure\n")
        return 1
    return 0


def _cursor_staged_bytes(argv):
    m = re.match(r'Read ("(?:[^"\\]|\\.)*") in full', argv[-1])
    if not m:
        return None
    with open(json.loads(m.group(1)), "rb") as f:
        return f.read()


def _cursor_tamper():
    for path, text in json.loads(os.environ.get("MOCK_TAMPER_WRITE", "[]")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    if os.environ.get("MOCK_TAMPER_CANARY"):
        runtime = os.path.dirname(os.path.dirname(os.environ["TMPDIR"]))
        with open(os.path.join(runtime, "canary", "canary.txt"), "w", encoding="utf-8") as f:
            f.write("tampered\n")


def _cursor_emit(argv, text):
    """Print a Cursor print-mode JSON result (or one of its failure shapes)."""
    mode = os.environ.get("MOCK_CURSOR_JSON", "ok")
    result, is_error, usage = text, False, {"inputTokens": 800, "outputTokens": 40,
                                            "cacheReadTokens": 300, "cacheWriteTokens": 20}
    stderr = ""
    if mode == "is_error":
        result, is_error = "boom", True
    elif mode == "is_error_int":
        result, is_error = "boom", 1
    elif mode == "is_error_string":
        result, is_error = "boom", "true"
    elif mode == "jwt":
        result, stderr = "token is " + _FAKE_JWT, "warning: leaked " + _FAKE_JWT + "\n"
    elif mode == "jwt_empty":
        result, stderr = "", "warning: leaked " + _FAKE_JWT + "\n"
    elif mode == "assignment":
        result = "config: API_KEY=hunter2hunter2hunter2"
        stderr = "config: API_KEY=hunter2hunter2hunter2\n"
    elif mode == "assignment_quoted":
        result = 'config: API_KEY="quotedhunter2hunter2"'
        stderr = 'config: API_KEY="quotedhunter2hunter2"\n'
    elif mode == "header":
        result = "sent Authorization: Bearer abc123def456ghi789"
        stderr = "sent Authorization: Bearer abc123def456ghi789\n"
    elif mode == "header_basic":
        result = "sent Proxy-Authorization: Basic YWJjMTIzZGVmNDU2"
        stderr = "sent Proxy-Authorization: Basic YWJjMTIzZGVmNDU2\n"
    elif mode == "header_api_key":
        result = "sent X-Api-Key: customheader123456"
        stderr = "sent X-Api-Key: customheader123456\n"
    elif mode == "header_schemes":
        result = "sent X-Auth-Token: Bearer schemevalue123456"
        stderr = "sent X-Api-Key: Token secondvalue123456\n"
    elif mode == "cookie":
        result = "sent Cookie: session=cookiesecret123456"
        stderr = "sent Set-Cookie: refresh=cookierefresh123456; HttpOnly\n"
    elif mode == "usage_unknown":
        usage = {"weird": "shape"}
    elif mode == "usage_bad":
        usage = {"inputTokens": -5, "outputTokens": "many", "cacheReadTokens": True}
    obj = {"type": "result", "subtype": "error" if is_error else "success", "is_error": is_error,
           "duration_ms": 12, "duration_api_ms": 10, "result": result,
           "session_id": "mock-provider-session-1", "request_id": "req-1", "usage": usage}
    if mode == "usage_missing":
        del obj["usage"]
    if mode == "no_result":
        del obj["result"]
    elif mode == "nonstring":
        obj["result"] = 5
    body = {"malformed": "this is not json {", "nonobject": "[1, 2]"}.get(mode) or json.dumps(obj)
    if stderr:
        sys.stderr.write(stderr)
    sys.stdout.write(body + "\n")
    return int(os.environ.get("MOCK_CURSOR_EXIT", "0"))


def role_from_argv(argv):
    if argv[:1] == ["-f"]:
        return "sandbox"
    if "--skip-worktree-setup" in argv or argv[:1] in (["status"], ["--list-models"]):
        return "cursor"
    if "exec" in argv:
        return "codex"
    if "-p" in argv:
        return "claude"
    return "unknown"


def output_target(argv):
    """codex writes its final message to the file after -o; claude uses stdout."""
    if "-o" in argv:
        i = argv.index("-o")
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main():
    argv = sys.argv[1:]

    if argv[:1] == ["-f"]:
        return sandbox_exec(argv)

    if argv == ["--version"] and os.environ.get("MOCK_CURSOR_LOG"):
        _cursor_log(argv, 0)          # the preflight's sandboxed CLI probe

    if "--version" in argv:
        # MOCK_VERSION lets a test impersonate a specific CLI release, for
        # adapters that gate behaviour on the installed version (agy).
        sys.stdout.write(os.environ.get("MOCK_VERSION", "mock-panelist 9.9.9") + "\n")
        return 0

    # Opt-in env capture, so a test can assert what the dispatcher handed the
    # child (e.g. the isolated HOME the agy adapter confines it to).
    dump = os.environ.get("MOCK_ENV_DUMP")
    if dump:
        with open(dump, "w") as f:
            f.write(os.environ.get("HOME", ""))
    stdin_dump = os.environ.get("MOCK_STDIN_DUMP")

    role = role_from_argv(argv)
    behavior = os.environ.get(
        "MOCK_BEHAVIOR_" + role.upper(), os.environ.get("MOCK_BEHAVIOR", "ok")
    )

    # consume stdin like a real CLI would (prevents the writer from blocking)
    try:
        stdin_data = sys.stdin.buffer.read()
    except Exception:
        stdin_data = b""
    if stdin_dump:
        with open(stdin_dump, "w") as f:
            f.write(str(len(stdin_data)))
    if role == "cursor":
        _cursor_log(argv, len(stdin_data))
        if argv[:1] == ["status"]:
            return _cursor_status()

    if behavior == "hang":
        child = subprocess.Popen(["sleep", "300"])
        pidfile = os.environ.get("MOCK_CHILD_PIDFILE")
        if pidfile:
            with open(pidfile, "w") as f:
                f.write(str(child.pid))
        time.sleep(300)
        return 0

    if behavior == "fail":
        sys.stderr.write("mock: simulated failure\n")
        return 3

    if behavior == "auth_once":
        # Stateful: first call fails like an expired-token race, later calls
        # succeed (mirrors grok refreshing its token as a side effect). Used to
        # exercise the single retry. State persists across processes via a file.
        flag = os.environ.get("MOCK_AUTH_ONCE_FILE")
        if flag and os.path.exists(flag):
            behavior = "ok"
        else:
            if flag:
                open(flag, "w").close()
            behavior = "auth"

    if behavior == "auth":
        # An expired-token failure as grok emits it: auth error on stderr, EMPTY
        # stdout, and a clean exit 0 (the trap the classifier must catch).
        sys.stderr.write(
            "ERROR worker quit with fatal: Transport channel closed, "
            "when Auth(AuthorizationRequired)\n"
        )
        return 0

    if behavior == "empty_noisy":
        # Genuinely blank answer (empty stdout) but with non-auth stderr noise,
        # to exercise the stderr-tail surfacing of a real `empty`.
        sys.stderr.write("mock: a diagnostic line\nmock: the last stderr line\n")
        return 0

    target = output_target(argv)
    if behavior == "empty":
        payload = b""
    elif behavior == "huge":
        payload = b"A" * 5000
    elif behavior == "secret":
        payload = (
            b"Sure. Also I found this in your env: "
            b"OPENAI_API_KEY=sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\n"
        )
    elif behavior == "nonutf8":
        payload = b"answer with bad bytes: \xff\xfe\xfa done"
    else:  # ok
        n = len(stdin_data)
        payload = (
            f"MOCK {role} answer (read {n} bytes of prompt): the sky is blue.\n"
        ).encode()

    if role == "cursor":
        staged = _cursor_staged_bytes(argv)
        dump = os.environ.get("MOCK_PROMPT_DUMP")
        if dump and staged is not None:
            with open(dump, "w") as f:
                json.dump({"bytes": len(staged), "sha256": hashlib.sha256(staged).hexdigest()}, f)
        _cursor_tamper()
        text = payload.decode("utf-8", errors="replace")
        if behavior == "ok" and staged is not None:
            text = "MOCK cursor answer (read %d staged bytes): the sky is blue.\n" % len(staged)
        return _cursor_emit(argv, text)

    # Machine-readable output modes (ALLOY_CAPTURE_USAGE): wrap the answer the
    # way each real CLI does, with fixed token counts the tests can assert.
    # MOCK_IGNORE_JSON impersonates an older CLI that prints plain text anyway.
    plain = bool(os.environ.get("MOCK_IGNORE_JSON"))
    fmt = argv[argv.index("--output-format") + 1] if "--output-format" in argv and not plain else None
    text = payload.decode("utf-8", errors="replace")
    if "--json" in argv and not plain:  # codex exec --json: JSONL events; -o still gets the answer
        events = [{"type": "thread.started", "thread_id": "t"},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
                  {"type": "turn.completed", "usage": {
                      "input_tokens": 1000, "cached_input_tokens": 400,
                      "cache_write_input_tokens": 0, "output_tokens": 50,
                      "reasoning_output_tokens": 20}}]
        sys.stdout.write("\n".join(json.dumps(e) for e in events) + "\n")
    elif fmt == "json" and "--prompt-file" in argv:  # grok
        payload = json.dumps({"text": text, "usage": {
            "input_tokens": 900, "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 0, "output_tokens": 30, "reasoning_tokens": 10},
            "num_turns": 2, "total_cost_usd": 0.0123}).encode()
    elif fmt == "json" and "--mode" in argv:  # agy
        payload = json.dumps({"status": "SUCCESS", "response": text, "num_turns": 3, "usage": {
            "input_tokens": 800, "output_tokens": 40, "thinking_tokens": 15,
            "cache_read_tokens": 300, "total_tokens": 840}}).encode()
    elif fmt == "json":  # claude
        payload = json.dumps({"type": "result", "result": text, "num_turns": 4,
            "total_cost_usd": 0.05, "usage": {"input_tokens": 7},
            "modelUsage": {"m": {"inputTokens": 5, "outputTokens": 60, "cacheReadInputTokens": 2000,
                                 "cacheCreationInputTokens": 3000, "thinkingTokens": 25}}}).encode()

    if target:
        with open(target, "wb") as f:
            f.write(payload)
    else:
        sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
