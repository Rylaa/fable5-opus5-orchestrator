"""Rule 0.5, second half: answers are not agreement.

The clarify gate asks "did you find out what the requirements ARE?".
This one asks the question after it: "does the user know what you made
of them?" Right answers to good questions still leave the wrong build
free to be approved silently, and no worker can check that with the
user — the `## Approved` section is where the chair states its reading
and stops until the user says go.
"""
from conftest import (
    APPROVED,
    CLARIFIED,
    LONG,
    SPAWN_GUARD as SCRIPT,
    VERY_LONG,
    is_deny,
    reason,
    run_hook,
    run_tasks,
    spawn_payload,
    task_payload,
    write_ledger,
)

ITEMS = "- [ ] 1. item\n"


def write_unapproved_ledger(repo, body=ITEMS):
    """A ledger that IS clarified and carries no approval record.

    The gates run in order, so a body with no `## Clarified` would draw
    the clarify deny and never reach the gate under test. The clarify
    record is prepended (unless the body brings its own); the approval
    record never is — its absence is the thing being tested.
    """
    return write_ledger(repo, body, ensure_approved=False)


# --- the gate itself ---

def test_approved_ledger_passes(repo_dir):
    write_ledger(repo_dir)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_unapproved_ledger_denied(repo_dir):
    write_unapproved_ledger(repo_dir)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "APPROVAL GUARD" in reason(result)
    # And it must not read as the gate before it: this chair has
    # already asked and been answered. "Go clarify" would loop it.
    assert "CLARIFY GUARD" not in reason(result)


def test_heading_alone_is_not_an_approval(repo_dir):
    write_unapproved_ledger(repo_dir, "## Approved\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


def test_empty_section_followed_by_heading_denied(repo_dir):
    write_unapproved_ledger(repo_dir, "## Approved\n\n## Items\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


def test_section_at_end_of_file_with_content_passes(repo_dir):
    write_unapproved_ledger(
        repo_dir, ITEMS + "\n## Approved\n- Yusuf: go, that scope\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_heading_level_and_case_are_free(repo_dir):
    # The rule is about the record existing, not markdown depth.
    for heading in ("# Approved", "## Approved", "### approved", "###### APPROVED"):
        write_unapproved_ledger(repo_dir, f"{heading}\n- Yusuf: go\n" + ITEMS)
        assert run_hook(
            SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None, heading


def test_lookalike_heading_does_not_satisfy(repo_dir):
    # "Approval pending" is not the record; the word has to be the
    # whole heading token, exactly like `## Clarified`.
    for heading in ("## Approval pending", "## Approvals", "## Unapproved",
                    "## Approvedness", "## Approved_later"):
        write_unapproved_ledger(repo_dir, f"{heading}\n- soon\n" + ITEMS)
        result = run_hook(SCRIPT, spawn_payload(repo_dir))
        assert is_deny(result) and "APPROVAL GUARD" in reason(result), heading


def test_sub_heading_stays_inside_the_section(repo_dir):
    # A re-approval after a plan change is naturally filed as a
    # sub-heading; ending the section at ANY heading would deny a
    # ledger that carries the go.
    write_unapproved_ledger(
        repo_dir,
        "## Approved\n### Round 2\n- Yusuf: go, with the rename dropped\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


# --- the bypasses the clarify scanner already learned, on the shared code ---

def test_any_checkbox_ends_the_section(repo_dir):
    # The approval is a PLAIN bullet. A checkbox line reads as a ledger
    # item, so an empty heading above the requirements must not pass as
    # if the items themselves were the user's go.
    for bullet in ("- [ ] 1. item", "* [x] 2. done", "+ [~] 3. deferred: ok",
                   "- [x] V. verified", "- [ ] ship it", "- [x] Yusuf: approved",
                   "-  [ ] 1. two spaces", "- [>] 1. odd marker"):
        write_unapproved_ledger(repo_dir, f"## Approved\n\n{bullet}\n")
        result = run_hook(SCRIPT, spawn_payload(repo_dir))
        assert is_deny(result), bullet
        assert "APPROVAL GUARD" in reason(result), bullet
        assert "plain bullets" in reason(result), bullet


def test_setext_heading_does_not_count_as_content(repo_dir):
    write_unapproved_ledger(repo_dir, "## Approved\n\nPlan\n----\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


def test_punctuation_alone_is_not_an_approval(repo_dir):
    # Typing the heading and a divider is the "approved nothing" case.
    for filler in ("---", "***", "___", "<!-- ask Yusuf tomorrow -->", "|  |"):
        write_unapproved_ledger(repo_dir, f"## Approved\n\n{filler}\n\n" + ITEMS)
        result = run_hook(SCRIPT, spawn_payload(repo_dir))
        assert is_deny(result) and "APPROVAL GUARD" in reason(result), filler


def test_fenced_example_is_not_an_approval(repo_dir):
    # The skill's own markdown example of the section must not satisfy
    # the gate it is teaching.
    write_unapproved_ledger(
        repo_dir,
        "## Notes\nCopy this shape:\n\n```markdown\n## Approved\n"
        "- <user>, <date>: approved\n```\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


def test_tilde_fence_is_stripped_like_a_backtick_one(repo_dir):
    write_unapproved_ledger(
        repo_dir,
        "## Notes\n~~~markdown\n## Approved\n- <user>: approved\n~~~\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


def test_fenced_example_beside_a_real_record_passes(repo_dir):
    write_unapproved_ledger(
        repo_dir,
        "## Approved\n- Yusuf: go, that scope\n\n"
        "```markdown\n## Approved\n- <user>, <date>: approved\n```\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_a_filled_section_below_an_empty_one_passes(repo_dir):
    # A plan change rewrites the section lower down; every heading is
    # checked, not just the first.
    write_unapproved_ledger(
        repo_dir,
        "## Approved\n\n" + ITEMS + "\n## Approved\n- Yusuf: go, v2 scope\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_spaceless_heading_ends_a_section_it_could_start(repo_dir):
    write_unapproved_ledger(repo_dir, "## Approved\n\n##Items\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)
    write_unapproved_ledger(repo_dir, "##Approved\n- Yusuf: go\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_a_fenced_clarified_example_still_earns_a_real_record(repo_dir):
    # The fixture decides "is this body already clarified?" and the
    # guard decides it again; when they disagree, a test written for
    # THIS gate is quietly answered by the one before it. The fixture
    # used to scan the raw body, so a body that merely QUOTED
    # `## Clarified` inside a fence was treated as clarified, given no
    # record, and denied by the CLARIFY guard — while every assertion
    # in this module that names no gate stayed green.
    write_unapproved_ledger(
        repo_dir,
        "## Notes\n```markdown\n## Clarified\n- Q1: <q> -> <a>\n```\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "APPROVAL GUARD" in reason(result), "the fixture and the guard disagree"


# --- scope: the gate rides the EXISTING thresholds, it does not widen them ---

def test_short_prompt_still_passes_unapproved(repo_dir):
    # This is also what the v0.22.0 docs rest on. Three review rounds
    # caught three wrong prose descriptions of this gate ("no size
    # condition", "only spawn prompts over 1500 chars", both silent
    # about guard_task_create's tracker-task path), so the documents
    # stopped describing the mechanics and now say the gates miss whole
    # paths and the go is never conditional on being caught. THIS test
    # is the record of the behaviour behind that sentence.
    write_unapproved_ledger(repo_dir)
    assert run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt="where is the config")) is None


def test_fork_still_exempt(repo_dir):
    write_unapproved_ledger(repo_dir)
    payload = spawn_payload(repo_dir, prompt=VERY_LONG,
                            tool_input={"subagent_type": "fork"})
    assert run_hook(SCRIPT, payload) is None


def test_workflow_script_gated_on_approval(repo_dir):
    write_unapproved_ledger(repo_dir)
    payload = spawn_payload(repo_dir, tool="Workflow")
    payload["tool_input"] = {"script": "y" * 5000}
    result = run_hook(SCRIPT, payload)
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


def test_threshold_env_still_applies(repo_dir):
    write_unapproved_ledger(repo_dir)
    assert run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt=LONG),
        env_extra={"LEDGER_GUARD_THRESHOLD": "3000"},
    ) is None


def test_teammate_spawns_are_not_gated(repo_dir, tmp_path):
    # Workers cannot get an approval from the user any more than they
    # can ask a question, so they are not held to either gate.
    import os
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env python3\n"
        "print('1 claude --agent-id worker@session-t --agent-name worker')\n",
        encoding="utf-8",
    )
    os.chmod(ps, 0o755)
    write_unapproved_ledger(repo_dir)
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    assert run_hook(SCRIPT, spawn_payload(repo_dir), env_extra=env,
                    tmpdir=tmp_path) is None


# --- order: ledger -> clarified -> approved, pinned ---

def test_missing_ledger_still_reports_the_ledger_gate(repo_dir):
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "LEDGER GUARD" in reason(result)
    assert "APPROVAL GUARD" not in reason(result)


def test_unclarified_ledger_reports_the_clarify_gate_even_when_approved(repo_dir):
    # The chair is never told to get approval for a plan it has not
    # been able to ask about yet.
    write_ledger(repo_dir, "## Approved\n- Yusuf: go\n\n" + ITEMS,
                 ensure_clarified=False)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "CLARIFY GUARD" in reason(result)
    assert "APPROVAL GUARD" not in reason(result)


def test_clarified_but_unapproved_reports_the_approval_gate(repo_dir):
    write_ledger(repo_dir, CLARIFIED + ITEMS, ensure_approved=False)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


# --- the escape hatch ---

def test_approval_guard_disabled_by_zero(repo_dir):
    write_unapproved_ledger(repo_dir)
    assert run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG),
        env_extra={"LEDGER_GUARD_APPROVAL": "0"},
    ) is None


def test_approval_guard_only_zero_disables(repo_dir):
    write_unapproved_ledger(repo_dir)
    for value in ("", "1", "off", "false"):
        result = run_hook(
            SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG),
            env_extra={"LEDGER_GUARD_APPROVAL": value},
        )
        assert is_deny(result), value


def test_disabled_approval_gate_leaves_the_others_armed(repo_dir):
    # No ledger at all, and no `## Clarified` — turning this gate off
    # is not a way out of the two before it.
    assert is_deny(run_hook(
        SCRIPT, spawn_payload(repo_dir),
        env_extra={"LEDGER_GUARD_APPROVAL": "0"},
    ))
    write_ledger(repo_dir, ITEMS, ensure_clarified=False, ensure_approved=False)
    result = run_hook(SCRIPT, spawn_payload(repo_dir),
                      env_extra={"LEDGER_GUARD_APPROVAL": "0"})
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)


def test_disabled_clarify_gate_leaves_the_approval_gate_armed(repo_dir):
    # The switches are separate: a repo that turns the questions off
    # has not thereby agreed to skip the go.
    write_ledger(repo_dir, ITEMS, ensure_clarified=False, ensure_approved=False)
    result = run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG),
        env_extra={"LEDGER_GUARD_CLARIFY": "0"},
    )
    assert is_deny(result) and "APPROVAL GUARD" in reason(result)


# --- the tracker-task gate carries the same rule ---

def test_third_task_on_unapproved_ledger_denied(repo_dir, tmp_path):
    write_unapproved_ledger(repo_dir)
    results = run_tasks(repo_dir, tmp_path, 4)
    assert results[0] is None and results[1] is None
    assert is_deny(results[2])
    assert "APPROVAL GUARD" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]
    assert results[3] is None          # still fires once per session


def test_tasks_pass_freely_on_an_approved_ledger(repo_dir, tmp_path):
    write_ledger(repo_dir)
    assert run_tasks(repo_dir, tmp_path, 5) == [None] * 5


def test_approval_nudge_has_its_own_reminder(repo_dir, tmp_path):
    # Three reminders that say different things: spending the clarify
    # one must not silence the approval one. What the approval one does
    # NOT get is its own two free tasks — the count is the session's,
    # so a chair already past the cap hears the new reminder on its
    # very next task instead of buying three more first.
    write_ledger(repo_dir, ITEMS, ensure_clarified=False, ensure_approved=False)
    results = run_tasks(repo_dir, tmp_path, 3)
    assert is_deny(results[2])
    assert "CLARIFY GUARD" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]

    write_unapproved_ledger(repo_dir)                  # the chair complies
    more = run_tasks(repo_dir, tmp_path, 2)
    assert is_deny(more[0]), "the approval nudge was silenced by the clarify one"
    assert "APPROVAL GUARD" in more[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert more[1] is None                             # once per session, per kind

    write_ledger(repo_dir)                             # and it complies again
    assert run_tasks(repo_dir, tmp_path, 3) == [None] * 3


# --- a guard never crashes the pipeline ---

def test_malformed_input_never_blocks():
    assert run_hook(SCRIPT, raw="{not json") is None


def test_unreadable_ledger_fails_open(repo_dir):
    # A guard never blocks on its own IO error, approval or not.
    import os
    import stat
    ledger = write_ledger(repo_dir, ITEMS, ensure_approved=False)
    os.chmod(ledger, 0)
    try:
        if os.access(ledger, os.R_OK):          # running as root: no such thing
            return
        assert run_hook(
            SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None
    finally:
        os.chmod(ledger, stat.S_IRUSR | stat.S_IWUSR)


# --- the deny text has to be actionable in ONE round trip ---

def test_approval_deny_says_what_to_write(repo_dir):
    write_unapproved_ledger(repo_dir)
    text = reason(run_hook(SCRIPT, spawn_payload(repo_dir)))
    assert "`## Approved`" in text
    assert "WILL build" in text and "NOT building" in text
    assert "'done' is observed" in text
    assert "WAIT" in text
    assert "LEDGER_GUARD_APPROVAL=0" in text


def test_ledger_deny_names_the_approved_section(repo_dir):
    # Following the missing-ledger text exactly must not walk straight
    # into the next gate — that is two round trips for obeying.
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert "`## Approved`" in reason(result)


def test_task_deny_names_the_approved_section(repo_dir, tmp_path):
    results = run_tasks(repo_dir, tmp_path, 3)
    assert "`## Approved`" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]


def test_clarify_deny_points_at_the_next_gate(repo_dir):
    # A chair that obeys the clarify deny and spawns again lands here
    # next; the text says so, so both records can be written in one go.
    write_ledger(repo_dir, ITEMS, ensure_clarified=False, ensure_approved=False)
    text = reason(run_hook(SCRIPT, spawn_payload(repo_dir)))
    assert "CLARIFY GUARD" in text and "`## Approved`" in text


# --- metrics and the summary they feed ---

def test_approval_metrics_reach_the_stats_summary(repo_dir, tmp_path):
    import json
    import subprocess
    import sys
    from conftest import REPO

    home = tmp_path / "home"
    home.mkdir()
    env = {"FABLE_ORCH_METRICS": "1", "HOME": str(home)}
    write_unapproved_ledger(repo_dir)
    run_hook(SCRIPT, spawn_payload(repo_dir), env_extra=env, tmpdir=tmp_path)
    for _ in range(3):
        run_hook(SCRIPT, task_payload(repo_dir), env_extra=env, tmpdir=tmp_path)

    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum(1 for e in events if e["event"] == "approval_deny") == 1
    assert sum(1 for e in events if e["event"] == "tasks_approval_deny") == 1
    # The separate names are the point: an approval deny counted as a
    # clarify one would report a gate nobody tripped.
    assert not [e for e in events if e["event"] == "clarify_deny"]

    stats = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "stats.py"), str(log)],
        capture_output=True, text=True, timeout=30,
    )
    assert stats.returncode == 0, stats.stderr
    assert "1 denied for a missing `## Approved` record" in stats.stdout
    assert "1 denied for approval" in stats.stdout


def test_approved_constant_matches_the_documented_shape(repo_dir):
    # The fixture and the skill have to agree on what a record looks
    # like, or the suite passes on a shape the plugin never ships.
    assert APPROVED.startswith("## Approved\n")
    write_ledger(repo_dir, CLARIFIED + APPROVED + ITEMS,
                 ensure_clarified=False, ensure_approved=False)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None
