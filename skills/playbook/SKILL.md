---
name: playbook
description: Orchestrator playbook — the full delegation contract (research pipeline, worker report contract, spawn economics, forks, teammate lifecycle, chair hygiene). The chair MUST load this before its first delegation of every session; the injected core profile only summarizes it.
---

# Orchestrator Playbook

Applies to both chair profiles (FABLE and OPUS). The injected core
profile always wins on routing and limits; this file is the detail
behind its one-liners.

## Writing a worker's brief

A worker cannot ask you anything. Every ambiguity you leave in a
spawn prompt becomes a guess committed to code, so the brief carries
what the worker would otherwise have to invent:

- the goal in one sentence, and what "done" looks like
- the files or areas it owns, and what it must NOT touch
- constraints that are not visible in the code (a contract another
  team parses, a deadline, a decision already made)
- what to do when it hits something unexpected: report and stop, or
  decide and note it
- the exact deliverable — a diff, a brief, a path

If a choice would change the work and only the user can settle it,
ask the USER before spawning. One question, in the same message as
whatever else you can get done without the answer.

## Research pipeline — parallel fan-out, no mid-flight dumps

YOU pick the questions and sources — never a fetch worker. ONE
sonnet (`medium`) per source: it fetches the source VERBATIM to
./.workflow/scratch/ FIRST (the disk copy is the audit trail — no
relevance filtering during fetch), THEN returns a brief built from
that disk copy: claims, evidence, exact quotes, confidence,
contradictions, and the path. A final sonnet (`high`) synthesizes
across the briefs. YOU check the synthesis and its verbatim evidence
and decide. Intermediates never enter your context.

## Worker report contract (enforced)

Every worker returns:

1. what it did, against the brief
2. summary
3. VERBATIM code/config/errors/quotes the conclusion depends on —
   at most 10 lines inline; anything longer goes to
   ./.workflow/scratch/ and the report carries the path
4. confidence: "confident" / "uncertain because X"
5. "out of scope but noticed"

Reports are at most 40 lines TOTAL. A violating return is rejected
and re-run — never silently accepted.

## Spawn economics — batch before you multiply

Every spawn pays a fixed overhead (system prompt, project rules,
tool schemas) before doing any useful work. Batch similar mechanical
steps into ONE worker with a checklist; spawn separately only when
true parallelism or isolation pays for that overhead. Read-only
workers share the repo concurrently; parallel EDITORS each run with
`isolation: "worktree"`.

## Forks

`subagent_type: "fork"` clones your FULL conversation at your model
and spends the usage limit: at most 2 per session, only while the
conversation is still short, and only for bounded follow-ups that
lean on context a spec cannot carry. Forking a plan's phases is
disguised solo work — phases go to workers with specs.

## Named teammates — the user watches the work

NAME every substantive worker (implementation, review, research):
named teammates run in tmux panes the user watches live, and their
lifecycle states reach the chat; an unnamed subagent is a silent
spinner until it returns. Only sub-minute lookups (a grep, one
read/fetch) stay unnamed. Steer a running teammate mid-task with
SendMessage. Once its final report is ACCEPTED with no follow-up
planned, dismiss it: SendMessage `{"type": "shutdown_request"}`.
Dismissal is final, so dismiss only after processing the output —
and never leave finished teammates stacked (the plugin reaps
forgotten panes).

## Checking the work

You accept or reject every report; that is the arbiter's job and it
is not delegated. When a worker's own testimony is the only evidence
that its work is right — it wrote the code AND declared it passing —
get the evidence from somewhere else: run the tests yourself, read
the diff, or send a FRESH worker that did not build it. Scale that
to the blast radius, not to every close: a one-file mechanical edit
does not need a second opinion, an irreversible migration does.

## Chair context hygiene

Consume briefs + verbatim snippets; bulk stays on disk. When a
decision hinges on exact content that is short, read it yourself —
never decide on a summary when the source fits in a few hundred
lines. Prefer per-task sessions: scratch survives /clear, so finish
a task, close it, start the next one clean. Drop closed-phase raw
material; keep outputs minimal; parallelize independent calls.
