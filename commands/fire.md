---
description: Start a task the orchestrator way — clarify it, write the ledger, hand it out, verify the close
---

The task: $ARGUMENTS

Run it end to end in the order below. Do not skip a step because the
task looks small — a small task with a wrong assumption is still wrong.

## 1 · Clarify before you commit

Load `orchestrator:clarify` and follow it exactly.

If the task above is empty, your first question is what the task is.
Otherwise scan it across the seven axes and ask the first thing that
would change the work — ONE question per message, each derived from
the last answer, and never something the repo already answers. Keep
going until the scan turns up nothing. There is no question limit.

## 2 · Write the ledger

`./.workflow/LEDGER-<topic>.md`, in this order:

- `## Clarified` at the top: every answer you got, plus every
  assumption you are proceeding on. Plain bullets — a checkbox line
  reads as a ledger item and ends the section.
- `- [ ] N. <item>` for every requirement, constraint, and edge case,
  one per line.
- `- [ ] V. fresh-eyes verification passed` as the last item.

The spawn guard denies serious delegation until this file has both
parts, so write it before the first worker, not after.

## 3 · Hand the work out

Load `orchestrator:playbook` before the first spawn. Then:

- Independent phases go out TOGETHER in one message; only a phase that
  consumes an earlier one's output waits.
- Every worker spec cites the ledger items it covers.
- Size each worker's effort on what the job needs to be right and
  fast, never on what it costs.
- Name every substantive worker, and parallel editors get
  `isolation: "worktree"`.
- Dismiss a worker with `{"type": "shutdown_request"}` the moment its
  report is accepted. Never leave finished workers stacked.

## 4 · Verify the close

ONE fresh agent that did not build the work, handed the original
request, the ledger path, and the diff — a concrete
`git diff <base>..HEAD`, not "go find what changed". Only it closes
`- [ ] V.`.

Findings become new phases; re-verify after fixing. Cap at three
verify-fix cycles, then stop and report what is still open.

## Stop and tell the user when

- an answer you need cannot be obtained, and proceeding either way
  would make the work useless if wrong;
- a tier declines a task twice (never reword it past a classifier);
- the third verify cycle still has findings.
