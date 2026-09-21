#!/usr/bin/env python3
"""PreToolUse guard: stop the chair from quietly doing the work itself.

The one failure this plugin exists to catch is the chair that reads
the profile, agrees with it, and then edits twenty files by hand on
the most expensive model in the session. Every earlier version gated
DELEGATION — spawn prompts, tracker tasks — so a session that never
delegated never met a gate at all. Measured in the wild: five
consecutive sessions received the profile and spawned zero workers.

So this gate watches the OTHER side. It counts the chair's own file
edits, and when the chair has made several with no worker running and
none ever spawned, the next one draws ONE deny:

    Agent / Task                          -> records a spawn, always allows
    Edit / Write / MultiEdit / NotebookEdit -> counted; the Nth in a
                                             session with zero spawns
                                             is denied, once

It fires at most once per session, so it is a nudge and not a wall:
the chair that genuinely has a two-line fix says so and carries on,
and the chair that was about to hand-implement a six-phase plan gets
told to name some workers instead. After the deny the counter keeps
running but stays quiet.

Exempt, always:
    teammates      a worker's whole job is to edit files; the rule is
                   the chair's alone (ancestor walk for --agent-id)
    a session that has spawned at least one worker — the chair is
    orchestrating and its own small edits are its business

Not covered on purpose: `Bash` heredocs and `sed -i`. Gating Bash
would mean parsing shell to tell `cat > file` from `cat file`, and a
guard that misreads a read as a write is worse than one with a known
hole. The per-prompt reminder covers that path instead.

Configuration (all optional):
    FABLE_ORCH_SOLO_EDITS    deny fires AT the Nth chair edit
                             (default 3 — two pass free; 0 or
                             negative disables the gate)
    FABLE_ORCH_SOLO_GUARD=0  disables this gate entirely
    FABLE_ORCH_METRICS=0     disables the local metrics log
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shared import (env_int, env_off, is_teammate_session, metric,  # noqa: E402
                     tmp_json, update_state)

DEFAULT_EDIT_LIMIT = 3
SPAWN_TOOLS = ("Agent", "Task")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

DENY_REASON = (
    "Dynamic Workflow Rule 0 — you are the ORCHESTRATOR, and this "
    "session has edited {count} files with no worker spawned.\n\n"
    "Delegate the rest: name the workers (they run in tmux panes the "
    "user watches live), give each a spec, and spawn independent ones "
    "in ONE message. sonnet carries the volume; opus takes the hard "
    "slices.\n\n"
    "If this really is a single-sitting fix the user asked for "
    "directly, say so in one line and redo the edit — this fires once "
    "per session and will not ask again."
)


def edit_limit():
    return env_int("FABLE_ORCH_SOLO_EDITS", DEFAULT_EDIT_LIMIT)


def _record_spawn(session_id):
    """Mark the session as orchestrating. Never blocks anything."""
    path = tmp_json("fable-orch-solo", session_id)

    def mutate(state):
        try:
            spawns = int(state.get("spawns") or 0)
        except (TypeError, ValueError):
            spawns = 0
        state["spawns"] = spawns + 1
        return state, None

    update_state(path, mutate)


def _count_edit(session_id):
    """Count this edit. Returns (count, spawns, denied_before) or None."""
    path = tmp_json("fable-orch-solo", session_id)

    def mutate(state):
        try:
            count = int(state.get("edits") or 0) + 1
        except (TypeError, ValueError):
            count = 1
        try:
            spawns = int(state.get("spawns") or 0)
        except (TypeError, ValueError):
            spawns = 0
        denied_before = bool(state.get("denied"))
        limit = edit_limit()
        deny_now = (limit > 0 and count >= limit and spawns == 0
                    and not denied_before)
        state["edits"] = count
        state["spawns"] = spawns
        state["denied"] = denied_before or deny_now
        return state, (count, spawns, denied_before)

    return update_state(path, mutate)


def guard(data):
    """Return a deny payload, or None to stay out of the way."""
    tool = data.get("tool_name") or ""
    session_id = data.get("session_id")

    if tool in SPAWN_TOOLS:
        # A fork is the chair's own context, not a worker — it does not
        # count as having delegated anything.
        if (data.get("tool_input") or {}).get("subagent_type") != "fork":
            _record_spawn(session_id)
        return None

    if tool not in EDIT_TOOLS:
        return None
    if env_off("FABLE_ORCH_SOLO_GUARD") or edit_limit() <= 0:
        return None
    if is_teammate_session():
        return None

    result = _count_edit(session_id)
    if result is None:
        return None
    count, spawns, denied_before = result
    if spawns:
        return None
    if count < edit_limit():
        return None
    if denied_before:
        metric("solo_suppressed", session_id, count=count)
        return None

    metric("solo_deny", session_id, count=count, threshold=edit_limit(),
           tool=tool)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_REASON.format(count=count),
        }
    }


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    try:
        out = guard(data)
    except Exception:
        return  # a broken guard must never block a tool call
    if out:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
