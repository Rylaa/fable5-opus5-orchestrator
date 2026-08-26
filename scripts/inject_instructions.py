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

PROFILE-SWITCH DELTA. When a session that already received a core
profile re-fires with the OTHER profile selected (the Fable limit ran
dry mid-session and the chair moved to Opus, or back), the full core is
NOT re-sent — it is already in context, and re-sending it spends the
very limit it exists to protect. A short switch note carries only the
deltas instead:

    fable -> opus -> profile-switch-to-opus.md
    opus  -> fable -> profile-switch-to-fable.md

The marker records the profile this session was last TOLD, so a plain
re-fire (same profile) is indistinguishable from before — it still gets
the full core. A marker with no recorded profile (a pre-0.15.0 marker,
or a session whose only fires were teammate skips) also gets the full
core: a delta is only ever safe on top of a core this session saw.

The delta is further gated to SessionStart `source == "resume"`, the
only fire that provably leaves the earlier injection in context.
`compact` fires precisely BECAUSE the context was rewritten, `clear`
because it was discarded, and a future source is simply unproven — all
three get the full core even when the profile changed. The switch note
says "every other rule from the already-injected core profile stays in
force", which is a lie the chair cannot detect if the core is gone.

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
import sys
import tempfile
import time
# Loaded by path (a hook command, a test's spec_from_file_location),
# so the scripts directory is not always on sys.path already.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _shared import (
        metric as _metric,
        is_teammate_session as _is_teammate_session)
except Exception:
    # `_shared.py` ships beside this file. A partial install, a half-copied
    # plugin directory or an unreadable sibling leaves this hook with no
    # helpers and therefore no decision it can make. Degrade to nothing at
    # all: say nothing, deny nothing, block nothing, exit 0. Every hook here
    # is fail-open by design, and an import error at module scope would be
    # the one failure that ignores that, killing a turn with a traceback on
    # every single prompt.
    sys.exit(0)


WATCHDOG_PLACEHOLDER = "{{WATCHDOG}}"

def session_model_cache_path(session_id):
    """Per-session marker file the stop/cleanup hooks read. None if no id."""
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"fable-orch-model-{safe}.json")


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
    """(started, model, profile) from the marker; (None, None, None) if unreadable.

    `profile` is the profile this session was last INJECTED with — the
    switch detector's only input. It is absent on markers written by
    pre-0.15.0 versions and on sessions whose fires were all teammate
    skips; in both cases the caller must fall back to the full core."""
    if not cache:
        return None, None, None
    try:
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d.get("started"), d.get("model"), d.get("profile")
    except Exception:
        pass
    return None, None, None


TEAMMATE_DETECT_BUDGET = 1.5  # seconds; the walk measures ~5ms in practice


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
    fire = data.get("source")  # startup | resume | clear | compact (advisory)
    cache = session_model_cache_path(session_id)
    prev_started, prev_model, prev_profile = _read_marker(cache)

    profile, source = resolve_profile(model, _configured_model(), prev_model)

    # Profile-switch delta: this session already carries a core profile
    # and the chair has since moved to the other tier. Re-sending ~3.7k
    # chars of unchanged rules costs the limit the profile exists to
    # protect, so only the deltas go out. Requires a RECORDED previous
    # profile — never inferred, because a delta on top of no core would
    # silently strip the chair of every orchestration rule.
    # GATED TO `resume`, the only fire that provably keeps the core in
    # context. `compact` re-fires BECAUSE the context was rewritten and
    # `clear` because it was discarded — a delta on either can leave the
    # chair with no threshold, no ledger rule and no routing, silently.
    # Any unrecognised future source takes the same safe side: an
    # unproven source gets the full core. Wrong-delta costs a ruleless
    # chair; wrong-full-core costs ~3.7k chars.
    switched = (bool(prev_profile) and prev_profile != profile
                and fire == "resume")
    filename = (f"profile-switch-to-{profile}.md" if switched
                else f"dynamic-workflow-{profile}.md")

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
        # The reply shape rides the FULL core only. A switch delta goes
        # to a session that already has it, and re-sending costs the
        # limit the delta exists to protect. Missing file is not fatal:
        # the profile matters more than the formatting rules.
        if not switched:
            try:
                with open(os.path.join(root, "instructions", "reply-shape.md"),
                          encoding="utf-8") as f:
                    text += f.read()
            except Exception:
                pass
        # The core tells the chair to RUN a script, and a relative path
        # cannot resolve from a user's project: the plugin lives under
        # ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/. The
        # injector is the only place that knows the real root, so the
        # placeholder is resolved here, at the moment the text is handed
        # to the chair.
        text = text.replace(WATCHDOG_PLACEHOLDER,
                            os.path.join(root, "scripts", "agent_watchdog.py"))

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
            # `profile` records what this session was actually TOLD, so
            # the next fire can tell a switch from a plain re-fire. A
            # teammate received nothing, so its marker carries the
            # previous value forward rather than claiming an injection
            # that never happened.
            stored_profile = prev_profile if teammate else profile
            # Atomic replace: a crash mid-write must never leave a
            # truncated marker. The tmp name keeps the fable-orch-*.json
            # shape so an orphan from a crash still matches the 96h sweep.
            tmp = f"{cache}.{os.getpid()}.tmp.json"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"model": stored_model, "session_id": session_id,
                     "started": round(started, 3), "profile": stored_profile},
                    f,
                )
            os.replace(tmp, cache)
    except Exception:
        pass

    if teammate:
        _metric("inject_skipped", session_id, model=model, profile=profile,
                source=source, reason="teammate")
        return

    if switched:
        # Distinct event, not a field on `inject`: an inject counts a
        # session that received the discipline, a switch counts a chair
        # that moved tiers mid-session. `fire` records which SessionStart
        # kind delivered the delta (resume/compact/clear).
        _metric("inject_switch", session_id, model=model, profile=profile,
                source=source, from_profile=prev_profile, fire=fire)
    else:
        _metric("inject", session_id, model=model, profile=profile,
                source=source)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))


if __name__ == "__main__":
    main()
