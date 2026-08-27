---
name: clarify
description: Clarification protocol — grill an ambiguous request into a Requirements Ledger before any delegation. The chair MUST load this whenever a request arrives carrying ambiguity that would change the work; Rule 0.5 in the core profile only summarizes it.
---

# Clarify Before You Delegate

A worker cannot ask the user anything. Every ambiguity you carry into
a spawn prompt becomes a guess the worker commits to code, and you pay
for it twice — once building the wrong thing, once rebuilding it.

Chair only. A subagent that hits an ambiguity reports it to the chair
with SendMessage and waits.

## The gate

Nothing is delegated, planned, or edited until every ambiguity that
would change the work is resolved by an answer or written down as an
assumption the user can veto — and then until the user
approves what you made of it. `## Clarified` and `## Approved` in the
ledger are the record. The guards deny on some paths and miss others —
see "Scale the ceremony" below — so the records are the discipline, not
a thing the hook will remind you about.

## Scale the ceremony to the work

Below Rule 0's SMALL-WORK line — one sitting, ≈ ≤3 files — the seven-axis
sweep is not the default. Read the request, ask what genuinely blocks
you, and write what is TRUE under `## Clarified`: the answers you got,
or the one-line `- No ambiguity:` form when the request does answer
itself. Never assert an unambiguity you did not test — that
line is a claim, not a stamp for small work.

Two things do NOT scale. The loop: a one-line fix can rest on an
ambiguity that decides the change, and when one is there you ask it,
uncapped, exactly as on big work. And the GO: `## Approved` is required
at every size — and not because a hook will force it. The gates miss
whole paths (forks, short spawns, a session that never reaches three
tracker tasks), so treat being caught as an accident and the rule as
the thing. It rests on the v0.21.0 lesson: answers are not agreement,
at any diff size.

## Scan — seven axes

Each axis that is unresolved AND would change the work is a question:

1. **Scope edge** — what is deliberately OUT? The unnamed neighbour is
   where scope creep lives.
2. **Acceptance** — how is "done" observed? Name the test, the
   command, the screen.
3. **Constraints** — backward compatibility, dependencies, budget,
   what must not move.
4. **Ownership of choices** — whose taste is each decision? Guessing
   on taste is expensive.
5. **Priority conflict** — when speed, correctness, and token cost
   disagree, which wins here?
6. **Contact with what exists** — which current file, pattern, or
   contract does this touch? Read first.
7. **Failure behaviour** — what happens on error, and what does
   rollback look like?

## Filter — ask only what changes the work

Before asking: *would a different answer produce different code?* If
no, do not ask — write the assumption and move on. This filter is what
makes an uncapped question loop safe. Never ask what the repo answers.

## One question per message

One question. Wait. The answer re-shapes the map — it closes some
axes, opens others, and the next question is DERIVED from it, not read
off a pre-written list.

No cap. Stop on the POSITIVE test — could you write the spec for a
worker who cannot ask you anything, without guessing at any part of it?
"The scan turned up nothing" is what a clean request and a lazy look
produce alike, so it is no test.

Two parts, ALWAYS, in this order:

1. THE QUESTION, one plain sentence. No jargon the user has not used
   first, no compound question, no "and also".
2. WHY YOU ARE ASKING, one short line under it, in basic words: what
   changes depending on the answer.

```
Does the new exporter replace the old one, or run beside it?
Asking because it decides whether I touch the old code path at all —
beside it is one new file, replacing it is a migration.
```

The why is not decoration. A question with no stated stake reads as
paperwork, and the user answers it to get past you rather than to
decide something. If you cannot write the why in one plain line, the
question probably fails the filter above — do not ask it.

Form:

- Choices are nameable (2-4 options) → `AskUserQuestion`, options
  concrete, recommendation FIRST and marked, plus ONE line of WHY. A
  mark with no reason gets rubber-stamped, and a rubber stamp is not an
  answer; the reason is what they can disagree with.
- Genuinely open → one plain sentence carrying your reading AND its
  reason: "I would go with X because Y — right?" Faster than "what do
  you mean?"

A recommendation is a PROPOSAL, never a recorded answer. `## Clarified`
holds what the USER picked.

## Record, then delegate

Write `## Clarified` at the TOP of ./.workflow/LEDGER*.md, above the
numbered items:

```markdown
## Clarified
- Q1: <question> -> <answer>
- Q2: <question> -> <answer>
- Assumption: <unasked but load-bearing> — say so if wrong
```

Then the `- [ ] N.` items, each traceable to an answer or an
assumption. Worker specs cite items, the items carry the answers, and
no worker has to guess. Answers that arrive mid-task are appended — a
second `## Clarified` block lower in the file counts.

Write answers as **plain bullets**. ANY checkbox line — `- [ ] 1.`,
`- [x] Q1: yes` — reads as a ledger item and closes the section
instead of filling it. A `## Clarified` inside a fenced code block is
an example, not a record, and a divider or an HTML comment is not an
answer. Sub-headings are fine: `### Round 2` stays inside the
section.

A genuinely unambiguous request still gets the section, at ANY size —
one line: `- No ambiguity: <why the request answers itself>`.

## Then get the go, then delegate

Answers are not agreement — right answers still leave the wrong build
free to be approved silently. Before the FIRST spawn, say what you are
about to do, and wait.

Shape that message the way the reply-shape rules in your injected core
shape every reply — numbered build steps (five max, longer splits into now/later),
what you are NOT building, how done is observed, the ask on its own
line — plus one thing that shape does not carry: a concrete COST line,
files and agents and rough wall-clock, which lets them answer "not
worth it". No preamble, no recap of the clarify round: readable
and answerable in under a minute.

```markdown
## Approved
- Building: <the change, in a line or two>
- Not building: <the neighbour you are deliberately leaving alone>
- Done when: <the command, test, or screen that shows it>
- <user>, <date>: approved
```

Ask once, then stop — no spawning while you wait. Plain bullets here
too; a checkbox line closes this section the same way. If the plan
changes, rewrite the section: the approval covers what it says now.
`LEDGER_GUARD_APPROVAL=0` turns the gate off.

## Red flags

| Thought | Reality |
|---------|---------|
| "I get the gist, I'll start" | The gist is the part you already knew. The ambiguity is the rest. |
| "I'll infer it from the code" | Code shows what IS, never what they WANT. |
| "Asking looks slow" | One question costs a message. A wrong build costs the session. |
| "I'll ask all four at once" | Answer 2 changes question 3. Batching guesses the order. |
| "They said go, so it's clear" | "Go" approves a direction. Say what you will build and get a second go. |
| "The worker will figure it out" | Workers cannot reach the user. Your ambiguity becomes their guess. |
| "Nothing here is ambiguous" | Then write that line under `## Clarified` and move — the section is never skipped. |
