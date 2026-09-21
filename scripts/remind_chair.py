#!/usr/bin/env python3
"""UserPromptSubmit hook: one line of orchestration, on every prompt.

The core profile arrives once, at SessionStart, and then competes with
every other instruction in a long session. Measured in the wild: five
sessions received the profile in full and delegated nothing. A rule
that is read once at hour zero loses to the thousand tokens that come
after it, so the shortest possible restatement rides every prompt.

It is deliberately tiny (~35 tokens). It restates the default and
nothing else — routing, effort and the report contract stay in the
core and the playbook, where they are read once.

Teammates are skipped: a worker told to delegate would spawn workers
of its own, which is the failure this plugin exists to prevent.

Configuration:
    FABLE_ORCH_REMIND=0   disables the per-prompt line
    FABLE_ORCH_METRICS=0  disables the local metrics log
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shared import env_off, is_teammate_session  # noqa: E402

REMINDER = (
    "[orchestrator] You are the CHAIR. Delegate by default: name the "
    "workers, spec them, spawn independent ones in one message. Solo "
    "only for a single-sitting fix the user asked for directly."
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if env_off("FABLE_ORCH_REMIND"):
        return
    if is_teammate_session():
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": REMINDER,
        }
    }))


if __name__ == "__main__":
    main()
