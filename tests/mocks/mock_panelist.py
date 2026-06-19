#!/usr/bin/env python3
"""A fake panelist CLI for alloy's tests.

It impersonates both codex and claude closely enough to exercise the dispatcher
without spending tokens, and can be told to misbehave via env vars so we can test
every failure mode (timeout, nonzero exit, empty/huge/non-UTF-8 output, leaked
secret).

Role is inferred from argv: codex passes `exec` (+ `-o <file>`), the stdin/stdout
adapters (claude) pass `-p`. Behavior is read from MOCK_BEHAVIOR_<ROLE> then
MOCK_BEHAVIOR (default ok):

  ok        read stdin, emit a canned answer
  empty     emit nothing
  fail      print to stderr and exit 3
  hang      spawn a child `sleep` (pid -> $MOCK_CHILD_PIDFILE), then sleep forever
  huge      emit a large answer (to test output capping)
  secret    emit a fake API key (to test redaction)
  nonutf8   emit invalid UTF-8 bytes (to test decode safety)
"""
import os
import subprocess
import sys
import time


def role_from_argv(argv):
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

    if "--version" in argv:
        sys.stdout.write("mock-panelist 9.9.9\n")
        return 0

    role = role_from_argv(argv)
    behavior = os.environ.get(
        "MOCK_BEHAVIOR_" + role.upper(), os.environ.get("MOCK_BEHAVIOR", "ok")
    )

    # consume stdin like a real CLI would (prevents the writer from blocking)
    try:
        stdin_data = sys.stdin.buffer.read()
    except Exception:
        stdin_data = b""

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

    if target:
        with open(target, "wb") as f:
            f.write(payload)
    else:
        sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
