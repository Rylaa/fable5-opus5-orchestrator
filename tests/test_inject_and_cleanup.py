import json
import os

from conftest import context_of, flat, REPO, run_hook

INJECT = "inject_instructions.py"
CLEANUP = "cleanup_session_cache.py"


CORES = ("dynamic-workflow-fable.md", "dynamic-workflow-opus.md")
SWITCHES = ("profile-switch-to-fable.md", "profile-switch-to-opus.md")
PLAYBOOK = ("skills", "playbook", "SKILL.md")
CLARIFY = ("skills", "clarify", "SKILL.md")


def _instr(name):
    return (REPO / "instructions" / name).read_text(encoding="utf-8")


def _playbook():
    return REPO.joinpath(*PLAYBOOK).read_text(encoding="utf-8")


def _clarify():
    return REPO.joinpath(*CLARIFY).read_text(encoding="utf-8")


def test_cores_stay_on_the_token_diet():
    # NOTE: the 10k cap itself is asserted end-to-end by
    # test_the_whole_injection_stays_under_the_hook_cap at the bottom of
    # this file. What survives here is the per-core STYLE budget: the
    # core is a summary, and a summary that doubles has stopped being
    # one even when the total still fits.
    #
    # Claude Code caps hook output at 10,000 chars, but the real budget
    # is tighter than the cap: this text is prepended to EVERY chair
    # session, so every char is paid on every start (v0.8.0 shipped at
    # 10,069 and silently stopped reaching the chair at all). v0.15.0
    # moved the detail to the playbook skill, which loads on demand —
    # the core is a summary now, and this pin keeps it one.
    #
    # v0.16.0 raised the pin from 4000 to 4400 to seat Rule 0.5. The
    # cores were at 3744/3781 and the rule added ~370 chars, which put
    # the opus core OVER the old 4000 pin — the raise was required, not
    # a comfort margin. 4.4k is still far under the 10k hook cap that
    # made this a pin at all.
    #
    # v0.21.0 raised it again, 4400 to 4800, for the watchdog sentence
    # in Rule 3: the opus core was at 4369 and had 31 chars of room, so
    # the rule could not be seated at all. Same shape as the 0.5 raise —
    # required, not comfort.
    #
    # v0.22.0 raised it 4800 to 6500 for four behaviour changes the
    # cores have to state or the chair cannot obey them: the chair no
    # longer writes the code (Rule 0), the clarify sweep scales to the
    # work (Rule 0.5), and the verifier carries an effort floor and a
    # convergence stop (Verification), and every question carrying one
    # plain line of why it is being asked (Rule 0.5). The opus core was
    # at 4778 with 22 chars of room — none of them could be seated.
    for name in CORES:
        text = _instr(name)
        assert len(text) < 6500, f"{name} is {len(text)} chars — over the 6.5k core diet"


def test_switch_notes_stay_tiny():
    # A switch note is pure delta on top of a core the session already
    # has. Anything approaching core size means the delta grew back into
    # a second profile and the saving is gone.
    for name in SWITCHES:
        text = _instr(name)
        assert len(text) < 600, f"{name} is {len(text)} chars — over the 600-char delta budget"


def test_playbook_skill_exists_and_stays_bounded():
    # The detail the cores shed has to land SOMEWHERE readable, and the
    # skill is loaded in full once per session — bounded, not a dumping
    # ground for everything trimmed from the cores.
    #
    # v0.22.0 raised the pin 5000 to 9000 — the largest raise this file
    # has taken, and deliberately so. The skill loads on DEMAND and is
    # not part of the injected payload, so detail moved here costs
    # nothing per session; detail left in a core or in fire.md costs
    # every session or every /fire. This release pushed the verifier's
    # effort rule, the per-wave review and the skip rule OUT of fire.md
    # and into this file for exactly that reason. The binding constraint
    # is test_the_whole_injection_stays_under_the_hook_cap, not this pin,
    # which is now a dumping-ground alarm rather than a token budget. The file was at 4995 with 5
    # chars of room and gained the two sections the cores only summarize:
    # what the chair actually does (it judges, it does not write code —
    # the verifier is its eyes) and the verification detail behind the
    # new core line, effort floor, convergence stop, per-wave background
    # review into FINDINGS-*.md, and when a skip is the chair's call.
    path = REPO.joinpath(*PLAYBOOK)
    assert path.is_file(), f"missing playbook skill: {path}"
    text = path.read_text(encoding="utf-8")
    assert len(text) < 9000, f"SKILL.md is {len(text)} chars — over the 9k budget"
    assert "name: playbook" in text  # the namespaced literal below depends on it


def test_cores_require_the_playbook_before_first_delegation():
    # The linchpin of progressive disclosure: the core only summarizes,
    # so a core that stops REQUIRING the playbook silently ships a chair
    # missing the research pipeline, output contract, fork cap, and
    # verification procedure. The literal is plugin-name-namespaced —
    # pinned against plugin.json below so a rename can't orphan it.
    plugin_name = json.loads(
        (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["name"]
    assert plugin_name == "orchestrator"
    for name in CORES:
        text = flat(_instr(name))
        assert f"{plugin_name}:playbook" in text, name
        assert "BEFORE YOUR FIRST DELEGATION" in text, name


def test_cores_carry_the_watchdog_rule():
    # v0.21.0: a spawn is not a start. Measured 2026-08-26 — a named
    # verifier's process stayed alive 39 minutes with no session log
    # while the chair reported it as running. The rule that sends a
    # watchdog out WITH the wave is what turns that wait into a
    # message; a core that drops it ships the old failure back.
    for name in CORES:
        text = flat(_instr(name))
        assert '"{{WATCHDOG}}" --watch' in text, name
        assert "`watchdog` teammate" in text, name
        assert "never poll" in text, name


def test_the_injector_resolves_the_watchdog_path(tmp_path):
    # The core tells the chair to RUN a script, and a relative path cannot
    # resolve from a user's project directory — the plugin lives under
    # ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/. The
    # injector is the only component that knows the real root, so it
    # substitutes the placeholder on the way out. A core that ships the
    # placeholder unresolved hands the watchdog teammate a command that
    # fails with "No such file or directory".
    text = context_of(run_hook(
        INJECT, {"model": "claude-opus-5", "session_id": "s-watchdog"},
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)}, tmpdir=tmp_path))
    assert "{{WATCHDOG}}" not in text
    assert str(REPO / "scripts" / "agent_watchdog.py") in text


def test_clarify_skill_exists_and_stays_bounded():
    # Rule 0.5's detail lives here for the same reason the delegation
    # contract lives in the playbook: the core summarizes, the skill
    # carries the protocol, and neither becomes a dumping ground.
    # v0.22.0 raised the pin 5000 to 8000. The file was at 4966 and
    # gained the ceremony-scaling section, the positive stop test, the
    # two-part shape every question takes, the reason a recommendation
    # has to carry, and the shape of the approval ask.
    path = REPO.joinpath(*CLARIFY)
    assert path.is_file(), f"missing clarify skill: {path}"
    text = path.read_text(encoding="utf-8")
    assert len(text) < 8000, f"SKILL.md is {len(text)} chars — over the 8k budget"
    assert "name: clarify" in text


def test_clarify_skill_carries_the_user_decisions():
    # User decisions (2026-08-26): one question per message, no cap on
    # the loop, the "does the answer change the work" filter that makes
    # an uncapped loop safe, and the record landing in the ledger. A
    # rewrite that drops one of these is a regression, not an edit.
    text = flat(_clarify())
    assert "One question per message" in text
    assert "No cap." in text
    assert "would a different answer produce different code?" in text
    assert "`## Clarified`" in text
    assert "SendMessage" in text          # subagents escalate, never ask the user


def test_clarify_skill_carries_the_approval_gate():
    # User decision (2026-08-26): answers are not agreement. The skill
    # is where the chair reads what the `## Approved` section has to
    # say — what it will build, what it will not, how done is observed —
    # and that it WAITS. A rewrite that drops the section leaves the
    # hook denying with nothing in the docs to act on.
    text = flat(_clarify())
    assert "## Approved" in text
    assert "Not building:" in text
    assert "Done when:" in text
    assert "LEDGER_GUARD_APPROVAL=0" in text


def test_cores_require_approval_before_delegation():
    # The gate is hook-enforced, but the core still has to TELL the
    # chair what the hook wants, and in which order — clarify first,
    # then the go, then the spawn. A deny the chair cannot act on is a
    # loop, not a guard.
    for name in CORES:
        text = flat(_instr(name))
        assert "`## Approved`" in text, name
        assert "GO before any spawn" in text, name
        assert text.index("`## Clarified`") < text.index("`## Approved`"), name


def test_cores_do_not_order_the_wave_out_before_the_go():
    # The two rules contradicted each other: Rule 0.5 wants the user's
    # go IN the ledger before any spawn, and Rule 1 still said "write
    # the ledger + first worker wave in ONE message". The go takes a
    # round trip, so both could not hold — and the cheapest way to obey
    # both was to write the go yourself and attribute it to the user,
    # which is the silent approval the gate exists to stop (it happened
    # once in real use before the review caught it). Rule 1 still
    # batches; what it batches is the WAVE, after the answer.
    for name in CORES:
        text = flat(_instr(name))
        assert "ledger + first worker wave in ONE message" not in text, name
        assert "the whole first wave in ONE message once the go lands" in text, name
        assert "never a ledger then solo work" in text, name
        # And the go is the user's to write.
        assert "their words, never yours" in text, name
        assert text.index("Ledger + plan in ONE message") > text.index("`## Approved`"), name


def test_the_opus_core_keeps_sizing_effort_to_the_work():
    # The rewrite that made room for the watchdog sentence dropped the
    # operative half of the effort rule and left only the negative one
    # ("never on what the call costs"). A chair told what NOT to price
    # on, and nothing about when to spend, rounds down.
    text = flat(_instr("dynamic-workflow-opus.md"))
    assert "a job that needs `max` gets `max`, a mechanical sweep does not" in text


def test_cores_require_clarification_before_delegation():
    # The gate is hook-enforced, but the core still has to TELL the
    # chair what the hook wants — a deny the chair cannot act on is a
    # loop, not a guard.
    for name in CORES:
        text = flat(_instr(name))
        assert "orchestrator:clarify" in text, name
        assert "`## Clarified`" in text, name
        assert "ONE question per" in text, name


def test_profiles_name_substantive_workers():
    # User decision (2026-07-25): workers are WATCHED live in tmux panes
    # and steered via SendMessage — visibility over lightness. Today's
    # naming behavior is a model tendency, not a guarantee; this pin
    # keeps a future model from drifting back to silent unnamed
    # subagents for substantive work. Survived the v0.15.0 diet in both
    # cores; the lifecycle detail moved to the playbook.
    for name in CORES:
        assert "NAME every substantive worker" in flat(_instr(name)), name
    assert "NAME every substantive worker" in flat(_playbook())


def test_preserved_decisions_survive_the_diet():
    # v0.15.0 cut ~60% of both cores. These are user decisions, not
    # prose — a trim that drops one is a regression, not a diet.
    for name in CORES:
        text = flat(_instr(name))
        assert "no haiku" in text, f"{name}: haiku ban dropped"
        assert "fork (≤2/session" in text, f"{name}: fork cap dropped"
        assert "EVERY close gets a FRESH" in text, f"{name}: fresh-eyes-every-close dropped"
        assert "./.workflow/LEDGER*.md" in text, f"{name}: ledger path dropped"
        # v0.15.0 additions: the report diet and the batching rule.
        assert "≤40 lines" in text, f"{name}: report line cap dropped"
        assert "five greps is one agent" in text, f"{name}: batching rule dropped"
    book = flat(_playbook())
    assert "at most 2 per session" in book          # fork cap, in full
    assert "at most 40 lines TOTAL" in book         # report diet, in full
    assert "at most 10 lines inline" in book        # verbatim spill rule


def test_injects_the_fable_profile(tmp_path):
    result = run_hook(
        INJECT,
        {"model": "claude-fable-5", "session_id": "s-fable"},
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
        tmpdir=tmp_path,
    )
    assert "(FABLE profile)" in context_of(result)
    cache = tmp_path / "fable-orch-model-s-fable.json"
    assert cache.is_file()
    data = json.loads(cache.read_text())
    assert data["model"] == "claude-fable-5"
    assert "started" in data


def test_non_opus_models_get_the_fable_profile(tmp_path):
    # Fable-first: everything that isn't an opus chair (sonnet chairs
    # included) gets the primary profile.
    result = run_hook(
        INJECT,
        {"model": "claude-sonnet-5", "session_id": "s-sonnet"},
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
        tmpdir=tmp_path,
    )
    assert "(FABLE profile)" in context_of(result)


def test_opus_chair_gets_the_opus_fallback_profile(tmp_path):
    # The Fable limit ran dry and the chair restarted on Opus: the
    # matching profile keeps the same discipline with the fable tier
    # resting.
    result = run_hook(
        INJECT,
        {"model": "claude-opus-5", "session_id": "s-opus"},
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
        tmpdir=tmp_path,
    )
    text = context_of(result)
    assert "(OPUS profile)" in text
    assert "(FABLE profile)" not in text


def test_every_opus_generation_and_spelling_detects(tmp_path):
    # Detection matches the tier name, not a dated ID, so it must survive
    # every new Opus release and every spelling the harness or
    # settings.json can hand it — display name, 1M-context suffix, and a
    # version glued straight onto the tier name.
    for model in ("claude-opus-5", "claude-opus-5[1m]", "opus[1m]",
                  "Opus 5 (1M context)", "claude-opus-4-8", "OPUS-5",
                  "claude-opus5", "opus6", "claude-opus-5.1"):
        result = run_hook(
            INJECT,
            {"model": model, "session_id": "s-gen"},
            env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
            tmpdir=tmp_path,
        )
        assert "(OPUS profile)" in context_of(result), model


def test_opus_lookalike_models_are_not_opus(tmp_path):
    # The match is word-boundary anchored: a model whose name merely
    # contains the letters "opus" is not an Opus chair.
    for model in ("claude-octopus-1", "opusculum-7", "myopus"):
        result = run_hook(
            INJECT,
            {"model": model, "session_id": "s-look"},
            env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
            tmpdir=tmp_path,
        )
        assert "(FABLE profile)" in context_of(result), model


def test_profiles_name_no_dated_opus_id():
    # The profiles teach "never a dated ID"; they must follow their own
    # rule, or they go stale on every release (they said "Opus 4.8"
    # while an Opus 5 chair was reading them). Matches any dotted or
    # dashed version glued to a tier name, not just the one that bit us.
    import re as _re

    dated = _re.compile(r"\b(opus|sonnet|fable|haiku)[ -]?\d+[.-]\d+",
                        _re.IGNORECASE)
    for name in CORES + SWITCHES:
        hit = dated.search(flat(_instr(name)))
        assert not hit, f"{name}: {hit.group(0) if hit else ''}"
    hit = dated.search(flat(_playbook()))
    assert not hit, f"SKILL.md: {hit.group(0) if hit else ''}"


def test_readme_carries_no_price_or_cost_figures():
    # User decision: the README sells the DISCIPLINE, not a number. Any
    # concrete price/spend figure dates instantly (tier prices move) and
    # invites arguing with the arithmetic instead of the design.
    import re as _re

    readme = flat((REPO / "README.md").read_text(encoding="utf-8"))
    money = _re.compile(
        r"[$€£]\s?\d|\b\d+(?:[.,]\d+)?\s?(?:USD|EUR|dollars?|cents?)\b"
        r"|\bper (?:million|1M) tokens\b",
        _re.IGNORECASE)
    hit = money.search(readme)
    assert not hit, f"README carries a price figure: {hit.group(0) if hit else ''}"


def _readme():
    return (REPO / "README.md").read_text(encoding="utf-8")


def test_readme_links_point_at_headings_that_exist():
    # A renamed heading leaves every link to it pointing nowhere, and
    # the page still renders: "Already on an older version? See
    # Upgrading to v0.16.0" survived the rename of that section to
    # "Upgrading" and quietly scrolled readers nowhere.
    import re as _re

    text = _readme()
    slugs = set()
    for line in text.splitlines():
        m = _re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if m:
            slug = _re.sub(r"[^a-z0-9 -]", "", m.group(1).lower()).replace(" ", "-")
            slugs.add(slug)
    dead = [t for t in _re.findall(r"\]\(#([^)]+)\)", text) if t not in slugs]
    assert not dead, f"README links to headings that do not exist: {dead}"


def test_readme_does_not_undersell_how_long_the_suite_takes():
    # The figure was written when the suite was seconds long and stayed
    # there: measured 2026-08-27, 349 tests in 94-128s depending on the
    # machine (340 in 103.3s before this release), of which
    # tests/test_watchdog.py is 57s of real sleeping through the birth
    # and stall thresholds. A reader who is told 25 seconds concludes
    # the run has hung. The pin is a floor, not the number itself, so
    # updating an honest figure does not break it.
    import re as _re

    m = _re.search(r"Runs in about (\d+) seconds", _readme())
    assert m, "the Tests section no longer states a runtime"
    assert int(m.group(1)) >= 60, (
        f"README claims {m.group(1)}s; the watchdog tests alone sleep for ~57s")


def test_manual_install_resolves_the_watchdog_placeholder():
    # The manual path appends the profile to CLAUDE.md by hand, and the
    # profile carries `{{WATCHDOG}}` — a placeholder ONLY the session-
    # start hook substitutes, which this path does not run. Unresolved,
    # the chair sends its watchdog worker off to run a file called
    # `{{WATCHDOG}}`.
    assert "{{WATCHDOG}}" in _instr("dynamic-workflow-fable.md")
    manual = _readme().split("## Manual install")[1]
    assert "{{WATCHDOG}}" in manual, "the manual path never mentions the placeholder"
    assert "agent_watchdog.py" in manual, "and never says what to point it at"
    # The recorder is what fills the sidecar the watchdog reads; without
    # it the manual install ships a watchdog that can only see nothing.
    assert "--record" in manual and "--surface" in manual


# --- chair detection chain: override > payload > settings > marker > fable ---

def _write_settings(tmp_path, model):
    """Seed the sandboxed Claude config (run_hook points CLAUDE_CONFIG_DIR here)."""
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    (cfg / "settings.json").write_text(json.dumps({"model": model}), encoding="utf-8")


def _inject(tmp_path, payload, **env):
    env.setdefault("CLAUDE_PLUGIN_ROOT", str(REPO))
    return run_hook(INJECT, payload, env_extra=env, tmpdir=tmp_path)


def test_null_payload_falls_back_to_settings_opus(tmp_path):
    # The real bug: SessionStart omits `model` on some fires. The user's
    # configured default (/model wrote "opus[1m]" to settings.json) must
    # still select the OPUS profile instead of defaulting to fable.
    _write_settings(tmp_path, "opus[1m]")
    assert "(OPUS profile)" in context_of(_inject(tmp_path, {"session_id": "s1"}))


def test_null_payload_falls_back_to_settings_fable(tmp_path):
    _write_settings(tmp_path, "claude-fable-5")
    assert "(FABLE profile)" in context_of(_inject(tmp_path, {"session_id": "s2"}))


def test_payload_model_beats_settings(tmp_path):
    # Payload is authoritative for THIS session start; settings is only a
    # fallback for when the payload omits the model.
    _write_settings(tmp_path, "claude-fable-5")
    r = _inject(tmp_path, {"model": "claude-opus-4-8", "session_id": "s3"})
    assert "(OPUS profile)" in context_of(r)


def test_env_override_opus_beats_fable_payload(tmp_path):
    r = _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s4"},
                FABLE_ORCH_PROFILE="opus")
    assert "(OPUS profile)" in context_of(r)


def test_env_override_fable_beats_opus_payload(tmp_path):
    r = _inject(tmp_path, {"model": "claude-opus-4-8", "session_id": "s5"},
                FABLE_ORCH_PROFILE="fable")
    assert "(FABLE profile)" in context_of(r)


def test_env_override_auto_falls_through_to_detection(tmp_path):
    r = _inject(tmp_path, {"model": "claude-opus-4-8", "session_id": "s6"},
                FABLE_ORCH_PROFILE="auto")
    assert "(OPUS profile)" in context_of(r)


def test_marker_keeps_opus_sticky_on_null_payload(tmp_path):
    # First injection sees opus -> marker records it. A later null-payload
    # resume (no settings) must stay opus, not regress to fable, and must
    # not overwrite the remembered model with null.
    _inject(tmp_path, {"model": "claude-opus-4-8", "session_id": "s7"})
    marker = tmp_path / "fable-orch-model-s7.json"
    assert json.loads(marker.read_text())["model"] == "claude-opus-4-8"
    assert "(OPUS profile)" in context_of(_inject(tmp_path, {"session_id": "s7"}))
    assert json.loads(marker.read_text())["model"] == "claude-opus-4-8"


def test_inject_metric_records_detection_source(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _write_settings(tmp_path, "opus[1m]")
    _inject(tmp_path, {"session_id": "s8"}, HOME=str(home), FABLE_ORCH_METRICS="1")
    rec = json.loads((home / ".claude" / "fable-orch" / "metrics.jsonl")
                     .read_text().splitlines()[0])
    assert rec["profile"] == "opus" and rec["source"] == "settings"


# --- profile-switch delta: same session, the chair changed tiers ---

def _marker(tmp_path, sid):
    return json.loads((tmp_path / f"fable-orch-model-{sid}.json")
                      .read_text(encoding="utf-8"))


def test_fable_to_opus_switch_on_resume_injects_only_the_delta(tmp_path):
    # The Fable limit ran dry mid-session and the user moved the chair to
    # Opus. On a RESUME the core is provably still in this session's
    # context; re-sending it spends the very limit the switch preserves.
    assert "(FABLE profile)" in context_of(
        _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-sw1"}))
    assert _marker(tmp_path, "s-sw1")["profile"] == "fable"

    text = context_of(_inject(tmp_path, {"model": "claude-opus-5",
                                         "session_id": "s-sw1",
                                         "source": "resume"}))
    assert "Profile switch → OPUS chair" in text
    assert "(OPUS profile)" not in text   # the full core is NOT re-sent
    assert len(text) < 600
    assert _marker(tmp_path, "s-sw1")["profile"] == "opus"


def test_opus_to_fable_switch_on_resume_injects_only_the_delta(tmp_path):
    # The limit reset and the chair moved back.
    assert "(OPUS profile)" in context_of(
        _inject(tmp_path, {"model": "claude-opus-5", "session_id": "s-sw2"}))
    text = context_of(_inject(tmp_path, {"model": "claude-fable-5",
                                         "session_id": "s-sw2",
                                         "source": "resume"}))
    assert "Profile switch → FABLE chair" in text
    assert "(FABLE profile)" not in text
    assert _marker(tmp_path, "s-sw2")["profile"] == "fable"


def test_switching_back_and_forth_on_resume_keeps_delivering_deltas(tmp_path):
    # fable -> opus -> fable inside one session: each hop is a delta, and
    # the marker tracks the CURRENT profile, never the original.
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-sw3"})
    assert "Profile switch → OPUS" in context_of(
        _inject(tmp_path, {"model": "claude-opus-5", "session_id": "s-sw3",
                           "source": "resume"}))
    assert "Profile switch → FABLE" in context_of(
        _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-sw3",
                           "source": "resume"}))
    assert _marker(tmp_path, "s-sw3")["profile"] == "fable"


def test_switch_on_a_context_losing_fire_gets_the_full_core(tmp_path):
    # `compact` re-fires BECAUSE the context was rewritten and `clear`
    # because it was discarded — the earlier core may be gone, and the
    # switch note's "every other rule from the already-injected core
    # profile stays in force" would then be a lie the chair cannot
    # detect. Both take the full core even though the profile changed,
    # and the marker still tracks the new chair.
    for i, fire in enumerate(("compact", "clear", "startup")):
        sid = f"s-fire{i}"
        assert "(FABLE profile)" in context_of(
            _inject(tmp_path, {"model": "claude-fable-5", "session_id": sid}))
        text = context_of(_inject(tmp_path, {"model": "claude-opus-5",
                                             "session_id": sid,
                                             "source": fire}))
        assert "(OPUS profile)" in text, fire     # the FULL core
        assert "Profile switch" not in text, fire
        assert _marker(tmp_path, sid)["profile"] == "opus", fire


def test_unknown_source_takes_the_safe_side(tmp_path):
    # An unrecognised (future) source is UNPROVEN, not assumed benign:
    # a delta is only ever emitted on a fire known to keep the core.
    # A missing `source` is the same case.
    for payload_extra in ({"source": "some-future-fire"}, {}):
        sid = "s-unk" + str(len(payload_extra))
        _inject(tmp_path, {"model": "claude-fable-5", "session_id": sid})
        payload = {"model": "claude-opus-5", "session_id": sid}
        payload.update(payload_extra)
        text = context_of(_inject(tmp_path, payload))
        assert "(OPUS profile)" in text, payload_extra
        assert "Profile switch" not in text, payload_extra


def test_same_profile_refire_still_gets_the_full_core(tmp_path):
    # An UNCHANGED chair, on every fire including the one that permits a
    # delta: behaviour is exactly what it was before the delta existed —
    # the full core, every time.
    for fire in (None, "resume", "compact"):
        payload = {"model": "claude-fable-5", "session_id": "s-same"}
        if fire:
            payload["source"] = fire
        text = context_of(_inject(tmp_path, payload))
        assert "(FABLE profile)" in text, fire
        assert "Profile switch" not in text, fire
    assert _marker(tmp_path, "s-same")["profile"] == "fable"


def test_legacy_marker_without_profile_never_gets_a_bare_delta(tmp_path):
    # A pre-0.15.0 marker records no profile. A delta on top of a core
    # this session may never have seen would strip the chair of every
    # orchestration rule silently — so an unrecorded profile means the
    # FULL core, even though the model plainly changed tier.
    cache = tmp_path / "fable-orch-model-s-legacy-p.json"
    cache.write_text(json.dumps({"model": "claude-fable-5", "started": 123.0}),
                     encoding="utf-8")
    # `source: resume` so the SOURCE gate is satisfied and the missing
    # profile is provably what holds the delta back.
    text = context_of(_inject(tmp_path, {"model": "claude-opus-5",
                                         "session_id": "s-legacy-p",
                                         "source": "resume"}))
    assert "(OPUS profile)" in text
    assert "Profile switch" not in text


def test_switch_metric_is_distinguishable(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "FABLE_ORCH_METRICS": "1"}
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-sw-m"}, **env)
    _inject(tmp_path, {"model": "claude-opus-5", "session_id": "s-sw-m",
                       "source": "resume"}, **env)
    lines = (home / ".claude" / "fable-orch" / "metrics.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["event"] == "inject"      # unchanged
    rec = json.loads(lines[1])
    assert rec["event"] == "inject_switch"                # its own event
    assert rec["profile"] == "opus" and rec["from_profile"] == "fable"
    # `fire` survives the gate: it is how we learn which sources real
    # fallback re-fires actually arrive on, before widening the gate.
    assert rec["fire"] == "resume"


def test_gated_full_core_is_not_counted_as_a_switch(tmp_path):
    # A profile change delivered as a full core is NOT an inject_switch —
    # otherwise the metric would report deltas that were never sent and
    # the data used to widen the gate would be self-confirming.
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "FABLE_ORCH_METRICS": "1"}
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-sw-g"}, **env)
    _inject(tmp_path, {"model": "claude-opus-5", "session_id": "s-sw-g",
                       "source": "compact"}, **env)
    lines = (home / ".claude" / "fable-orch" / "metrics.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert [json.loads(l)["event"] for l in lines] == ["inject", "inject"]


def test_teammate_is_skipped_even_when_the_profile_switched(tmp_path):
    # A teammate never received a core, so it can never receive a delta —
    # and its marker must not claim an injection that did not happen, or
    # the chair's next fire would be handed a delta with no core under it.
    cache = tmp_path / "fable-orch-model-s-tm-sw.json"
    cache.write_text(json.dumps({"model": "claude-fable-5", "started": 123.0,
                                 "profile": "fable"}), encoding="utf-8")
    env = _fake_ps_env(
        tmp_path, "1 claude --agent-id worker@session-t --agent-name worker")
    assert run_hook(INJECT, {"model": "claude-opus-5", "session_id": "s-tm-sw",
                             "source": "resume"},
                    env_extra=env, tmpdir=tmp_path) is None
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["model"] == "claude-opus-5"   # marker still tracks the model
    assert data["profile"] == "fable"         # but NOT a phantom injection


def test_missing_model_still_injects(tmp_path):
    result = run_hook(
        INJECT,
        {"session_id": "s-nomodel"},
        env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
        tmpdir=tmp_path,
    )
    assert "(FABLE profile)" in context_of(result)
    cache = tmp_path / "fable-orch-model-s-nomodel.json"
    assert "started" in json.loads(cache.read_text())


def test_plugin_root_fallback_to_script_location(tmp_path):
    # No CLAUDE_PLUGIN_ROOT: the script resolves the repo from its own path.
    result = run_hook(
        INJECT,
        {"model": "claude-fable-5", "session_id": "s-fallback"},
        tmpdir=tmp_path,
    )
    assert "(FABLE profile)" in context_of(result)


def test_metrics_written_when_enabled(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    run_hook(
        INJECT,
        {"model": "claude-fable-5", "session_id": "s-metrics"},
        env_extra={
            "CLAUDE_PLUGIN_ROOT": str(REPO),
            "HOME": str(home),
            "FABLE_ORCH_METRICS": "1",
        },
        tmpdir=tmp_path,
    )
    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    assert log.is_file()
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert rec["event"] == "inject"
    assert rec["model"] == "claude-fable-5"
    assert rec["profile"] == "fable"


def test_stats_reads_the_switch_event_without_crashing(tmp_path):
    # stats.py is the "how is this performing?" answer; a new event kind
    # that makes it traceback turns the whole log unreadable, not just
    # the new line. Mixed old + new events, one malformed line.
    import subprocess
    import sys

    log = tmp_path / "metrics.jsonl"
    log.write_text("\n".join([
        json.dumps({"ts": 1.0, "event": "inject", "profile": "fable"}),
        json.dumps({"ts": 2.0, "event": "inject_switch", "profile": "opus",
                    "from_profile": "fable", "fire": "compact"}),
        json.dumps({"ts": 3.0, "event": "inject_skipped", "reason": "teammate"}),
        "{not json",
    ]) + "\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "stats.py"),
                           str(log)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    # Bind to the SUMMARY line, not the raw event name: the generic
    # totals table prints every event kind verbatim, so asserting
    # "inject_switch" passes even with the summary deleted.
    assert "mid-session profile switches: 1" in proc.stdout


def test_metrics_optout(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    run_hook(
        INJECT,
        {"model": "claude-fable-5", "session_id": "s-nometrics"},
        env_extra={
            "CLAUDE_PLUGIN_ROOT": str(REPO),
            "HOME": str(home),
            "FABLE_ORCH_METRICS": "0",
        },
        tmpdir=tmp_path,
    )
    assert not (home / ".claude" / "fable-orch" / "metrics.jsonl").exists()


def test_inject_preserves_started_across_reruns(tmp_path):
    env = {"CLAUDE_PLUGIN_ROOT": str(REPO)}
    run_hook(INJECT, {"model": "claude-fable-5", "session_id": "s-started"},
             env_extra=env, tmpdir=tmp_path)
    cache = tmp_path / "fable-orch-model-s-started.json"
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert "started" in data
    data["started"] = 123.0  # pretend the session started long ago
    cache.write_text(json.dumps(data), encoding="utf-8")
    # Re-injection (resume/clear/compact) must not move `started` forward.
    run_hook(INJECT, {"model": "claude-fable-5", "session_id": "s-started"},
             env_extra=env, tmpdir=tmp_path)
    assert json.loads(cache.read_text(encoding="utf-8"))["started"] == 123.0


def _fake_ps_env(tmp_path, argv_line):
    """A fake `ps` on PATH: its one output line is the ancestor walk's
    first hop — the same fixture the stop guard's teammate tests use."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env python3\nprint(%r)\n" % argv_line, encoding="utf-8")
    os.chmod(ps, 0o755)
    return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "CLAUDE_PLUGIN_ROOT": str(REPO)}


def test_teammate_session_gets_no_profile(tmp_path):
    # Teammates fire SessionStart like any session, but the profile is
    # chair-only: injected into a worker it says "you are the
    # ORCHESTRATOR" and invites it to spawn subagents of its own.
    # Measured before the fix: 172 of 270 injected sessions were
    # teammates.
    env = _fake_ps_env(
        tmp_path, "1 claude --agent-id worker@session-t --agent-name worker")
    result = run_hook(INJECT, {"model": "claude-sonnet-5", "session_id": "s-tm"},
                      env_extra=env, tmpdir=tmp_path)
    assert result is None
    # The marker is still written: stop, spawn, and cleanup key off it.
    cache = tmp_path / "fable-orch-model-s-tm.json"
    assert cache.is_file()
    assert json.loads(cache.read_text(encoding="utf-8"))["model"] == "claude-sonnet-5"


def test_teammate_skip_records_metric(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _fake_ps_env(tmp_path, "1 claude --agent-id w@s --agent-name w")
    env.update({"HOME": str(home), "FABLE_ORCH_METRICS": "1"})
    run_hook(INJECT, {"model": "claude-sonnet-5", "session_id": "s-tm-m"},
             env_extra=env, tmpdir=tmp_path)
    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert rec["event"] == "inject_skipped"
    assert rec["reason"] == "teammate"
    # Resolution ran before the skip: the record still says which
    # profile the worker WOULD have received.
    assert rec["profile"] == "fable"
    assert rec["source"] == "payload"


def test_teammate_inject_escape_hatch(tmp_path):
    # FABLE_ORCH_TEAMMATE_INJECT=1 restores the old inject-everyone
    # behaviour, mirroring FABLE_ORCH_TEAMMATE_STOP on the close guard.
    env = _fake_ps_env(tmp_path, "1 claude --agent-id w@s --agent-name w")
    env["FABLE_ORCH_TEAMMATE_INJECT"] = "1"
    result = run_hook(INJECT, {"model": "claude-sonnet-5", "session_id": "s-tm-e"},
                      env_extra=env, tmpdir=tmp_path)
    assert "(FABLE profile)" in context_of(result)


def test_chair_still_injected_when_ancestor_is_plain_claude(tmp_path):
    # Same fake ps, no --agent-id: this is the chair and must keep
    # receiving the profile.
    env = _fake_ps_env(tmp_path, "1 claude")
    result = run_hook(INJECT, {"model": "claude-fable-5", "session_id": "s-chair"},
                      env_extra=env, tmpdir=tmp_path)
    assert "(FABLE profile)" in context_of(result)


def test_metrics_rotation_caps_the_log(tmp_path):
    home = tmp_path / "home"
    d = home / ".claude" / "fable-orch"
    d.mkdir(parents=True)
    log = d / "metrics.jsonl"
    log.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    run_hook(CLEANUP, {"session_id": "s-rot"},
             env_extra={"HOME": str(home), "FABLE_ORCH_METRICS": "1"},
             tmpdir=tmp_path)
    assert (d / "metrics.jsonl.old").is_file()
    assert log.is_file() and b"cleanup" in log.read_bytes()


def test_cleanup_removes_cache(tmp_path):
    cache = tmp_path / "fable-orch-model-s-clean.json"
    cache.write_text(json.dumps({"profile": "fable"}), encoding="utf-8")
    assert run_hook(CLEANUP, {"session_id": "s-clean"}, tmpdir=tmp_path) is None
    assert not cache.exists()


def test_cleanup_removes_stop_sidecar_and_sweeps_old(tmp_path):
    import os
    import time

    cache = tmp_path / "fable-orch-model-s-clean.json"
    cache.write_text("{}", encoding="utf-8")
    sidecar = tmp_path / "fable-orch-stop-s-clean.json"
    sidecar.write_text("{}", encoding="utf-8")
    tasks = tmp_path / "fable-orch-tasks-s-clean.json"
    tasks.write_text('{"count": 2}', encoding="utf-8")
    stale = tmp_path / "fable-orch-model-dead-session.json"
    stale.write_text("{}", encoding="utf-8")
    old = time.time() - 120 * 3600  # past the 96h sweep window
    os.utime(stale, (old, old))
    fresh = tmp_path / "fable-orch-model-alive.json"
    fresh.write_text("{}", encoding="utf-8")

    assert run_hook(CLEANUP, {"session_id": "s-clean"}, tmpdir=tmp_path) is None
    assert not cache.exists()
    assert not sidecar.exists()
    assert not tasks.exists()  # the task-gate counter dies with the session
    assert not stale.exists()  # older than the 96h sweep window
    assert fresh.exists()      # other live sessions' files stay


FAKE_TMUX = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
sock = args[1] if len(args) > 1 and args[0] == "-S" else ""
cmd = args[2] if len(args) > 2 else ""
if os.environ.get("FAKE_TMUX_DEAD") == "1":
    sys.stderr.write("no server running\\n")
    sys.exit(1)
if os.environ.get("FAKE_TMUX_MISMATCH") == "1":
    sys.stderr.write("protocol version mismatch (client 3.4, server 3.3)\\n")
    sys.exit(1)
if cmd == "list-panes":
    print(os.environ.get("FAKE_PANES", "%1 12345"))
elif cmd == "list-windows":
    print(os.environ.get("FAKE_WINDOW_ACTIVITY", "0"))
elif cmd == "kill-pane":
    with open(os.environ["FAKE_KILL_LOG"], "a") as f:
        f.write("pane " + sock + " " + " ".join(args[3:]) + "\\n")
elif cmd == "kill-server":
    with open(os.environ["FAKE_KILL_LOG"], "a") as f:
        f.write(sock + "\\n")
sys.exit(0)
"""

FAKE_PS = """#!/usr/bin/env python3
import json, os, sys
log = os.environ.get("FAKE_PS_LOG")
if log:
    with open(log, "a") as f:
        f.write(" ".join(sys.argv[1:]) + "\\n")
if "ppid=,command=" in sys.argv:
    # nearest-claude ancestor walk: "<ppid> <command of queried pid>"
    anc = os.environ.get("FAKE_ANCESTRY")
    if anc:
        m = json.loads(anc)
        print(m.get(sys.argv[-1], m.get("default", "1 init")))
    else:
        print(os.environ.get("FAKE_PPID", "1") + " claude")
elif "ppid=" in sys.argv:
    print(os.environ.get("FAKE_PPID", "1"))   # legacy ancestor walk
elif any("cputime" in a for a in sys.argv):
    print(os.environ.get("FAKE_PS_PANE",       # pane idle sampling
          "12345 0:05.00 claude --agent-id w@session-t --agent-name w"))
else:
    print(os.environ.get("FAKE_PS_OUTPUT", ""))  # command lookup
"""


def _swarm_fixture(tmp_path):
    """Fake tmux/ps on PATH + a fake socket dir with one swarm socket."""
    import os as _os

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("tmux", FAKE_TMUX), ("ps", FAKE_PS)):
        p = bin_dir / name
        p.write_text(body, encoding="utf-8")
        _os.chmod(p, 0o755)
    swarm_root = tmp_path / "tmuxroot"
    sock_dir = swarm_root / f"tmux-{_os.getuid()}"
    sock_dir.mkdir(parents=True)
    (sock_dir / "claude-swarm-111").write_text("", encoding="utf-8")
    kill_log = tmp_path / "kills.log"
    env = {
        "PATH": f"{bin_dir}:{_os.environ.get('PATH', '')}",
        "TMUX_TMPDIR": str(swarm_root),
        "FABLE_ORCH_SWARM_CLEANUP": "1",
        "FAKE_KILL_LOG": str(kill_log),
        "FAKE_PS_LOG": str(tmp_path / "ps.log"),
    }
    return env, kill_log


def test_cleanup_reaps_own_swarm(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-s-swarm- --agent-name worker"
    import time
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))  # fresh — sweep must not fire
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert kill_log.is_file()
    assert "claude-swarm-111" in kill_log.read_text()
    # The tag matcher must actually query ps with the pane pids it collected.
    ps_log = tmp_path / "ps.log"
    assert ps_log.is_file() and "-p 12345" in ps_log.read_text()


def test_cleanup_leaves_other_sessions_swarm(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-deadbeef --agent-name worker"
    import time
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_cleanup_sweeps_idle_swarm(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-deadbeef --agent-name worker"
    env["FAKE_WINDOW_ACTIVITY"] = "1000"  # ancient — way past the 48h window
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert kill_log.is_file()
    assert "claude-swarm-111" in kill_log.read_text()


def test_cleanup_reaps_by_ancestor_pid_socket(tmp_path):
    # Current Claude Code tags teammates with a per-team id, not the parent
    # session id — the reaper must still find OUR server via its socket
    # name, claude-swarm-<main pid>, using the hook's ancestor chain.
    import os
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{os.getuid()}"
    own = sock_dir / f"claude-swarm-{os.getpid()}"  # test process = hook's parent
    own.write_text("", encoding="utf-8")
    env["FAKE_PPID"] = str(os.getpid())
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-otherteam --agent-name w"
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    text = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert f"claude-swarm-{os.getpid()}" in text   # ours: killed via pid match
    assert "claude-swarm-111" not in text          # foreign tag + fresh: untouched


def test_swarm_idle_sweep_disabled_by_zero(tmp_path):
    # MAX_IDLE_H=0 turns off the idle kill even for ancient servers;
    # own-session reaping is a separate switch and stays available.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    env["FABLE_ORCH_SWARM_MAX_IDLE_H"] = "0"
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-deadbeef --agent-name w"
    env["FAKE_WINDOW_ACTIVITY"] = "1000"  # ancient, but the sweep is off
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_inject_started_falls_back_to_mtime_for_legacy_cache(tmp_path):
    # A cache written by an older plugin version has no `started`. On the
    # next re-injection (compact/resume) the injector must anchor to the
    # file's mtime — never to "now", which would disown the session's
    # pre-compaction ledgers.
    import os
    import time

    cache = tmp_path / "fable-orch-model-s-legacy.json"
    cache.write_text(json.dumps({"profile": "fable"}), encoding="utf-8")
    old = time.time() - 7200
    os.utime(cache, (old, old))
    run_hook(INJECT, {"model": "claude-fable-5", "session_id": "s-legacy"},
             env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)}, tmpdir=tmp_path)
    started = json.loads(cache.read_text(encoding="utf-8"))["started"]
    assert abs(started - old) < 5


def test_swarm_cleanup_optout(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FABLE_ORCH_SWARM_CLEANUP"] = "0"
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-s-swarm- --agent-name worker"
    env["FAKE_WINDOW_ACTIVITY"] = "1000"
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_cleanup_unlinks_dead_socket(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_TMUX_DEAD"] = "1"
    sock = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}" / "claude-swarm-111"
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not sock.exists()
    assert not kill_log.exists()


def test_cleanup_without_session_id_is_noop(tmp_path):
    assert run_hook(CLEANUP, {}, tmpdir=tmp_path) is None


def test_cleanup_malformed_input_is_noop():
    assert run_hook(CLEANUP, raw="not json") is None


def test_non_object_stdin_never_crashes(tmp_path):
    # Valid JSON that isn't an object: both hooks stay on the contract.
    assert run_hook(CLEANUP, raw="[1, 2]", tmpdir=tmp_path) is None
    result = run_hook(INJECT, raw="[1, 2]",
                      env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
                      tmpdir=tmp_path)
    assert "(FABLE profile)" in context_of(result)  # still injects


def test_nested_claude_does_not_kill_outer_swarm(tmp_path):
    # A nested `claude -p` (fusion helpers, scripts) ends: its hook's
    # ancestor chain CONTAINS the outer session's claude. Matching every
    # ancestor used to kill the outer session's LIVE team — only the
    # NEAREST claude ancestor (pid 900, the inner session) may match.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    (sock_dir / "claude-swarm-900").write_text("", encoding="utf-8")  # inner's team
    (sock_dir / "claude-swarm-500").write_text("", encoding="utf-8")  # OUTER's team
    env["FAKE_ANCESTRY"] = json.dumps({
        "default": "900 python3 hook.py",   # hook's parent is the inner claude
        "900": "800 claude -p run this",    # inner claude — NEAREST match
        "800": "500 -bash",                 # shell between the two sessions
        "500": "1 claude",                  # outer interactive claude
    })
    env["FAKE_PS_OUTPUT"] = "claude --agent-id w@session-otherteam --agent-name w"
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-nested"}, env_extra=env, tmpdir=tmp_path) is None
    text = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert "claude-swarm-900" in text      # the inner session's own team dies
    assert "claude-swarm-500" not in text  # the outer session's team LIVES


def test_session_end_kills_own_panes_in_default_server(tmp_path):
    # Current layout: teammates are panes inside the USER'S default tmux
    # server, tagged with --parent-session-id. SessionEnd must kill the
    # session's own PANES there — and must NEVER kill-server a non-swarm
    # socket.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    default_sock = sock_dir / "default"
    default_sock.write_text("", encoding="utf-8")
    env["FAKE_PS_OUTPUT"] = (
        "12345 claude --agent-id w@session-team1 --agent-name w "
        "--parent-session-id s-own-full-id"
    )
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-own-full-id"}, env_extra=env, tmpdir=tmp_path) is None
    lines = kill_log.read_text(encoding="utf-8").splitlines() if kill_log.exists() else []
    assert any("pane" in l and "default -t %1" in l for l in lines)
    assert not any(l.strip() == str(default_sock) for l in lines)  # no kill-server on default


def test_session_end_leaves_other_sessions_panes(tmp_path):
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    (sock_dir / "default").write_text("", encoding="utf-8")
    env["FAKE_PS_OUTPUT"] = (
        "12345 claude --agent-id w@session-team1 --agent-name w "
        "--parent-session-id another-sessions-id"
    )
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-own-full-id"}, env_extra=env, tmpdir=tmp_path) is None
    log = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert "default" not in log  # the other session's pane lives


def test_session_id_prefix_collision_does_not_kill(tmp_path):
    # Session "s-own" must not claim a teammate of "s-own-full-id":
    # the --parent-session-id match is token-exact, not substring.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    (sock_dir / "default").write_text("", encoding="utf-8")
    env["FAKE_PS_OUTPUT"] = (
        "12345 claude --agent-id w@session-team1 --agent-name w "
        "--parent-session-id s-own-full-id"
    )
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-own"}, env_extra=env, tmpdir=tmp_path) is None
    log = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert "default" not in log


def test_protocol_mismatch_socket_survives(tmp_path):
    # tmux binary upgraded mid-flight: the server answers rc=1 with
    # "protocol version mismatch" but is ALIVE — unlinking its socket
    # would orphan it forever. Only truly dead sockets get removed.
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_TMUX_MISMATCH"] = "1"
    sock = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}" / "claude-swarm-111"
    assert run_hook(CLEANUP, {"session_id": "s-mismatch"}, env_extra=env, tmpdir=tmp_path) is None
    assert sock.exists()
    assert not kill_log.exists()


def test_the_chair_does_not_write_the_code():
    # v0.22.0. A chair that writes the code is also the chair that
    # cannot review it — and the verifier stops being its eyes and
    # becomes a formality. The cores carry the rule and the playbook
    # carries the reasoning; a rewrite that drops either ships a chair
    # that quietly starts implementing again.
    for name in CORES:
        text = flat(_instr(name))
        assert "does NOT write code" in text, name
        assert "one mechanical file edit" in text, name
    book = flat(_playbook())
    assert "it does not write the code" in book
    assert "CHAIR'S EYES" in book


def test_the_clarify_sweep_scales_but_the_go_does_not():
    # v0.22.0. The SWEEP is what scales with size; the go does not. The
    # docs say WHY without describing the hook's mechanics, because two
    # earlier attempts to describe them shipped two different false
    # claims — the gate has several paths (prompt length, tracker-task
    # count) and exempts forks, so "you will be denied" is wrong and
    # "you will not be denied" is wrong too. The behaviour itself is
    # pinned in test_the_approval_gate_is_prompt_sized_not_work_sized
    # in test_spawn_guard.py; here we pin that the docs rest the rule on
    # the v0.21.0 lesson rather than on enforcement.
    for name in CORES:
        text = flat(_instr(name))
        assert "their words, never yours — at EVERY size" in text, name
        assert "Scale the SWEEP, never the go" in text, name
        assert "The gates do NOT catch every path" in text, name
    text = flat(_clarify())
    assert "Scale the ceremony to the work" in text
    assert "`## Approved` is required at every size" in text
    assert "not because a hook will force it" in text


def test_the_verifier_carries_a_floor_and_a_convergence_stop():
    # v0.22.0. Two user decisions: the verifier never runs at `low`, and
    # a cycle that repeats a finding is disagreement rather than
    # progress — a third fresh reader repeats it again, so it goes to
    # the user instead of burning the cap.
    for name in CORES:
        text = flat(_instr(name))
        assert "effort floor `medium`" in text, name
        assert "repeated finding is disagreement" in text, name
    book = flat(_playbook())
    assert "effort FLOOR `medium` — never `low`" in book
    assert "a repeated finding is disagreement, not progress" in book


def test_the_per_wave_review_has_a_home_and_a_lifecycle():
    # v0.22.0. Wave reviews write to FINDINGS-*.md, never LEDGER*.md:
    # find_ledger() takes the most recent LEDGER*.md, so a findings file
    # wearing that name carries no `## Clarified`/`## Approved` and
    # denies every later spawn. One file PER WAVE, because the reviews
    # run in the background and concurrent appends to one shared file
    # lose a whole wave silently. And a pinned REF, not the working tree
    # the next wave is already editing — worded so it still holds when
    # the wave's editors ran in worktrees and have to land first.
    book = flat(_playbook())
    assert "FINDINGS-<topic>-w<N>.md" in book
    assert "kept OUT of LEDGER*.md" in book
    assert "after any worktree branches are merged back" in book
    assert "never append to one file and clobber each other" in book
    for name in CORES:
        assert "FINDINGS-*.md" in flat(_instr(name)), name


def test_a_skipped_verification_is_deferred_not_dropped():
    # v0.22.0. A skipped verification leaves `- [ ] V.` open, and
    # ledger_guard_stop holds the turn end over it — once per session
    # per ledger, not forever, but the item never goes away on its own.
    # The skip is a DEFERRAL the USER grants: `- [~]` stops matching the
    # guard's open-item regex, so it IS a close, and the docs have to
    # say whose close it is. `- [x]` stays the verifier's alone.
    book = flat(_playbook())
    assert "`- [~] deferred: <reason>`" in book
    assert "a deferral the USER granted" in book
    assert "`- [x]` still belongs to the verifier alone" in book
    for name in CORES:
        assert "recorded `- [~] deferred:`" in flat(_instr(name)), name


def test_the_whole_injection_stays_under_the_hook_cap(tmp_path):
    # The core diet pin is a proxy; THIS is the real limit. What reaches
    # the chair is core + instructions/reply-shape.md + the watchdog
    # placeholder resolved to an absolute plugin path, and v0.8.0 shipped
    # 10,069 chars of it and got silently truncated. Every raise of the
    # core pin moves this sum, so the sum is what gets asserted — a
    # per-file budget cannot see it.
    for model in ("claude-opus-5", "claude-fable-5"):
        text = context_of(run_hook(
            INJECT, {"model": model, "session_id": f"s-cap-{model}"},
            env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)}, tmpdir=tmp_path))
        assert len(text) < 10000, f"{model}: injected {len(text)} chars — near the 10k hook cap"


def test_questions_carry_their_own_why():
    # User decision, 2026-08-27: a question with no stated stake reads
    # as paperwork and gets answered to get past the chair rather than
    # to decide anything. Every question is the question in one plain
    # sentence plus one basic line of what changes depending on the
    # answer — distinct from the pin above, which is about the
    # recommended ANSWER carrying its reason.
    for name in CORES:
        text = flat(_instr(name))
        assert "Each question is TWO parts" in text, name
        assert "why you are asking" in text, name
    text = flat(_clarify())
    assert "WHY YOU ARE ASKING" in text
    assert "reads as paperwork" in text
