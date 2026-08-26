"""One definition per helper — the pin that keeps the copies from coming back.

`_metric` lived in five hook scripts, `_tmp_json` in three, `_budget` in six,
and by the time anyone looked the copies had already drifted: `_budget`
floored at 0.2s in three files and 0.1s in two, so the same call had two
different minimum timeouts depending on which hook made it. Hoisting them
fixes today; this file is what stops the next hook from pasting them back.
"""
import ast
import importlib.util
import re

from conftest import SCRIPTS

SHARED = {"tmp_json", "metric", "budget", "cpu_seconds", "is_claude_exe",
          "is_teammate_session"}
HOOK_SCRIPTS = ("agent_watchdog.py", "cleanup_session_cache.py",
                "inject_instructions.py", "ledger_guard_spawn.py",
                "ledger_guard_stop.py", "remind_reply_shape.py")
# The hooks that run subprocesses of their own, and so import the
# budget. Pinned as a SET, not discovered: the drift this file exists
# to end lived in the two that dropped out of the list, and a check
# that skips whatever it fails to find would have skipped them.
BUDGET_USERS = {"agent_watchdog.py", "cleanup_session_cache.py",
                "ledger_guard_stop.py"}
# `timeout=` on a call, with anything other than the shared budget
# behind it. `--timeout` flags and `args.timeout` reads are not calls.
HAND_TIMEOUT_RE = re.compile(r"(?<![-\w])timeout\s*=\s*(?!_?budget\()[^\n]*")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_probe_{name}", SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _top_level_defs(name):
    tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_the_shared_module_defines_every_hoisted_helper():
    assert _top_level_defs("_shared.py") >= SHARED


def test_no_script_redefines_a_shared_helper():
    # The underscore-prefixed names are what the call sites use, via an
    # aliased import. A script that defines one again has forked the
    # behaviour, silently: nothing else in the suite would notice.
    for name in HOOK_SCRIPTS:
        clashes = {d for d in _top_level_defs(name)
                   if d.lstrip("_") in SHARED or d in SHARED}
        assert not clashes, f"{name} redefines {clashes} instead of importing it"


def test_every_hook_script_can_be_imported_by_path():
    # Hooks are launched as `python3 "$ROOT/scripts/<hook>.py"`, where the
    # scripts directory lands on sys.path by itself — but a test, a REPL,
    # or any tool that loads one BY PATH gets no such favour, and the
    # `import _shared` line fails with ModuleNotFoundError. Each script
    # puts its own directory on the path first; this proves it.
    for name in HOOK_SCRIPTS:
        assert _load(name) is not None


def test_the_budget_floor_is_one_number_everywhere():
    # The drift that started this: an expired deadline must yield the same
    # floor no matter which hook asked.
    #
    # Comparing the floors the importing hooks report cannot catch that
    # drift on its own — they all bind the SAME function object, so the
    # set is one element by construction, and the two hooks that
    # actually carried the 0.1s floor no longer expose `_budget` at all
    # and were skipped. What can drift is a hook growing a second
    # source of truth: a local `_budget`, or a subprocess call whose
    # timeout is not the shared budget. Both are checked here, on every
    # hook, whether or not it imports one today.
    import time

    shared = _load("_shared.py")
    expired = time.monotonic() - 5.0
    floors = {}
    for name in HOOK_SCRIPTS:
        fn = getattr(_load(name), "_budget", None)
        if fn is None:
            continue          # not every hook runs subprocesses
        # It has to BE the shared one, not merely agree with it today.
        # (Identity is no good here: _load re-executes _shared, so the
        # probe's copy is a different object from the one the hooks
        # imported. Where the function was DEFINED is the real test.)
        assert fn.__module__ == "_shared", f"{name} has a budget of its own again"
        floors[name] = fn(expired)
    assert set(floors) == BUDGET_USERS, (
        f"the hooks running subprocesses changed: {sorted(floors)}")
    assert set(floors.values()) == {shared.BUDGET_FLOOR_S}, floors

    # And nothing may time a subprocess by hand. `timeout=4` in one hook
    # is exactly how 0.1 and 0.2 came to mean the same thing in two.
    for name in HOOK_SCRIPTS + ("_shared.py",):
        src = (SCRIPTS / name).read_text(encoding="utf-8")
        hand_rolled = [m.group(0) for m in HAND_TIMEOUT_RE.finditer(src)]
        assert not hand_rolled, f"{name} times a call outside the budget: {hand_rolled}"


def test_metrics_stay_off_when_the_switch_is_off(tmp_path, monkeypatch):
    # Every hook writes through this one function now, so the kill switch
    # is also one behaviour rather than five.
    shared = _load("_shared.py")
    monkeypatch.setenv("FABLE_ORCH_METRICS", "0")
    monkeypatch.setenv("HOME", str(tmp_path))
    shared.metric("test_event", "sess", extra=1)
    assert not (tmp_path / ".claude" / "fable-orch").exists()


def _run_alone(script_path, tmp_path, payload="{}"):
    """Run one hook in a directory where `_shared` cannot be imported."""
    import os
    import subprocess
    import sys as _sys

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["FABLE_ORCH_METRICS"] = "0"
    return subprocess.run(
        [_sys.executable, str(script_path)],
        input=payload, capture_output=True, text=True,
        env=env, cwd=str(tmp_path), timeout=30,
    )


def test_a_broken_shared_module_never_breaks_a_turn(tmp_path):
    # `_shared.py` is new in this version, and the six hooks import it at
    # MODULE scope — above every `try: main() except: pass` guard they
    # have. A partial manual install, a half-copied plugin directory or an
    # unreadable sibling therefore turned a silent no-op into a traceback
    # on EVERY turn, including the two UserPromptSubmit hooks that run on
    # every single prompt. That is the one failure mode the rest of this
    # codebase is built to avoid: a reporting hook must never break a turn.
    #
    # Both halves of "missing or unreadable" are exercised, because they
    # raise different exceptions — ModuleNotFoundError and SyntaxError —
    # and an `except ImportError` would only have caught the first.
    for flavour in ("missing", "broken"):
        for name in HOOK_SCRIPTS:
            sandbox = tmp_path / flavour / name[:-3]
            sandbox.mkdir(parents=True)
            (sandbox / name).write_text(
                (SCRIPTS / name).read_text(encoding="utf-8"), encoding="utf-8")
            if flavour == "broken":
                (sandbox / "_shared.py").write_text(
                    "def metric(  # unterminated\n", encoding="utf-8")
            proc = _run_alone(sandbox / name, sandbox)
            where = f"{name} with a {flavour} _shared"
            assert proc.returncode == 0, f"{where} exited {proc.returncode}"
            assert "Traceback" not in proc.stderr, f"{where}: {proc.stderr}"
            assert proc.stderr.strip() == "", f"{where}: {proc.stderr}"
            # Silence on stdout is what "does not deny, does not block"
            # looks like from the harness's side: no decision emitted.
            assert proc.stdout.strip() == "", f"{where}: {proc.stdout}"


def test_every_hook_guards_its_shared_import_the_same_way():
    # One pattern in six files, not six variations — the same reason this
    # module exists at all. Pinned on the source so a seventh hook, or a
    # rewrite of one of these, cannot quietly reintroduce a bare import.
    handlers = {}
    for name in HOOK_SCRIPTS:
        tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.ImportFrom) and n.module == "_shared"]
        assert not bare, f"{name} imports _shared unguarded at module scope"
        guards = [n for n in tree.body
                  if isinstance(n, ast.Try)
                  and any(isinstance(s, ast.ImportFrom) and s.module == "_shared"
                          for s in n.body)]
        assert len(guards) == 1, f"{name} has {len(guards)} _shared import guards"
        (handler,) = guards[0].handlers
        assert isinstance(handler.type, ast.Name) and handler.type.id == "Exception", \
            f"{name} narrows the guard; a broken _shared raises SyntaxError too"
        handlers[name] = [ast.unparse(s) for s in handler.body]
    assert len({tuple(v) for v in handlers.values()}) == 1, handlers
    assert set(handlers.values().__iter__().__next__()) == {"sys.exit(0)"}
