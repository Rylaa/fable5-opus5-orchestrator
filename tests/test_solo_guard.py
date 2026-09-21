"""The solo guard: the gate that watches the chair, not the delegation.

Every earlier version gated the act of delegating, so a chair that
never delegated never met a gate. These tests pin the inversion.
"""
import json

from conftest import fake_ps_env, run_hook

SCRIPT = "solo_guard.py"


def edit(session="s1", tool="Edit", **kw):
    return {"tool_name": tool, "session_id": session, "tool_input": {}, **kw}


def spawn(session="s1", tool="Agent", subagent_type="general-purpose"):
    return {"tool_name": tool, "session_id": session,
            "tool_input": {"subagent_type": subagent_type, "prompt": "x"}}


def denies(result):
    if result is None:
        return False
    out = result["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    return out["permissionDecision"] == "deny"


def run(payload, tmp_path, **env):
    return run_hook(SCRIPT, payload, env_extra=env or None, tmpdir=tmp_path)


def test_first_edits_pass_then_the_third_is_denied(tmp_path):
    # Two free edits is the whole tolerance: a genuine single-sitting
    # fix fits, a hand-implemented plan does not.
    assert not denies(run(edit(), tmp_path))
    assert not denies(run(edit(), tmp_path))
    assert denies(run(edit(), tmp_path))


def test_the_deny_fires_once_per_session(tmp_path):
    # A nudge, not a wall. The chair that answers "this really is a
    # one-off" must be able to carry on without fighting the hook on
    # every subsequent edit.
    for _ in range(2):
        run(edit(), tmp_path)
    assert denies(run(edit(), tmp_path))
    for _ in range(4):
        assert not denies(run(edit(), tmp_path))


def test_a_spawned_worker_disarms_the_gate_for_good(tmp_path):
    # The gate asks one question: is this chair orchestrating? Once it
    # has spawned a worker the answer is yes, and its own small edits
    # are its business.
    assert run(spawn(), tmp_path) is None
    for _ in range(6):
        assert not denies(run(edit(), tmp_path))


def test_a_spawn_after_two_edits_still_disarms_it(tmp_path):
    # Order must not matter: reading around with two edits and THEN
    # delegating is exactly the behaviour the plugin wants.
    run(edit(), tmp_path)
    run(edit(), tmp_path)
    run(spawn(), tmp_path)
    assert not denies(run(edit(), tmp_path))


def test_a_fork_is_not_a_worker(tmp_path):
    # A fork clones the chair's own context at the chair's own model:
    # forking a plan's phases is disguised solo work, so it must not
    # buy an exemption from the gate.
    run(spawn(subagent_type="fork"), tmp_path)
    run(edit(), tmp_path)
    run(edit(), tmp_path)
    assert denies(run(edit(), tmp_path))


def test_every_edit_tool_counts(tmp_path):
    # Counting only `Edit` would leave `Write` as a free path around
    # the gate, which is the same hole the ledger gates had.
    assert not denies(run(edit(tool="Write"), tmp_path))
    assert not denies(run(edit(tool="MultiEdit"), tmp_path))
    assert denies(run(edit(tool="NotebookEdit"), tmp_path))


def test_unwatched_tools_are_ignored(tmp_path):
    # Reads are not work the chair should delegate; a guard that
    # counted them would deny a chair that had done nothing at all.
    for tool in ("Read", "Grep", "Glob", "Bash"):
        for _ in range(5):
            assert not denies(run(edit(tool=tool), tmp_path))


def test_sessions_are_counted_separately(tmp_path):
    for _ in range(3):
        run(edit(session="a"), tmp_path)
    assert not denies(run(edit(session="b"), tmp_path))


def test_teammates_are_never_denied(tmp_path):
    # A worker's whole job is to edit files. Denying its third edit
    # would break the delegation this plugin exists to encourage.
    env = fake_ps_env(tmp_path, "1 claude --agent-id w@s --agent-name w")
    for _ in range(6):
        assert not denies(run(edit(session="tm"), tmp_path, **env))


def test_chair_is_still_gated_when_the_ancestor_is_plain_claude(tmp_path):
    env = fake_ps_env(tmp_path, "1 claude")
    run(edit(session="ch"), tmp_path, **env)
    run(edit(session="ch"), tmp_path, **env)
    assert denies(run(edit(session="ch"), tmp_path, **env))


def test_threshold_is_configurable(tmp_path):
    env = {"FABLE_ORCH_SOLO_EDITS": "2"}
    assert not denies(run(edit(session="t2"), tmp_path, **env))
    assert denies(run(edit(session="t2"), tmp_path, **env))


def test_zero_or_negative_threshold_disables_the_gate(tmp_path):
    for value, session in (("0", "z"), ("-1", "n")):
        for _ in range(6):
            assert not denies(run(edit(session=session), tmp_path,
                                  FABLE_ORCH_SOLO_EDITS=value))


def test_unparseable_threshold_falls_back_to_the_default(tmp_path):
    env = {"FABLE_ORCH_SOLO_EDITS": "many"}
    run(edit(session="bad"), tmp_path, **env)
    run(edit(session="bad"), tmp_path, **env)
    assert denies(run(edit(session="bad"), tmp_path, **env))


def test_escape_hatch_disables_the_gate(tmp_path):
    env = {"FABLE_ORCH_SOLO_GUARD": "0"}
    for _ in range(6):
        assert not denies(run(edit(session="off"), tmp_path, **env))


def test_a_session_without_an_id_is_never_denied(tmp_path):
    # No id means no sidecar, so the count cannot be trusted; the gate
    # stays out of the way rather than denying on a guess.
    for _ in range(6):
        payload = {"tool_name": "Edit", "tool_input": {}}
        assert not denies(run_hook(SCRIPT, payload, tmpdir=tmp_path))


def test_malformed_sidecar_does_not_crash_the_gate(tmp_path):
    (tmp_path / "fable-orch-solo-junk.json").write_text(
        "not json at all", encoding="utf-8")
    run(edit(session="junk"), tmp_path)
    run(edit(session="junk"), tmp_path)
    assert denies(run(edit(session="junk"), tmp_path))


def test_wrong_typed_sidecar_coerces(tmp_path):
    (tmp_path / "fable-orch-solo-typed.json").write_text(
        json.dumps({"edits": "lots", "spawns": None}), encoding="utf-8")
    assert not denies(run(edit(session="typed"), tmp_path))


def test_garbage_stdin_is_survivable(tmp_path):
    assert run_hook(SCRIPT, raw="{not json", tmpdir=tmp_path) is None
    assert run_hook(SCRIPT, raw="[]", tmpdir=tmp_path) is None
    assert run_hook(SCRIPT, raw="", tmpdir=tmp_path) is None


def test_deny_reason_tells_the_chair_what_to_do(tmp_path):
    for _ in range(2):
        run(edit(session="msg"), tmp_path)
    reason = run(edit(session="msg"), tmp_path)[
        "hookSpecificOutput"]["permissionDecisionReason"]
    assert "ORCHESTRATOR" in reason
    assert "name the workers" in reason
    # It must also say how to proceed when the chair is right, or the
    # nudge reads as a wall and the chair argues with it instead.
    assert "fires once per session" in reason


def test_metrics_record_the_deny_and_the_suppression(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "FABLE_ORCH_METRICS": "1"}
    for _ in range(4):
        run(edit(session="met"), tmp_path, **env)
    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    events = [json.loads(l)["event"]
              for l in log.read_text(encoding="utf-8").strip().splitlines()]
    assert events == ["solo_deny", "solo_suppressed"]


def test_metrics_optout(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "FABLE_ORCH_METRICS": "0"}
    for _ in range(3):
        run(edit(session="nomet"), tmp_path, **env)
    assert not (home / ".claude" / "fable-orch" / "metrics.jsonl").exists()
