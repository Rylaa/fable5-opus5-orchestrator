#!/usr/bin/env python3
"""Agent watchdog: tell a working teammate apart from one that never started.

The failure this exists for, measured in the wild on 2026-08-26: the chair
spawned a named verifier at 18:50:40 and got back "Spawned successfully ...
The agent is now running". The pane opened and the process was alive — `ps`
showed `--agent-id verifier@session-7070d3e7` with 2m34s elapsed — but its
session never booted: no SessionStart, no transcript, and the brief on disk
was never read. The chair reported "still running (35 min)" and waited 39
minutes for a process that was wedged before its first turn.

So "the process exists" is NOT liveness — and its absence is NOT death.
The process table is wrong in BOTH directions and cannot be the deciding
evidence either way. It is often right: on 2026-08-27 a scan of
`ps -axww` matched four live named agents by `--agent-name` and
`--team-name`. But some named spawns never appear in it at all, and a
single `ps` that fails, times out, or is run a moment too late looks
exactly like a dead wave. An agent is therefore judged by what it has
PRODUCED — its own session log — and the process table only colours the
reason and confirms what the log already says. A missing `ps` row must
never outrank a log written seconds ago: one `elif not proc: gone`
deleted live agents from the record, and because both alarms first
required a listed process, no alarm in this module could ever fire.

A real teammate line, captured live:

    --agent-id angleA-2@session-7070d3e7 --agent-name angleA-2
    --team-name session-7070d3e7 --parent-session-id dfa11252-... --model opus

Three things decide the whole design:

  * `--agent-name` is the ASSIGNED name and the only reliable join key. The
    chair asked for `angleA`; the harness disambiguated it to `angleA-2`.
    Keying on the requested name loses every renamed agent. The name is
    read back out of the spawn result, which carries it as
    `agent_id: <assigned>@<team>` with a `name: <assigned>` line beside it.
  * a pane is claimed only when its `--team-name` matches the record's.
    Two teams routinely run an agent with the same name, and joining on
    the bare name lent one team's pane — its pid, its cpu time — to
    another team's wedged agent.
  * a session log is this agent's only if its own records declare BOTH
    `agentName` and `teamName`, read as FIELDS and not as substrings. The
    chair's log declares neither and quotes the spawn result verbatim, so
    a substring test handed the chair's own transcript to a wedged agent
    and reported it working — the one verdict this module exists to
    prevent.

`claude agents --json` is not a source here: measured with ten live team
members, it returned ten top-level sessions and not one of them. Team
members do not appear in it, so nothing joins.

NOTHING HERE BLOCKS OR KILLS. `--record` runs as a PostToolUse hook, which
cannot block by design; `--surface` adds at most one line of context to a
turn the user was starting anyway; `--check` and `--watch` are read-only
reporters. Acting on a stalled agent is the chair's decision, made with
this table in front of it — never this script's.

States:
    starting   spawned, nothing produced yet, still inside the birth window
    unborn     past the birth window with no session log of its own
    working    its session log was written inside the stall window
    stalled    the log went quiet past the stall window with work in flight
    idle       quiet past the stall window, but its last turn ENDED — it
               has reported and is waiting to be dismissed
    gone       dismissed by the chair, or its turn ended and no pane is
               listed by a process scan that succeeded

Only `unborn` and `stalled` are alarms, and each one is reported ONCE: the
verdict is written back to the record, so a watchdog teammate that loops
and a hook that runs on every prompt do not repeat themselves.

Modes:
    --record            PostToolUse: remember a NAMED spawn (stdin payload)
    --check [--json]    one-shot status table for every remembered agent
    --watch             loop for a watchdog teammate: quiet until a new
                        alarm, the wave ends, or --timeout expires
    --surface           UserPromptSubmit: one line, and only for an alarm
                        nobody has been told about yet

Configuration:
    FABLE_ORCH_WATCHDOG=0        disable every mode (all become no-ops)
    FABLE_ORCH_WATCH_BIRTH_S     seconds before a log-less agent is called
                                 `unborn` (default 120)
    FABLE_ORCH_WATCH_STALL_S     seconds of log silence before `stalled`
                                 (default 600)
    FABLE_ORCH_WATCH_INTERVAL    --watch poll interval (default 30, floor 5)
    FABLE_ORCH_WATCH_SELF        comma-separated watcher names, excluded from
                                 their OWN alarms (default "watchdog")
"""
import argparse
import glob
import json
import os
import re
import sys
import subprocess
import tempfile
import time
# Loaded by path (a hook command, a test's spec_from_file_location),
# so the scripts directory is not always on sys.path already.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _shared import (
        tmp_json as _tmp_json,
        metric as _metric,
        budget as _budget,
        cpu_seconds as _cpu_seconds)
except Exception:
    # `_shared.py` ships beside this file. A partial install, a half-copied
    # plugin directory or an unreadable sibling leaves this hook with no
    # helpers and therefore no decision it can make. Degrade to nothing at
    # all: say nothing, deny nothing, block nothing, exit 0. Every hook here
    # is fail-open by design, and an import error at module scope would be
    # the one failure that ignores that, killing a turn with a traceback on
    # every single prompt.
    sys.exit(0)

try:
    import fcntl
except ImportError:                                   # pragma: no cover
    fcntl = None

BIRTH_S = 120.0
STALL_S = 600.0
INTERVAL_S = 30.0
INTERVAL_FLOOR_S = 5.0
WATCH_TIMEOUT_S = 100.0     # under the Bash tool's 120s default, on purpose
SELF_NAMES = ("watchdog",)
ALARM_STATES = ("unborn", "stalled")
WATCHER_ALARM_PREFIX = "watcher-"
TAIL_BYTES = 65536          # of a session log, enough for the last tool call
HEAD_BYTES = 8192           # a log names itself in its first records
HEAD_RECORDS = 40
# Candidate logs read per poll — ONE index is built for the whole wave, so
# this is paid once and not once per agent. Measured on this machine: 430
# session logs, ~20 touched in the last hour. The old cap of 40 was taken
# off the most-recently-written end, which drops the QUIETEST logs first —
# exactly the agents this module hunts.
MAX_TRANSCRIPT_SCAN = 200
PS_BUDGET_S = 5.0

AGENT_ID_RE = re.compile(r"--agent-id\s+(\S+)")
AGENT_NAME_RE = re.compile(r"--agent-name\s+(\S+)")
TEAM_NAME_RE = re.compile(r"--team-name\s+(\S+)")
# Both spellings, quoted or bare: a text result reads `agent_id: a@b`, a
# dict one serializes to `"agentId": "a8f8974b8ad5803a9"`.
SPAWNED_ID_RE = re.compile(r'agent[_-]?id"?\s*[:=]\s*"?([^\s",}]+)', re.I)
SPAWNED_NAME_RE = re.compile(r'(?:^|[\s,{])"?name"?\s*[:=]\s*"?([^\s",}]+)',
                             re.I | re.M)
TRAILING_PUNCT = ".,;:)]}"


def _enabled():
    return (os.environ.get("FABLE_ORCH_WATCHDOG") or "").strip() != "0"


def _float_env(name, default, floor=0.0):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(floor, float(raw))
    except ValueError:
        return default


def _self_names():
    raw = os.environ.get("FABLE_ORCH_WATCH_SELF")
    if raw is None:
        return set(SELF_NAMES)
    names = {n.strip() for n in raw.split(",") if n.strip()}
    # An empty setting means "no watcher exemption", not "disable the
    # feature" — but an empty STRING is far more likely a mistake than an
    # intent, so it falls back to the default rather than silently
    # dropping the exemption.
    return names or set(SELF_NAMES)


def sidecar_path(session_id):
    return _tmp_json("fable-orch-agents", session_id)


# --- the sidecar -----------------------------------------------------------

def _decode(text):
    """The agents dict out of the sidecar, or an empty one.

    `raw_decode` rather than `loads`: a writer killed at the PostToolUse
    deadline can leave the tail of an older, longer object behind the new
    one, and `loads` calls that whole file garbage. An empty read renders
    as "no spawn was seen" — the false all-clear this module must never
    print — so the first complete object wins and any tail is ignored.
    """
    try:
        data, _ = json.JSONDecoder().raw_decode(text.lstrip())
        agents = data.get("agents")
        return agents if isinstance(agents, dict) else {}
    except Exception:
        return {}


def _lock(handle, shared=False):
    """Take the file lock if this filesystem has one, and say whether it did.

    fcntl is missing on non-POSIX, and `flock` itself fails with
    EOPNOTSUPP on NFS and several network mounts. That OSError used to
    escape into the caller's `except Exception: pass`, so on such a mount
    NOTHING was ever recorded and every mode reported "no spawned agents
    on record". The spawn guard degrades the same way.
    """
    if fcntl is None:
        return False
    try:
        fcntl.flock(handle.fileno(),
                    fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        return True
    except OSError:
        return False


def _unlock(handle, locked):
    if not locked:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:                                   # pragma: no cover
        pass


def _read_sidecar(path):
    """The sidecar's contents, read under a SHARED lock.

    An unlocked reader can land between a writer's truncate and its
    write: measured, a reader polling during 300 updates saw the file at
    zero bytes, which decodes to "nothing on record".
    """
    try:
        with open(path, encoding="utf-8") as f:
            locked = _lock(f, shared=True)
            try:
                return _decode(f.read())
            finally:
                _unlock(f, locked)
    except Exception:
        return {}


def _locked_update(path, mutate):
    """Read-modify-write the sidecar under an exclusive lock.

    A wave spawns in ONE message, so its PostToolUse hooks run at the same
    moment: measured without the lock, 3 of 8 concurrent runs lost agents,
    because each hook read the file, added its own key, and wrote the whole
    dict back over a sibling's write. The lock is held across read AND
    write; where the filesystem has no lock to give it degrades to the old
    behaviour rather than refusing to record at all.

    The file is opened read-write rather than append: the new bytes are
    serialized first, written over the old ones, and the truncate happens
    AT THE END of them. The old order — truncate, then serialize into the
    handle — left the file at zero bytes for the length of the dump.
    """
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+", encoding="utf-8") as f:
            locked = _lock(f)
            try:
                f.seek(0)
                agents = mutate(_decode(f.read()))
                if agents is None:
                    return
                blob = json.dumps({"agents": agents})
                f.seek(0)
                f.write(blob)
                f.flush()
                f.truncate()
                os.fsync(f.fileno())
            finally:
                _unlock(f, locked)
    except Exception:
        pass


def record(data):
    """Remember a NAMED spawn so the later modes have something to look for.

    Only named spawns are tracked. An unnamed subagent returns THROUGH the
    tool call: the chair is inside that call while it runs, and the harness
    ends it one way or another. A named one detaches into its own session,
    and that is the only shape that can strand the chair.

    The record is keyed on the name the harness ASSIGNED — which the tool
    result carries as `agent_id: <name>@<team>`, with a `name:` line beside
    it — not on the name the chair asked for. A collision turns `angleA`
    into `angleA-2`, and every later lookup sees only the assigned one.
    """
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    requested = tool_input.get("name")
    if not isinstance(requested, str) or not requested.strip():
        return
    requested = requested.strip()
    path = sidecar_path(data.get("session_id"))
    if not path:
        return
    agent_id, spawned_name = _spawned_identity(data.get("tool_response"))
    assigned, team = requested, None
    if agent_id and "@" in agent_id:
        assigned, team = agent_id.split("@", 1)
    elif spawned_name:
        # Some spawn surfaces answer with an opaque id (`agentId:
        # a8f8974b8ad5803a9`) and name the agent on its own line. The id
        # is not a name and must never be keyed on as one.
        assigned = spawned_name
    entry = {
        "requested": requested,
        "assigned": assigned,
        "team": team,
        "agent_id": agent_id,
        "tool": data.get("tool_name"),
        "spawn": round(time.time(), 3),
    }

    def mutate(agents):
        agents[assigned] = entry
        return agents

    _locked_update(path, mutate)
    _metric("watch_record", data.get("session_id"), agent=assigned,
            renamed=assigned != requested, tool=data.get("tool_name"))


def _spawned_identity(response):
    """(agent id, assigned name) out of whatever shape the tool returned.

    The teammate surface answers `agent_id: angleA-2@session-7070d3e7`
    followed by `name: angleA-2`; another answers `agentId:` with an
    opaque id. Both spellings are read, and the capture stops at the
    first quote, comma or brace so a trailing `.` cannot end up inside a
    team name that then matches no log at all.
    """
    if isinstance(response, list):
        response = " ".join(
            c.get("text", "") for c in response if isinstance(c, dict))
    elif isinstance(response, dict):
        response = json.dumps(response)
    if not isinstance(response, str):
        return None, None
    found = SPAWNED_ID_RE.search(response)
    named = SPAWNED_NAME_RE.search(response)
    agent_id = found.group(1).rstrip(TRAILING_PUNCT) if found else None
    name = named.group(1).rstrip(TRAILING_PUNCT) if named else None
    return (agent_id or None), (name or None)


def load_agents(session_id=None):
    """Every remembered agent: this session's sidecar, or all of them.

    A watchdog TEAMMATE does not know the chair's session id, so with no
    id it reads every sidecar in the temp dir. Records are kept apart by
    the file they came from, never merged by name: two chairs each spawn
    a `verifier`, and collapsing them on the bare name made one chair's
    stalled agent surface in the other chair's session — where the advice
    is to dismiss it.
    """
    if session_id:
        paths = [p for p in [sidecar_path(session_id)] if p]
    else:
        paths = sorted(glob.glob(os.path.join(
            tempfile.gettempdir(), "fable-orch-agents-*.json")))
    loaded = {}
    for path in paths:
        for name, rec in _read_sidecar(path).items():
            if not isinstance(rec, dict):
                continue
            rec = dict(rec)
            rec.setdefault("assigned", name)
            rec.setdefault("requested", name)
            rec["key"] = name
            rec["source"] = path
            loaded[f"{path}\0{name}"] = rec
    return loaded


def prune_finished(rows):
    """Forget agents that are provably over, so the cheap modes stay cheap.

    A sidecar entry costs a log lookup on every call, and `--surface` runs
    on every prompt for the rest of the session. Only `gone` prunes, and
    `gone` needs positive evidence: a dismissal in the agent's own log, or
    a finished turn plus a process scan that SUCCEEDED and did not list
    it. A failed scan deletes nothing — the record is the only memory the
    feature has, and one transient `ps` failure once erased a live wave.
    """
    by_source = {}
    for row in rows:
        if row["state"] == "gone" and row.get("source"):
            by_source.setdefault(row["source"], set()).add(row["key"])
    for path, finished in by_source.items():
        if not os.path.isfile(path):
            continue

        def mutate(agents, finished=finished):
            remaining = {k: v for k, v in agents.items() if k not in finished}
            return remaining if len(remaining) != len(agents) else None

        _locked_update(path, mutate)


def mark_reported(rows):
    """Write an alarm back to the record, so it is raised once and not again.

    Nothing used to remember a reported alarm: `--watch` returned on the
    first alarming poll and was told to call again, and `--surface`
    re-injected the same sentence on every prompt for the rest of the
    session. The verdict itself is the memory — a state that CHANGES
    (unborn, then stalled) is news again.
    """
    by_source = {}
    for row in rows:
        if row.get("source"):
            by_source.setdefault(row["source"], {})[row["key"]] = row["state"]
    for path, states in by_source.items():
        if not os.path.isfile(path):
            continue

        def mutate(agents, states=states):
            touched = False
            for key, state in states.items():
                rec = agents.get(key)
                if isinstance(rec, dict) and rec.get("reported") != state:
                    rec["reported"] = state
                    touched = True
            return agents if touched else None

        _locked_update(path, mutate)


# --- signals ---------------------------------------------------------------

def live_processes(deadline=None):
    """({assigned name: fields}, ok) for live agent panes.

    `ok` is False when the scan itself failed. A successful scan that
    lists nothing is not "everything died" either — many named agents
    never appear here at all — so the process table only ever confirms a
    verdict the session logs already support.
    """
    try:
        proc = subprocess.run(
            ["ps", "-axww", "-o", "pid=,cputime=,command="],
            capture_output=True, text=True, timeout=_budget(deadline),
        )
        if proc.returncode != 0:
            return {}, False
        out = proc.stdout
    except Exception:
        return {}, False
    found = {}
    for line in out.splitlines():
        if "--agent-id" not in line:
            continue
        bits = line.split(None, 2)
        if len(bits) < 3:
            continue
        pid, cpu_text, command = bits
        name = AGENT_NAME_RE.search(command)
        if name:
            name = name.group(1)
        else:  # older harnesses carried only the id
            m = AGENT_ID_RE.search(command)
            if not m:
                continue
            name = m.group(1).split("@", 1)[0]
        team = TEAM_NAME_RE.search(command)
        found[name] = {
            "pid": pid,
            "cpu": _cpu_seconds(cpu_text),
            "team": team.group(1) if team else None,
        }
    return found, True


def match_process(procs, rec):
    """This agent's own pane, or None.

    The name alone does not identify a pane. A record for `verifier-2`
    falling back to a live `verifier` borrowed another team's pid and cpu
    time and reported them as its own — and the fallback could only fire
    after a rename, which is precisely when the requested name belongs to
    somebody else. So: the assigned name, and a team that agrees.
    """
    assigned = rec.get("assigned") or rec.get("requested")
    proc = procs.get(assigned)
    if not proc:
        return None
    team = rec.get("team")
    if team and proc.get("team") and proc["team"] != team:
        return None
    return proc


def _config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")


def _identity(path):
    """(agentName, teamName) declared by a session log, or None.

    A teammate's log names itself in its first user record — measured on
    four live panes, always inside the first kilobyte. A chair's log names
    nobody, which is what keeps the chair's own transcript out of the
    index: this reads the FIELD, where the old substring test also matched
    the spawn result that the chair quotes verbatim.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(HEAD_BYTES)
    except OSError:
        return None
    for line in head.splitlines()[:HEAD_RECORDS]:
        try:
            rec = json.loads(line)
        except Exception:
            continue                    # metadata, or a truncated last line
        if isinstance(rec, dict) and rec.get("agentName"):
            return rec.get("agentName"), rec.get("teamName")
    return None


def transcript_index(root, since):
    """{agent name: [{path, mtime, team}]} for logs written since the wave.

    Built ONCE per assessment. Each agent used to run this hunt for
    itself: a glob of ~/.claude/projects plus up to forty 64KB reads,
    then the matched file re-opened and re-read for its last tool. A wave
    of ten agents paid that ten times over on every user prompt, inside a
    10-second hook budget.
    """
    entries = {}
    try:
        paths = glob.glob(os.path.join(root, "*", "*.jsonl"))
    except Exception:
        return entries
    candidates = []
    for path in paths:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime >= since - 5.0:
            candidates.append((mtime, path))
    candidates.sort(reverse=True)
    for mtime, path in candidates[:MAX_TRANSCRIPT_SCAN]:
        ident = _identity(path)
        if not ident:
            continue
        name, team = ident
        entries.setdefault(name, []).append(
            {"path": path, "mtime": mtime, "team": team})
    return entries


def pick_transcript(index, rec, proc):
    """The log that belongs to THIS agent, or None.

    Name and team together, as the module docstring says. When the record
    carries no team — an unparseable spawn result — only a log that names
    no team either can agree with it: a log that DOES name one belongs to
    a team nobody can show is ours, and every wave in the playbook uses
    the same handful of names. Accepting it on the name alone is how one
    chair's `verifier` reported another chair's work as its own; refusing
    costs an alarm the chair answers with a single ping.
    """
    assigned = rec.get("assigned") or rec.get("requested")
    if not assigned:
        return None
    hits = index.get(assigned) or []
    if not hits:
        return None
    team = rec.get("team") or (proc or {}).get("team")
    if team:
        hits = ([h for h in hits if h["team"] == team]
                or [h for h in hits if h["team"] is None])
    else:
        hits = [h for h in hits if h["team"] is None]
        if len(hits) > 1:
            return None
    return max(hits, key=lambda h: h["mtime"]) if hits else None


def transcript_activity(path):
    """(last tool name, what the agent was in the middle of).

    `in_flight`   the log ends on work: a tool call, a tool result, or a
                  message nobody has answered yet
    `turn_ended`  it ends on the agent's own reply — it has reported and
                  is waiting for whatever comes next
    `dismissed`   the chair has already sent a shutdown_request

    This is what separates a wedged teammate from one that delivered.
    Measured on two live panes: the finished one ends with an assistant
    text record, the working one with a tool_use / tool_result pair. The
    reaper leaves a delivered teammate alive for an hour, so without this
    every agent of a finished wave read STALLED ten minutes later, while
    the chair was still synthesizing their reports.

    Only the tail is read, and the first line of that tail is dropped: a
    seek into the middle of a session log lands mid-record, and half a
    JSON object parses as nothing.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
            blob = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None, None
    lines = blob.splitlines()
    if size > TAIL_BYTES and lines:
        lines = lines[1:]
    last_tool = None
    activity = None
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        message = rec.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if content is None:
            continue
        kinds = set()
        if isinstance(content, list):
            kinds = {b.get("type") for b in content if isinstance(b, dict)}
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    last_tool = block.get("name") or last_tool
        if (message.get("role") or rec.get("type")) == "assistant":
            # A reply with text and no tool call ENDS the turn. A record
            # holding only `thinking` does not: the agent is mid-answer.
            activity = ("turn_ended"
                        if "text" in kinds and "tool_use" not in kinds
                        else "in_flight")
        else:
            # Anything addressed TO the agent — a tool result, a teammate
            # message — leaves work in flight until it answers.
            activity = ("dismissed" if _is_shutdown(content)
                        else "in_flight")
    return last_tool, activity


def _is_shutdown(content):
    """True for the chair's dismissal, not for a message that mentions it.

    The protocol marker is a `{"type":"shutdown_request"}` object inside
    the delivered message. The word alone is not enough: this module's
    own surface line tells the chair to "dismiss with a shutdown_request",
    and any agent handed that text would otherwise read as dismissed.
    Measured against two real logs — one dismissed, one working — the
    marker separates them and the bare word does not.
    """
    if isinstance(content, list):
        content = " ".join(
            b.get("text") or "" for b in content if isinstance(b, dict))
    if not isinstance(content, str):
        return False
    return ('"type":"shutdown_request"' in content
            or '"type": "shutdown_request"' in content)


# --- verdicts --------------------------------------------------------------

def assess(agents, deadline=None):
    """One record per remembered agent, worst state first."""
    now = time.time()
    birth = _float_env("FABLE_ORCH_WATCH_BIRTH_S", BIRTH_S)
    stall = _float_env("FABLE_ORCH_WATCH_STALL_S", STALL_S)
    procs, scan_ok = live_processes(deadline)
    selves = _self_names()
    since = min([rec.get("spawn") or now for rec in agents.values()] or [now])
    root = os.path.join(_config_dir(), "projects")
    index = transcript_index(root, since) if agents else {}

    out = []
    for rec in agents.values():
        assigned = rec.get("assigned") or rec.get("requested")
        requested = rec.get("requested") or assigned
        spawn = rec.get("spawn") or now
        age = max(0.0, now - spawn)
        proc = match_process(procs, rec)
        hit = pick_transcript(index, rec, proc)
        path = hit["path"] if hit else None
        quiet = (now - hit["mtime"]) if hit else None
        last_tool, activity = (transcript_activity(path) if path
                               else (None, None))

        # The session log leads. The process table can confirm that a
        # finished agent is over, and it can say a log-less pane is up,
        # but it never overrules work that is on disk.
        if path and activity == "dismissed":
            state = "gone"
            why = "dismissed by the chair"
        elif path and quiet < stall:
            state = "working"
            why = f"last wrote {int(quiet)}s ago"
        elif path and activity == "in_flight":
            state = "stalled"
            why = f"session log untouched for {int(quiet)}s, mid-work"
        elif path and scan_ok and not proc:
            state = "gone"
            why = "its last turn ended and no pane is listed"
        elif path:
            state = "idle"
            why = f"reported {int(quiet)}s ago, waiting to be dismissed"
        elif age < birth:
            state = "starting"
            why = "still starting up"
        else:
            state = "unborn"
            why = ("process alive but no session log — it never ran a turn"
                   if proc else "no session log — it never ran a turn")

        watcher = assigned in selves or requested in selves
        if watcher and state in ALARM_STATES:
            state = WATCHER_ALARM_PREFIX + state
        out.append({
            "name": assigned, "requested": requested, "state": state,
            "why": why, "age_s": int(age),
            "idle_s": int(quiet) if quiet is not None else None,
            "cpu_s": (proc or {}).get("cpu"), "last_tool": last_tool,
            "pid": (proc or {}).get("pid"), "transcript": path,
            "agent_id": rec.get("agent_id"), "watcher": watcher,
            "reported": rec.get("reported"),
            "key": rec.get("key", assigned), "source": rec.get("source"),
        })
    order = {"unborn": 0, "stalled": 1, "starting": 2, "idle": 3,
             "working": 4, "gone": 5}
    out.sort(key=lambda r: (order.get(r["state"].replace(
        WATCHER_ALARM_PREFIX, ""), 2), r["name"]))
    return out, scan_ok


def alarms(rows, include_watchers=False):
    """Rows worth waking someone for.

    A watcher never alarms on ITSELF — it would message the chair about
    its own health forever. But a wedged watcher is the one failure that
    silences the whole feature, so the chair-side hook DOES count it:
    `include_watchers=True` is what `--surface` passes.
    """
    hits = []
    for r in rows:
        state = r["state"]
        if state in ALARM_STATES:
            hits.append(r)
        elif include_watchers and state.startswith(WATCHER_ALARM_PREFIX):
            hits.append(r)
    return hits


def unreported(rows):
    """The alarms nobody has been told about yet."""
    return [r for r in rows if r.get("reported") != r["state"]]


def render(rows):
    if not rows:
        return "no spawned agents on record"
    lines = []
    for r in rows:
        label = r["name"]
        if r["requested"] and r["requested"] != r["name"]:
            label = f"{r['name']} (asked for {r['requested']})"
        bits = [f"{label}: {r['state'].upper()}", f"age {r['age_s']}s"]
        if r["idle_s"] is not None:
            bits.append(f"quiet {r['idle_s']}s")
        if r["last_tool"]:
            bits.append(f"last tool {r['last_tool']}")
        if r["cpu_s"] is not None:
            bits.append(f"cpu {r['cpu_s']:.0f}s")
        lines.append(" · ".join(bits) + f" — {r['why']}")
    return "\n".join(lines)


# --- modes -----------------------------------------------------------------

def mode_check(args, data):
    """The full table, on demand — the mode the chair runs by hand.

    It reports every row every time and remembers nothing: this is the
    answer to "what is the wave doing right now", asked by someone who
    already knows an alarm is open.
    """
    session = args.session or (data or {}).get("session_id")
    rows, _ = assess(load_agents(session),
                     deadline=time.monotonic() + PS_BUDGET_S)
    prune_finished(rows)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(render(rows))
    for r in alarms(rows, include_watchers=True):
        _metric("watch_alarm", session, agent=r["name"], state=r["state"],
                age=r["age_s"])


def mode_watch(args, data):
    """Poll until something is worth saying, then print the table and stop.

    This is the WATCHDOG TEAMMATE's loop, never the chair's: the chair goes
    idle after spawning its wave exactly as before, and hears from the
    watchdog only when a state changes for the worse. Quiet is the default
    — a healthy `starting -> working` transition is not news, and returning
    on it made the watchdog a one-shot that died two minutes into every
    wave. An alarm already reported is not news either, or the loop would
    return in 50ms and message the chair about the same agent forever.

    The default deadline sits under the Bash tool's 120s default so a
    plain call returns a table instead of being killed with no output.
    The caller loops.
    """
    session = args.session or (data or {}).get("session_id")
    deadline = time.monotonic() + args.timeout
    interval = (args.interval if args.interval is not None
                else _float_env("FABLE_ORCH_WATCH_INTERVAL", INTERVAL_S))
    interval = max(INTERVAL_FLOOR_S, interval)
    previous = None
    seen_live = False
    while True:
        rows, scan_ok = assess(load_agents(session),
                               deadline=time.monotonic() + PS_BUDGET_S)
        state = {r["key"]: r["state"] for r in rows}
        hits = unreported(alarms(rows))
        # The watchdog is itself a recorded named spawn, and a watcher's
        # own row would keep the wave "live" for as long as the watcher
        # runs — which is always.
        wave = [r for r in rows if not r["watcher"]]
        live = [r for r in wave if r["state"] != "gone"]
        seen_live = seen_live or bool(live)
        changed = previous is not None and state != previous
        previous = state

        if hits:
            reason = "alarm"
        elif wave and not live and seen_live:
            reason = "all agents finished"
        elif args.verbose and changed:
            reason = "state changed"
        else:
            reason = None

        if reason:
            print(f"[watchdog] {reason}")
            print(render(rows))
            mark_reported(hits)
            for r in hits:
                _metric("watch_alarm", session, agent=r["name"],
                        state=r["state"], age=r["age_s"])
            return
        if time.monotonic() + interval >= deadline:
            # An empty record is NOT a finished wave: it is equally what a
            # missing hook looks like. Saying "finished" there is a false
            # all-clear, which is worse than no watchdog at all.
            if not rows:
                print("[watchdog] nothing on record — no spawn was seen. "
                      "Check that the PostToolUse hook is installed; do NOT "
                      "read this as a finished wave.")
                return
            print("[watchdog] no change" if scan_ok
                  else "[watchdog] no change (process scan failed)")
            print(render(rows))
            return
        time.sleep(interval)


def mode_surface(args, data):
    """UserPromptSubmit: one line, and only for an alarm not yet raised.

    Silence is the default and the common case. This runs on the user's
    own keystroke, so it stays to one `ps` call and one pass over the
    session logs the record already implies.
    """
    session = (data or {}).get("session_id")
    rows, _ = assess(load_agents(session),
                     deadline=time.monotonic() + PS_BUDGET_S)
    prune_finished(rows)
    hits = unreported(alarms(rows, include_watchers=True))
    if not hits:
        return
    mark_reported(hits)
    summary = "; ".join(f"{r['name']} {r['state']} for {r['age_s']}s"
                        for r in hits[:4])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                f"AGENT WATCHDOG: {summary}. These agents are not producing "
                "work. Ping with SendMessage; if there is no reply, dismiss "
                "with a shutdown_request and re-spawn, or do the work in the "
                f"chair. Full table: python3 \"{os.path.abspath(__file__)}\" "
                "--check"
            ),
        }
    }))


def watch_disabled(timeout):
    """`--watch` with the feature switched off, without a spin.

    `FABLE_ORCH_WATCHDOG=0` cannot reach the teammate's instructions: the
    profile tells it to call `--watch` and call again when it returns.
    Returning at once measured 0.05s per call, which turns that loop into
    a fork bomb for the life of the session. So the call says plainly
    that nothing is being watched and then sits out its own deadline — a
    caller that keeps looping costs one process per deadline.
    """
    print("[watchdog] disabled by FABLE_ORCH_WATCHDOG=0 — stop looping and "
          "tell the chair that this wave is unwatched.")
    sys.stdout.flush()
    time.sleep(max(0.0, timeout))


def main():
    parser = argparse.ArgumentParser(add_help=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--watch", action="store_true")
    group.add_argument("--surface", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--session")
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--timeout", type=float, default=WATCH_TIMEOUT_S)
    parser.add_argument("--verbose", action="store_true",
                        help="--watch: also return on a harmless state change")
    args = parser.parse_args()

    if not _enabled():
        if args.watch:
            watch_disabled(args.timeout)
        return

    # ONLY the two hook modes are handed a payload. `--watch` and
    # `--check` are run from a Bash call whose stdin is an open pipe, and
    # reading it there never returns: measured, `--watch --timeout 6` was
    # still alive when it was killed at 25 seconds.
    data = None
    if (args.record or args.surface) and not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            data = json.loads(raw) if raw.strip() else None
        except Exception:
            data = None
    if not isinstance(data, dict):
        data = None

    try:
        if args.record:
            if data:
                record(data)
        elif args.check:
            mode_check(args, data)
        elif args.watch:
            mode_watch(args, data)
        elif args.surface:
            mode_surface(args, data)
    except Exception:
        return  # read-only reporter: it never breaks a turn


if __name__ == "__main__":
    main()
