---
name: clarify
description: Clarification protocol — grill an ambiguous request into a Requirements Ledger before any delegation. The chair MUST load this whenever a request arrives carrying ambiguity that would change the work; Rule 0.5 in the core profile only summarizes it.
---

# Clarify Before You Delegate

A worker cannot ask the user anything. Every ambiguity you carry into
a spawn prompt becomes a guess the worker commits to code, and you pay
for it twice — once building the wrong thing, once rebuilding it. The
cheapest question is the one asked before the first spawn.

Chair only. A subagent that hits an ambiguity does NOT run this skill:
it reports the ambiguity to the chair with SendMessage and waits.

## The gate

Nothing is delegated, planned, or edited until every ambiguity that
would change the work is either resolved by an answer or written down
as an explicit assumption the user can veto. `## Clarified` in the
ledger is the record, and the spawn guard denies without it.

## Scan — seven axes

Each axis that is unresolved AND would change the work is a question:

1. **Scope edge** — what is deliberately OUT? The unnamed neighbour is
   where scope creep lives.
2. **Acceptance** — how is "done" observed? Name the test, the
   command, the screen.
3. **Constraints** — backward compatibility, dependencies, budget,
   what must not move.
4. **Ownership of choices** — which decisions are the user's taste and
   which are yours? Guessing on taste is expensive.
5. **Priority conflict** — when speed, correctness, and token cost
   disagree, which wins here?
6. **Contact with what exists** — which current file, pattern, or
   contract does this touch? Read first; never ask what the repo
   answers.
7. **Failure behaviour** — what happens on error, and what does
   rollback look like?

## Filter — ask only what changes the work

Before asking: *would a different answer produce different code?* If
no, do not ask — write the assumption and move on. This filter is what
makes an uncapped question loop safe. Never ask what you can read; a
question the repo already answers spends the user's attention on your
laziness.

## One question per message

One question. Wait. The answer re-shapes the map — it closes some
axes, opens others, and the next question is DERIVED from it, not read
off a pre-written list. Batching guesses the order and kills the
derivation.

No cap. Stop when the scan turns up nothing that would change the
work, never at a number.

Form:

- Choices are nameable (2-4 options) → `AskUserQuestion`, options
  concrete, your recommendation first and marked.
- Genuinely open → one plain-prose sentence.

State your reading when the answer depends on it: "I read this as X,
which means Y — right?" is a faster question than "what do you mean?"

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
assumption. Then spawn. Worker specs cite items, the items carry the
answers, and no worker has to guess. Answers that arrive mid-task are
appended, never merged away — a second `## Clarified` block lower in
the file counts.

Write answers as **plain bullets**. A numbered checkbox (`- [ ] 1.`)
is a ledger item, so it closes the section instead of filling it, and
a `## Clarified` inside a fenced code block is an example, not a
record.

A genuinely unambiguous request still gets the section — one line:
`- No ambiguity: <why the request answers itself>`.

## Red flags

| Thought | Reality |
|---------|---------|
| "I get the gist, I'll start" | The gist is the part you already knew. The ambiguity is the rest. |
| "I'll infer it from the code" | Code shows what IS, never what they WANT. |
| "Asking looks slow" | One question costs a message. A wrong build costs the session. |
| "I'll ask all four at once" | Answer 2 changes question 3. Batching guesses the order. |
| "They said go, so it's clear" | "Go" approves a direction, not every detail. |
| "It's a small change" | A small change on a wrong assumption is still wrong. |
| "The worker will figure it out" | Workers cannot reach the user. Your ambiguity becomes their guess. |
| "Nothing here is ambiguous" | Then write that line under `## Clarified` and move — the section is never skipped. |
