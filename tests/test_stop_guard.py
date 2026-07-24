import json
import os
import time

from conftest import run_hook, write_ledger

SCRIPT = "ledger_guard_stop.py"


def stop_payload(cwd, **extra):
    payload = {"cwd": str(cwd), "session_id": "test-session"}
    payload.update(extra)
    return payload


def blocks(result):
    return result is not None and result["decision"] == "block"


def test_no_ledger_passes(repo_dir, tmp_path):
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_open_items_block(repo_dir, tmp_path):
    write_ledger(repo_dir, "- [ ] 1. first\n- [x] 2. done\n- [ ] 3. third\n")
    result = run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path)
    assert blocks(result)
    assert "2 open item(s)" in result["reason"]
    assert "- [ ] 1. first" in result["reason"]


def test_bare_open_checkbox_counts(repo_dir, tmp_path):
    # A placeholder "- [ ]" with no text after it is still an open item.
    write_ledger(repo_dir, "- [ ]\n")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))


def test_star_bullets_also_count(repo_dir, tmp_path):
    write_ledger(repo_dir, "* [ ] 1. star bullet\n")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))


def test_all_closed_passes(repo_dir, tmp_path):
    write_ledger(repo_dir, "- [x] 1. done\n- [~] 2. deferred: user approved\n")
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_loop_guard_lets_second_stop_through(repo_dir, tmp_path):
    write_ledger(repo_dir, "- [ ] 1. still open\n")
    assert run_hook(
        SCRIPT, stop_payload(repo_dir, stop_hook_active=True), tmpdir=tmp_path
    ) is None


def test_second_stop_same_session_suppressed(repo_dir, tmp_path):
    write_ledger(repo_dir, "- [ ] 1. open\n")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_other_session_gets_its_own_reminder(repo_dir, tmp_path):
    write_ledger(repo_dir, "- [ ] 1. open\n")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))
    assert blocks(run_hook(
        SCRIPT, stop_payload(repo_dir, session_id="other-session"), tmpdir=tmp_path
    ))


def test_every_turn_mode_blocks_repeatedly(repo_dir, tmp_path):
    write_ledger(repo_dir, "- [ ] 1. open\n")
    env = {"LEDGER_GUARD_STOP_MODE": "every-turn"}
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path))
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path))


def test_stale_ledger_from_before_session_passes(repo_dir, tmp_path):
    # Ledger predates the session start (cache mtime) -> another session's
    # workflow; this session is not held on it.
    ledger = write_ledger(repo_dir, "- [ ] 1. open\n")
    cache = tmp_path / "fable-orch-model-test-session.json"
    cache.write_text(json.dumps({"profile": "fable"}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(ledger, (old, old))
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_ledger_touched_this_session_blocks(repo_dir, tmp_path):
    # Session started an hour ago; the ledger was written just now -> owned.
    ledger = write_ledger(repo_dir, "- [ ] 1. open\n")
    cache = tmp_path / "fable-orch-model-test-session.json"
    cache.write_text(json.dumps({"profile": "fable"}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(cache, (old, old))
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))


def test_ownership_survives_compact_reinjection(repo_dir, tmp_path):
    # The ledger was touched mid-session; then SessionStart re-fired on a
    # compact and REWROTE the cache (fresh file mtime). The immutable
    # `started` field must keep the ledger owned by this session.
    ledger = write_ledger(repo_dir, "- [ ] 1. open\n")
    mid = time.time() - 1800
    os.utime(ledger, (mid, mid))
    cache = tmp_path / "fable-orch-model-test-session.json"
    cache.write_text(
        json.dumps({"profile": "fable", "started": time.time() - 3600}),
        encoding="utf-8",
    )  # file mtime = now (post-compact rewrite); started = an hour ago
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))


def test_ledger_in_parent_blocks(repo_dir, tmp_path):
    write_ledger(repo_dir, "- [ ] 1. open\n")
    sub = repo_dir / "pkg" / "inner"
    sub.mkdir(parents=True)
    assert blocks(run_hook(SCRIPT, stop_payload(sub), tmpdir=tmp_path))


def test_upward_search_stops_at_repo_root(tmp_path):
    write_ledger(tmp_path, "- [ ] 1. outside\n")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert run_hook(SCRIPT, stop_payload(repo), tmpdir=tmp_path) is None


def test_upward_search_stops_at_worktree_boundary(tmp_path):
    # .git as a FILE (worktree/submodule) is a boundary too: the open
    # ledger above it must not block a stop inside the worktree.
    write_ledger(tmp_path, "- [ ] 1. outside\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
    assert run_hook(SCRIPT, stop_payload(worktree), tmpdir=tmp_path) is None


def test_upward_search_stops_at_home(tmp_path):
    # A ledger ABOVE $HOME belongs to nobody — never holds sessions below.
    write_ledger(tmp_path, "- [ ] 1. above home\n")
    home = tmp_path / "home"
    sub = home / "notes"
    sub.mkdir(parents=True)
    assert run_hook(
        SCRIPT, stop_payload(sub), env_extra={"HOME": str(home)}, tmpdir=tmp_path
    ) is None


def test_ledger_at_home_still_found(tmp_path):
    home = tmp_path / "home"
    (home / "docs").mkdir(parents=True)
    write_ledger(home, "- [ ] 1. home ledger\n")
    assert blocks(run_hook(
        SCRIPT, stop_payload(home / "docs"),
        env_extra={"HOME": str(home)}, tmpdir=tmp_path,
    ))


def test_malformed_input_passes():
    assert run_hook(SCRIPT, raw="{{{") is None


# --- teammate pane reaping (piggybacked on the Stop hook) -------------------

def _pane_env(tmp_path):
    from test_inject_and_cleanup import _swarm_fixture

    env, kill_log = _swarm_fixture(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    env["HOME"] = str(home)
    return env, kill_log, home


PANE_KEY = "claude-swarm-111:%1:12345"  # socket : pane id : pid


def _seed_pane_state(home, cpu=5.0, since_ago=7200, stale_marker=True, key=PANE_KEY):
    d = home / ".claude" / "fable-orch"
    d.mkdir(parents=True, exist_ok=True)
    state = d / "swarm-state.json"
    state.write_text(json.dumps(
        {"panes": {key: {"cpu": cpu, "since": time.time() - since_ago}}}),
        encoding="utf-8")
    if stale_marker:
        old = time.time() - 3600  # let the 30-min rate limit allow a sweep
        os.utime(state, (old, old))
    return state


def test_idle_teammate_pane_reaped(repo_dir, tmp_path):
    # CPU sample matches the previous one (0:05.00) and the baseline is 2h
    # old -> the pane is a finished teammate and gets killed.
    env, kill_log, home = _pane_env(tmp_path)
    _seed_pane_state(home)
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    assert kill_log.is_file()
    log = kill_log.read_text(encoding="utf-8")
    assert "pane" in log
    assert "-t %1" in log  # kill must target the PANE id, not the pid


def test_active_teammate_pane_survives(repo_dir, tmp_path):
    # 1 cpu-sec over 60s (~1.7%) is above the parked rate -> active
    # worker; re-baseline, no kill.
    env, kill_log, home = _pane_env(tmp_path)
    state = _seed_pane_state(home, cpu=4.0, since_ago=60)
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()
    rebaselined = json.loads(state.read_text(encoding="utf-8"))["panes"][PANE_KEY]
    assert rebaselined["cpu"] == 5.0  # fresh sample, idle clock restarted


def test_heartbeat_pane_still_reaped(repo_dir, tmp_path):
    # A PARKED teammate is not CPU-frozen — it polls its mailbox at
    # ~0.4%. 0.3 cpu-sec over 2h is far under the 1% rate: reaped.
    # (Equality-based idleness never fired on this, measured live.)
    env, kill_log, home = _pane_env(tmp_path)
    env["FAKE_PS_PANE"] = "12345 0:05.30 claude --agent-id w@session-t --agent-name w"
    _seed_pane_state(home, cpu=5.0)
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    assert kill_log.is_file()
    assert "-t %1" in kill_log.read_text(encoding="utf-8")


def test_default_server_pane_reaped(repo_dir, tmp_path):
    # Current Claude Code parks teammates in the USER'S default tmux
    # server — the sweep must scan it, and must kill only the pane.
    env, kill_log, home = _pane_env(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{os.getuid()}"
    (sock_dir / "default").write_text("", encoding="utf-8")
    _seed_pane_state(home, key="default:%1:12345")
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    log = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert "default -t %1" in log


def test_first_sighting_never_reaped(repo_dir, tmp_path):
    # No prior state: the sweep only takes a baseline, never kills.
    env, kill_log, home = _pane_env(tmp_path)
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()
    state = home / ".claude" / "fable-orch" / "swarm-state.json"
    assert json.loads(state.read_text(encoding="utf-8"))["panes"][PANE_KEY]["cpu"] == 5.0


def test_pane_sweep_rate_limited(repo_dir, tmp_path):
    # State file written moments ago -> the sweep is skipped entirely.
    env, kill_log, home = _pane_env(tmp_path)
    _seed_pane_state(home, stale_marker=False)
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_legacy_pid_keyed_state_never_kills(repo_dir, tmp_path):
    # Pre-0.10 state was keyed by bare pid — with pid reuse that hands a
    # NEW pane a stale idle baseline. Old keys must not match; the pane
    # is a first sighting and survives.
    env, kill_log, home = _pane_env(tmp_path)
    _seed_pane_state(home, key="12345")
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_wrapper_shell_pane_never_reaped(repo_dir, tmp_path):
    # Pane root is `sh -c '... claude --agent-id ...'`: the shell's CPU
    # clock is frozen while the child works — judging idleness by it
    # would kill a LIVE worker. Non-claude roots are never touched.
    env, kill_log, home = _pane_env(tmp_path)
    env["FAKE_PS_PANE"] = "12345 0:00.01 sh -c cd /repo && claude --agent-id w@session-t"
    _seed_pane_state(home, cpu=0.01)
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_real_ps_cputime_parses():
    # The fakes never exercise the REAL ps output shape; parse our own
    # process's cputime with the actual binary on this OS (macOS + Linux).
    import importlib.util
    import subprocess
    import sys
    from conftest import SCRIPTS

    spec = importlib.util.spec_from_file_location(
        "ledger_guard_stop_real", SCRIPTS / "ledger_guard_stop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = subprocess.run(["ps", "-o", "cputime=", "-p", str(os.getpid())],
                         capture_output=True, text=True, timeout=10).stdout.strip()
    assert out, "real ps returned nothing"
    assert mod._cpu_seconds(out) is not None


# --- hardening: corrupt sidecars, hostile stdin, ledger dialects ---

def test_wrong_typed_stop_sidecar_recovers(repo_dir, tmp_path):
    # {"blocked": [1]} used to TypeError past the decision print — the
    # guard must still block, exit 0, and rewrite a proper dict.
    write_ledger(repo_dir, "- [ ] 1. open\n")
    sidecar = tmp_path / "fable-orch-stop-test-session.json"
    sidecar.write_text(json.dumps({"blocked": [1]}), encoding="utf-8")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))
    assert isinstance(json.loads(sidecar.read_text())["blocked"], dict)
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_non_object_stdin_never_crashes():
    assert run_hook(SCRIPT, raw="[1, 2]") is None
    assert run_hook(SCRIPT, raw="42") is None


def test_fenced_checklist_is_not_an_open_item(repo_dir, tmp_path):
    write_ledger(repo_dir,
                 "- [x] 1. done\n```\n- [ ] example inside a code fence\n```\n")
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_open_item_outside_fence_still_blocks(repo_dir, tmp_path):
    write_ledger(repo_dir,
                 "```\n- [ ] fenced example\n```\n- [ ] 1. real open item\n")
    result = run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path)
    assert blocks(result)
    assert "1 open item(s)" in result["reason"]


def test_crlf_ledger_blocks(repo_dir, tmp_path):
    (repo_dir / ".workflow").mkdir(exist_ok=True)
    (repo_dir / ".workflow" / "LEDGER.md").write_bytes(b"- [ ] 1. open\r\n")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))


def test_indented_checkbox_blocks(repo_dir, tmp_path):
    write_ledger(repo_dir, "  - [ ] 1. nested open item\n")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))


def test_plus_bullet_is_out_of_dialect(repo_dir, tmp_path):
    # Documented scope: '- [ ]' and '* [ ]' count; '+ [ ]' does not.
    write_ledger(repo_dir, "+ [ ] 1. plus bullet\n")
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_future_started_still_owns(repo_dir, tmp_path):
    # A marker `started` in the future (clock jump) must clamp to now —
    # not silently disown every ledger for the whole session.
    write_ledger(repo_dir, "- [ ] 1. open\n")
    cache = tmp_path / "fable-orch-model-test-session.json"
    cache.write_text(json.dumps({"started": time.time() + 3600}), encoding="utf-8")
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))


def _load_script(name):
    import importlib.util
    from conftest import SCRIPTS

    spec = importlib.util.spec_from_file_location(f"_probe_{name}", SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeClock:
    """A monotonic clock that only advances, and a wall clock that can
    jump backwards under it — the shape an NTP correction produces."""

    def __init__(self):
        self.mono = 1000.0
        self.wall = 1_700_000_000.0

    def monotonic(self):
        return self.mono

    def time(self):
        return self.wall

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


def test_teammate_detection_terminates_when_the_wall_clock_jumps_back():
    # Behavioural proof, not a source check: a wall-clock deadline stops
    # expiring the moment the clock steps backwards, so the 12-hop walk
    # runs to completion — inside a hook that has not emitted its
    # decision yet. Each faked `ps` costs a simulated second and the
    # wall clock rewinds a day on the first one.
    mod = _load_script("ledger_guard_stop.py")
    clock = _FakeClock()
    calls = []

    class _Result:
        stdout = "99999 some-unrelated-process\n"

    def fake_run(*args, **kwargs):
        calls.append(kwargs.get("timeout"))
        clock.advance(1.0)
        if len(calls) == 1:
            clock.wall -= 86400.0          # NTP steps the wall clock back
        return _Result()

    real_time, real_run = mod.time, mod.subprocess.run
    try:
        mod.time, mod.subprocess.run = clock, fake_run
        assert mod._is_teammate_session() is False
    finally:
        mod.time, mod.subprocess.run = real_time, real_run

    # TEAMMATE_DETECT_BUDGET is 1.5s and each hop costs 1s, so a
    # monotonic deadline stops the walk after 2 calls. A wall-clock one
    # would never expire and burn all 12 hops.
    assert len(calls) <= 3, f"walk was not capped: {len(calls)} ps calls"
    assert all(t is None or t <= 5.0 for t in calls), calls


def test_every_deadline_is_built_from_the_monotonic_clock():
    # Structural companion: catches a wall clock reaching a deadline
    # through a variable (`now = time.time(); deadline = now + BUDGET`),
    # which is exactly the shape the original bug had and which no
    # single-line text scan can see.
    import ast
    from conftest import SCRIPTS

    def clock_of(node):
        """'monotonic' / 'time' / None for the clock a subtree reads."""
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "time"):
                return sub.func.attr
        return None

    def clocks_read_in(node):
        return {sub.func.attr for sub in ast.walk(node)
                if isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and isinstance(sub.func.value, ast.Name)
                and sub.func.value.id == "time"}

    for name in ("ledger_guard_stop.py", "cleanup_session_cache.py"):
        tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
        # _budget subtracts *from* a monotonic deadline, so it must read
        # the same clock. Reading the wall clock there does not merely
        # fail to bound — it collapses every budget to the 0.2s floor
        # and starves healthy subprocess calls.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_budget":
                assert clocks_read_in(node) == {"monotonic"}, (
                    f"{name}:{node.lineno} _budget reads "
                    f"{clocks_read_in(node)}, must read only monotonic")
        # Every local name that was assigned straight from a clock call.
        # Both plain and annotated assignments count: `deadline: float =
        # time.time() + N` is the same bug wearing a type hint.
        def bindings(t):
            for node in ast.walk(t):
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    tgt = node.targets[0]
                    if isinstance(tgt, ast.Name):
                        yield node, tgt.id, node.value
                    elif isinstance(tgt, (ast.Tuple, ast.List)) \
                            and isinstance(node.value, (ast.Tuple, ast.List)) \
                            and len(tgt.elts) == len(node.value.elts):
                        # `a, deadline = 0, time.time() + B` — pair them up.
                        for name_node, val in zip(tgt.elts, node.value.elts):
                            if isinstance(name_node, ast.Name):
                                yield node, name_node.id, val
                elif isinstance(node, ast.AnnAssign) \
                        and isinstance(node.target, ast.Name) \
                        and node.value is not None:
                    yield node, node.target.id, node.value
                elif isinstance(node, ast.NamedExpr) \
                        and isinstance(node.target, ast.Name):
                    # `if (deadline := time.time() + B) ...`
                    yield node, node.target.id, node.value

        from_clock = {}
        for _node, target, value in bindings(tree):
            src = clock_of(value)
            if src:
                from_clock[target] = src
        for node, target, value in bindings(tree):
            if "deadline" not in target.lower():
                continue
            # A `deadline = None` sentinel disables budgeting on purpose;
            # only arithmetic on a clock is under review here.
            if isinstance(value, ast.Constant) and value.value is None:
                continue
            direct = clock_of(value)
            if direct is None:  # built from a variable — follow it one hop
                names = {n.id for n in ast.walk(value)
                         if isinstance(n, ast.Name)}
                sources = {from_clock[n] for n in names if n in from_clock}
                assert sources and sources <= {"monotonic"}, (
                    f"{name}:{node.lineno} deadline built from a wall clock "
                    f"via {names & set(from_clock)}")
            else:
                assert direct == "monotonic", (
                    f"{name}:{node.lineno} deadline built from time.{direct}()")

    # Functional floor: an already-expired deadline yields the floor,
    # never a large budget.
    for name in ("ledger_guard_stop.py", "cleanup_session_cache.py"):
        mod = _load_script(name)
        assert mod._budget(time.monotonic() - 5.0) == 0.2, name
        assert mod._budget(None) == 5.0, name


def test_slow_ps_cannot_swallow_the_decision(repo_dir, tmp_path):
    # Teammate detection runs BEFORE the guard prints anything, so its
    # cost is charged against the 10s hook timeout with nothing emitted
    # yet. A `ps` that is slow but ANSWERS is the dangerous shape: each
    # hop succeeds, so the per-call timeout never trips and the walk
    # runs all 12 hops. At 1s a hop that is 12s — the hook is killed
    # with no decision at all. The detection budget caps the whole walk.
    write_ledger(repo_dir, "- [ ] 1. open\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps = bin_dir / "ps"
    # Answers every time (never a claude ancestor, so the walk continues)
    # but takes a second per hop.
    ps.write_text("#!/bin/sh\nsleep 1\necho '99999 some-unrelated-process'\n",
                  encoding="utf-8")
    os.chmod(ps, 0o755)
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    started = time.time()
    result = run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path)
    elapsed = time.time() - started
    assert blocks(result), "decision must still be emitted"
    assert elapsed < 5, f"took {elapsed:.1f}s — the 12-hop walk was not capped"


def test_per_task_ledger_name_holds_the_close(repo_dir, tmp_path):
    # The close guard must see per-task ledger names too, or every
    # session that names its ledger LEDGER-<topic>.md closes unchecked.
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER-tiktok-sdk-e2e.md").write_text(
        "- [ ] 1. open\n", encoding="utf-8")
    result = run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path)
    assert blocks(result)
    assert "LEDGER-tiktok-sdk-e2e.md" in result["reason"]


def test_unreadable_ledger_does_not_mask_a_live_sibling(repo_dir, tmp_path):
    # A newer but unreadable file would win the mtime race, then fail to
    # open — and the guard would return silently, hiding the live ledger
    # whose open items should have held the close.
    import pytest

    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    live = d / "LEDGER.md"
    live.write_text("- [ ] 1. live work\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(live, (old, old))
    locked = d / "LEDGER-locked.md"
    locked.write_text("- [ ] 1. unreadable\n", encoding="utf-8")
    os.chmod(locked, 0o000)
    try:
        result = run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path)
        assert blocks(result), "the live ledger must still hold the close"
        assert "LEDGER.md" in result["reason"]
    finally:
        os.chmod(locked, 0o644)


def test_archived_ledger_stays_silent(repo_dir, tmp_path):
    # The block message tells the model to archive a ledger to silence
    # it for good; that promise must hold.
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER-done-work-archive.md").write_text(
        "- [ ] 1. never finished\n", encoding="utf-8")
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None


def test_teammate_close_is_never_held(repo_dir, tmp_path):
    # The ledger belongs to the chair. Holding a teammate's close on it
    # costs the teammate a turn and can eat the report it was about to
    # deliver — observed in the wild. Fake ps puts an --agent-id claude
    # in the ancestor chain.
    write_ledger(repo_dir, "- [ ] 1. open\n")
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
    assert run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path) is None
    # The escape hatch restores the old behaviour.
    env["FABLE_ORCH_TEAMMATE_STOP"] = "1"
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path))


def test_chair_close_still_held_when_ancestors_are_not_agents(repo_dir, tmp_path):
    # Same fake ps, but the ancestor carries no --agent-id: this is the
    # chair, and its open ledger must still hold the close.
    write_ledger(repo_dir, "- [ ] 1. open\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env python3\nprint('1 claude')\n", encoding="utf-8")
    os.chmod(ps, 0o755)
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), env_extra=env, tmpdir=tmp_path))


def test_symlinked_cwd_finds_the_real_ledger(tmp_path):
    # The spawn guard resolves symlinks (realpath); the stop guard must
    # too, or the two disagree about whether the session has a ledger and
    # an open ledger reached through a symlinked cwd never holds a close.
    real = tmp_path / "real"
    (real / ".git").mkdir(parents=True)
    (real / "sub").mkdir()
    write_ledger(real, "- [ ] 1. open\n")
    link = tmp_path / "link"
    os.symlink(real / "sub", link)
    assert blocks(run_hook(SCRIPT, stop_payload(link), tmpdir=tmp_path))


def test_marker_touch_does_not_disown_a_started_less_marker(repo_dir, tmp_path):
    # The warmth touch must land AFTER the ownership check. A marker with
    # no `started` (legacy or corrupt) falls back to its own mtime; if the
    # touch ran first it would reset that to "now" and silently disown
    # every ledger the session had already worked on.
    ledger = write_ledger(repo_dir, "- [ ] 1. open\n")
    cache = tmp_path / "fable-orch-model-test-session.json"
    cache.write_text(json.dumps({"model": "fable"}), encoding="utf-8")
    started = time.time() - 3600          # session began an hour ago
    os.utime(cache, (started, started))
    mid = time.time() - 1800              # ledger touched mid-session
    os.utime(ledger, (mid, mid))
    assert blocks(run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path))
    assert os.path.getmtime(cache) > time.time() - 300  # still warmed


def test_stop_warms_every_session_sidecar(repo_dir, tmp_path):
    # Warming only the marker let the 96h sweep reap the stop and tasks
    # sidecars — resetting the task counter and re-blocking a ledger that
    # had already had its one reminder.
    old = time.time() - 7200
    paths = []
    for name, body in (("fable-orch-model-test-session.json", '{"started": 1.0}'),
                       ("fable-orch-stop-test-session.json", '{"blocked": {}}'),
                       ("fable-orch-tasks-test-session.json", '{"count": 2}')):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        os.utime(p, (old, old))
        paths.append(p)
    run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path)
    for p in paths:
        assert os.path.getmtime(p) > time.time() - 300, p.name


def test_stop_touches_the_session_marker(repo_dir, tmp_path):
    # Every Stop refreshes the marker's mtime so the 96h temp sweep can
    # never eat a LIVE session's files; `started` content is untouched.
    cache = tmp_path / "fable-orch-model-test-session.json"
    cache.write_text(json.dumps({"started": 123.0}), encoding="utf-8")
    old = time.time() - 7200
    os.utime(cache, (old, old))
    assert run_hook(SCRIPT, stop_payload(repo_dir), tmpdir=tmp_path) is None
    assert os.path.getmtime(cache) > time.time() - 300
    assert json.loads(cache.read_text())["started"] == 123.0
