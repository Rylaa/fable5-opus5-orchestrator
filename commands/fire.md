---
description: Start a task the orchestrator way — clarify it, write the ledger, hand it out, verify the close
---

The task: $ARGUMENTS

Run it end to end in the order below. No step is skipped because the
task looks small — a small task with a wrong assumption is still wrong.
What scales with size is the WEIGHT of each step, never whether it
runs.

## 1 · Clarify before you commit

Load `orchestrator:clarify` and follow it exactly.

If the task above is empty, your first question is what the task is.
Below the SMALL-WORK line — one sitting, ≈ ≤3 files — the seven-axis
sweep is not the default: write what is TRUE under `## Clarified` and
move on, asking anything that genuinely blocks you exactly as you would
on big work. Above it, scan across the seven axes and ask the first
thing that would change the work — ONE question per message, each
derived from the last answer, and never something the repo already
answers. Every QUESTION is two parts — the question in one plain
sentence, then one basic line saying why you are asking it and what
changes depending on the answer. Every RECOMMENDATION carries its own
line of why: a marked option with no reason gets rubber-stamped, not
judged.

Stop on the POSITIVE test: could you write the spec for a worker who
cannot ask you anything, without guessing? No question limit, no
number, and the go in step 2 is never skipped at any size.

## 2 · Write the ledger

`./.workflow/LEDGER-<topic>.md`, in this order:

- `## Clarified` at the top: every answer you got, plus every
  assumption you are proceeding on. Plain bullets — a checkbox line
  reads as a ledger item and ends the section.
- `## Approved` under it: what you WILL build, what you are
  deliberately NOT building, how "done" is observed. Then ask the user
  for the go in ONE message and WAIT — their answer goes in the
  section, and nothing is handed out before it is there — at EVERY
  size. The gates miss whole paths — forks, short spawns — so never
  treat "nothing denied me" as approval. Shape it as the clarify
  skill
  does: numbered build steps (five max), what you are not building, how
  done is observed, a concrete cost line, the ask on its own line.
- `- [ ] N. <item>` for every requirement, constraint, and edge case,
  one per line.
- `- [ ] V. fresh-eyes verification passed` as the last item.

The spawn guard denies serious delegation until this file carries all
three parts, so write it before the first worker, not after.

## 3 · Hand the work out

Load `orchestrator:playbook` before you hand anything out OR verify —
small work reaches step 4 without ever spawning, and the playbook is
where the verifier's effort, the per-wave review and the skip rule
live. Then:

- Independent phases go out TOGETHER in one message; only a phase that
  consumes an earlier one's output waits.
- Every worker spec cites the ledger items it covers.
- Size each worker's effort on what the job needs to be right and
  fast, never on what it costs.
- Name every substantive worker, and parallel editors get
  `isolation: "worktree"`.
- Dismiss a worker with `{"type": "shutdown_request"}` the moment its
  report is accepted. Never leave finished workers stacked.
- Send a `watchdog` worker (sonnet, low) out WITH the wave. Its one job
  is to LOOP the watchdog command from your profile
  (`python3 "<path>" --watch`, each call returns within ~100s) and to
  report only `unborn` or `stalled`. A spawn is not a start. You do not
  poll and you do not wait — act when it speaks.

## 4 · Verify the close

ONE fresh agent that did not build the work, handed the original
request, the ledger path, and the diff — a concrete
`git diff <base>..HEAD`, not "go find what changed". Only it closes
`- [ ] V.`.

It is opus. The playbook sets its effort.

Findings become new phases; re-verify after fixing. A cycle that
repeats a finding is disagreement, not progress: stop and put it to the
user. Cap at three verify-fix cycles regardless, then stop and report
what is still open.

Effort sizing, the per-wave background review, and when a skip is
allowed: the playbook carries all three, and you loaded it in step 3.

## Stop and tell the user when

- an answer you need cannot be obtained, and proceeding either way
  would make the work useless if wrong;
- a tier declines a task twice (never reword it past a classifier);
- the third verify cycle still has findings.
