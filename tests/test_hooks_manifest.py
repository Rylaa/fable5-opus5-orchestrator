"""The registration contract: every other test drives the scripts
directly, so a broken hooks.json (dropped matcher entry, mistyped
script path) would ship green. This file pins the manifest itself."""
import json
import re

from conftest import REPO


def _manifest():
    with open(REPO / "hooks" / "hooks.json", encoding="utf-8") as f:
        return json.load(f)["hooks"]


def test_all_six_events_registered():
    assert set(_manifest()) == {"SessionStart", "PreToolUse", "PostToolUse",
                                "Stop", "SessionEnd", "UserPromptSubmit"}


def test_every_hook_command_script_exists():
    for entries in _manifest().values():
        for entry in entries:
            for hook in entry["hooks"]:
                cmd = hook["command"]
                assert cmd.startswith('python3 "${CLAUDE_PLUGIN_ROOT}/')
                # The path ends at the closing quote, not at the end of
                # the command: watchdog entries carry a mode flag after
                # it (`.../agent_watchdog.py" --record`).
                rel = cmd.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1].split('"', 1)[0]
                assert (REPO / rel).is_file(), f"missing script: {rel}"
                assert isinstance(hook.get("timeout"), int)


def test_pretooluse_matcher_covers_the_gated_tools():
    matcher = _manifest()["PreToolUse"][0]["matcher"]
    pattern = re.compile(matcher)
    for tool in ("Agent", "Task", "Workflow", "TaskCreate"):
        assert pattern.search(tool), f"matcher misses {tool}"
    for tool in ("TaskUpdate", "TaskList", "AgentOutput", "WorkflowX"):
        assert not pattern.search(tool), f"matcher over-matches {tool}"


def test_posttooluse_records_named_spawns():
    # The watchdog can only report on spawns it was told about, and the
    # only place that knowledge exists is the tool result. A dropped
    # matcher entry here is invisible everywhere else: --check simply
    # says "no spawned agents on record" and the chair waits blind.
    entry = _manifest()["PostToolUse"][0]
    pattern = re.compile(entry["matcher"])
    for tool in ("Agent", "Task"):
        assert pattern.search(tool), f"matcher misses {tool}"
    for tool in ("TaskUpdate", "AgentOutput"):
        assert not pattern.search(tool), f"matcher over-matches {tool}"
    assert "--record" in entry["hooks"][0]["command"]


def test_the_recorder_watches_a_subset_of_what_the_gate_stops():
    """The two matchers differ, and the difference is a decision.

    The gate stops a spawn before it happens and reads whatever the tool
    carries. The recorder has to REMEMBER an agent under a name it can
    join later to a process row and a session log, and two of the gated
    tools cannot give it one:

      * `TaskCreate` carries a subject and a description, never a `name`,
        so the recorder returned early on every one of them — a python3
        fork per tracker task, to do nothing at all.
      * `Workflow` names a SCRIPT. Its agents run inside the workflow
        runtime, the harness reports their completion itself, and they
        never appear under a name the watchdog could look up. Recorded
        here, the workflow's own name would sit in the sidecar as an
        agent that can never be found and alarm `unborn` for the rest of
        the session — a false alarm every prompt, in place of a gap.

    Pinned as a subset so a tool the gate learns to stop is a deliberate
    choice here too, and never a silently dropped matcher.
    """
    gate = re.compile(_manifest()["PreToolUse"][0]["matcher"])
    recorder = re.compile(_manifest()["PostToolUse"][0]["matcher"])
    spawn_tools = ("Agent", "Task", "Workflow", "TaskCreate")
    gated = {tool for tool in spawn_tools if gate.search(tool)}
    recorded = {tool for tool in spawn_tools if recorder.search(tool)}
    assert recorded < gated, "the recorder must not watch an ungated tool"
    assert gated - recorded == {"Workflow", "TaskCreate"}


def test_userpromptsubmit_surfaces_watchdog_alarms():
    commands = [h["command"] for e in _manifest()["UserPromptSubmit"]
                for h in e["hooks"]]
    assert any("--surface" in c for c in commands)
