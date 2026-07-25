import functools
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"

# Env vars that would leak the host's configuration into the tests.
STRIP_ENV = [
    "LEDGER_GUARD_THRESHOLD",
    "LEDGER_GUARD_TASKS",
    "LEDGER_GUARD_STOP_MODE",
    "FABLE_ORCH_METRICS",
    "FABLE_ORCH_SWARM_CLEANUP",
    "FABLE_ORCH_SWARM_MAX_IDLE_H",
    "FABLE_ORCH_TEAMMATE_IDLE_H",
    "FABLE_ORCH_TEAMMATE_IDLE_RATE",
    "FABLE_ORCH_PROFILE",
    "FABLE_ORCH_TEAMMATE_STOP",
    "FABLE_ORCH_TEAMMATE_INJECT",
    "CLAUDE_CONFIG_DIR",
    "TMUX_TMPDIR",
    "CLAUDE_PLUGIN_ROOT",
]


@functools.lru_cache(maxsize=1)
def _chair_ps_dir():
    """A PATH shim that pins the ancestor walk to an untagged `claude`.

    The hooks answer "am I a teammate?" by walking the REAL process
    tree for `--agent-id`. That makes the suite's result depend on WHO
    RAN IT: from inside a named agent-teams worker — a teammate running
    the tests, or a fresh-eyes verifier checking a release — every hook
    correctly decides "teammate", skips its chair behaviour, and ~40
    tests fail for a reason that has nothing to do with the code under
    test. Pinning the ambient here is the same move as the
    CLAUDE_CONFIG_DIR and FABLE_ORCH_SWARM_CLEANUP defaults below: the
    sandbox states its own world instead of inheriting the developer's.

    Only the ancestor-walk invocation is answered; every other `ps`
    call falls through to the real binary, and any test that exercises
    the detection supplies its own `ps` via env_extra["PATH"] and never
    reaches this shim.
    """
    bin_dir = Path(tempfile.mkdtemp(prefix="fable-orch-testshim-"))
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "if 'ppid=,command=' in sys.argv:\n"
        "    print('1 claude')\n"
        "    sys.exit(0)\n"
        "os.execv('/bin/ps', ['ps'] + sys.argv[1:])\n",
        encoding="utf-8",
    )
    os.chmod(ps, 0o755)
    return str(bin_dir)


def run_hook(script, payload=None, raw=None, env_extra=None, tmpdir=None):
    """Run a hook script as a subprocess, exactly as Claude Code would.

    Returns the parsed JSON it printed, or None for empty output.
    `tmpdir` redirects tempfile.gettempdir() inside the subprocess so
    session-cache reads/writes stay inside the test sandbox.
    """
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env["FABLE_ORCH_METRICS"] = "0"        # keep tests from writing ~/.claude metrics
    env["FABLE_ORCH_SWARM_CLEANUP"] = "0"  # keep tests away from real tmux servers
    # Point Claude Code config at an (empty) sandbox dir so the injector's
    # settings.json model-detection never reads the developer's real
    # default. A test that wants the settings fallback writes
    # <tmpdir>/cfg/settings.json; others get no model key -> no leak.
    env["CLAUDE_CONFIG_DIR"] = str(Path(tmpdir) / "cfg") if tmpdir else "/nonexistent-fable-orch-cfg"
    if tmpdir is not None:
        env["TMPDIR"] = str(tmpdir)
        env["TEMP"] = str(tmpdir)
        env["TMP"] = str(tmpdir)
    if env_extra:
        env.update(env_extra)
    # Ambient "this is a chair" — unless the test drives `ps` itself.
    if not (env_extra or {}).get("PATH"):
        env["PATH"] = _chair_ps_dir() + os.pathsep + env.get("PATH", "")
    # Insurance: a test that turns the swarm cleanup ON without pointing
    # tmux at a sandbox would sweep the developer's REAL tmux servers.
    assert env.get("FABLE_ORCH_SWARM_CLEANUP") != "1" or "TMUX_TMPDIR" in env, \
        "FABLE_ORCH_SWARM_CLEANUP=1 requires a sandboxed TMUX_TMPDIR"
    stdin = raw if raw is not None else json.dumps(payload or {})
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    return json.loads(out) if out else None


@pytest.fixture
def repo_dir(tmp_path):
    """A fake repo root: the upward ledger search stops at .git."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def write_ledger(root, body="- [ ] 1. item\n"):
    d = root / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER.md").write_text(body, encoding="utf-8")
    return d / "LEDGER.md"
