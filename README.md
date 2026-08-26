# Fable Orchestrator

[![CI](https://github.com/Rylaa/fable5-opus5-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/Rylaa/fable5-opus5-orchestrator/actions/workflows/ci.yml)

**Keep Claude Fable 5 in the chair all day.** Fable plans and decides. Sonnet 5 carries the volume, Opus 5 takes the hard slices. Four hooks enforce it, so the discipline does not depend on the model remembering it.

## TL;DR

- **Problem** — Fable 5 is the best chair a Claude Code session can have, and the fastest way to spend your usage limit.
- **Fix** — the chair only thinks. Everything bulky is delegated, by tier and by effort.
- **Teeth** — four hook gates block the four places this workflow actually breaks. Instructions are advice; hooks are mechanism.
- **Setup** — two commands, no configuration.

## Install

```
/plugin marketplace add Rylaa/fable5-opus5-orchestrator
/plugin install orchestrator@fable-orchestrator
```

Restart Claude Code afterwards. Needs `python3` on PATH; macOS and Linux only (the hooks shell out to `tmux`). [Manual install](#manual-install-without-the-plugin-system) if you don't use the plugin system.

## What a session looks like

1. **You give the chair a task.**
2. **It asks questions** — one per message, each derived from your last answer, until nothing that would change the work is still open.
3. **It writes the ledger** — every requirement as one checkbox line in `./.workflow/LEDGER.md`.
4. **It delegates** — Sonnet for volume, Opus for hard slices, effort sized per task.
5. **A fresh agent verifies** the close, and only it ticks the last box.

Skip step 2, 3, or 5 and a hook stops you.

## Who does what

```
                        ┌─────────────────────────────────┐
                        │         FABLE 5 — chair         │
                        │    plan · arbitrate · decide    │
                        │  sizes tier + effort per task   │
                        └────────────────┬────────────────┘
                                         │
                specs & ledger down      │      briefs & verdicts up
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
                                                          │  the valve · by blast radius │
                                                          │  verify: OPUS 5 / FABLE 5    │
                                                          │  escalate: OPUS 5 → FABLE 5  │
                                                          └──────────────────────────────┘
```

Your Fable limit pays for the thinking, plus at most one verification per close:

```
┌─────────────────────────────────────────┬─────────────────┬─────────────────────┐
│ Work                                    │ Runs on         │ Fable limit pays    │
├─────────────────────────────────────────┼─────────────────┼─────────────────────┤
│ Phase planning, arbitration, decisions  │ Fable 5 (chair) │ yes                 │
│ Implementation, tests, refactors        │ Sonnet 5        │ nothing             │
│ Source briefs, filtering, code review   │ Sonnet 5        │ nothing             │
│ Bulk gathering (fetch, grep, scan)      │ Sonnet 5 (low)  │ nothing             │
│ Hard slices: architecture, migrations   │ Opus 5 (direct) │ nothing             │
│ Security / adversarial review           │ Opus 5 (max)    │ nothing             │
│ Escalations (sonnet "uncertain")        │ Opus → Fable    │ mostly nothing      │
│ Fresh-eyes verification — EVERY close   │ Opus/Fable 5    │ at most 1 per close │
└─────────────────────────────────────────┴─────────────────┴─────────────────────┘
```

**How escalation works**

- Sonnet returns "uncertain" → it goes to Opus, never back to the chair.
- Opus is the ceiling for hard work and the *only* tier for security review; Fable is the last stop above it, and it spends the chair's own limit.
- Escalation is one-way. If a tier declines a task, it is re-run **unchanged** on another tier — never reworded to slip past a classifier. If that tier declines too, the chair stops and tells you.
- Verification is mandatory on every close; what scales is the effort, not whether it happens. `max` for architecture, irreversible changes, security, and the largest closes; `high` is allowed for small, low-risk, non-security ones.

**Three rules keep worker output from undoing the saving:**

- Reports are capped at 40 lines. Verbatim over ten lines goes to `./.workflow/scratch/` and the report carries the path. A violating report is re-run, not accepted.
- Research is one worker per source: fetch verbatim to disk first, then brief from that copy. One synthesizer reads across the briefs.
- Similar mechanical work is batched. Five greps are one agent with a checklist, not five agents.

## The four gates

This is the part that has teeth. Each gate fences one measured failure.

```
┌───┬────────────────┬──────────────────────────────┬──────────────────────────────────┐
│ # │ Gate           │ Fires when                   │ What unblocks it                 │
├───┼────────────────┼──────────────────────────────┼──────────────────────────────────┤
│ 1 │ Clarify        │ a spawn over the threshold,  │ a non-empty `## Clarified`       │
│   │ (PreToolUse)   │ ledger has no answers in it  │ section at the top of the ledger │
│ 2 │ Spawn          │ spawn prompt > 1500 chars,   │ any `.workflow/LEDGER*.md` with  │
│   │ (PreToolUse)   │ no active ledger             │ numbered checkbox items          │
│ 3 │ Task list      │ 3rd tracker task, still no   │ same — write the ledger and      │
│   │ (PreToolUse)   │ ledger (fires once)          │ delegate instead of going solo   │
│ 4 │ Close          │ turn ends with open items    │ finish them, defer with your     │
│   │ (Stop)         │ (fires once per session)     │ approval, or say so in one line  │
└───┴────────────────┴──────────────────────────────┴──────────────────────────────────┘
```

**Never gated:** short spawns (quick lookups), forks (`subagent_type: "fork"` already sees the ledger), and teammates (a worker's close is never held on the chair's ledger).

**A ledger goes stale** when every item is closed *and* it was untouched before this session started — last week's finished ledger doesn't disarm anything. Retire one for good by renaming it `LEDGER-<topic>-archive.md`.

## 1 · Clarification before commitment

**A worker cannot ask you anything.** Every ambiguity the chair carries into a spawn prompt becomes a guess committed to code — you pay once building the wrong thing, once rebuilding it. So the chair grills the request *before* writing a single ledger item.

The protocol is [`skills/clarify/SKILL.md`](skills/clarify/SKILL.md) (`orchestrator:clarify`), loaded on demand. It scans seven axes — scope edge, acceptance, constraints, whose call each choice is, priority conflicts, contact with existing code, failure behaviour — and turns each unresolved one into a question.

- **One question per message.** The answer re-shapes the map and the next question is derived from it. Asking four at once guesses the order in which they depend on each other.
- **No cap.** It stops when the scan is clean, not at a number.
- **Only questions that change the work.** "Would a different answer produce different code?" If no, the chair writes the assumption down instead. That filter is what makes an uncapped loop safe — and it forbids asking what the repo already answers.

Answers land in the ledger, above the numbered items:

```markdown
## Clarified
- Q1: does this replace the old exporter, or run beside it? -> beside it, for one release
- Q2: is the CSV column order part of the contract? -> yes, downstream parses by position
- Assumption: existing exports are not backfilled — say so if wrong
```

Answers are **plain bullets**. A *numbered* checkbox (`- [ ] 1.`) is a ledger item, so it ends the section rather than filling it, and a `## Clarified` inside a code fence is an example, not a record.

An unambiguous request still gets the section, as one line: `- No ambiguity: <why>`. It is never skipped, because "nothing here is ambiguous" is exactly what a chair thinks right before it builds the wrong thing.

## 2 · The Requirements Ledger

**Files survive context compaction; conversation context does not.** Before serious delegation the chair writes every requirement, constraint, and edge case as one checkbox line in `./.workflow/LEDGER.md` — or `LEDGER-<topic>.md` when one project runs several.

```markdown
- [ ] 1. Every explicit requirement, one line each
- [ ] 2. Implicit expectations and constraints too
- [x] 3. Marked done only after verification confirms it
- [~] 4. deferred: user approved postponing this
- [ ] V. fresh-eyes verification passed
```

Phases cite item numbers. Discoveries are appended. The `V.` line is closed by the verifier alone.

## 3 · The profile — a slim core plus two skills

A SessionStart hook injects the chair profile ([`instructions/dynamic-workflow-fable.md`](instructions/dynamic-workflow-fable.md)) into every **chair** session. Auto-detected, nothing to configure.

```
┌──────────────────────────┬──────────────────────────────┐
│ Scarce resource          │ your usage limit             │
│ Clarification            │ asked out before the ledger  │
│ Requirements Ledger      │ file, before any delegation  │
│ Bounded / medium work    │ delegated                    │
│ Worker effort            │ sized per task by the chair  │
│ Verification             │ fresh-eyes on every close    │
│ Disk hand-off            │ the default                  │
│ Subagent report cap      │ 40 lines; bulk to disk       │
│ Detail (playbook·clarify)│ skills, loaded on demand     │
└──────────────────────────┴──────────────────────────────┘
```

**The injected text is deliberately small.** It is prepended to every chair session, so every character is paid on every start. The core carries only what must be true from the first token and defers the rest to two on-demand skills: [`orchestrator:playbook`](skills/playbook/SKILL.md) (the full delegation contract — research pipeline, output contract, spawn economics, forks, teammate lifecycle, verification), required before the first delegation, and [`orchestrator:clarify`](skills/clarify/SKILL.md) whenever a request carries ambiguity. Sessions that never delegate never pay for either.

## When the Fable limit runs dry

Move the chair to Opus with `/model`. The injector serves the [OPUS profile](instructions/dynamic-workflow-opus.md): same discipline, the fable tier rests, verification and the escalation ceiling fall to Opus.

- **Switching costs a few lines, not a whole profile.** A *resumed* session that already has a core gets only a short [switch note](instructions/profile-switch-to-opus.md).
- **Resume only, on purpose.** `compact` fires because the context was rewritten and `clear` because it was discarded — both get the full core, because the switch note's "every other rule still applies" would otherwise be unverifiable.
- **Detection order:** `FABLE_ORCH_PROFILE` pin → the SessionStart payload's model → the default model `/model` wrote to `settings.json` → the last model this session saw → fable.
- A mid-session `/model` switch takes effect at the *next* session start. `FABLE_ORCH_PROFILE=opus` pins it immediately.

**Teammates never get the profile.** Named workers fire SessionStart too, but the profile is written for the chair: delivered to a worker it says "you are the orchestrator" and inverts the discipline (measured: 172 of 270 injected sessions were teammates). They are detected and skipped. `FABLE_ORCH_TEAMMATE_INJECT=1` restores the old behaviour.

## Watching the team live

Teammates are real `claude` processes in tmux panes — you can watch every agent think and type.

```bash
# who is on the field, by name
tmux list-panes -a -F '#{pane_id} #{pane_current_command}'

# every pane, mapped: session, pane id, pid, what it runs
tmux list-panes -a -F '#{session_name} #{pane_id} #{pane_pid} #{pane_current_command}'

# older Claude Code parked teams in dedicated servers — attach read-only
tmux -L claude-swarm-<pid> attach -r
```

If you launched `claude` from inside tmux, the team appears as extra panes in your window: `prefix q` jumps, `prefix z` zooms, `prefix w` shows the tree.

**Finished teammates are reaped automatically.** The agent-teams backend never reaps them (measured: 63 orphaned agents holding ~5 GB; later, 9 panes parked for 11–30 hours). A `SessionEnd` hook kills this session's teammates wherever they live, and a rate-limited sweep on `Stop` kills panes idling below ~1% CPU for `FABLE_ORCH_TEAMMATE_IDLE_H` hours. The chair's own rule is the front line: dismiss a teammate the moment its report is accepted.

## Configuration

Optional. Set these in `~/.claude/settings.json` under `"env"`.

```
┌───────────────────────────────┬────────────────────┬────────────────────────────────────────────┐
│ Env var                       │ Default            │ Meaning                                    │
├───────────────────────────────┼────────────────────┼────────────────────────────────────────────┤
│ LEDGER_GUARD_THRESHOLD        │ 1500               │ spawn-guard gate (chars)                   │
│ LEDGER_GUARD_CLARIFY          │ (on)               │ 0 disables the clarify gate                │
│ LEDGER_GUARD_TASKS            │ 3                  │ 3rd ledgerless tracker task denied; 0 off  │
│ LEDGER_GUARD_STOP_MODE        │ once-per-session   │ every-turn restores per-turn blocking      │
│ FABLE_ORCH_PROFILE            │ auto               │ pin the chair profile: auto | fable | opus │
│ FABLE_ORCH_TEAMMATE_STOP      │ (off)              │ 1 lets the close guard hold teammates too  │
│ FABLE_ORCH_TEAMMATE_INJECT    │ (off)              │ 1 injects the profile into teammates too   │
│ FABLE_ORCH_METRICS            │ (on)               │ 0 disables local metrics logging           │
│ FABLE_ORCH_SWARM_CLEANUP      │ (on)               │ 0 disables all teammate reaping            │
│ FABLE_ORCH_SWARM_MAX_IDLE_H   │ 48                 │ sweep swarms idle ≥ N hours; 0 disables    │
│ FABLE_ORCH_TEAMMATE_IDLE_H    │ 1                  │ kill teammate panes idle ≥ N hours; 0 off  │
│ FABLE_ORCH_TEAMMATE_IDLE_RATE │ 0.01               │ cpu-sec/sec under which a pane is idle     │
└───────────────────────────────┴────────────────────┴────────────────────────────────────────────┘
```

**Metrics.** Every hook appends one event line to `~/.claude/fable-orch/metrics.jsonl` — events only, never prompt content. `python3 scripts/stats.py` prints the summary. Disable with `FABLE_ORCH_METRICS=0`.

**The session marker.** The injector writes a per-session temp file whose `started` timestamp survives resume/clear/compact, so the guards can tell your ledger from another session's. `SessionEnd` removes it and sweeps anything older than 96 hours.

## Upgrading to v0.16.0

The clarify gate is new, and no existing ledger has a `## Clarified` section. So:

1. For each **live** ledger, add the section — for work already underway, a short record of what was already agreed is the honest entry.
2. Or set `LEDGER_GUARD_CLARIFY=0` for that session and add it later.

Finished ledgers need nothing: rename them `LEDGER-<topic>-archive.md`.

## Tests

```
python3 -m pytest tests/ -q
```

The hooks are plain stdin/stdout JSON filters, so the tests run them end-to-end as subprocesses: thresholds and env overrides, the fork exemption, Workflow script gating, the clarify gate (heading level and case, code fences, setext boundaries, multiple sections, the numbered-item stop, precedence against a missing or stale ledger), the task-list gate, the upward ledger search and its boundaries, stop-guard scoping, metrics, injection, the profile-switch delta, cache cleanup, and teammate reaping against a fake tmux.

A second layer pins the *content*: the cores stay under budget, both keep requiring the playbook and the `## Clarified` record, and the decisions that survived past rewrites are asserted line by line.

## Honest limitations

- **Hooks check shape, not fidelity.** A shallow ledger passes. A one-line `- No ambiguity: <why>` passes. Mechanizing further buys ritual compliance, not clarity.
- **Freshness is half-checked.** A fully-closed ledger from a previous session re-arms the gates, but a stale one with open items still satisfies them — it looks like active work.
- **`- [x]` without verifying is possible.** Ticking a box is not proof.
- **Two chairs only.** Fable (primary) and Opus (fallback). Any other model gets the Fable profile.
- **Enforcement is only as strong as the host's hook pipeline.** On one experimental spawn backend an async `Agent` launch proceeded despite a deny. Verify once on your setup.
- **Pane idleness is a heuristic.** A teammate blocked for hours in one quiet external wait can be reaped mid-wait. Raise `FABLE_ORCH_TEAMMATE_IDLE_H` or disable it for such workloads.
- **The task guard counts tasks, not work.** A solo multi-phase session that never creates tracker tasks still slips through, and the deny is one nudge, not a wall.

## Why these guards

Details die in four places, and each gate fences one of them:

1. **Before the workflow** — ambiguity the chair never resolved. A worker cannot ask you anything, so an unasked question ships as a guess.
2. **Entering it** — task→plan translation, where requirements quietly drop.
3. **Never starting** — the chair implementing a multi-phase plan solo on the most expensive model.
4. **Leaving it** — closing with items silently unaddressed.

Everything between is judgment, and judgment belongs to the model, not to a regex.

## Manual install (without the plugin system)

1. Copy `scripts/ledger_guard_spawn.py`, `scripts/ledger_guard_stop.py`, and `scripts/cleanup_session_cache.py` to `~/.claude/hooks/`.
2. Merge this into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "^(Agent|Task|Workflow|TaskCreate)$",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/ledger_guard_spawn.py", "timeout": 10 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/ledger_guard_stop.py", "timeout": 10 }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/cleanup_session_cache.py", "timeout": 20 }
        ]
      }
    ]
  }
}
```

3. Append `instructions/dynamic-workflow-fable.md` to `~/.claude/CLAUDE.md`, and copy both skills to `~/.claude/skills/playbook/SKILL.md` and `~/.claude/skills/clarify/SKILL.md`. Note the name mismatch: the core asks for `orchestrator:playbook` and `orchestrator:clarify`, which only resolve when the plugin is installed. Copied by hand they are plain `playbook` and `clarify`.
4. Without the SessionStart injector there is no per-session marker, so the stop guard can't tell another session's ledger from yours and the gates can't ignore stale closed ledgers.

> Don't run the plugin **and** the manual install side by side — you'd get every guard twice.

## License

MIT
