#!/usr/bin/env python3
"""UserPromptSubmit hook: one line, so the reply shape survives the session.

The full rules go in ONCE, at session start, appended to the chair's
core profile (instructions/reply-shape.md). Rules injected once decay:
by turn thirty the chair is writing prose walls again, and nothing in
the transcript reminds it otherwise. This hook costs ~150 chars per
turn to keep the shape in front of the model at the moment it composes
an answer — the only moment that can still change the output.

Chair only. A teammate's "reply" is a report to the chair under the
playbook's 40-line output contract, not an answer to a person, and
telling it to lead with a next action fights that contract.

Configuration:
    FABLE_ORCH_REPLY_SHAPE=0   disables the per-turn reminder; the
                               session-start injection is unaffected
"""
import json
import os
import re
import subprocess
import sys
import time

REMINDER = (
    "Reply shape (see the rules injected at session start): next action or "
    "command FIRST, numbered steps for multi-step work, one topic, at most "
    "five items in a list, concrete time estimates, no preamble and no "
    "closing pleasantry."
)
DETECT_BUDGET = 1.5  # seconds; the walk measures ~5ms in practice


def _budget(deadline, cap=5.0):
    if deadline is None:
        return cap
    return max(0.1, min(cap, deadline - time.monotonic()))


def _is_claude_exe(path):
    base = os.path.basename(path)
    return (base.startswith("claude")
            or "claude-code" in path
            or re.match(r"^\d+\.\d+", base) is not None)


def _is_teammate_session(max_hops=12):
    """True when this hook runs inside a named teammate.

    Same walk, same hard budget, and the same fail-open default as the
    other guards: on exhaustion answer False, so the chair still gets
    its reminder. A spurious reminder in a worker costs one line; the
    opposite default would silently drop the rule for everyone.
    """
    deadline = time.monotonic() + DETECT_BUDGET
    pid = os.getpid()
    for _ in range(max_hops):
        if time.monotonic() > deadline:
            return False
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,command=", "-p", str(pid)],
                capture_output=True, text=True, timeout=_budget(deadline),
            ).stdout.strip()
            bits = (out.splitlines()[0] if out else "").split(None, 1)
            ppid = int(bits[0])
        except Exception:
            return False
        command = bits[1] if len(bits) > 1 else ""
        for tok in command.split():
            if _is_claude_exe(tok.strip("\"'")):
                return "--agent-id" in command
        if ppid <= 1:
            return False
        pid = ppid
    return False


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass  # the reminder does not depend on the payload
    if (os.environ.get("FABLE_ORCH_REPLY_SHAPE") or "").strip() == "0":
        return
    try:
        if _is_teammate_session():
            return
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": REMINDER,
            }
        }))
    except Exception:
        return  # never break a turn


if __name__ == "__main__":
    main()
