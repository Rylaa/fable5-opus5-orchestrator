---
name: playbook
description: Orchestrator playbook — the full delegation contract (research pipeline, subagent output contract, spawn economics, forks, teammate lifecycle, verification procedure, chair hygiene). The chair MUST load this before its first delegation of every session; the core only summarizes it.
---

# Orchestrator Playbook

Applies to both chair profiles (FABLE and OPUS). The injected core wins
on routing and limits; this file is the detail behind it.

## Research pipeline — parallel fan-out, no mid-flight dumps

YOU pick the questions and sources — never a fetch worker. ONE sonnet
(`medium`) per source: it fetches the source VERBATIM to
./.workflow/scratch/ FIRST (the disk copy is the audit trail — no
filtering during fetch), THEN returns a brief from that copy: claims,
evidence, exact quotes, confidence, contradictions, and the path. A
final sonnet (`high`) synthesizes across the briefs. YOU check the
synthesis and its verbatim evidence against the ledger and decide.
Intermediates never enter your context.

## Subagent output contract (enforced)

Every subagent returns:

1. ledger items addressed, by number
2. summary
3. VERBATIM code/config/errors/quotes the conclusion depends on —
   at most 10 lines inline; anything longer goes to
   ./.workflow/scratch/ and the report carries the path
4. confidence: "confident" / "uncertain because X"
5. "out of scope but noticed"

Reports are at most 40 lines TOTAL. A violating return is rejected and
re-run, never silently accepted.

## Spawn economics — batch before you multiply

Every spawn pays a fixed overhead (system prompt, project rules, tool
schemas) before any useful work. Batch similar mechanical steps into ONE
worker with a checklist; spawn separately only when parallelism or
isolation pays for it. Read-only agents share the repo; parallel
EDITORS each run with `isolation: "worktree"`.

## Forks

`subagent_type: "fork"` clones your FULL conversation at your model
and spends the usage limit: at most 2 per session, only while the
conversation is short, and only for bounded follow-ups that lean on
context a spec cannot carry. Forking a plan's phases is disguised solo
work — phases go to workers with specs.

## Named teammates — the user watches the work

NAME every substantive worker (implementation, review, research,
verification): named teammates run in tmux panes the user watches live,
and their lifecycle states reach the chat; an unnamed subagent is a
silent spinner until it returns. Only sub-minute lookups (a grep, one
read/fetch) stay unnamed. Steer a running teammate with SendMessage.
Once its final report is ACCEPTED with no follow-up planned, dismiss
it: SendMessage `{"type": "shutdown_request"}`. Dismissal is final, so
process the output first — and never leave finished teammates stacked
(the plugin reaps forgotten panes).

## Watchdog — a spawn is not a start

"Spawned successfully" means a pane opened, not that a session booted:
measured twice in one day, whole waves lived past 20 minutes with no
session log while the chair called them running. Time is not progress.

Every async wave carries one more teammate, `watchdog` (sonnet, low).
Its job is to LOOP `python3 "<path in your profile>" --watch` — each
call polls read-only and returns in ~100s, so it calls again — and to
message the chair only on `unborn` (process alive, no log) or
`stalled` (log quiet past the threshold). A healthy `starting ->
working` transition is not news. The chair idles as usual, never polls.

It covers named `Agent` and `Task` spawns only, never `Workflow`: a
workflow names a script rather than an agent, so recording one would
park a name no log can match — a standing `unborn` alarm instead of a
gap.

Nothing is killed for you. On an alarm: ping; with no reply dismiss the
pane and RE-SPAWN — that is the default, because the work was delegated
for a reason and a stall does not shrink it. Taking it back yourself is
bounded by Rule 0 like anything else: one mechanical file, and you say
so.

## What the chair actually does

The chair's one act is the comparison: I said this, you did that. It
owns the work, hands it out, sequences it, judges what comes back — it
does not write the code. That comparison needs an account of the
delivery it can TRUST, and the builder's own report is not one: the
party being checked wrote it. The verifier is the CHAIR'S EYES, not a
gate at the end. Reading delegates; judgement does not. So the chair
reads reports, not diffs, and opens the code only when a report cannot
settle it — worker and verifier disagree, the report itself looks
wrong, or the decision hinges on short exact content, which Chair
context hygiene below tells you to read for yourself.

Rule 0's one writing exception — a single mechanical file — still
cannot close itself. Its `V.` goes to the verifier, or to the deferral
the user grants under SKIPPING; either way the reader is not you.

## Verification procedure

The verifier is FRESH — it has not worked on the task. Give it the
original request, the ledger path, and THE DIFF — a
`git diff <base>..HEAD` command or a patch file on disk, plus the
report paths. Never the raw scratch dump, and never "go find what
changed": a verifier that must locate the change spends its budget
looking instead of checking. Its only job is to find what is missing,
wrong, or unaddressed, item by item — and only it closes the `V.` ledger
item. It is ONE call over the whole change, not one per phase.

TIER AND EFFORT. opus, effort FLOOR `medium` — never `low`. `xhigh` is
the normal ceiling; `max` is for complex STRUCTURE, not mere size.
Size it on how hard the change is to JUDGE, never on line count: a
hundred one-line mechanical edits are `medium`, three files of
interlocking state are `xhigh`.

CYCLES. Findings become new phases; re-verify. Stop as soon as a cycle
finds nothing NEW — a repeated finding is disagreement, not progress,
and a third fresh reader repeats it again: put it to the user instead.
CAP: 3 verify→fix cycles regardless, then STOP and report open items.

PER-WAVE REVIEW, long jobs. Review each wave as it LANDS instead of
saving it all for the end. It runs in the BACKGROUND — the chair sends
the next wave meanwhile — against a PINNED ref: the sha in the chair's
repo where that wave's work landed, after any worktree branches are
merged back. Never the live working tree the next wave is editing, and
never a wave whose output has not landed yet — that review waits for it.

Each wave writes its OWN file, ./.workflow/FINDINGS-<topic>-w<N>.md, so
two background reviewers never append to one file and clobber each
other. Ledger form, `- [ ] W2.3 <finding>`, kept OUT of LEDGER*.md:
hooks read that path and raw findings there fire the stop guard on
noise — and one NAMED LEDGER-* is worse still, because find_ledger()
takes the most recent LEDGER*.md and a file carrying no
`## Clarified`/`## Approved` denies every later spawn. The chair
promotes the real ones into numbered ledger items and closes the W-item
`- [x]` when it does; the wave files retire with the topic. Nothing
enforces that either: no hook reads FINDINGS-*, so a W-item you forget
to promote is in no ledger, reaches no final pass, and goes when the
topic does. Promotion is a habit, not a guard.

The final pass reads those files instead of re-deriving, and narrows to
what no per-wave review can see — items no wave claimed, and collisions
where separate waves touched the same files.

SKIPPING. On a small diff the chair may PROPOSE a skip. With the user's
ok `V.` is recorded `- [~] deferred: <reason>` — a deferral the USER
granted, never a pass the chair awarded itself, and `- [x]` still
belongs to the verifier alone. When the diff is the chair's own lone
mechanical edit, SAY so in the proposal: the user becomes the fresh
reader, and they need to know that is what they are agreeing to.
Nothing enforces any of this — the stop guard only stops counting a
line once it is no longer `- [ ]`, so `- [~]` with no reason and no
user behind it closes just as quietly. The marker is a record of a
decision someone made, not proof that they made it.

## Chair context hygiene

Consume briefs + verbatim snippets; bulk stays on disk. When a decision
hinges on short exact content, read it yourself — never decide on a
summary when the source fits in a few hundred lines. Prefer per-task
sessions: the ledger and scratch survive /clear — finish one, close it,
start the next clean. Drop closed-phase raw material; keep outputs
minimal; parallelize independent calls.
