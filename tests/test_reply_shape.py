"""The reply shape: injected once, reminded every turn.

Rules delivered only at session start decay — by turn thirty the chair
is writing prose walls again and nothing in the transcript says
otherwise. The full rules ride the core; a one-line reminder rides
every prompt, at the moment the model composes its answer.
"""
import json
import os

from conftest import REPO, run_hook

SCRIPT = "remind_reply_shape.py"
INJECT = "inject_instructions.py"
RULES = REPO / "instructions" / "reply-shape.md"


def _rules():
    return RULES.read_text(encoding="utf-8")


def _flat(text):
    return " ".join(text.split())


def context_of(result):
    return result["hookSpecificOutput"]["additionalContext"]


# --- the rules file ---

def test_rules_exist_and_stay_small(tmp_path):
    # Paid on every chair session start, on top of the core. A file
    # that grows into a second profile spends the limit the core diet
    # exists to protect.
    assert RULES.is_file()
    assert len(_rules()) < 2500, f"{len(_rules())} chars — over the budget"


def test_rules_carry_the_user_decisions():
    # User decision (2026-08-26): the plugin ships these itself so that
    # everyone who installs it gets them — no dependency on any
    # formatting skill being present.
    text = _flat(_rules())
    assert "LEAD WITH THE NEXT ACTION" in text
    assert "NUMBER multi-step work" in text
    assert "NO preamble" in text
    assert "LISTS cap at five" in text
    assert "Override when" in text          # explain / destructive / ambiguous
    assert "i-have-adhd" not in text        # embedded, not delegated


# --- the per-turn reminder ---

def test_chair_gets_the_reminder():
    result = run_hook(SCRIPT, {"session_id": "s", "prompt": "hi"})
    assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "next action" in context_of(result)


def test_reminder_stays_one_line_sized():
    # It is paid on EVERY prompt. A reminder that grows into the rules
    # themselves defeats the split.
    result = run_hook(SCRIPT, {"session_id": "s"})
    assert len(context_of(result)) < 400


def test_teammate_gets_no_reminder(tmp_path):
    # A worker's reply is a report to the chair under the 40-line
    # output contract, not an answer to a person.
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
    assert run_hook(SCRIPT, {"session_id": "s"}, env_extra=env) is None


def test_versioned_binary_teammate_is_still_skipped(tmp_path):
    # Teammates run as .../claude/versions/2.1.246, basename `2.1.246`.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env python3\n"
        "print('1 /Users/y/.local/share/claude/versions/2.1.246 "
        "--agent-id worker@session-t')\n",
        encoding="utf-8",
    )
    os.chmod(ps, 0o755)
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    assert run_hook(SCRIPT, {"session_id": "s"}, env_extra=env) is None


def test_env_switch_disables_only_the_reminder():
    assert run_hook(SCRIPT, {"session_id": "s"},
                    env_extra={"FABLE_ORCH_REPLY_SHAPE": "0"}) is None
    for value in ("", "1", "off"):
        assert run_hook(SCRIPT, {"session_id": "s"},
                        env_extra={"FABLE_ORCH_REPLY_SHAPE": value}) is not None


def test_malformed_input_never_breaks_a_turn():
    assert run_hook(SCRIPT, raw="{not json") is not None   # still reminds
    assert run_hook(SCRIPT, raw="") is not None


# --- injection: the rules ride the full core, never the delta ---

def test_full_core_carries_the_rules(tmp_path):
    result = run_hook(INJECT, {"session_id": "inj-1", "source": "startup",
                               "model": "claude-fable-5"}, tmpdir=tmp_path)
    text = context_of(result)
    assert "Dynamic Workflow" in text
    assert "## Reply shape" in text


def test_switch_delta_does_not_resend_the_rules(tmp_path):
    # The delta goes to a session that already has them; re-sending
    # spends the limit the delta exists to save.
    run_hook(INJECT, {"session_id": "inj-2", "source": "startup",
                      "model": "claude-fable-5"}, tmpdir=tmp_path)
    result = run_hook(INJECT, {"session_id": "inj-2", "source": "resume",
                               "model": "claude-opus-5"}, tmpdir=tmp_path)
    text = context_of(result)
    assert "## Reply shape" not in text
    assert len(text) < 900


def test_missing_rules_file_never_breaks_session_start(tmp_path):
    # The profile matters more than the formatting: a plugin tree
    # without the rules file still injects the core.
    root = tmp_path / "plugin"
    (root / "instructions").mkdir(parents=True)
    (root / "instructions" / "dynamic-workflow-fable.md").write_text(
        "# core\n", encoding="utf-8")
    result = run_hook(INJECT, {"session_id": "inj-3", "source": "startup",
                               "model": "claude-fable-5"},
                      env_extra={"CLAUDE_PLUGIN_ROOT": str(root)},
                      tmpdir=tmp_path)
    assert context_of(result) == "# core\n"
