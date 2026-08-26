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
import sys
# Loaded by path (a hook command, a test's spec_from_file_location),
# so the scripts directory is not always on sys.path already.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _shared import is_teammate_session as _is_teammate_session
except Exception:
    # `_shared.py` ships beside this file. A partial install, a half-copied
    # plugin directory or an unreadable sibling leaves this hook with no
    # helpers and therefore no decision it can make. Degrade to nothing at
    # all: say nothing, deny nothing, block nothing, exit 0. Every hook here
    # is fail-open by design, and an import error at module scope would be
    # the one failure that ignores that, killing a turn with a traceback on
    # every single prompt.
    sys.exit(0)

REMINDER = (
    "Reply shape (see the rules injected at session start): next action or "
    "command FIRST, numbered steps for multi-step work, one topic, at most "
    "five items in a list, concrete time estimates, no preamble and no "
    "closing pleasantry."
)


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
