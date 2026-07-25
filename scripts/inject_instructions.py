#!/usr/bin/env python3
"""SessionStart hook: inject the Dynamic Workflow instructions.

This plugin is built for a Claude Fable 5 chair, with an Opus
fallback: when the Fable limit is spent and the user moves the chair to
Opus, the OPUS profile keeps the same discipline (the fable tier rests,
verification and the escalation ceiling fall to opus). The chair is
detected per session start and the matching profile injected:

    opus chair    -> dynamic-workflow-opus.md
    anything else -> dynamic-workflow-fable.md   (fable / unknown)

Detection, in priority order (first hit wins):

    1. FABLE_ORCH_PROFILE = fable | opus   — explicit pin, overrides all
       (auto / unset falls through to detection)
    2. the SessionStart payload's `model`  — authoritative for THIS
       session start, but the harness omits it on some resume/compact
       fires
    3. the user's configured default model in Claude Code settings.json
       — what `/model` persists, so it still tracks the chair when (2)
       is absent (the common "I switched to Opus but the payload was
       empty" case)
    4. the last model this session's marker saw — sticky fallback so a
       null-payload resume never regresses an opus session to fable
    5. fable — the safe default

A mid-session /model switch still only takes visible effect at the next
session start (startup/resume/clear), because SessionStart is the sole
injection point — but (3) makes that next start reliable instead of
racy.

TEAMMATE sessions are skipped entirely. Named agent-teams workers are
full claude sessions and fire SessionStart like the chair does — but the
profile is written for the chair alone: injected into a worker it says
"you are the ORCHESTRATOR" and invites it to spawn subagents, inverting
the very discipline the plugin enforces (measured in the wild: 172 of
270 injected sessions were teammates). Detection is the same ancestor
walk the stop guard uses (`--agent-id` on the nearest claude ancestor);
the session marker is still written so the other guards keep working.
FABLE_ORCH_TEAMMATE_INJECT=1 restores the old inject-everyone
behaviour.

The hook also maintains the per-session marker the Stop and SessionEnd
hooks rely on: its immutable `started` timestamp survives the re-runs
SessionStart gets on resume/clear/compact, and the stop guard compares
ledger mtimes against it to decide ownership.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time


def session_model_cache_path(session_id):
    """Per-session marker file the stop/cleanup hooks read. None if no id."""
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"fable-orch-model-{safe}.json")


def _metric(event, session_id=None, **extra):
    """Append one event line to ~/.claude/fable-orch/metrics.jsonl (best effort)."""
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


def _is_opus(value):
    """True when the model string names the opus tier.

    Bounded, not a bare substring: `claude-octopus-1` and `opusculum`
    contain "opus" but are not Opus chairs. The bound stays permissive
    on the right so a version can follow with or without a separator —
    `claude-opus-5`, `opus5`, `opus[1m]`, `Opus 5 (1M context)` all
    match; only a letter immediately after "opus" disqualifies it.
    """
    return re.search(r"\bopus(?![a-z])", str(value or ""),
                     re.IGNORECASE) is not None


def _configured_model():
    """The user's configured default model from Claude Code settings, or
    None. `/model` persists the default here, so it tracks the current
    chair even when the SessionStart payload omits `model`. settings.local
    overrides settings; either may carry the key."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    for name in ("settings.local.json", "settings.json"):
        try:
            with open(os.path.join(base, name), encoding="utf-8") as f:
                m = json.load(f).get("model")
        except Exception:
            continue
        if isinstance(m, str) and m.strip():
            return m
    return None


def _read_marker(cache):
    """(started, model) from the marker file; (None, None) if unreadable."""
    if not cache:
        return None, None
    try:
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d.get("started"), d.get("model")
    except Exception:
        pass
    return None, None


TEAMMATE_DETECT_BUDGET = 1.5  # seconds; the walk measures ~5ms in practice


def _budget(deadline, cap=5.0):
    """Seconds a subprocess may run without overshooting the deadline.

    Monotonic, exactly as in the stop guard: a wall clock can step
    backwards (NTP, a manual change) and would then hand back a budget
    that never expires, defeating the bound entirely."""
    if deadline is None:
        return cap
    return max(0.2, min(cap, deadline - time.monotonic()))


def _is_teammate_session(max_hops=12):
    """True when this hook is running inside a named teammate.

    Teammates are launched with `--agent-id`. The profile belongs to the
    CHAIR: a worker that receives it is told it is the orchestrator and
    may spawn subagents liberally — the inverse of its actual job. Walks
    up to the first claude ancestor and answers from its argv; same
    logic as the stop guard's copy, kept verbatim so a future common
    module can unify them.

    HARD-BUDGETED because SessionStart must never hang a session open:
    on budget exhaustion the answer is False — "assume chair", so the
    profile is still delivered. That failure costs one teammate carrying
    the profile (the pre-fix behaviour for every teammate); the opposite
    default would strip the chair of its orchestration instructions.
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


def resolve_profile(payload_model, configured_model, marker_model):
    """Return (profile, source) — 'opus'|'fable' and which signal decided.
    Priority: env override > payload model > settings default > marker."""
    override = (os.environ.get("FABLE_ORCH_PROFILE") or "").strip().lower()
    if override in ("fable", "opus"):
        return override, "override"
    if str(payload_model or "").strip():
        return ("opus" if _is_opus(payload_model) else "fable"), "payload"
    if str(configured_model or "").strip():
        return ("opus" if _is_opus(configured_model) else "fable"), "settings"
    if str(marker_model or "").strip():
        return ("opus" if _is_opus(marker_model) else "fable"), "marker"
    return "fable", "default"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    model = data.get("model")  # optional; the harness omits it on some fires
    session_id = data.get("session_id")
    cache = session_model_cache_path(session_id)
    prev_started, prev_model = _read_marker(cache)

    profile, source = resolve_profile(model, _configured_model(), prev_model)
    filename = f"dynamic-workflow-{profile}.md"

    # The profile is chair-only; a teammate session skips the injection
    # but still gets its marker below — stop, spawn, and cleanup key off
    # it. Resolution ran first so the skip metric records which profile
    # the worker WOULD have received.
    teammate = False
    if (os.environ.get("FABLE_ORCH_TEAMMATE_INJECT") or "").strip() != "1":
        teammate = _is_teammate_session()

    text = None
    if not teammate:
        root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        path = os.path.join(root, "instructions", filename)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return  # never break session start

    # Session marker for the guards (best effort; never fatal).
    # `started` marks the session's FIRST start and must survive the
    # re-runs SessionStart gets on resume/clear/compact — the stop guard
    # compares ledger mtimes against it to decide ownership, so it can
    # never move forward. `model` keeps the last NON-EMPTY model seen, so
    # a later null-payload fire stays sticky instead of forgetting the
    # chair.
    try:
        if cache:
            started = prev_started
            try:
                started = float(started)
            except (TypeError, ValueError):
                # Marker from an older version (no `started`) or corrupt:
                # fall back to the file's mtime — NEVER to "now", which
                # would disown every ledger touched before this re-run.
                try:
                    started = os.path.getmtime(cache)
                except OSError:
                    started = time.time()
            stored_model = model if str(model or "").strip() else prev_model
            # Atomic replace: a crash mid-write must never leave a
            # truncated marker. The tmp name keeps the fable-orch-*.json
            # shape so an orphan from a crash still matches the 96h sweep.
            tmp = f"{cache}.{os.getpid()}.tmp.json"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"model": stored_model, "session_id": session_id,
                     "started": round(started, 3)},
                    f,
                )
            os.replace(tmp, cache)
    except Exception:
        pass

    if teammate:
        _metric("inject_skipped", session_id, model=model, profile=profile,
                source=source, reason="teammate")
        return

    _metric("inject", session_id, model=model, profile=profile, source=source)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))


if __name__ == "__main__":
    main()
