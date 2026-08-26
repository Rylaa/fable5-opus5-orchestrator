#!/usr/bin/env python3
"""PreToolUse guard (Agent|Task|Workflow|TaskCreate): keep multi-phase work on the ledger.

Dynamic Workflow Rule 1: serious multi-phase delegation requires
a Requirements Ledger in .workflow/ — any LEDGER*.md there, most
recent wins, *-archive.md excluded (searched from the working
directory up to the repo root or $HOME). Short spawn
prompts (quick searches/lookups) pass freely so casual Explore
agents are never blocked.

What is gated:
    Agent / Task  -> length of tool_input.prompt
    Workflow      -> length of tool_input.script (an orchestration
                     script IS the delegation plan; name/scriptPath
                     resume calls carry no new plan text and pass)
    TaskCreate    -> the SOLO path the spawn gates can't see: a chair
                     that never delegates never trips them, but the
                     tracker tasks it creates for itself are the tell.
                     The Nth TaskCreate of a session (default 3rd)
                     with no ledger draws ONE deny — "multi-phase
                     work: write the ledger, delegate to workers" —
                     then stays quiet (measured in the wild: a
                     6-phase plan implemented entirely on the chair).
Exempt:
    fork subagents (subagent_type == "fork") — a fork inherits the
    full conversation context, so the ledger is already in front
    of it; forcing a file adds nothing.

Rule 0.5 rides the same gates. A ledger only satisfies them when it
carries a NON-EMPTY `## Clarified` section: the answers the chair got
from the user, plus the assumptions it is proceeding on. Workers
cannot ask the user anything, so every ambiguity that reaches a spawn
prompt becomes a guess committed to code — the section is where that
guessing is spent instead. The heading alone does not count; a chair
that types the header and spawns anyway has clarified nothing.

The threshold defaults to 1500 chars — strict on purpose. This
plugin is built for a Claude Fable 5 chair, where even small
delegations should carry a ledger: Fable tokens are the scarce
resource, and detail loss at task->plan translation is exactly
what the ledger exists to catch.

Staleness: a ledger satisfies the gates unless it is STALE-COMPLETE —
every item closed AND untouched since before this session started
(session start read from the injector's marker). Without that rule,
last week's finished ledger would silence the gates in a repo forever.
A ledger with open items, or one touched this session, always
satisfies; without a marker (manual install) existence alone wins.

Configuration (all optional):
    LEDGER_GUARD_THRESHOLD   gate in chars (default 1500; unparseable
                             values fall back to it, negatives clamp
                             to 0)
    LEDGER_GUARD_TASKS       deny fires AT the Nth ledgerless tracker
                             task (default 3 — two tasks pass free;
                             0 or negative disables the task gate)
    LEDGER_GUARD_CLARIFY=0   disables the Rule 0.5 clarify gate; the
                             ledger gates keep working
    FABLE_ORCH_METRICS=0     disables the local metrics log
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # non-POSIX: run unlocked, best effort
    fcntl = None

DEFAULT_THRESHOLD = 1500
DEFAULT_TASK_LIMIT = 3
# The close guard's dialect, character for character: `-` and `*` only.
# A `+` bullet is deliberately outside it, and a guard that counted `+`
# while the close guard did not would keep a `+`-bulleted ledger
# permanently non-stale while its close was never held.
OPEN_ITEM_RE = r"^\s*[-*] \[ \](?:\s.*)?$"
CLARIFIED_HEADING_RE = r"^[ \t]{0,3}(#{1,6})[ \t]*clarified\b[^\n]*$"
# No space required after the hashes, because the heading that OPENS
# the section does not require one either: `##Clarified` started a
# section that `##Items` could not end, so an empty section ran on
# past the ledger's own headings looking for content.
ATX_HEADING_RE = r"^[ \t]{0,3}(#{1,6})(?!#)"
SETEXT_UNDERLINE_RE = r"^[ \t]{0,3}(?:=+|-+)[ \t]*$"
# ANY checkbox ends the Clarified section: the numbered items live
# directly below it with no heading in between, and a rule that only
# recognised `- [ ] 3.` let an empty heading over unnumbered items pass
# as if the requirements were the answers. Answers are plain bullets;
# the deny text says so.
CHECKBOX_RE = r"^\s*[-*+][ \t]+\[[^\]]?\]"
# Lines that are punctuation rather than an answer: thematic breaks,
# HTML comments, and table rules. A chair that typed the heading and a
# divider has still clarified nothing.
NON_ANSWER_RE = (r"^[ \t]{0,3}(?:(?:[-*_][ \t]*){3,}"
                 r"|<!--.*"
                 r"|\|[ \t|:-]*\|[ \t]*)$")


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


def threshold():
    raw = os.environ.get("LEDGER_GUARD_THRESHOLD")
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_THRESHOLD


def task_limit():
    raw = os.environ.get("LEDGER_GUARD_TASKS")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_TASK_LIMIT


def _task_sidecar(session_id):
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"fable-orch-tasks-{safe}.json")


def _bump_task_count(path, key="denied"):
    """Read-increment-write the sidecar under an exclusive lock.

    Parallel TaskCreate hooks race on this file; without the lock the
    deny can be skipped or fired twice (proven under forced
    concurrency). Valid-JSON-but-wrong-typed content must coerce, not
    crash — the hook contract is exit 0 always. Returns
    (count, denied_before) or None when the file can't be used.

    `key` picks WHICH one-per-session budget is being spent: the
    missing/stale-ledger nudge ("denied") and the clarify nudge
    ("denied_clarify") are separate reminders that say different
    things, so spending one must not silence the other. The COUNT is
    per key for the same reason — a shared counter meant the blocker
    that appeared second got none of the documented free tasks, so a
    chair that obeyed the first nudge was denied again on its very
    next task.
    """
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
        counts = state.get("counts")
        if not isinstance(counts, dict):
            counts = {}
        try:
            count = int(counts.get(key) or 0)
        except (TypeError, ValueError, OverflowError):
            count = 0
        count += 1
        counts = {k: v for k, v in counts.items() if k in ("denied", "denied_clarify")}
        counts[key] = count
        denied_before = bool(state.get(key))
        deny_now = count >= task_limit() and not denied_before
        flags = {k: bool(state.get(k)) for k in ("denied", "denied_clarify")}
        flags[key] = denied_before or deny_now
        try:
            f.seek(0)
            f.truncate()
            json.dump(dict(counts=counts, **flags), f)
            f.flush()
        except (OSError, ValueError):
            pass
        return count, denied_before
    finally:
        f.close()


def guard_task_create(data):
    """Deny the Nth unguarded tracker task of a session — once.

    Unguarded means the ledger is missing, stale, or carries no
    `## Clarified` record; the deny text names which. Counting lives
    in a per-session sidecar so the gate never leaks across sessions;
    without a session_id there is nothing safe to scope to, so the
    call passes. The denied call creates no task and may simply be
    re-issued once the ledger is in order.
    """
    limit = task_limit()
    if limit <= 0:
        return
    session_id = data.get("session_id")
    ledger, blocker = ledger_state(data)
    if blocker is None:
        return

    path = _task_sidecar(session_id)
    if path is None:
        return
    bumped = _bump_task_count(
        path, "denied_clarify" if blocker == "unclarified" else "denied")
    if bumped is None:
        return
    count, denied_before = bumped

    if count < limit:
        return
    if denied_before:
        _metric("tasks_suppressed", session_id, count=count, blocker=blocker)
        return

    _refuse(
        blocker, ledger,
        f"this is tracker task #{count} this session — multi-phase work — but",
        "Rule 0's hard cap: work that needs a task list of 3+ items is "
        "OVER the orchestration threshold, and an approved plan is NOT "
        "an exemption. Write the Requirements Ledger to "
        "./.workflow/LEDGER.md now — a `## Clarified` section carrying "
        "the answers you got from the user, then the numbered "
        "`- [ ] N. <item>` lines — and delegate implementation to sonnet "
        "workers citing ledger items instead of implementing the phases "
        "yourself. Re-issue this task afterwards — this reminder fires "
        "once per session.",
        ("tasks_deny", "tasks_clarify_deny"), session_id,
        count=count, threshold=limit,
    )


def active_ledger_in(dirpath):
    """The live ledger in dirpath/.workflow, or None.

    Any `LEDGER*.md` counts, not just the bare name: measured in the
    wild, 42 of 56 real ledger files carried a per-task name like
    `LEDGER-<topic>.md`, and every one of them was invisible to these
    guards. A name ENDING in `-archive.md` (or `_archive.md`) is
    retired and excluded — that rename is the documented way to put a
    ledger to rest, and the deny messages below ask for exactly it.
    The suffix has to be trailing: `LEDGER-archive-migration.md` is a
    live ledger whose topic happens to be archives, and it counts.
    Matching is case-insensitive. When several are live the most
    recently modified readable one wins: that is the one this session
    is working in. An UNREADABLE ledger never masks a readable
    sibling, but when it is the only candidate it is returned anyway,
    and the guards fail open on the read — the documented behaviour.
    Skipping it here instead produced "no active ledger exists in any
    .workflow/" about a file that plainly does exist.
    """
    workflow = os.path.join(dirpath, ".workflow")
    try:
        names = os.listdir(workflow)
    except OSError:
        return None
    best, best_mtime = None, -1.0
    unreadable, unreadable_mtime = None, -1.0
    for name in names:
        low = name.lower()
        if not (low.startswith("ledger") and low.endswith(".md")):
            continue
        # "ledger" must be a whole segment: LEDGER.md, LEDGER-topic.md,
        # LEDGER_topic.md — but not ledgers.md or ledgerish.md.
        if low[6:7] not in (".", "-", "_"):
            continue
        # Retired only when "archive" is the trailing segment, the form
        # this hook's own message asks for. A live ledger ABOUT archives
        # (LEDGER-archive-migration.md) must still count.
        if low.endswith("-archive.md") or low.endswith("_archive.md"):
            continue
        path = os.path.join(workflow, name)
        try:
            if not os.path.isfile(path):
                continue
            mtime = os.path.getmtime(path)
            # An unreadable file must not mask a live sibling by being
            # newer — but remember it, in case it is all there is.
            if not os.access(path, os.R_OK):
                if mtime > unreadable_mtime:
                    unreadable, unreadable_mtime = path, mtime
                continue
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    return best or unreadable


def find_ledger(start_dir):
    """Path of the live .workflow/ ledger from start_dir up to the repo root or $HOME.

    Walks parent directories so sessions running in a subdirectory
    still see the project ledger. Stops at the first directory that
    contains .git (checked with os.path.exists, not isdir — in
    worktrees and submodules .git is a FILE), at the home directory
    (a ledger above $HOME belongs to nobody), or at the filesystem
    root. realpath, not abspath: a symlinked cwd must climb the REAL
    project tree, or a legitimate ledger next to it is never found.
    """
    if not isinstance(start_dir, str) or not start_dir:
        start_dir = os.getcwd()
    d = os.path.realpath(start_dir)
    home = os.path.realpath(os.path.expanduser("~"))
    while True:
        candidate = active_ledger_in(d)
        if candidate:
            return candidate
        if os.path.exists(os.path.join(d, ".git")) or d == home:
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _session_started(session_id):
    """The session's immutable start time from the injector marker, or None."""
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    path = os.path.join(tempfile.gettempdir(), f"fable-orch-model-{safe}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f).get("started")
        if raw is not None:
            return float(raw)
    except Exception:
        pass
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def read_ledger(path):
    """The ledger's text, or None when it cannot be read.

    One read per gated call: ledger_state hands the same text to both
    checks. Reading twice left a window where the file could be
    replaced or archived between them and the second read would fail
    open on a ledger that no longer existed.
    """
    try:
        # utf-8-sig, not utf-8: an editor that writes a BOM put U+FEFF
        # in front of a line-1 `## Clarified`, the heading stopped
        # matching, and the chair was denied every time it rewrote the
        # very section it already had — a loop with no way out.
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def ledger_satisfies(ledger, session_id, text=None):
    """False only for a STALE-COMPLETE ledger: all items closed AND
    untouched since before this session started. Open items or a
    this-session touch keep it armed; no marker → existence wins."""
    if text is None:
        text = read_ledger(ledger)
    if text is None:
        return True
    # Fences stripped, exactly like the close guard: a ledger that
    # QUOTES the `- [ ] 1. <item>` format in a markdown example is not
    # a ledger with an open item, and counting one there kept finished
    # ledgers permanently non-stale.
    if re.findall(OPEN_ITEM_RE, "\n".join(_outside_fences(text)), flags=re.M):
        return True
    started = _session_started(session_id)
    if started is None:
        return True
    try:
        return os.path.getmtime(ledger) >= min(started, time.time()) - 5.0
    except OSError:
        return True


TEAMMATE_DETECT_BUDGET = 1.5  # seconds; the walk measures ~5ms in practice


def _budget(deadline, cap=5.0):
    if deadline is None:
        return cap
    return max(0.1, min(cap, deadline - time.monotonic()))


def _is_teammate_session(max_hops=12):
    """True when this hook is running inside a named teammate.

    These gates are CHAIR discipline. A teammate cannot reach the user
    to clarify anything, cannot be given the clarify skill (the
    injector skips it), and does not own the chair's ledger — denying
    its spawns tells it to do something structurally impossible. The
    close guard and the injector already skip workers; this one did
    not. Same walk, same hard budget, same fail-open default: on
    exhaustion answer False so the guard still runs for the chair.
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


def clarify_gate_on():
    """The Rule 0.5 gate, on unless LEDGER_GUARD_CLARIFY is exactly "0"."""
    return (os.environ.get("LEDGER_GUARD_CLARIFY") or "").strip() != "0"


def _outside_fences(text):
    """Drop fenced code blocks — a ``` example section is not a record.

    Tracks the fence character and its length, so a ~~~ block counts
    the same as a ``` one and a four-backtick block can quote a
    three-backtick example without the inner fence closing the outer.
    A markdown example of what `## Clarified` should look like must not
    satisfy the gate that example is teaching.
    """
    kept = []
    fence = None                      # (char, length) while inside a block
    for line in text.splitlines():
        stripped = line.lstrip()
        char = stripped[:1]
        if char in ("`", "~"):
            run = len(stripped) - len(stripped.lstrip(char))
            if run >= 3:
                if fence is None:
                    fence = (char, run)
                    continue
                if char == fence[0] and run >= fence[1]:
                    fence = None
                    continue
        if fence is None:
            kept.append(line)
    return kept


def _is_answer_line(lines, index):
    """True when lines[index] is a real answer, not punctuation.

    A divider, an HTML comment, or a table rule is not clarification.
    Neither is the text half of a setext heading — but only when it is
    a paragraph: `- No ambiguity: ...` followed by a `---` divider is a
    LIST ITEM plus a break, and the deny text tells chairs to write
    exactly that line.
    """
    line = lines[index]
    if not line.strip():
        return False
    if re.match(NON_ANSWER_RE, line):
        return False
    nxt = lines[index + 1] if index + 1 < len(lines) else ""
    if re.match(SETEXT_UNDERLINE_RE, nxt) and not re.match(r"^\s*[-*+>]", line):
        return False                  # a setext heading, not an answer
    return True


def _section_has_content(lines, index, level):
    """True when the section starting at `index` carries a real answer.

    It ends at the first checkbox — the numbered items sit directly
    below with no heading between — or at a heading of the SAME or a
    shallower level. A DEEPER sub-heading is inside the section, not
    after it: the protocol appends later rounds, and `### Round 2` is
    how a chair naturally files them.
    """
    while index < len(lines):
        line = lines[index]
        if re.match(CHECKBOX_RE, line):
            return False
        atx = re.match(ATX_HEADING_RE, line)
        if atx and len(atx.group(1)) <= level:
            return False
        if _is_answer_line(lines, index):
            return True
        index += 1
    return False


def ledger_clarified(ledger, text=None):
    """True when the ledger carries a NON-EMPTY `## Clarified` section.

    The heading alone is not the record: a chair that types the header
    and spawns anyway has clarified nothing. EVERY heading is checked,
    not just the first — the protocol appends later answers, so a
    filled section lower in the file counts even when an empty one
    sits above it.

    Level and case are free (`# Clarified`, `### clarified`): the rule
    is about the record existing, not about markdown depth. An
    unreadable ledger fails OPEN, exactly like ledger_satisfies — a
    guard never blocks on its own IO error.
    """
    if text is None:
        text = read_ledger(ledger)
    if text is None:
        return True
    lines = _outside_fences(text)
    starts = [(i, len(m.group(1)))
              for i, line in enumerate(lines)
              for m in [re.match(CLARIFIED_HEADING_RE, line, flags=re.I)] if m]
    if not starts:
        return False
    return any(_section_has_content(lines, i + 1, level) for i, level in starts)


def ledger_state(data):
    """(ledger path or None, blocker or None).

    blocker is "missing", "stale", "unclarified", or None when the
    ledger clears both Rule 0.5 and Rule 1. Both gates below share
    this so a spawn and a tracker task can never disagree about what
    the ledger says.
    """
    ledger = find_ledger(data.get("cwd"))
    if not ledger:
        return None, "missing"
    text = read_ledger(ledger)
    if text is None:
        return ledger, None                    # unreadable → fail open
    if not ledger_satisfies(ledger, data.get("session_id"), text=text):
        return ledger, "stale"
    if clarify_gate_on() and not ledger_clarified(ledger, text=text):
        return ledger, "unclarified"
    return ledger, None


def _stale_note(ledger, blocker):
    if blocker != "stale":
        return ""
    return (
        f" (a fully-closed ledger from a previous session was found at {ledger} "
        "and ignored — archive it as LEDGER-<topic>-archive.md or write a "
        "fresh one)"
    )


def _clarify_reason(ledger, lead):
    """The Rule 0.5 deny text, shared by both gates."""
    return (
        f"CLARIFY GUARD: {lead} the ledger at {ledger} has no `## Clarified` "
        "section with content in it, so unresolved ambiguity is about to reach "
        "workers who cannot ask the user anything. Per Dynamic Workflow Rule "
        "0.5, ask the user ONE question at a time — scope edge, acceptance, "
        "constraints, whose call each choice is, priority conflicts, contact "
        "with existing code, failure behaviour — each question derived from the "
        "last answer, until nothing that would change the work is still open. "
        "Then record the answers and any explicit assumptions under "
        "`## Clarified` at the TOP of the ledger and re-issue this call. Load "
        "`orchestrator:clarify` for the protocol. Answers are PLAIN BULLETS: "
        "a checkbox line (`- [ ]`, `- [x]`) reads as a ledger item and ends "
        "the section, and a fenced example, a divider, or a bare heading does "
        "not count as content. If the request genuinely is unambiguous, say so "
        "in one line under the heading ('- No ambiguity: <why>') — the section "
        "is never skipped. If this ledger belongs to ABANDONED or unrelated "
        "work, do not write into it: archive it as "
        "LEDGER-<topic>-archive.md and start a fresh one for this task. "
        "LEDGER_GUARD_CLARIFY=0 disables this gate."
    )


def _refuse(blocker, ledger, lead, tail, events, session_id, **fields):
    """Emit the deny for `blocker` — message and metric chosen by kind.

    Both gates used to hand-roll this three-way dispatch, and the
    LEDGER GUARD preamble was written out twice. ledger_state() was
    introduced to stop exactly this drift one layer down; the same
    duplication had reappeared one layer up. `events` is
    (ledger_event, clarify_event).
    """
    if blocker == "unclarified":
        _metric(events[1], session_id, **fields)
        _deny(_clarify_reason(ledger, lead))
        return
    _metric(events[0], session_id, stale=blocker == "stale", **fields)
    _deny(
        f"LEDGER GUARD: {lead} no active ledger exists in any .workflow/ "
        f"from the working directory up to the repo root"
        f"{_stale_note(ledger, blocker)}. {tail}"
    )


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _guard(data):
    if _is_teammate_session():
        return

    if (data.get("tool_name") or "") == "TaskCreate":
        guard_task_create(data)
        return

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    # Forks inherit the full conversation context — ledger already visible.
    if str(tool_input.get("subagent_type") or "").strip().lower() == "fork":
        return

    if (data.get("tool_name") or "") == "Workflow":
        text = tool_input.get("script")
        what = "orchestration script"
    else:
        text = tool_input.get("prompt")
        what = "spawn prompt"
    if not isinstance(text, str):
        text = ""

    limit = threshold()
    if len(text) <= limit:
        return

    session_id = data.get("session_id")
    ledger, blocker = ledger_state(data)
    if blocker is None:
        _metric("spawn_pass_over_threshold", session_id,
                chars=len(text), threshold=limit,
                tool=data.get("tool_name") or "")
        return

    _refuse(
        blocker, ledger,
        f"this looks like a detailed delegation ({what} > {limit} chars) but",
        "Per Dynamic Workflow Rules 0.5 "
        "and 1, write ./.workflow/LEDGER.md with BOTH parts before you "
        "re-spawn: a `## Clarified` section holding the answers you got "
        "from the user (plain bullets, not checkboxes), then the numbered "
        "items in checkbox format ('- [ ] N. <item>'). A ledger without "
        "the first part is denied again by the clarify gate. Then re-spawn "
        "citing which ledger items each agent covers. If this is genuinely "
        "a small single-phase task, do it directly; if it is multi-phase, "
        "write the ledger and delegate — never keep multi-phase work solo.",
        ("spawn_deny", "clarify_deny"), session_id,
        chars=len(text), threshold=limit, tool=data.get("tool_name") or "",
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # malformed input -> never block
    if not isinstance(data, dict):
        return
    try:
        _guard(data)
    except Exception:
        return  # a guard fails open; it never crashes the hook pipeline


if __name__ == "__main__":
    main()
