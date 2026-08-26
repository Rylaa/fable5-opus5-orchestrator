#!/usr/bin/env python3
"""The handful of helpers every hook in this plugin needs.

Not a utility drawer: each function here was COPIED into five or six hook
scripts, and the copies had already drifted. `_budget` — the guard that
keeps a subprocess from overshooting a hook's 10-second deadline — floored
at 0.2s in three files and 0.1s in two, so the same call had two different
minimum timeouts depending on which hook made it. That is what duplication
costs before anyone notices: not a bug yet, but two behaviours wearing one
name.

Hooks run as `python3 "$CLAUDE_PLUGIN_ROOT/scripts/<hook>.py"`, so the
scripts directory is `sys.path[0]` and a plain `import _shared` resolves
without any path juggling.

Every function here is best-effort by design. These run inside hooks, and
a hook that raises takes the user's turn with it: metrics swallow their
own errors, and the process walks answer "no" rather than propagate.
"""
import json
import os
import re
import subprocess
import tempfile
import time

BUDGET_FLOOR_S = 0.2     # the unified floor; see the module docstring
BUDGET_CAP_S = 5.0
DETECT_BUDGET_S = 1.5    # for the ancestor walk; it measures ~5ms in practice
DETECT_MAX_HOPS = 12


def tmp_json(prefix, session_id):
    """Path of a per-session sidecar in the temp dir, or None without an id."""
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"{prefix}-{safe}.json")


def metric(event, session_id=None, **extra):
    """Append one event line to ~/.claude/fable-orch/metrics.jsonl.

    Events only, never prompt content. Best effort: a metrics failure must
    never be the reason a hook did not do its job.
    """
    if (os.environ.get("FABLE_ORCH_METRICS") or "").strip() == "0":
        return
    try:
        d = os.path.join(os.path.expanduser("~"), ".claude", "fable-orch")
        os.makedirs(d, exist_ok=True)
        rec = {"ts": round(time.time(), 3), "event": event}
        if session_id:
            rec["session"] = str(session_id)[:8]
        rec.update(extra)
        with open(os.path.join(d, "metrics.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def budget(deadline, cap=BUDGET_CAP_S):
    """Seconds a subprocess may run without overshooting `deadline`.

    Checked before EVERY subprocess call, not once per batch: a wedged
    command answers at its own timeout, and three of those in a row walk
    straight past a 10-second hook deadline into a SIGKILL.

    Deadlines are monotonic. A wall clock can step backwards (NTP, a
    manual change) and would then hand back a budget that never expires,
    defeating the bound entirely.
    """
    if deadline is None:
        return cap
    return max(BUDGET_FLOOR_S, min(cap, deadline - time.monotonic()))


def cpu_seconds(text):
    """Parse a ps cputime ([DD-]HH:MM:SS[.ff] or MM:SS[.ff]) into seconds."""
    text = text.strip()
    days = 0
    if "-" in text:
        day_part, text = text.split("-", 1)
        try:
            days = int(day_part)
        except ValueError:
            return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    if not parts:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return days * 86400 + seconds


def is_claude_exe(path):
    """True for the claude binary, including the versioned install path.

    A teammate launched from ~/.local/share/claude/versions/2.1.246 has an
    argv[0] whose BASENAME is `2.1.246`, not `claude`. A check that tested
    only `basename.startswith("claude")` skipped every real teammate pane.
    """
    base = os.path.basename(path)
    return (base.startswith("claude")
            or "claude-code" in path
            or re.match(r"^\d+\.\d+", base) is not None)


def is_teammate_session(max_hops=DETECT_MAX_HOPS):
    """True when the caller is running inside a named teammate.

    Teammates are launched with `--agent-id`. Most of this plugin's rules
    belong to the CHAIR: a teammate that gets the orchestrator profile is
    invited to spawn workers of its own, and a teammate held on the
    chair's ledger loses a turn to a reminder about someone else's work.

    HARD-BUDGETED, because callers run it BEFORE printing their decision:
    an unbounded walk of 12 hops at a 5s subprocess timeout would be 60s
    against a 10s hook deadline, and the hook would be killed with no
    decision emitted at all. On exhaustion the answer is False — "assume
    chair", so the guard still runs. That costs a teammate one spurious
    reminder; the opposite default would silently disable the guard for
    everyone.
    """
    deadline = time.monotonic() + DETECT_BUDGET_S
    pid = os.getpid()
    for _ in range(max_hops):
        if time.monotonic() > deadline:
            return False
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,command=", "-p", str(pid)],
                capture_output=True, text=True, timeout=budget(deadline),
            ).stdout.strip()
            bits = (out.splitlines()[0] if out else "").split(None, 1)
            ppid = int(bits[0])
        except Exception:
            return False
        command = bits[1] if len(bits) > 1 else ""
        for tok in command.split():
            if is_claude_exe(tok.strip("\"'")):
                return "--agent-id" in command
        if ppid <= 1:
            return False
        pid = ppid
    return False
