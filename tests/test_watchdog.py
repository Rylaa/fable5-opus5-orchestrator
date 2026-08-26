"""The watchdog: does it tell a working agent from one that never started?

The fixtures here are built from a CAPTURED command line, not an imagined
one. The first cut of this suite invented a `--session-id` flag that real
agents do not carry, and two green tests covered code that could never run
in production. The real thing, taken from a live pane on 2026-08-26:

    --agent-id angleA-2@session-7070d3e7 --agent-name angleA-2
    --team-name session-7070d3e7 --parent-session-id dfa11252-... --model opus

Note `angleA-2`: the chair asked for `angleA` and the harness disambiguated
it. Note also what is NOT there: any flag naming the agent's OWN session.

The second review caught a worse version of the same disease: the whole
suite was green while no alarm in the module could fire at all, because
every fixture handed `ps` a row for the agent under test. `ps` often DOES
list a named agent — four live ones were matched by `--agent-name` and
`--team-name` on 2026-08-27 — but it is not owed: a spawn without a pane
of its own, a `ps` that fails, and a scan that times out all look the
same. So the tests below drive the verdicts with an EMPTY process table
wherever that is the honest input.
"""
import builtins
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from conftest import SCRIPTS, STRIP_ENV

WATCHDOG = SCRIPTS / "agent_watchdog.py"
TEAM = "session-7070d3e7"
PARENT = "dfa11252-3184-4287-9281-69af1407f218"

FAKE_PS = """#!/usr/bin/env python3
import os, sys, tempfile
# FAKE_PS_COUNT_FILE: one byte per fork. `--watch` scans the process
# table exactly once per poll, so the size of this file IS the number of
# polls — the only thing that separates a floored interval from a spin.
_tally = os.environ.get("FAKE_PS_COUNT_FILE")
if _tally:
    with open(_tally, "a") as f:
        f.write("x")
if os.environ.get("FAKE_PS_FAIL"):
    sys.stderr.write("ps: cannot fork\\n")
    sys.exit(1)
# FAKE_PS_ONESHOT: answer once with the live wave, then with an empty
# table — a wave that finishes between two polls.
if os.environ.get("FAKE_PS_ONESHOT"):
    marker = os.path.join(tempfile.gettempdir(), "fake-ps-oneshot")
    if os.path.exists(marker):
        sys.exit(0)
    open(marker, "w").close()
print(os.environ.get("FAKE_PS_OUTPUT", ""))
"""

# A filesystem whose flock is refused: NFS and several network mounts
# answer EOPNOTSUPP. `fcntl` is a loadable module, so a directory on
# PYTHONPATH shadows it for the child process.
FAKE_FCNTL = """LOCK_SH = 1
LOCK_EX = 2
LOCK_UN = 8


def flock(fd, op):
    raise OSError(45, "Operation not supported")
"""


@pytest.fixture
def sandbox(tmp_path):
    """A world of its own: temp dir, a `ps` shim, and a projects root."""
    (tmp_path / "tmp").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "cfg" / "projects" / "proj").mkdir(parents=True)
    path = tmp_path / "bin" / "ps"
    path.write_text(FAKE_PS, encoding="utf-8")
    os.chmod(path, 0o755)
    return tmp_path


def env_for(sandbox, ps="", ps_fail=False, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env.update({
        "TMPDIR": str(sandbox / "tmp"),
        "TEMP": str(sandbox / "tmp"),
        "TMP": str(sandbox / "tmp"),
        "CLAUDE_CONFIG_DIR": str(sandbox / "cfg"),
        "PATH": str(sandbox / "bin") + os.pathsep + env.get("PATH", ""),
        "FABLE_ORCH_METRICS": "0",
        "FAKE_PS_OUTPUT": ps,
    })
    if ps_fail:
        env["FAKE_PS_FAIL"] = "1"
    env.update(env_extra or {})
    return env


def run(sandbox, *args, payload=None, ps="", ps_fail=False, env_extra=None):
    """Run the watchdog with argv, returning (stdout, parsed json or None)."""
    proc = subprocess.run(
        [sys.executable, str(WATCHDOG), *args],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True, timeout=90,
        env=env_for(sandbox, ps, ps_fail, env_extra),
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    parsed = None
    if out.startswith(("{", "[")):
        try:
            parsed = json.loads(out)
        except ValueError:
            parsed = None
    return out, parsed


def ps_line(name, cpu="00:04.03", team=TEAM, parent=PARENT):
    """One `ps -axww -o pid=,cputime=,command=` row, shaped like the real one."""
    return (f" 23725 {cpu} /Users/yusuf/.local/share/claude/versions/2.1.246"
            f" --agent-id {name}@{team} --agent-name {name}"
            f" --team-name {team} --agent-color purple"
            f" --parent-session-id {parent} --agent-type general-purpose"
            f" --model opus")


def spawn_payload(requested, assigned=None, session="chair", team=TEAM):
    """A PostToolUse payload, carrying the spawn result verbatim.

    The real one, captured from a chair's own transcript on 2026-08-27:

        Spawned successfully. (This tool result is internal metadata ...)
        agent_id: watchdog-repair@session-04c60c56
        name: watchdog-repair
        The agent is now running and will receive instructions via mailbox.
    """
    assigned = assigned or requested
    return {
        "session_id": session, "tool_name": "Agent",
        "tool_input": {"name": requested, "prompt": "read the brief"},
        "tool_response": [{"type": "text", "text":
                           "Spawned successfully.\nagent_id: "
                           f"{assigned}@{team}\nname: {assigned}\n"
                           "The agent is now running."}],
    }


def sidecar(sandbox, session="chair"):
    path = sandbox / "tmp" / f"fable-orch-agents-{session}.json"
    return json.loads(path.read_text(encoding="utf-8"))["agents"] if path.exists() else {}


def remember(sandbox, requested, assigned=None, age_s=300.0, session="chair",
             team=TEAM):
    """Record a spawn through the real hook, then age it."""
    run(sandbox, "--record",
        payload=spawn_payload(requested, assigned, session, team))
    path = sandbox / "tmp" / f"fable-orch-agents-{session}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for rec in data["agents"].values():
        rec["spawn"] = time.time() - age_s
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def transcript(sandbox, name, quiet_s=10.0, last_tool="Grep", team=TEAM,
               session_id="11111111-2222-3333-4444-555555555555",
               state="working"):
    """A teammate's own session log, aged so `quiet_s` seconds have passed.

    Shaped like the real thing: every record carries `agentName` AND
    `teamName`, which together are what make attribution exact.

    `state` decides how the log ENDS, which is what separates an agent
    that is wedged from one that delivered. Both shapes were read off
    live panes on 2026-08-27:

        working    an assistant tool_use, its result still to come
        reported   an assistant text reply — the turn ended
        dismissed  a shutdown_request the chair has already delivered
    """
    path = sandbox / "cfg" / "projects" / "proj" / f"{session_id}.jsonl"
    records = [{
        "type": "assistant", "agentName": name, "teamName": team,
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": last_tool, "input": {}}]},
    }]
    if state in ("reported", "dismissed"):
        records.append({
            "type": "assistant", "agentName": name, "teamName": team,
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Done — the report is above."}]},
        })
    if state == "dismissed":
        records.append({
            "type": "user", "agentName": name, "teamName": team,
            "message": {"role": "user", "content":
                        '<teammate-message teammate_id="team-lead">'
                        '{"type":"shutdown_request","requestId":"shut-1"}'},
        })
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    stamp = time.time() - quiet_s
    os.utime(path, (stamp, stamp))
    return path


def noise_logs(sandbox, count, quiet_s=1.0):
    """Other people's session logs, freshly written.

    The transcript hunt keeps the most recently modified candidates, so a
    busy machine is what pushes a QUIET agent's log off the end of the
    list — the one agent the module is looking for.
    """
    for i in range(count):
        path = (sandbox / "cfg" / "projects" / "proj"
                / f"noise-{i:04d}-0000-0000-0000-000000000000.jsonl")
        path.write_text(json.dumps({
            "type": "assistant", "agentName": f"noise{i}",
            "teamName": "session-noise",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Read", "input": {}}]},
        }) + "\n", encoding="utf-8")
        stamp = time.time() - quiet_s
        os.utime(path, (stamp, stamp))


def watchdog_module():
    """The script itself, imported by path, for the tests that count I/O."""
    spec = importlib.util.spec_from_file_location(
        "_fixture_watchdog", WATCHDOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- recording -------------------------------------------------------------

def test_record_keys_on_the_name_the_harness_assigned(sandbox):
    """The chair asks for `angleA`; a collision makes it `angleA-2`.

    Keyed on the REQUESTED name, every later lookup misses: the live
    process is `angleA-2`, so a healthy agent reads GONE and the prune
    deletes it. The assigned name is already in the tool result.
    """
    run(sandbox, "--record", payload=spawn_payload("angleA", "angleA-2"))
    saved = sidecar(sandbox)
    assert set(saved) == {"angleA-2"}
    assert saved["angleA-2"]["requested"] == "angleA"
    assert saved["angleA-2"]["team"] == TEAM


def test_a_renamed_agent_is_found_alive(sandbox):
    remember(sandbox, "angleA", "angleA-2", age_s=900)
    transcript(sandbox, "angleA-2", quiet_s=5)
    out, _ = run(sandbox, "--check", ps=ps_line("angleA-2"))
    assert "angleA-2 (asked for angleA): WORKING" in out


def test_record_ignores_unnamed_spawns(sandbox):
    # An unnamed subagent returns THROUGH the tool call — the chair is
    # inside that call while it runs and cannot be stranded by it.
    run(sandbox, "--record", payload={
        "session_id": "chair", "tool_name": "Agent",
        "tool_input": {"prompt": "quick grep"}})
    assert sidecar(sandbox) == {}


def test_record_survives_an_unparseable_response(sandbox):
    run(sandbox, "--record", payload={
        "session_id": "chair", "tool_name": "Task",
        "tool_input": {"name": "worker"}, "tool_response": {"weird": True}})
    saved = sidecar(sandbox)
    assert saved["worker"]["agent_id"] is None
    assert saved["worker"]["assigned"] == "worker"


def test_an_opaque_agent_id_is_not_mistaken_for_a_name(sandbox):
    """One spawn surface answers `agentId: <hex>` and names the agent below.

    The id is not a name: keyed on it, the record can never be joined to
    a process or to a session log, and the agent reads unborn forever.
    The old pattern also read only the snake_case spelling, so this whole
    result parsed as nothing and the rename was lost with it.
    """
    run(sandbox, "--record", payload={
        "session_id": "chair", "tool_name": "Agent",
        "tool_input": {"name": "worker"},
        "tool_response": "Spawned successfully.\n"
                         "agentId: a8f8974b8ad5803a9\nname: worker-2\n"})
    saved = sidecar(sandbox)
    assert set(saved) == {"worker-2"}
    assert saved["worker-2"]["agent_id"] == "a8f8974b8ad5803a9"
    assert saved["worker-2"]["requested"] == "worker"


def test_a_full_stop_never_lands_inside_the_team_name(sandbox):
    # `\\S+` swallowed the sentence's punctuation, and a team recorded as
    # `session-7070d3e7.` matches no session log at all.
    run(sandbox, "--record", payload={
        "session_id": "chair", "tool_name": "Agent",
        "tool_input": {"name": "verifier"},
        "tool_response": f"Spawned successfully. agent_id: verifier@{TEAM}. "
                         "The agent is now running."})
    assert sidecar(sandbox)["verifier"]["team"] == TEAM


def test_concurrent_records_keep_every_agent(sandbox):
    """A wave spawns in ONE message, so its hooks run at the same moment.

    Without a lock this lost agents in 3 of 8 measured trials: each hook
    read the file, added its key, and wrote the whole dict back over a
    sibling's write.
    """
    names = [f"angle{c}" for c in "ABCDEFGH"]
    procs = [subprocess.Popen(
        [sys.executable, str(WATCHDOG), "--record"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, text=True, env=env_for(sandbox))
        for _ in names]
    for proc, name in zip(procs, names):
        proc.stdin.write(json.dumps(spawn_payload(name)))
        proc.stdin.close()
    for proc in procs:
        assert proc.wait(timeout=60) == 0
    assert set(sidecar(sandbox)) == set(names)


def test_a_record_survives_a_filesystem_without_flock(sandbox):
    """`flock` is not universal: NFS and several mounts answer EOPNOTSUPP.

    That OSError escaped into the outer `except Exception: pass`, so on
    such a mount nothing was ever recorded and every mode answered "no
    spawned agents on record" — the watchdog silently absent exactly
    where a $TMPDIR is unusual.
    """
    shim = sandbox / "shim"
    shim.mkdir()
    (shim / "fcntl.py").write_text(FAKE_FCNTL, encoding="utf-8")
    run(sandbox, "--record", payload=spawn_payload("verifier"),
        env_extra={"PYTHONPATH": str(shim)})
    assert set(sidecar(sandbox)) == {"verifier"}


def test_a_half_written_sidecar_is_still_read(sandbox):
    """A writer killed at the 10s hook deadline leaves the older tail behind.

    `json.loads` calls the whole file garbage and the modes report
    "nothing on record — no spawn was seen": the false all-clear, from a
    record that is sitting right there.
    """
    path = remember(sandbox, "verifier", age_s=2400)
    path.write_text(path.read_text(encoding="utf-8") + '} "stale tail"',
                    encoding="utf-8")
    out, _ = run(sandbox, "--check", ps=ps_line("verifier"))
    assert "verifier: UNBORN" in out


def test_a_reader_never_sees_an_empty_sidecar(sandbox):
    """The old order truncated the file, then serialized into the handle.

    Measured: a reader polling during 300 updates observed the sidecar at
    zero bytes, which decodes to an empty record and renders as a
    finished wave.
    """
    path = sandbox / "tmp" / "fable-orch-agents-chair.json"
    remember(sandbox, "angleA", age_s=10)
    sizes = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            try:
                sizes.append(os.path.getsize(path))
            except OSError:
                pass

    watcher = threading.Thread(target=poll, daemon=True)
    watcher.start()
    try:
        for i in range(25):
            run(sandbox, "--record", payload=spawn_payload(f"angle{i}"))
    finally:
        stop.set()
        watcher.join(timeout=5)
    assert sizes, "the reader never sampled the sidecar"
    assert 0 not in sizes


# --- verdicts --------------------------------------------------------------

def test_alive_process_with_no_session_log_is_unborn(sandbox):
    # THE incident: `ps` shows the pane, and nothing else ever appears.
    remember(sandbox, "verifier", age_s=300)
    out, _ = run(sandbox, "--check", ps=ps_line("verifier"))
    assert "verifier: UNBORN" in out
    assert "never ran a turn" in out


def test_a_fresh_spawn_is_starting_not_unborn(sandbox):
    remember(sandbox, "verifier", age_s=5)
    out, _ = run(sandbox, "--check", ps=ps_line("verifier"))
    assert "verifier: STARTING" in out


def test_a_writing_agent_is_working(sandbox):
    remember(sandbox, "worker", age_s=300)
    transcript(sandbox, "worker", quiet_s=10, last_tool="Bash")
    out, _ = run(sandbox, "--check", ps=ps_line("worker"))
    assert "worker: WORKING" in out
    assert "last tool Bash" in out


def test_a_quiet_log_past_the_threshold_is_stalled(sandbox):
    remember(sandbox, "worker", age_s=1800)
    transcript(sandbox, "worker", quiet_s=1200)
    out, _ = run(sandbox, "--check", ps=ps_line("worker"))
    assert "worker: STALLED" in out


def test_a_finished_agent_is_gone(sandbox):
    # Its last turn ended, it wrote nothing for twenty minutes, and a
    # process scan that SUCCEEDED does not list it. That is over.
    remember(sandbox, "worker", age_s=1800)
    transcript(sandbox, "worker", quiet_s=1200, state="reported")
    out, _ = run(sandbox, "--check", ps="")
    assert "worker: GONE" in out


def test_a_dismissed_agent_is_gone_at_once(sandbox):
    # The chair already sent the shutdown_request: no window to wait out.
    remember(sandbox, "worker", age_s=900)
    transcript(sandbox, "worker", quiet_s=5, state="dismissed")
    out, _ = run(sandbox, "--check", ps=ps_line("worker"))
    assert "worker: GONE" in out


def test_a_message_that_mentions_a_shutdown_is_not_a_dismissal(sandbox):
    """This module's own surface line says "dismiss with a shutdown_request".

    Matching the bare word marks any agent handed that advice as
    dismissed — and a dismissed agent is `gone`, which prunes it from the
    record that is the only memory the feature has. Only the protocol
    marker counts. Checked against two real logs on 2026-08-27, one
    dismissed and one working: the marker separates them, the word does
    not, and both logs contain the word.
    """
    remember(sandbox, "worker", age_s=900)
    path = transcript(sandbox, "worker", quiet_s=5)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "user", "agentName": "worker", "teamName": TEAM,
            "message": {"role": "user", "content":
                        "AGENT WATCHDOG: verifier unborn for 2400s. Ping "
                        "with SendMessage; if there is no reply, dismiss "
                        "with a shutdown_request and re-spawn."},
        }) + "\n")
    stamp = time.time() - 5
    os.utime(path, (stamp, stamp))
    out, _ = run(sandbox, "--check", ps=ps_line("worker"))
    assert "worker: WORKING" in out
    assert "GONE" not in out


def test_a_delivered_teammate_is_idle_not_stalled(sandbox):
    """The wave reports at minute 8; the chair synthesizes until minute 20.

    The reaper leaves a delivered teammate's pane up for an hour, so
    every one of them sat there with a static log well past the 600s
    stall window. Reported as STALLED, the whole finished wave read as
    wedged, and the advice attached to that word is "dismiss and
    re-spawn".
    """
    remember(sandbox, "worker", age_s=1800)
    transcript(sandbox, "worker", quiet_s=1200, state="reported")
    out, _ = run(sandbox, "--check", ps=ps_line("worker"))
    assert "worker: IDLE" in out
    assert "STALLED" not in out


def test_a_sibling_log_is_never_borrowed(sandbox):
    """A wave shares one team id — attribution must name the AGENT.

    An early cut matched `"teamName"`, so a wedged agent inherited a busy
    sibling's log and reported WORKING: the one verdict this module exists
    to prevent, produced by the module itself.
    """
    remember(sandbox, "angleE", age_s=900)
    remember(sandbox, "verifier", age_s=900)
    transcript(sandbox, "angleE", quiet_s=10)
    out, _ = run(sandbox, "--check",
                 ps=ps_line("angleE") + "\n" + ps_line("verifier"))
    assert "verifier: UNBORN" in out
    assert "angleE: WORKING" in out


def test_the_chairs_own_log_is_never_borrowed(sandbox):
    """The chair's log quotes the spawn result verbatim.

    `agent_id: verifier@session-...` appears in the CHAIR's transcript,
    never in the agent's own. Matching on it attributed the chair's own
    freshly-written log to a wedged agent and reported it WORKING.
    """
    remember(sandbox, "verifier", age_s=2400)
    chair_log = sandbox / "cfg" / "projects" / "proj" / f"{PARENT}.jsonl"
    chair_log.write_text(json.dumps({
        "type": "user", "message": {"content": [
            {"type": "tool_result",
             "content": f"Spawned successfully.\nagent_id: verifier@{TEAM}"}]},
    }) + "\n", encoding="utf-8")
    out, _ = run(sandbox, "--check", ps=ps_line("verifier"))
    assert "verifier: UNBORN" in out


def test_a_log_from_another_team_is_never_borrowed(sandbox):
    """With the team unknown, a name match alone decided attribution.

    `team` is None whenever the spawn result could not be parsed — the
    path `test_record_survives_an_unparseable_response` pins — and every
    wave in the playbook uses the same handful of names. A wedged
    `worker` then inherited another team's `worker` and reported WORKING.
    """
    run(sandbox, "--record", payload={
        "session_id": "chair", "tool_name": "Agent",
        "tool_input": {"name": "worker"}, "tool_response": {"weird": True}})
    path = sandbox / "tmp" / "fable-orch-agents-chair.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["agents"]["worker"]["spawn"] = time.time() - 2400
    path.write_text(json.dumps(data), encoding="utf-8")
    transcript(sandbox, "worker", quiet_s=5, team="session-somebody-else")
    out, _ = run(sandbox, "--check", ps="")
    assert "worker: UNBORN" in out


def test_a_pane_from_another_team_is_never_borrowed(sandbox):
    """`procs.get(assigned) or procs.get(requested)` joined on the name.

    The fallback could only fire after a rename — which is exactly when
    the requested name belongs to somebody else. Measured: a record for
    `verifier-2` in one team reported the pid and cpu time of a live
    `verifier` in another as its own.
    """
    remember(sandbox, "verifier", "verifier-2", age_s=900, team="session-b")
    _, parsed = run(sandbox, "--check", "--json",
                    ps=ps_line("verifier", team="session-a"))
    assert parsed[0]["name"] == "verifier-2"
    assert parsed[0]["pid"] is None
    assert parsed[0]["cpu_s"] is None


def test_a_failed_process_scan_prunes_nothing(sandbox):
    """`ps` failing is not evidence that every agent died.

    Measured: one transient failure reported all three agents GONE and
    rewrote the sidecar to `{}` in the same call, after which --check said
    "no spawned agents on record" for the rest of the session while the
    agents were still working.
    """
    path = remember(sandbox, "worker", age_s=900)
    out, _ = run(sandbox, "--check", ps_fail=True)
    assert "worker: UNBORN" in out
    assert "worker" in json.loads(path.read_text(encoding="utf-8"))["agents"]


def test_check_json_is_machine_readable(sandbox):
    remember(sandbox, "verifier", age_s=300)
    _, parsed = run(sandbox, "--check", "--json", ps=ps_line("verifier"))
    assert [r["name"] for r in parsed] == ["verifier"]
    assert parsed[0]["state"] == "unborn"
    assert parsed[0]["age_s"] >= 300


def test_nothing_on_record_says_so(sandbox):
    out, _ = run(sandbox, "--check")
    assert "no spawned agents" in out


def test_finished_agents_leave_the_record(sandbox):
    path = remember(sandbox, "worker", age_s=1800)
    transcript(sandbox, "worker", quiet_s=1200, state="reported")
    run(sandbox, "--check", "--session", "chair", ps="")
    assert json.loads(path.read_text(encoding="utf-8"))["agents"] == {}


def test_live_agents_stay_on_the_record(sandbox):
    path = remember(sandbox, "verifier", age_s=1800)
    run(sandbox, "--check", "--session", "chair", ps=ps_line("verifier"))
    assert "verifier" in json.loads(path.read_text(encoding="utf-8"))["agents"]


# --- the process table is corroboration, never the verdict -----------------

def test_a_missing_process_never_overrides_a_fresh_log(sandbox):
    """The finding that made the whole feature dead code.

    Reproduced by the reviewer: a record 300s old, a matching session log
    written 0s ago, and a `ps` that succeeds and lists nothing ->
    `angleD: GONE — process exited`, with the sidecar rewritten to
    `{"agents": {}}` in the same call. The line printed its own
    contradiction, and the record — the only memory this feature has —
    was gone with it.
    """
    path = remember(sandbox, "angleD", age_s=300)
    transcript(sandbox, "angleD", quiet_s=0)
    out, _ = run(sandbox, "--check", "--session", "chair", ps="")
    assert "angleD: WORKING" in out
    assert "angleD" in json.loads(path.read_text(encoding="utf-8"))["agents"]


def test_an_unborn_agent_alarms_when_ps_lists_nothing(sandbox):
    """A live agent is not owed a row in the process table.

    Both alarms used to require a listed process, so whenever `ps` came
    back without the agent — no pane of its own, a failed scan, a scan
    that timed out — no alarm could fire at all. A spawn that has
    produced nothing past the birth window is the finding, listed or not.
    """
    remember(sandbox, "verifier", age_s=300)
    out, _ = run(sandbox, "--check", ps="")
    assert "verifier: UNBORN" in out


def test_a_stalled_agent_alarms_when_ps_lists_nothing(sandbox):
    remember(sandbox, "worker", age_s=1800)
    transcript(sandbox, "worker", quiet_s=1200)
    out, _ = run(sandbox, "--check", ps="")
    assert "worker: STALLED" in out


def test_a_quiet_log_is_not_dropped_by_a_busy_machine(sandbox):
    """The scan kept the most recently modified candidates and cut the rest.

    That drops the QUIETEST logs first — the agents this module hunts.
    Measured on the review machine: 430 session logs, 20 touched in the
    last hour, against a cap of 40. Here a stalled agent sits behind 60
    busier logs and still has to be found.
    """
    remember(sandbox, "worker", age_s=1800)
    transcript(sandbox, "worker", quiet_s=1200)
    noise_logs(sandbox, 60)
    out, _ = run(sandbox, "--check", ps="")
    assert "worker: STALLED" in out


def test_the_transcript_hunt_reads_each_log_once(sandbox, monkeypatch):
    """Every agent used to run the whole hunt for itself.

    A glob of ~/.claude/projects plus up to forty 64KB reads per agent,
    then the matched file re-opened and re-read for its last tool: a
    ten-agent wave paid ~400 opens and ~25MB on every user prompt, inside
    a 10-second hook budget. One index, built once, is what that costs
    now.
    """
    module = watchdog_module()
    for i in range(12):
        transcript(sandbox, f"agent{i}", quiet_s=30,
                   session_id=f"2222{i:04d}-2222-3333-4444-555555555555")
    agents = {
        f"key{i}": {"assigned": f"agent{i}", "requested": f"agent{i}",
                    "team": TEAM, "spawn": time.time() - 300,
                    "key": f"agent{i}",
                    "source": str(sandbox / "tmp" / "s.json")}
        for i in range(6)
    }
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(sandbox / "cfg"))
    monkeypatch.setattr(module, "live_processes",
                        lambda deadline=None: ({}, True))
    opened = []
    real_open = builtins.open

    def counting_open(path, *args, **kwargs):
        if str(path).endswith(".jsonl"):
            opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    rows, _ = module.assess(agents)
    monkeypatch.setattr(builtins, "open", real_open)
    assert {r["state"] for r in rows} == {"working"}
    # 12 logs indexed once, plus one tail read per matched agent.
    assert len(opened) <= 12 + len(agents), f"{len(opened)} opens"


# --- the watcher itself ----------------------------------------------------

def test_a_watcher_does_not_alarm_on_itself_while_watching(sandbox):
    remember(sandbox, "watchdog", age_s=900)
    out, _ = run(sandbox, "--check", ps=ps_line("watchdog"))
    assert "watchdog: WATCHER-UNBORN" in out


def test_a_wedged_watcher_still_reaches_the_chair(sandbox):
    """The one agent whose failure silences the feature.

    The watchdog is spawned in the same wave and is exactly as likely to
    wedge. It must not alarm on itself — it would message the chair about
    its own health forever — but the chair-side hook has to see it, or the
    chair believes it is covered and waits: the original 39-minute failure,
    one level up.
    """
    remember(sandbox, "watchdog", age_s=2400)
    out, parsed = run(sandbox, "--surface", payload={"session_id": "chair"},
                      ps=ps_line("watchdog"))
    assert "watchdog watcher-unborn" in parsed[
        "hookSpecificOutput"]["additionalContext"]


def test_an_empty_watch_self_falls_back_to_the_default(sandbox):
    remember(sandbox, "watchdog", age_s=900)
    out, _ = run(sandbox, "--check", ps=ps_line("watchdog"),
                 env_extra={"FABLE_ORCH_WATCH_SELF": ""})
    assert "WATCHER-UNBORN" in out


# --- surfacing -------------------------------------------------------------

def test_surface_is_silent_while_the_wave_is_healthy(sandbox):
    remember(sandbox, "worker", age_s=300)
    transcript(sandbox, "worker", quiet_s=10)
    out, _ = run(sandbox, "--surface", payload={"session_id": "chair"},
                 ps=ps_line("worker"))
    assert out == ""


def test_surface_reports_an_open_alarm(sandbox):
    remember(sandbox, "verifier", age_s=2400)
    out, parsed = run(sandbox, "--surface", payload={"session_id": "chair"},
                      ps=ps_line("verifier"))
    context = parsed["hookSpecificOutput"]["additionalContext"]
    assert parsed["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "verifier unborn" in context
    assert "SendMessage" in context
    assert "agent_watchdog.py" in context and context.count("/") > 2  # absolute


def test_an_alarm_is_raised_once_not_on_every_prompt(sandbox):
    """Nothing remembered a reported alarm.

    Reproduced: three consecutive --surface runs injected the identical
    'AGENT WATCHDOG: verifier unborn for 2400s' context. On the watchdog
    side the same gap made `--watch` return in ~50ms and message the
    chair again, for as long as the agent stayed wedged. The table on
    demand still shows it — only the interruption is spent once.
    """
    remember(sandbox, "verifier", age_s=2400)
    first, _ = run(sandbox, "--surface", payload={"session_id": "chair"},
                   ps=ps_line("verifier"))
    second, _ = run(sandbox, "--surface", payload={"session_id": "chair"},
                    ps=ps_line("verifier"))
    assert "verifier unborn" in first
    assert second == ""
    table, _ = run(sandbox, "--check", ps=ps_line("verifier"))
    assert "verifier: UNBORN" in table


# --- watching --------------------------------------------------------------

def test_watch_returns_immediately_on_an_alarm(sandbox):
    remember(sandbox, "verifier", age_s=2400)
    started = time.monotonic()
    out, _ = run(sandbox, "--watch", "--timeout", "30", "--interval", "5",
                 ps=ps_line("verifier"))
    assert "[watchdog] alarm" in out
    assert "verifier: UNBORN" in out
    assert time.monotonic() - started < 20


def test_watch_does_not_repeat_an_alarm_it_already_raised(sandbox):
    # The watchdog teammate is told to call again as soon as this
    # returns. Without a memory the second call returns at once with the
    # same row, and the chair is messaged about it forever.
    remember(sandbox, "verifier", age_s=2400)
    first, _ = run(sandbox, "--watch", "--timeout", "30", "--interval", "5",
                   ps=ps_line("verifier"))
    second, _ = run(sandbox, "--watch", "--timeout", "8", "--interval", "5",
                    ps=ps_line("verifier"))
    assert "[watchdog] alarm" in first
    assert "[watchdog] no change" in second


def test_watch_stays_quiet_through_a_healthy_start(sandbox):
    """`starting -> working` is not news.

    Returning on ANY state change made the watchdog a one-shot: it exited
    on the first healthy transition, roughly two minutes into every wave,
    and the unborn/stalled detection it exists for never ran.

    The transition has to happen DURING the run or there is nothing to
    stay quiet about. This test used to write the session log BEFORE the
    run, so poll 1 already read `working`, `changed` was never True, and
    dropping the `args.verbose` gate from `mode_watch` left it green —
    a check that could not fail. Now poll 1 finds no log at all, which
    is `starting`, and the log lands between poll 1 and poll 2.
    """
    remember(sandbox, "worker", age_s=5)
    log = (sandbox / "cfg" / "projects" / "proj"
           / "11111111-2222-3333-4444-555555555555.jsonl")
    assert not log.exists(), "poll 1 has to find no session log"
    # 2s in: after poll 1 (immediate), well before poll 2 (t+5s).
    writer = threading.Timer(2.0, transcript, args=(sandbox, "worker"),
                             kwargs={"quiet_s": 0})
    writer.start()
    try:
        out, _ = run(sandbox, "--watch", "--timeout", "12", "--interval", "5",
                     ps=ps_line("worker"))
    finally:
        writer.cancel()
    # The transition really happened — the log the last poll reads was
    # not there when the first one looked.
    assert log.exists()
    assert "worker: WORKING" in out, out
    # ... and the default said nothing about it.
    assert "state changed" not in out, out
    assert "[watchdog] no change" in out, out


def test_verbose_watch_reports_a_state_change(sandbox):
    """`--verbose` returns on a harmless transition; the default does not.

    The old version of this test could not fail: it ran its deadline out
    and asserted only that the output contained `[watchdog]`, which the
    "no change" line satisfies. The transition here is real — a delivered
    agent crossing the stall window from `working` into `idle` — and the
    assertion is the word the flag exists to produce. No hook, core,
    command or skill passes `--verbose`; it is a debugging flag, and this
    is the only place it is exercised.
    """
    remember(sandbox, "worker", age_s=300)
    transcript(sandbox, "worker", quiet_s=3, state="reported")
    out, _ = run(sandbox, "--watch", "--verbose", "--timeout", "20",
                 "--interval", "5", ps=ps_line("worker"),
                 env_extra={"FABLE_ORCH_WATCH_STALL_S": "8"})
    assert "[watchdog] state changed" in out
    assert "worker: IDLE" in out


def test_watch_returns_when_the_wave_is_over(sandbox):
    remember(sandbox, "worker", age_s=300)
    transcript(sandbox, "worker", quiet_s=3, state="reported")
    # first poll sees it live, a later one does not: that is a finished wave
    out, _ = run(sandbox, "--watch", "--timeout", "30", "--interval", "5",
                 ps=ps_line("worker"),
                 env_extra={"FAKE_PS_ONESHOT": "1",
                            "FABLE_ORCH_WATCH_STALL_S": "1"})
    assert "all agents finished" in out


def test_the_watchdogs_own_row_does_not_hide_a_finished_wave(sandbox):
    """The watchdog is itself a recorded named spawn.

    Its own row is never `gone` while it is running, so counting it made
    the "all agents finished" exit unreachable in the real deployment:
    every call burned its full 100s printing "no change" over a wave that
    was over. The test that passed did so only because its fixture never
    recorded a watchdog.
    """
    remember(sandbox, "watchdog", age_s=900)
    remember(sandbox, "worker", age_s=300)
    transcript(sandbox, "worker", quiet_s=3, state="reported")
    out, _ = run(sandbox, "--watch", "--timeout", "30", "--interval", "5",
                 ps=ps_line("worker") + "\n" + ps_line("watchdog"),
                 env_extra={"FAKE_PS_ONESHOT": "1",
                            "FABLE_ORCH_WATCH_STALL_S": "1"})
    assert "all agents finished" in out


def test_an_empty_record_is_never_reported_as_finished(sandbox):
    """Nothing on record and a finished wave look identical from here.

    Given a lost record — a rename, a pruned entry, a missing hook — the
    empty case is the COMMON one, and announcing "all agents finished"
    there is a false all-clear: worse than no watchdog.
    """
    out, _ = run(sandbox, "--watch", "--timeout", "8", "--interval", "5")
    assert "nothing on record" in out
    assert "all agents finished" not in out


def test_watch_merges_every_sidecar_when_it_has_no_session_id(sandbox):
    # The watchdog teammate does not know the chair's session id, so with
    # no --session it has to read every sidecar or watch nothing at all.
    remember(sandbox, "verifier", age_s=2400, session="chair-one")
    remember(sandbox, "other", age_s=2400, session="chair-two")
    out, _ = run(sandbox, "--watch", "--timeout", "20", "--interval", "5",
                 ps=ps_line("verifier"))
    assert "verifier: UNBORN" in out


def test_two_chairs_may_each_have_an_agent_of_the_same_name(sandbox):
    """Merging every sidecar on the bare name loses one of them.

    The colliding names are the ones the playbook mandates every wave —
    watchdog, verifier, angleA. Collapsing them by newest spawn dropped
    one chair's row entirely, and surfaced the survivor's verdict in the
    other chair's session, where the advice is to dismiss it.
    """
    remember(sandbox, "verifier", age_s=900, session="chair-one",
             team="session-aaaaaaaa")
    remember(sandbox, "verifier", age_s=900, session="chair-two",
             team="session-bbbbbbbb")
    transcript(sandbox, "verifier", quiet_s=5, team="session-aaaaaaaa")
    out, _ = run(sandbox, "--check", ps="")
    assert "verifier: WORKING" in out
    assert "verifier: UNBORN" in out


def test_watch_never_waits_on_stdin(sandbox):
    """The teammate loops `--watch` from a Bash call: stdin is an open pipe.

    `main()` read it whenever stdin was not a tty, before anything else.
    Reproduced: `--watch --timeout 6` was still running when it was
    killed at 25 seconds, and `FABLE_ORCH_WATCHDOG=0` did not save it
    either, because the read came first.
    """
    proc = subprocess.Popen(
        [sys.executable, str(WATCHDOG), "--watch", "--timeout", "6",
         "--interval", "5"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env_for(sandbox))
    try:
        proc.wait(timeout=45)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("--watch blocked on an open stdin pipe")
    assert proc.returncode == 0
    assert "nothing on record" in proc.stdout.read()


# --- discipline ------------------------------------------------------------

def test_thresholds_are_configurable(sandbox):
    remember(sandbox, "verifier", age_s=60)
    out, _ = run(sandbox, "--check", ps=ps_line("verifier"),
                 env_extra={"FABLE_ORCH_WATCH_BIRTH_S": "30"})
    assert "verifier: UNBORN" in out


def test_a_zero_interval_cannot_spin(sandbox):
    """`args.interval or env` treated 0 as unset, and `sleep(0)` never yields.

    Measured: `FABLE_ORCH_WATCH_INTERVAL=0` burned a full 3s deadline
    forking `ps` back to back, from a process whose entire premise is that
    it costs the chair nothing.

    Wall-clock proves NOTHING here, and the version of this test that
    asserted `elapsed >= 4` could not fail: an unfloored interval does
    not return early, it busy-loops to the very same deadline, so the
    elapsed time is identical for the bug and the fix and setting
    INTERVAL_FLOOR_S to 0.0 left the test green. What actually separates
    them is how many times the loop goes round, and every poll forks
    `ps` exactly once.
    """
    remember(sandbox, "worker", age_s=5)
    transcript(sandbox, "worker", quiet_s=1)
    tally = sandbox / "tmp" / "ps-forks"
    run(sandbox, "--watch", "--timeout", "12", ps=ps_line("worker"),
        env_extra={"FABLE_ORCH_WATCH_INTERVAL": "0",
                   "FAKE_PS_COUNT_FILE": str(tally)})
    polls = len(tally.read_text(encoding="utf-8"))
    # A 12s deadline floored to 5s polls at t=0, 5 and 10: three forks,
    # with room for startup drift. Unfloored, the same deadline costs
    # hundreds of them.
    assert 2 <= polls <= 6, f"{polls} `ps` forks inside a 12s watch"


def test_the_watch_default_fits_inside_a_bash_call(sandbox):
    # The Bash tool defaults to 120s. A watchdog whose default deadline is
    # longer gets killed with no output at all, and reports a timeout
    # instead of a wave status.
    source = WATCHDOG.read_text(encoding="utf-8")
    assert "WATCH_TIMEOUT_S = 100.0" in source


def test_the_kill_switch_silences_every_mode(sandbox):
    remember(sandbox, "verifier", age_s=2400)
    off = {"FABLE_ORCH_WATCHDOG": "0"}
    for args in (("--check",), ("--surface",)):
        out, _ = run(sandbox, *args, payload={"session_id": "chair"},
                     ps=ps_line("verifier"), env_extra=off)
        assert out == ""
    run(sandbox, "--record", payload=spawn_payload("x", session="off"),
        env_extra=off)
    assert not (sandbox / "tmp" / "fable-orch-agents-off.json").exists()


def test_a_disabled_watch_does_not_spin(sandbox):
    """The kill switch cannot reach the teammate's instructions.

    Measured: with the switch off, `--watch --timeout 30` returned empty
    in 0.05s, while the profile tells the watchdog teammate to call again
    as soon as it returns — an infinite Bash loop for the life of the
    session. It now says what happened and sits out its own deadline.
    """
    started = time.monotonic()
    out, _ = run(sandbox, "--watch", "--timeout", "3",
                 env_extra={"FABLE_ORCH_WATCHDOG": "0"})
    assert "disabled" in out
    assert "stop looping" in out
    assert time.monotonic() - started >= 3


def test_garbage_input_never_breaks_a_turn(sandbox):
    for raw in ("not json", "", "[]", '{"tool_input": "wrong type"}'):
        proc = subprocess.run(
            [sys.executable, str(WATCHDOG), "--record"],
            input=raw, capture_output=True, text=True, timeout=30,
            env=env_for(sandbox))
        assert proc.returncode == 0, proc.stderr


def test_it_never_kills_anything(sandbox):
    # The user's constraint, pinned: detection must not stop the work.
    source = WATCHDOG.read_text(encoding="utf-8")
    for forbidden in ("kill-pane", "os.kill", "SIGTERM", "SIGKILL",
                      '"kill"', "terminate("):
        assert forbidden not in source, f"watchdog must not {forbidden}"


def test_it_never_blocks_a_turn(sandbox):
    source = WATCHDOG.read_text(encoding="utf-8")
    assert '"block"' not in source
    assert "permissionDecision" not in source


def test_it_does_not_ask_the_roster_about_team_members(sandbox):
    """`claude agents --json` does not list team members.

    Measured with ten live members: it returned ten top-level sessions and
    not one of them. Forking it per poll bought a dict nothing could join.
    """
    source = WATCHDOG.read_text(encoding="utf-8")
    assert '"agents", "--json"' not in source


def test_no_verdict_globs_the_temp_dir_for_a_session_marker(sandbox):
    """The reason line's '; no SessionStart either' could never fire.

    The Stop hook utimes the injector's marker in its `finally` block at
    every turn end, and the chair's turn ends right after it spawns — so
    the marker was always fresh and the qualifier always suppressed. It
    cost a $TMPDIR glob per unborn verdict per poll: measured at 130ms
    against a temp dir holding 200,457 entries.
    """
    source = WATCHDOG.read_text(encoding="utf-8")
    assert "fable-orch-model-" not in source
