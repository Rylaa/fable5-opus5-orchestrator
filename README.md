# Fable Orchestrator

[![CI](https://github.com/Rylaa/fable5-opus5-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/Rylaa/fable5-opus5-orchestrator/actions/workflows/ci.yml)

Claude Fable 5 stays in the chair and only thinks. Sonnet 5 and Opus 5 do the work. Four hooks make sure it actually happens.

## Install

```
/plugin marketplace add Rylaa/fable5-opus5-orchestrator
/plugin install orchestrator@fable-orchestrator
```

Restart Claude Code. Takes about a minute. Needs `python3`. macOS and Linux only — the hooks call `tmux`. Nothing to configure.

Already on an older version? See [Upgrading to v0.16.0](#upgrading-to-v0160).

## What changes in your next session

1. **You give Claude a task.**
2. **Claude asks questions** — one at a time, until nothing is left that would change the work.
3. **Claude writes a ledger** — every requirement, one checkbox line, in `./.workflow/LEDGER.md`.
4. **Claude hands the work out** — Sonnet 5 for volume, Opus 5 for the hard parts.
5. **A fresh agent checks the result** before anything is called done.

Skip step 2, 3, or 5 and a hook blocks the tool call and says what is missing.

## Why

Fable 5 is the best model to run a session, and the fastest way to hit your usage limit. Every token it types itself is a token you cannot spend on thinking later.

## Who runs what

Your Fable limit pays for the chair and nothing else, plus one check per close.

```
┌─────────────────────────────────────────┬─────────────────┬─────────────────────┐
│ Work                                    │ Runs on         │ Fable limit pays    │
├─────────────────────────────────────────┼─────────────────┼─────────────────────┤
│ Planning, decisions, arbitration        │ Fable 5 (chair) │ yes                 │
│ Code, tests, refactors                  │ Sonnet 5        │ nothing             │
│ Research briefs, filtering, review      │ Sonnet 5        │ nothing             │
│ Bulk reading (fetch, grep, scan)        │ Sonnet 5 (low)  │ nothing             │
│ Architecture, migrations                │ Opus 5 (direct) │ nothing             │
│ Security review                         │ Opus 5 (max)    │ nothing             │
│ Final check — every close               │ Opus/Fable 5    │ at most 1 per close │
└─────────────────────────────────────────┴─────────────────┴─────────────────────┘
```

Four rules keep the answers coming back small:

1. A worker's report is at most 40 lines. Longer output goes to `./.workflow/scratch/` and the report sends the path.
2. One worker per source when researching. It saves the source to disk first, then writes the brief from that copy.
3. Five greps are one worker with a checklist, not five workers.
4. A worker that is unsure goes up a tier. It never comes back to the chair unresolved.

## The four gates

Instructions get ignored. These do not.

```
┌───┬─────────────┬───────────────────────────────┬────────────────────────────────┐
│ # │ Gate        │ Blocks when                   │ Unblock it by                  │
├───┼─────────────┼───────────────────────────────┼────────────────────────────────┤
│ 1 │ Clarify     │ big spawn, ledger has no      │ writing a `## Clarified`       │
│   │             │ answers written down          │ section with real content      │
│ 2 │ Spawn       │ spawn prompt over 1500 chars, │ writing `.workflow/LEDGER.md`  │
│   │             │ no ledger at all              │ with numbered checkbox items   │
│ 3 │ Task list   │ 3rd tracker task, still no    │ same — write the ledger and    │
│   │             │ ledger (blocks once)          │ hand the phases to workers     │
│ 4 │ Close       │ turn ends with open items     │ finishing them, or saying in   │
│   │             │ (blocks once per session)     │ one line why not               │
└───┴─────────────┴───────────────────────────────┴────────────────────────────────┘
```

Never blocked: short spawns, forks, and workers (a worker's turn is never held on the chair's ledger).

A ledger stops counting when every item is closed **and** it was last touched before this session. Retire one for good by renaming it `LEDGER-<topic>-archive.md`.

Each gate covers one place work goes wrong: a question nobody asked, requirements dropped between your task and the plan, the chair doing a six-phase job alone on the most expensive model, and closing with items still open. Everything in between is judgment — and that belongs to the model, not to a regex.

## Step 2 in detail: the questions

A worker cannot ask you anything. So every unanswered question the chair carries into a task becomes a guess that ends up in your code.

The rules, from [`skills/clarify/SKILL.md`](skills/clarify/SKILL.md):

1. **One question per message.** Your answer changes the next question. Asking four at once guesses which order they depend on.
2. **No limit on how many.** It stops when there is nothing left that would change the work.
3. **Only questions that change the work.** "Would a different answer produce different code?" If no, Claude writes down an assumption instead.
4. **Never asks what the repo answers.** It reads first.
5. **Everything gets written down** — answers and assumptions both.

What lands in your ledger:

```markdown
## Clarified
- Q1: does this replace the old exporter, or run beside it? -> beside it, for one release
- Q2: is the CSV column order part of the contract? -> yes, downstream parses by position
- Assumption: existing exports are not backfilled — say so if wrong
```

Plain bullets. A numbered checkbox (`- [ ] 1.`) is a ledger item, so it ends the section instead of filling it. A `## Clarified` inside a code fence is an example, not a record.

Nothing to ask? The section is still written, as one line: `- No ambiguity: <why>`.

## Step 3 in detail: the ledger

Files survive context compaction. Chat does not.

```markdown
- [ ] 1. Every requirement you stated, one line each
- [ ] 2. The ones you did not state but expect
- [x] 3. Ticked only after it was actually checked
- [~] 4. deferred: you approved postponing this
- [ ] V. fresh-eyes verification passed
```

Each task Claude hands out names the item numbers it covers. New findings get appended. The `V.` line can only be ticked by the agent that did the checking — not by the one that did the work.

## What Claude gets told at session start

A hook adds the chair profile ([`instructions/dynamic-workflow-fable.md`](instructions/dynamic-workflow-fable.md)) to every chair session. It is short on purpose: it is paid for on every single start.

The long version lives in two skills that load only when needed:

- [`orchestrator:playbook`](skills/playbook/SKILL.md) — the full rules for handing out work. Required before the first task goes out.
- [`orchestrator:clarify`](skills/clarify/SKILL.md) — the question protocol. Loads when a request is unclear.

A session that never hands out work never pays for either.

Workers never get the profile. It tells its reader "you are the orchestrator", which would turn a worker into a second chair. They are detected and skipped.

## When your Fable limit runs out

Type `/model` and pick Opus. The hook swaps in the Opus profile: same rules, Opus takes over checking and escalation.

- Switching mid-session costs a few lines, not the whole profile — a resumed session already has the rules and only gets what changed.
- The swap takes effect at the **next** session start. Set `FABLE_ORCH_PROFILE=opus` to skip the wait, or leave it on `auto`: detection reads the session's model, then your `/model` default in `settings.json`, then the last model this session saw.

## Watching the team work

Workers are real `claude` processes in tmux panes. You can watch them type.

```bash
# who is running right now
tmux list-panes -a -F '#{pane_id} #{pane_current_command}'
```

Started `claude` inside tmux? They show up as extra panes: `prefix q` to jump, `prefix z` to zoom, `prefix w` for the tree.

Finished workers are killed automatically — on session end, and on a slow sweep that kills panes sitting under ~1% CPU for an hour. Left alone they pile up: one measured run had 63 orphans holding about 5 GB.

## Settings

All optional, in `~/.claude/settings.json` under `"env"`. The five worth knowing:

```
┌───────────────────────────────┬────────────────────┬────────────────────────────────────────────┐
│ Env var                       │ Default            │ Meaning                                    │
├───────────────────────────────┼────────────────────┼────────────────────────────────────────────┤
│ LEDGER_GUARD_THRESHOLD        │ 1500               │ spawn-guard gate (chars)                   │
│ LEDGER_GUARD_CLARIFY          │ (on)               │ 0 disables the clarify gate                │
│ LEDGER_GUARD_TASKS            │ 3                  │ 3rd ledgerless tracker task denied; 0 off  │
│ FABLE_ORCH_PROFILE            │ auto               │ pin the chair profile: auto | fable | opus │
│ FABLE_ORCH_TEAMMATE_IDLE_H    │ 1                  │ kill worker panes idle ≥ N hours; 0 off    │
└───────────────────────────────┴────────────────────┴────────────────────────────────────────────┘
```

Rarely needed: `LEDGER_GUARD_STOP_MODE` (`every-turn` blocks every turn instead of once), `FABLE_ORCH_TEAMMATE_STOP` (`1` holds workers on the ledger too), `FABLE_ORCH_TEAMMATE_INJECT` (`1` gives workers the profile), `FABLE_ORCH_METRICS` (`0` stops the local log), `FABLE_ORCH_SWARM_CLEANUP` (`0` stops all reaping), `FABLE_ORCH_SWARM_MAX_IDLE_H` (default 48), `FABLE_ORCH_TEAMMATE_IDLE_RATE` (default 0.01).

Every hook writes one event line to `~/.claude/fable-orch/metrics.jsonl` — events only, never prompt content. Read it with `python3 scripts/stats.py`.

## Upgrading to v0.16.0

The clarify gate is new, and no ledger written before this release has a `## Clarified` section. Takes about two minutes per live ledger.

1. Open each `.workflow/LEDGER*.md` you are still working on.
2. Add a `## Clarified` section at the top with what was already agreed.
3. Or skip it for now: set `LEDGER_GUARD_CLARIFY=0` for that session.

Finished ledgers need nothing.

## Tests

```
python3 -m pytest tests/ -q
```

Runs in about 25 seconds. The hooks are plain stdin/stdout JSON filters, so every test runs one as a real subprocess: thresholds, the fork exemption, the clarify gate (heading level and case, code fences, setext headings, multiple sections, the numbered-item stop), the task-list gate, the upward ledger search and where it stops, close-guard scoping, metrics, profile injection and switching, cleanup, and worker reaping against a fake tmux.

A second layer checks the *text*: the profiles stay under their size budget and keep the decisions that earlier rewrites were not allowed to drop.

## What this does not do

1. **Hooks check shape, not quality.** A thin ledger passes. A one-line "no ambiguity" passes. Checking harder would just teach the model to write filler.
2. **Ticking `- [x]` without checking is possible.** The box is not proof.
3. **Two chairs only** — Fable and Opus. Any other model gets the Fable profile.
4. **A solo session that never creates tracker tasks slips through** the task gate. It counts tasks, not work.
5. **Idle-worker detection is a guess.** A worker stuck in one long quiet wait can be killed mid-wait. Raise `FABLE_ORCH_TEAMMATE_IDLE_H` if that is your workload.

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

3. Append `instructions/dynamic-workflow-fable.md` to `~/.claude/CLAUDE.md`, and copy both skills to `~/.claude/skills/playbook/SKILL.md` and `~/.claude/skills/clarify/SKILL.md`. The profile asks for `orchestrator:playbook` and `orchestrator:clarify`; copied by hand they are just `playbook` and `clarify`.
4. Without the session-start hook there is no session marker, so the close guard cannot tell your ledger from another session's.

Do not run the plugin **and** the manual install together. You would get every hook twice.

## License

MIT
