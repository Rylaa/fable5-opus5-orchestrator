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
walk the solo guard uses (`--agent-id` on the nearest claude ancestor);
the session marker is still written so the other hooks keep working.
FABLE_ORCH_TEAMMATE_INJECT=1 restores the old inject-everyone
behaviour.

The hook also maintains the per-session marker the other hooks rely
on: its immutable `started` timestamp survives the re-runs SessionStart
gets on resume/clear/compact, and the SessionEnd sweep keys off it.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shared import is_teammate_session, metric, tmp_json  # noqa: E402


def session_model_cache_path(session_id):
    """Per-session marker file the other hooks read. None if no id."""
    return tmp_json("fable-orch-model", session_id)


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
    # chair with no threshold, no spawn discipline and no routing.
    # Any unrecognised future source takes the same safe side: an
    # unproven source gets the full core. Wrong-delta costs a ruleless
    # chair; wrong-full-core costs ~3.7k chars.
    # ALSO GATED TO AN AUTHORITATIVE SIGNAL. Only the payload model and
    # the env pin describe THIS session's chair; the settings default is
    # global (another session's `/model` moves it) and the marker model
    # is sticky history. A "switch" derived from either would tell a
    # chair that never moved that its limit is spent and ban the tier it
    # is sitting on — then ping-pong back on the next real payload.
    switched = (bool(prev_profile) and prev_profile != profile
                and fire == "resume" and source in ("payload", "override"))
    filename = (f"profile-switch-to-{profile}.md" if switched
                else f"dynamic-workflow-{profile}.md")

    # The profile is chair-only; a teammate session skips the injection
    # but still gets its marker below — stop, spawn, and cleanup key off
    # it. Resolution ran first so the skip metric records which profile
    # the worker WOULD have received.
    teammate = False
    if (os.environ.get("FABLE_ORCH_TEAMMATE_INJECT") or "").strip() != "1":
        teammate = is_teammate_session()

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
            text = None  # nothing delivered; the marker below records that

    # Session marker for the guards (best effort; never fatal).
    # `started` marks the session's FIRST start and must survive the
    # re-runs SessionStart gets on resume/clear/compact — the stop guard
    # the sweep and the solo guard key off it, so it can never move
    # forward. `model` keeps the last NON-EMPTY model seen, so
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
                # would disown state written before this re-run.
                try:
                    started = os.path.getmtime(cache)
                except OSError:
                    started = time.time()
            stored_model = model if str(model or "").strip() else prev_model
            # `profile` records what this session was actually TOLD, so
            # the next fire can tell a switch from a plain re-fire. A
            # fire that delivered nothing (teammate skip, unreadable
            # instructions) records no new profile: on `resume` the
            # earlier core is provably still in context, so the previous
            # value carries forward; on any other fire the context may
            # have been rewritten or discarded, so the record is CLEARED
            # — a later switch then gets the full core, never a bare
            # delta on top of nothing.
            if text is not None:
                stored_profile = profile
            elif fire == "resume":
                stored_profile = prev_profile
            else:
                stored_profile = None
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
        metric("inject_skipped", session_id, model=model, profile=profile,
               source=source, reason="teammate")
        return
    if text is None:
        return  # never break session start

    if switched:
        # Distinct event, not a field on `inject`: an inject counts a
        # delivery of the discipline, a switch counts a chair that moved
        # tiers mid-session and received only the delta.
        metric("inject_switch", session_id, model=model, profile=profile,
               source=source, from_profile=prev_profile, fire=fire)
    elif prev_profile and prev_profile != profile:
        # A profile change the gate turned into a full core. Still a
        # plain `inject`, but `from_profile` + `fire` record WHICH
        # SessionStart kinds real fallback re-fires arrive on — the data
        # a decision to widen the delta gate has to rest on.
        metric("inject", session_id, model=model, profile=profile,
               source=source, from_profile=prev_profile, fire=fire)
    else:
        metric("inject", session_id, model=model, profile=profile,
               source=source)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))


if __name__ == "__main__":
    main()
