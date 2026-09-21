# Fable Orchestrator

[![CI](https://github.com/Rylaa/fable5-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/Rylaa/fable5-orchestrator/actions/workflows/ci.yml)

**Run Claude Fable 5 all day — without watching the usage meter.**

Fable 5 is the best chair a Claude Code session can have, and the most expensive seat in the house. Let it type every token itself and the session ends rate-limited, waiting out the reset window.

This plugin makes the split mechanical. **Fable 5 keeps the chair** and spends tokens on planning, arbitration and final decisions. Everything else goes to named workers: the volume — implementation, research, briefs, review, bulk reading — to **Sonnet 5**, and the predictably hard slices — architecture, irreversible migrations, security review — straight to **Opus 5**, which doubles as the escalation lane. The chair sizes each worker's reasoning effort to the job, `low` for mechanical sweeps, `max` for architecture and security.

**No ledger, no interview, no mandatory verification phase.** Earlier versions gated the act of delegating with a requirements file and a clarification loop. Both are gone. What is left is one rule with teeth: delegation is the default, and a hook notices when the chair quietly does the work itself.

## The division of labor

```
                        ┌─────────────────────────────────┐
                        │         FABLE 5 — chair         │
                        │    plan · arbitrate · decide    │
                        │  sizes tier + effort per task   │
                        └────────────────┬────────────────┘
                                         │
                    specs down           │           briefs up
                                         │
           ┌────────────────────────┬────┴───────────────────┬────────────────────────┐
           ▼                        ▼                        ▼                        ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ SONNET 5 · low–med  │  │ SONNET 5 · med–high │  │ SONNET 5 · med–high │  │  OPUS 5 · high–max  │
│   mechanical bulk   │  │   implementation    │  │   routine judgment  │  │  hard work · direct │
│   grep·fetch·scan   │  │   code · tests      │  │   briefs · review   │  │  architecture       │
│   format · read     │  │   debug · refactor  │  │   filtering         │  │  migrations·security│
└─────────────────────┘  └─────────────────────┘  └──────────┬──────────┘  └──────────┬──────────┘
                                                             │ uncertain /            │ beyond
                                                             │ high stakes            │ opus
                                                          ┌──▼────────────────────────▼──┐
                                                          │   escalation · one way only  │
                                                          │   OPUS 5 → FABLE 5 → stop    │
                                                          └──────────────────────────────┘
```

Your Fable limit pays for the thinking and almost nothing else:

```
┌─────────────────────────────────────────┬─────────────────┬─────────────────────┐
│ Work                                    │ Runs on         │ Fable limit pays    │
├─────────────────────────────────────────┼─────────────────┼─────────────────────┤
│ Planning, arbitration, decisions         │ Fable 5 (chair) │ yes                 │
│ Implementation, tests, refactors         │ Sonnet 5        │ nothing             │
│ Source briefs, filtering, code review    │ Sonnet 5        │ nothing             │
│ Bulk gathering (fetch, grep, scan)       │ Sonnet 5 (low)  │ nothing             │
│ Hard slices: architecture, migrations    │ Opus 5 (direct) │ nothing             │
│ Security / adversarial review            │ Opus 5 (max)    │ nothing             │
│ Escalations (sonnet "uncertain")         │ Opus → Fable    │ mostly nothing      │
└─────────────────────────────────────────┴─────────────────┴─────────────────────┘
```

## Why this trio

- **Fable tokens are the heaviest draw on your limit.** Every token of bulk work kept off the chair extends how long Fable stays in it.
- **Sonnet 5 carries the volume.** Near-Opus quality on coding and agentic work, with the full effort ladder (`low` → `max`) — and the chair dials that ladder per task.
- **Opus 5 takes the hard slices directly.** Architecture tradeoffs, irreversible migrations, complex multi-system implementation and all security review are assigned straight to Opus, with no failed Sonnet pass required.
- **Escalation is one-way.** Sonnet returns "uncertain" and it goes to Opus, never back to the chair. If a tier declines a task it is re-run **unchanged** on another tier, never reworded to slip past a classifier. If that tier declines too, the chair stops and tells you.

## What the plugin does

### 1 · The Fable profile — a slim core plus a playbook

Every chair session starts with a ~3.3k-char core profile: the default (delegate), the disk hand-off, spawn discipline, routing and effort. The detail lives in the `orchestrator:playbook` skill, which the core requires **before the first delegation** — the research pipeline, the worker report contract, spawn economics, the fork cap, teammate lifecycle. Sessions that never delegate never pay for it.

Three rules keep worker output from undoing the saving:

- Reports are capped at 40 lines. Verbatim over ten lines goes to `./.workflow/scratch/` and the report carries the path. A violating report is re-run, not accepted.
- Research is one worker per source: fetch verbatim to disk first, then brief from that copy. One synthesizer reads across the briefs.
- Similar mechanical work is batched. Five greps are one agent with a checklist, not five agents.

**Teammates never get the profile.** Named workers are full sessions and fire SessionStart too, but the profile is written for the chair alone: delivered to a worker it says "you are the orchestrator" and invites it to spawn workers of its own, inverting the discipline (measured: 172 of 270 injected sessions were teammates). The injector walks the process tree for `--agent-id` and skips them, while still writing the session marker so the other hooks keep working.

**Two chairs.** Fable is primary; when its limit runs dry and you move the chair to Opus, the OPUS profile keeps the same discipline with the fable tier resting. A mid-session switch on a `resume` gets a short delta note instead of the whole core.

### 2 · The solo guard — the gate that watches the chair

This is the part with teeth, and it is new in v0.16.0.

Every earlier version gated **delegation**: spawn prompts over a length threshold, the third tracker task, the close with open ledger items. A chair that never delegated never met a gate at all — measured in the wild, five consecutive sessions received the profile in full and spawned zero workers while hand-editing dozens of files.

So the gate now watches the other side:

```
┌──────────────────────────────┬───────────────────────────────────────────────┐
│ Tool                         │ What the hook does                            │
├──────────────────────────────┼───────────────────────────────────────────────┤
│ Agent · Task                 │ records a spawn, always allows                │
│ Edit · Write · MultiEdit ·   │ counts; the 3rd in a session that has spawned │
│ NotebookEdit                 │ nothing draws ONE deny, then stays quiet      │
└──────────────────────────────┴───────────────────────────────────────────────┘
```

It is a nudge, not a wall. Two edits pass free, the deny fires **once per session**, and the message tells the chair how to proceed if it really was a single-sitting fix. One spawned worker disarms it for the rest of the session — a chair that is orchestrating can make its own small edits.

**Exempt:** teammates (a worker's job *is* to edit files), and any session that has already spawned a worker. A **fork** does not count as delegating: it clones the chair's own context at the chair's own model, so forking a plan's phases is disguised solo work.

**Not covered on purpose:** `Bash` heredocs and `sed -i`. Gating Bash would mean parsing shell to tell `cat > file` from `cat file`, and a guard that misreads a read as a write is worse than one with a known hole.

### 3 · The per-prompt reminder

The core profile arrives once, at SessionStart, and then competes with everything that comes after it. A ~35-token line rides every prompt instead:

```
[orchestrator] You are the CHAIR. Delegate by default: name the workers,
spec them, spawn independent ones in one message. Solo only for a
single-sitting fix the user asked for directly.
```

It restates the default and nothing else — routing, effort and the report contract stay in the core and the playbook, where they are read once. Teammates are skipped.

## Watching the team live

Teammates are real `claude` processes in tmux panes — you can watch every agent think, call tools, and type in real time. Claude Code opens the panes inside **your own default tmux server**: if you launched `claude` from inside tmux, the team appears as extra panes right in your window (`prefix q` jumps between panes, `prefix z` zooms one to full screen, `prefix w` shows a session/window tree).

Launch `claude` **outside** tmux and the panes go to a separate detached session instead, which you have to `tmux attach` to see. If you want the team in the window you are already looking at, start tmux first:

```
tmux new-session -s claude
claude
```

```
# who is on the field, by name
ps -axo pid=,command= | grep -- --agent-id

# every pane, mapped: session, pane id, pid, what it runs
tmux list-panes -a -F '#{session_name} #{pane_id} #{pane_pid} #{pane_current_command}'
```

Watch, don't type: a teammate's pane is its working terminal, and stray input interferes with it — talk to agents through the lead session instead. The reaper keeps this view honest: dismissed and idle teammates disappear instead of stacking up.

## Install

```
/plugin marketplace add Rylaa/fable5-orchestrator
/plugin install orchestrator@fable-orchestrator
```

Restart Claude Code afterwards — **a plugin's hooks are registered when the CLI process starts**, so a session already running (including one you `/clear`) keeps the hook set it booted with and will not see the plugin.

Requires `python3` on PATH; macOS and Linux only — the hooks shell out to `tmux` for teammate reaping, and Windows is not supported. No configuration needed.

### Manual install (without the plugin system)

1. Copy `scripts/inject_instructions.py`, `scripts/solo_guard.py`, `scripts/remind_chair.py`, `scripts/cleanup_session_cache.py` and `scripts/_shared.py` (every hook imports it) to `~/.claude/hooks/`.
2. Merge this into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/inject_instructions.py", "timeout": 10 } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/remind_chair.py", "timeout": 10 } ] }
    ],
    "PreToolUse": [
      {
        "matcher": "^(Agent|Task|Edit|Write|MultiEdit|NotebookEdit)$",
        "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/solo_guard.py", "timeout": 10 } ]
      }
    ],
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/cleanup_session_cache.py", "timeout": 20 } ] }
    ]
  }
}
```

3. Append `instructions/dynamic-workflow-fable.md` to `~/.claude/CLAUDE.md`, and copy the playbook to `~/.claude/skills/playbook/SKILL.md`. Note the name mismatch: the core asks for `orchestrator:playbook`, which only resolves when the plugin is installed. Copied by hand it is plain `playbook`.

> Don't run the plugin **and** the manual install side by side — you'd get every hook twice.

## Configuration

Set these in `~/.claude/settings.json` under `"env"`.

```
┌───────────────────────────────┬────────────────────┬────────────────────────────────────────────┐
│ Env var                       │ Default            │ Meaning                                    │
├───────────────────────────────┼────────────────────┼────────────────────────────────────────────┤
│ FABLE_ORCH_SOLO_EDITS         │ 3                  │ deny at the Nth chair edit; 0 disables     │
│ FABLE_ORCH_SOLO_GUARD         │ (on)               │ 0 disables the solo gate entirely          │
│ FABLE_ORCH_REMIND             │ (on)               │ 0 disables the per-prompt line             │
│ FABLE_ORCH_PROFILE            │ auto               │ pin the chair profile: auto | fable | opus │
│ FABLE_ORCH_TEAMMATE_INJECT    │ (off)              │ 1 injects the profile into teammates too   │
│ FABLE_ORCH_METRICS            │ (on)               │ 0 disables local metrics logging           │
│ FABLE_ORCH_SWARM_CLEANUP      │ (on)               │ 0 disables all teammate reaping            │
│ FABLE_ORCH_SWARM_MAX_IDLE_H   │ 48                 │ sweep swarms idle ≥ N hours; 0 disables    │
│ FABLE_ORCH_TEAMMATE_IDLE_H    │ 1                  │ kill teammate panes idle ≥ N hours; 0 off  │
│ FABLE_ORCH_TEAMMATE_IDLE_RATE │ 0.01               │ cpu-sec/sec under which a pane is idle     │
└───────────────────────────────┴────────────────────┴────────────────────────────────────────────┘
```

**Metrics.** Every hook appends one event line to `~/.claude/fable-orch/metrics.jsonl` — events only, never prompt content: injections per profile, mid-session switches, solo denies and suppressions, reaps. `python3 scripts/stats.py` prints the summary. Disable with `FABLE_ORCH_METRICS=0`.

**The session marker.** The injector writes a per-session temp file whose `started` timestamp survives resume/clear/compact. `SessionEnd` removes the session's temp files and sweeps anything older than 96 hours.

## Upgrading from v0.15.x

The ledger is gone, and so are the three gates that enforced it. Nothing breaks: an existing `./.workflow/LEDGER.md` is simply ignored, and the directory is still where scratch material goes. If you liked the ledger, keep writing one — the chair just won't be asked for it.

What is new that you will notice: a line on every prompt, and a one-time deny if the chair edits three files without delegating. Set `FABLE_ORCH_SOLO_EDITS=0` and `FABLE_ORCH_REMIND=0` to run the profile with no enforcement at all.

## Tests

```
python3 -m pytest tests/ -q
```

The hooks are plain stdin/stdout JSON filters, so the tests run them end-to-end as subprocesses: the solo gate's threshold, its once-per-session deny, the spawn exemption and the fork non-exemption, every counted edit tool, teammate detection against a fake `ps`, the env overrides, malformed sidecars and garbage stdin, the per-prompt reminder and its skip, injection and the profile-switch delta, cache cleanup, and teammate reaping against a fake tmux.

A second layer pins the *content*: the cores stay under budget, both keep requiring the playbook, the decisions that survived past rewrites are asserted line by line, and the retired gates are asserted **absent** — a core that still promises a ledger or a mandatory verifier is a worse lie than never having had one.

## Honest limitations

- **The solo gate counts edits, not work.** A chair that does everything through `Bash` heredocs never trips it. The per-prompt reminder is the only thing covering that path.
- **It fires once.** By design — but a determined chair can absorb the nudge and carry on solo, and nothing stops it.
- **Hooks check shape, not fidelity.** A worker spawned to satisfy the gate, then ignored, passes.
- **Two chairs only.** Fable (primary) and Opus (fallback). Any other model gets the Fable profile.
- **Enforcement is only as strong as the host's hook pipeline.** On one experimental spawn backend an async `Agent` launch proceeded despite a deny. Verify once on your setup.
- **Pane idleness is a heuristic.** A teammate blocked for hours in one quiet external wait can be reaped mid-wait. Raise `FABLE_ORCH_TEAMMATE_IDLE_H` or disable it for such workloads.
- **A plugin's hooks load at CLI start.** Install it and keep working in the same window and nothing happens — not a bug, but it looks exactly like one.

## License

MIT
