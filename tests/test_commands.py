"""The /fire command: one entry point that runs the whole discipline.

Everything else in this plugin is passive — it waits for the chair to
delegate and then gates it. /fire is the active path: the user hands
over a task and the command drives clarify -> ledger -> delegate ->
verify in order. If it drifts out of step with the guards, the user's
first experience of the plugin is a deny.
"""
import json
import re

from conftest import flat, REPO

COMMAND = REPO / "commands" / "fire.md"


def _text():
    return COMMAND.read_text(encoding="utf-8")


def test_command_exists_and_stays_bounded():
    # Loaded in full whenever the user types /fire, so it is a
    # checklist, not a second playbook.
    #
    # v0.22.0 raised the pin 3500 to 4900. The file was at 2977 and
    # gained the size-scaled clarify path, the shape of the approval
    # ask, and the verifier's convergence stop. Effort sizing, per-wave
    # review and the skip rule stayed in the playbook on purpose: this
    # file is loaded on every /fire, and duplicating them here is what
    # turns a checklist into a second playbook.
    assert COMMAND.is_file(), f"missing command: {COMMAND}"
    assert len(_text()) < 4900, f"{len(_text())} chars — over the budget"


def test_frontmatter_carries_a_description():
    text = _text()
    assert text.startswith("---\n")
    front = text.split("---", 2)[1]
    assert re.search(r"^description:\s*\S", front, re.M), "no description in frontmatter"


def test_argument_placeholder_is_present():
    # Without it the command silently drops whatever the user typed.
    assert "$ARGUMENTS" in _text()


def test_the_four_steps_are_in_order():
    # Order is the whole point: clarifying after the ledger is written
    # is just documenting a guess, and verifying before delegating
    # verifies nothing.
    text = flat(_text())
    steps = ("## 1 · Clarify", "## 2 · Write the ledger",
             "## 3 · Hand the work out", "## 4 · Verify the close")
    for step in steps:
        assert step in text, f"missing step: {step}"
    order = [text.index(step) for step in steps]
    assert order == sorted(order), "the command's steps are out of order"


def test_command_matches_what_the_guards_enforce():
    # Every claim here is a gate the chair will actually hit. A command
    # that teaches a different shape hands the user a deny.
    text = flat(_text())
    assert "./.workflow/LEDGER" in text
    assert "- [ ] N." in text
    assert "- [ ] V. fresh-eyes verification passed" in text
    assert "Plain bullets" in text            # checkbox lines end the section
    assert "## Approved" in text              # the approval gate, same file
    assert "WAIT" in text                     # ...and it is a stop, not a note
    assert "ONE question per message" in text
    assert "shutdown_request" in text         # finished workers get dismissed
    assert "three verify-fix cycles" in text  # the documented cap


def test_plugin_ships_the_commands_directory():
    # Claude Code discovers commands/ from the plugin root; a rename
    # would leave /fire undiscoverable with every test still green.
    assert (REPO / "commands").is_dir()
    plugin = json.loads(
        (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "orchestrator"


def test_command_carries_the_v0_22_rules():
    # fire.md's new material was protected by the char budget alone,
    # while the same rules in the cores, the playbook and the clarify
    # skill each got a content pin. A future diet of this file would
    # drop all five and stay green. These are the five it must keep.
    text = flat(_text())
    assert "POSITIVE test" in text                        # the stop test
    assert "SMALL-WORK line" in text                      # the sweep scales
    assert "at EVERY size" in text                        # the go does not
    assert 'never treat "nothing denied me" as approval' in text
    assert "repeats a finding is disagreement" in text    # convergence stop
    assert "Every QUESTION is two parts" in text          # question shape
    assert "one-line footnote for any name" in text       # unfamiliar names
