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

def test_any_checkbox_ends_the_section(repo_dir):
    # Answers are plain bullets. Recognising only NUMBERED checkboxes
    # let an empty heading above ordinary `- [ ] fix login` items pass
    # as if the ledger's own requirements were the answers — a silent
    # bypass of the whole gate. Every checkbox form ends the section,
    # and the deny text says so instead of claiming the file is empty.
    for bullet in ("- [ ] 1. item", "* [x] 2. done", "+ [~] 3. deferred: ok",
                   "- [x] V. verified", "- [ ] fix login", "- [x] Q1: beside it",
                   "-  [ ] 1. two spaces", "- [>] 1. odd marker"):
        unclarified(repo_dir, f"## Clarified\n\n{bullet}\n")
        result = run_hook(SCRIPT, spawn_payload(repo_dir))
        assert is_deny(result), bullet
        assert "PLAIN BULLETS" in reason(result), bullet


def test_open_checkbox_answers_would_break_the_close_guard(repo_dir):
    # `- [ ] Q2: still waiting` passed the clarify gate while matching
    # OPEN_ITEM_RE, so the ledger could never go stale and every close
    # was held forever. Ending the section on any checkbox closes it.
    unclarified(repo_dir,
                "## Clarified\n- [ ] Q2: still waiting on the user\n\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_sub_heading_stays_inside_the_section(repo_dir):
    # The protocol appends later rounds, and `### Round 1` is how a
    # chair files them. Ending the section at ANY heading denied a
    # ledger full of answers, with nothing in the message to act on.
    unclarified(repo_dir,
                "## Clarified\n### Round 1\n- Q1: replace it? -> beside it\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_same_level_heading_ends_the_section(repo_dir):
    unclarified(repo_dir, "## Clarified\n\n## Items\n- something\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_setext_heading_does_not_count_as_content(repo_dir):
    # The other markdown heading syntax ends the section too.
    unclarified(repo_dir, "## Clarified\n\nRequirements\n------------\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_divider_under_the_one_line_escape_is_fine(repo_dir):
    # `- No ambiguity: <why>` is the line the deny text asks for. A
    # `---` after it is a thematic break, not a setext underline, and
    # denying it looped the chair against its own instructions.
    unclarified(repo_dir,
                "## Clarified\n- No ambiguity: the rename is exact\n---\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_punctuation_alone_is_not_an_answer(repo_dir):
    # Typing the heading and a divider is the "clarified nothing" case.
    for filler in ("---", "***", "___", "<!-- TODO fill this in -->", "|  |"):
        unclarified(repo_dir, f"## Clarified\n\n{filler}\n\n" + ITEMS)
        assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir))), filler


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
    more = run_tasks(repo_dir, tmp_path, 4)
    assert more[0] is None and more[1] is None      # its own two free tasks
    assert is_deny(more[2]), "the missing-ledger nudge was silenced by the clarify one"
    assert "LEDGER GUARD" in more[2]["hookSpecificOutput"]["permissionDecisionReason"]
    assert more[3] is None                          # still once per session, per kind


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


# --- regressions from the v0.16.0 review, round two ---

def test_tilde_fence_is_stripped_like_a_backtick_one(repo_dir):
    unclarified(repo_dir,
                "## Notes\n~~~markdown\n## Clarified\n- Q1: <q> -> <a>\n~~~\n\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_longer_fence_wraps_a_shorter_one(repo_dir):
    unclarified(repo_dir,
                "## Notes\n````markdown\n```\n## Clarified\n- Q1: <q>\n```\n````\n\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))


def test_fenced_open_item_cannot_keep_a_finished_ledger_fresh(repo_dir, tmp_path):
    # The staleness scan read RAW text while the clarify scan stripped
    # fences, so a closed ledger QUOTING the `- [ ] 1. <item>` format
    # looked permanently live and disarmed every gate in that repo.
    import os
    write_marker(tmp_path, time.time())
    ledger = write_ledger(
        repo_dir,
        "- [x] 1. done\n- [x] V. verified\n\n"
        "Format reminder:\n\n```markdown\n- [ ] 1. <item>\n```\n")
    old = time.time() - 3600
    os.utime(ledger, (old, old))
    result = run_hook(SCRIPT, spawn_payload(repo_dir), tmpdir=tmp_path)
    assert is_deny(result) and "previous session" in reason(result)


def test_plus_bullet_stays_out_of_the_open_item_dialect(repo_dir, tmp_path):
    # The close guard counts `-` and `*` only. A spawn guard that also
    # counted `+` kept a `+`-bulleted ledger non-stale forever while its
    # close was never held — one file, two dialects.
    import os
    write_marker(tmp_path, time.time())
    ledger = write_ledger(repo_dir, "+ [ ] 1. open\n")
    old = time.time() - 3600
    os.utime(ledger, (old, old))
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir), tmpdir=tmp_path))


# --- the deny texts have to be actionable in ONE round trip ---

def test_ledger_deny_names_the_clarified_section(repo_dir):
    # Following the old text exactly — write the numbered ledger, re-spawn —
    # walked straight into a clarify deny. Two round trips for obeying.
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "`## Clarified`" in reason(result)


def test_task_deny_names_the_clarified_section(repo_dir, tmp_path):
    results = run_tasks(repo_dir, tmp_path, 3)
    assert "`## Clarified`" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]


def test_clarify_deny_offers_the_archive_remedy(repo_dir):
    # An abandoned ledger with one never-closed item is never "stale",
    # so it falls through to the clarify deny — which used to tell the
    # chair to write this session's answers into a foreign file.
    unclarified(repo_dir, "- [ ] 2. something from six months ago\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "archive" in reason(result).lower()


# --- workers cannot satisfy these gates, so they are not held to them ---

def test_teammate_spawns_are_not_gated(repo_dir, tmp_path):
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
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    # No ledger at all: the chair would be denied, the worker is not.
    assert run_hook(SCRIPT, spawn_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None


def test_chair_spawns_are_still_gated(repo_dir, tmp_path):
    import os
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env python3\n"
        "print('1 claude --dangerously-skip-permissions')\n",
        encoding="utf-8",
    )
    os.chmod(ps, 0o755)
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir), env_extra=env, tmpdir=tmp_path))


def test_each_blocker_gets_its_own_free_tasks(repo_dir, tmp_path):
    # Counting both blockers together meant the second one to appear
    # was already at the limit: a chair that obeyed the ledger nudge
    # drew a clarify deny on its very next task.
    import shutil
    results = run_tasks(repo_dir, tmp_path, 3)          # no ledger at all
    assert is_deny(results[2])
    assert "LEDGER GUARD" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]

    unclarified(repo_dir)                               # the chair complies
    more = run_tasks(repo_dir, tmp_path, 3)
    assert more[0] is None and more[1] is None, "clarify budget started spent"
    assert is_deny(more[2])
    assert "CLARIFY GUARD" in more[2]["hookSpecificOutput"]["permissionDecisionReason"]
    shutil.rmtree(repo_dir / ".workflow")


# --- round-three fixes ---

def test_byte_order_mark_does_not_hide_a_line_one_heading(repo_dir):
    # An editor that writes a BOM put U+FEFF in front of `## Clarified`,
    # the heading stopped matching, and the chair was denied every time
    # it rewrote the section it already had.
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER.md").write_bytes(
        b"\xef\xbb\xbf## Clarified\n- Q1: scope -> all of it\n\n- [ ] 1. open\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_spaceless_heading_ends_a_section_it_could_start(repo_dir):
    # `##Clarified` opens a section, so `##Items` has to be able to
    # close one — otherwise an empty section runs past the ledger's own
    # headings hunting for content.
    unclarified(repo_dir, "## Clarified\n\n##Items\n" + ITEMS)
    assert is_deny(run_hook(SCRIPT, spawn_payload(repo_dir)))
    unclarified(repo_dir, "##Clarified\n- Q1: scope -> all of it\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_unreadable_ledger_fails_open_instead_of_lying(repo_dir):
    # Dropping an unreadable file during the scan produced "no active
    # ledger exists in any .workflow/" about a file that plainly does.
    # It is selected, the read fails open, and the spawn passes.
    import os
    import stat
    ledger = write_ledger(repo_dir)
    os.chmod(ledger, 0)
    try:
        if os.access(ledger, os.R_OK):          # running as root: no such thing
            return
        result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
        assert result is None, "an unreadable ledger must not deny"
    finally:
        os.chmod(ledger, stat.S_IRUSR | stat.S_IWUSR)


def test_unreadable_ledger_does_not_mask_a_readable_sibling(repo_dir):
    import os
    import stat
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    live = d / "LEDGER-live.md"
    live.write_text("- [ ] 1. open, and no answers here\n", encoding="utf-8")
    newer = d / "LEDGER-unreadable.md"
    newer.write_text(CLARIFIED + "- [ ] 1. open\n", encoding="utf-8")
    os.chmod(newer, 0)
    try:
        if os.access(newer, os.R_OK):
            return
        # The readable one wins, and it has no `## Clarified` record.
        result = run_hook(SCRIPT, spawn_payload(repo_dir))
        assert is_deny(result) and "CLARIFY GUARD" in reason(result)
    finally:
        os.chmod(newer, stat.S_IRUSR | stat.S_IWUSR)
