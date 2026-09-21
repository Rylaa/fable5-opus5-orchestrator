#!/usr/bin/env python3
"""Helpers shared by the orchestrator hooks.

Kept in one module so the teammate walk, the metrics line and the
per-session sidecar cannot drift between the guards that use them — a
drifted copy is a guard that fires on the chair but not on a worker,
or the reverse, and nothing in the output says which one you got.
"""
import json
import os
import subprocess
import tempfile
import time

try:
    import fcntl
except ImportError:  # non-POSIX: run unlocked, best effort
    fcntl = None

TEAMMATE_DETECT_BUDGET = 1.5  # seconds; the walk measures ~5ms in practice


def metric(event, session_id=None, **extra):
    """Append one event line to ~/.claude/fable-orch/metrics.jsonl.

    Events only — never prompt content. Best effort: a metrics failure
    must never change a hook's decision or its exit code.
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


def tmp_json(prefix, session_id):
    """Path of a per-session temp file, or None without a session id.

    The name keeps the `fable-orch-*.json` shape so the SessionEnd
    sweep finds an orphan left by a crash.
    """
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"{prefix}-{safe}.json")


def env_int(name, default):
    """An int from the environment; unparseable values fall back."""
    raw = os.environ.get(name)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return default


def env_off(name):
    """True when the variable is explicitly set to "0"."""
    return (os.environ.get(name) or "").strip() == "0"


def update_state(path, mutate):
    """Read-modify-write a small JSON sidecar under an exclusive lock.

    Parallel PreToolUse hooks race on this file; without the lock a
    once-per-session deny can be skipped or fired twice. `mutate` takes
    the current dict and returns (new_dict, result). Valid-JSON-but-
    wrong-typed content must coerce, not crash — the hook contract is
    exit 0 always. Returns `result`, or None when the file is unusable.
    """
    if not path:
        return None
    try:
        f = open(path, "a+", encoding="utf-8")
    except OSError:
        return None
    try:
        if fcntl is not None:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass
        f.seek(0)
        try:
            state = json.load(f)
        except Exception:
            state = {}
        if not isinstance(state, dict):
            state = {}
        new_state, result = mutate(state)
        try:
            f.seek(0)
            f.truncate()
            json.dump(new_state, f)
            f.flush()
        except (OSError, ValueError):
            pass
        return result
    finally:
        f.close()


def _budget(deadline, cap=5.0):
    """Seconds a subprocess may run without overshooting the deadline.

    Monotonic on purpose: a wall clock can step backwards (NTP, a
    manual change) and would then hand back a budget that never
    expires, defeating the bound entirely.
    """
    if deadline is None:
        return cap
    return max(0.2, min(cap, deadline - time.monotonic()))


def is_teammate_session(max_hops=12):
    """True when this hook is running inside a named teammate.

    Teammates are launched with `--agent-id`. Every rule these hooks
    carry belongs to the CHAIR: a worker that is told "delegate this"
    would spawn workers of its own, inverting the discipline, and a
    worker held at its close loses the report it was about to deliver.
    Walks up to the first claude ancestor and answers from its argv.

    HARD-BUDGETED, because this runs BEFORE the caller prints its
    decision: an unbounded walk of 12 hops at a 5s subprocess timeout
    would be 60s against a 10s hook timeout, and the hook would be
    killed with no decision emitted at all. On budget exhaustion the
    answer is False — "assume chair", so the guard still runs.
    """
    deadline = time.monotonic() + TEAMMATE_DETECT_BUDGET
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
            base = os.path.basename(tok.strip("\"'"))
            if base == "claude" or "claude-code" in tok or base.startswith("2."):
                return "--agent-id" in command
        if ppid <= 1:
            return False
        pid = ppid
    return False
