"""The per-prompt reminder: the core profile arrives once, this rides
every prompt. Measured in the wild: five sessions received the profile
in full and delegated nothing."""
from conftest import fake_ps_env, run_hook

SCRIPT = "remind_chair.py"


def context_of(result):
    out = result["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    return out["additionalContext"]


def test_every_prompt_carries_the_default(tmp_path):
    text = context_of(run_hook(SCRIPT, {"prompt": "fix the thing"},
                               tmpdir=tmp_path))
    assert "CHAIR" in text
    assert "Delegate by default" in text


def test_the_reminder_stays_tiny(tmp_path):
    # It is paid on EVERY prompt, so it restates the default and
    # nothing else — routing and the report contract live in the core
    # and the playbook, which are read once.
    text = context_of(run_hook(SCRIPT, {"prompt": "x"}, tmpdir=tmp_path))
    assert len(text) < 250, f"reminder is {len(text)} chars"


def test_teammates_get_no_reminder(tmp_path):
    # A worker told to delegate would spawn workers of its own, which
    # is the exact failure this plugin exists to prevent.
    env = fake_ps_env(tmp_path, "1 claude --agent-id w@s --agent-name w")
    assert run_hook(SCRIPT, {"prompt": "x"}, env_extra=env,
                    tmpdir=tmp_path) is None


def test_chair_still_reminded_when_the_ancestor_is_plain_claude(tmp_path):
    env = fake_ps_env(tmp_path, "1 claude")
    assert context_of(run_hook(SCRIPT, {"prompt": "x"}, env_extra=env,
                               tmpdir=tmp_path))


def test_escape_hatch(tmp_path):
    assert run_hook(SCRIPT, {"prompt": "x"},
                    env_extra={"FABLE_ORCH_REMIND": "0"},
                    tmpdir=tmp_path) is None


def test_garbage_stdin_is_survivable(tmp_path):
    assert context_of(run_hook(SCRIPT, raw="{not json", tmpdir=tmp_path))
    assert context_of(run_hook(SCRIPT, raw="", tmpdir=tmp_path))
