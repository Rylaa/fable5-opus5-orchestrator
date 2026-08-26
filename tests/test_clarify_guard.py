"""Rule 0.5: a ledger only disarms the spawn gates once it is CLARIFIED.

The ledger gates ask "did you write the requirements down?". These ask
the question before it: "did you find out what the requirements ARE?"
Workers cannot reach the user, so an ambiguity that survives into a
spawn prompt is a guess that ships — the `## Clarified` section is
where the chair spends that ambiguity instead.
"""
from conftest import CLARIFIED, run_hook, write_ledger
from test_spawn_guard import (
    LONG,
    VERY_LONG,
    is_deny,
    run_tasks,
    spawn_payload,
    task_payload,
    write_marker,
)
import time

SCRIPT = "ledger_guard_spawn.py"
ITEMS = "- [ ] 1. item\n"


def reason(result):
    return result["hookSpecificOutput"]["permissionDecisionReason"]


def unclarified(repo, body=ITEMS):
    return write_ledger(repo, body, clarified=False)


# --- the gate itself ---

def test_clarified_ledger_passes(repo_dir):
    write_ledger(repo_dir)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_unclarified_ledger_denied(repo_dir):
    unclarified(repo_dir)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "CLARIFY GUARD" in reason(result)
    assert "orchestrator:clarify" in reason(result)


def test_heading_alone_is_not_a_record(repo_dir):
    # A chair that types the header and spawns anyway has clarified
    # nothing — the section has to carry content.
    unclarified(repo_dir, "## Clarified\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)


def test_empty_section_followed_by_heading_denied(repo_dir):
    unclarified(repo_dir, "## Clarified\n\n## Items\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_section_at_end_of_file_with_content_passes(repo_dir):
    unclarified(repo_dir, ITEMS + "\n## Clarified\n- Q1: scope -> all of it\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_heading_level_and_case_are_free(repo_dir):
    # The rule is about the record existing, not markdown depth.
    for heading in ("## Clarified", "### clarified", "###### CLARIFIED"):
        unclarified(repo_dir, f"{heading}\n- No ambiguity: request is literal\n" + ITEMS)
        assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None, heading


def test_no_ambiguity_line_satisfies_the_gate(repo_dir):
    # The documented escape for a genuinely literal request: one line,
    # not a skipped section.
    unclarified(repo_dir, "## Clarified\n- No ambiguity: rename is exact\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_crlf_ledger_still_reads_as_clarified(repo_dir):
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER.md").write_bytes(b"## Clarified\r\n- Q1: scope -> all\r\n\r\n- [ ] 1. open\r\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_lookalike_heading_does_not_satisfy(repo_dir):
    # "Clarifications pending" is not the record; the word has to be
    # the whole heading token.
    unclarified(repo_dir, "## Clarifying later\n- soon\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


# --- scope: the gate rides the EXISTING thresholds, it does not widen them ---

def test_short_prompt_still_passes_unclarified(repo_dir):
    # Quick lookups were never gated and still are not.
    unclarified(repo_dir)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt="where is the config")) is None


def test_fork_still_exempt(repo_dir):
    unclarified(repo_dir)
    payload = spawn_payload(repo_dir, prompt=VERY_LONG, tool_input={"subagent_type": "fork"})
    assert run_hook(SCRIPT, payload) is None


def test_workflow_script_gated_on_clarification(repo_dir):
    unclarified(repo_dir)
    payload = spawn_payload(repo_dir, tool="Workflow")
    payload["tool_input"] = {"script": "y" * 5000}
    result = run_hook(SCRIPT, payload)
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)


def test_threshold_env_still_applies(repo_dir):
    unclarified(repo_dir)
    assert run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt=LONG),
        env_extra={"LEDGER_GUARD_THRESHOLD": "3000"},
    ) is None


# --- precedence: a missing or stale ledger is still a LEDGER problem ---

def test_missing_ledger_reports_the_ledger_gate(repo_dir):
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "LEDGER GUARD" in reason(result) and "CLARIFY GUARD" not in reason(result)


def test_stale_clarified_ledger_reports_staleness(repo_dir, tmp_path):
    import os
    write_marker(tmp_path, time.time())
    ledger = write_ledger(repo_dir, "- [x] 1. done\n- [x] V. verified\n")
    old = time.time() - 3600
    os.utime(ledger, (old, old))
    result = run_hook(SCRIPT, spawn_payload(repo_dir), tmpdir=tmp_path)
    assert is_deny(result) and "previous session" in reason(result)


# --- the tracker-task gate carries the same rule ---

def test_third_task_on_unclarified_ledger_denied(repo_dir, tmp_path):
    unclarified(repo_dir)
    results = run_tasks(repo_dir, tmp_path, 4)
    assert results[0] is None and results[1] is None
    assert is_deny(results[2])
    assert "CLARIFY GUARD" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]
    assert results[3] is None          # still fires once per session


def test_tasks_pass_freely_on_a_clarified_ledger(repo_dir, tmp_path):
    write_ledger(repo_dir)
    assert run_tasks(repo_dir, tmp_path, 5) == [None] * 5


# --- the escape hatch ---

def test_clarify_guard_disabled_by_zero(repo_dir):
    unclarified(repo_dir)
    assert run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG),
        env_extra={"LEDGER_GUARD_CLARIFY": "0"},
    ) is None


def test_clarify_guard_only_zero_disables(repo_dir):
    unclarified(repo_dir)
    for value in ("", "1", "off", "false"):
        result = run_hook(
            SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG),
            env_extra={"LEDGER_GUARD_CLARIFY": value},
        )
        assert is_deny(result), value


def test_disabled_gate_leaves_the_ledger_gate_armed(repo_dir):
    assert is_deny(run_hook(
        SCRIPT, spawn_payload(repo_dir),
        env_extra={"LEDGER_GUARD_CLARIFY": "0"},
    ))


# --- a guard never crashes the pipeline ---

def test_malformed_input_never_blocks():
    assert run_hook(SCRIPT, raw="{not json") is None


def test_binary_ledger_never_crashes(repo_dir):
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER.md").write_bytes(b"\xff\xfe\x00## Clarified\n- Q1: x\n\n- [ ] 1. open\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert result is None or is_deny(result)


def test_clarified_constant_matches_the_documented_shape(repo_dir):
    # The fixture and the skill have to agree on what a record looks
    # like, or the suite passes on a shape the plugin never ships.
    assert CLARIFIED.startswith("## Clarified\n")
    unclarified(repo_dir, CLARIFIED + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


# --- regressions from the v0.16.0 review: what counts as an ANSWER ---

def test_checkbox_shaped_answers_count_as_content(repo_dir):
    # A chair writing its answers in the ledger's own checkbox idiom has
    # clarified the work. Denying that shape told it the section it just
    # filled in was empty — a deny with no action behind it.
    unclarified(repo_dir,
                "## Clarified\n"
                "- [x] Q1: replace the old exporter? -> beside it, one release\n"
                "- [~] Assumption: no backfill\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_numbered_checkbox_still_ends_the_section(repo_dir):
    # `- [ ] 1.` is a ledger ITEM, so an empty heading above the items
    # must not read the requirements back as answers.
    for bullet in ("- [ ] 1. item", "* [x] 2. done", "+ [~] 3. deferred: ok",
                   "- [x] V. verified"):
        unclarified(repo_dir, f"## Clarified\n\n{bullet}\n")
        assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir))), bullet


def test_setext_heading_does_not_count_as_content(repo_dir):
    # The other markdown heading syntax ends the section too.
    unclarified(repo_dir, "## Clarified\n\nRequirements\n------------\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_fenced_example_is_not_a_record(repo_dir):
    # The skill's own markdown example of the section must not satisfy
    # the gate it is teaching — same rule as the close guard's fences.
    unclarified(repo_dir,
                "## Notes\nCopy this shape:\n\n```markdown\n## Clarified\n"
                "- Q1: <question> -> <answer>\n```\n\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_fenced_example_beside_a_real_record_passes(repo_dir):
    unclarified(repo_dir,
                "## Clarified\n- Q1: scope -> all of it\n\n"
                "```markdown\n## Clarified\n- Q1: <question>\n```\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_a_filled_section_below_an_empty_one_passes(repo_dir):
    # The protocol appends later answers, so every heading is checked.
    unclarified(repo_dir,
                "## Clarified\n\n" + ITEMS + "\n## Clarified\n- Q2: round two -> yes\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_h1_clarified_counts(repo_dir):
    unclarified(repo_dir, "# Clarified\n- Q1: scope -> all of it\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


# --- the two tracker-task reminders are separate budgets ---

def test_clarify_nudge_does_not_spend_the_ledger_nudge(repo_dir, tmp_path):
    import shutil
    unclarified(repo_dir)
    results = run_tasks(repo_dir, tmp_path, 3)
    assert is_deny(results[2])
    assert "CLARIFY GUARD" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]

    shutil.rmtree(repo_dir / ".workflow")          # now the ledger is gone
    more = run_tasks(repo_dir, tmp_path, 2)
    assert is_deny(more[0]), "the missing-ledger nudge was silenced by the clarify one"
    assert "LEDGER GUARD" in more[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert more[1] is None                          # still once per session, per kind


# --- metrics and the summary they feed ---

def test_clarify_metrics_reach_the_stats_summary(repo_dir, tmp_path):
    import json
    import subprocess
    import sys
    from conftest import REPO

    home = tmp_path / "home"
    home.mkdir()
    env = {"FABLE_ORCH_METRICS": "1", "HOME": str(home)}
    unclarified(repo_dir)
    run_hook(SCRIPT, spawn_payload(repo_dir), env_extra=env, tmpdir=tmp_path)
    for _ in range(3):
        run_hook(SCRIPT, task_payload(repo_dir), env_extra=env, tmpdir=tmp_path)

    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum(1 for e in events if e["event"] == "clarify_deny") == 1
    assert sum(1 for e in events if e["event"] == "tasks_clarify_deny") == 1

    stats = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "stats.py"), str(log)],
        capture_output=True, text=True, timeout=30,
    )
    assert stats.returncode == 0, stats.stderr
    # The old summary counted only spawn_deny/tasks_deny and reported a
    # blocked session as "0 denied".
    assert "1 denied for a missing `## Clarified` record" in stats.stdout
    assert "1 denied for clarification" in stats.stdout
