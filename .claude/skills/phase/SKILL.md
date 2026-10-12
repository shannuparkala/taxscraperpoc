---
name: phase
description: Run one numbered phase of the tax engine refactor from docs/refactor-plan.md, then stop and report.
argument-hint: "[phase number, 1-6]"
disable-model-invocation: true
---

Run phase `$ARGUMENTS` of the refactor.

## Read one phase, not the plan

`docs/refactor-plan.md` holds all six. Read the `## Guiding architecture`
section - it constrains every phase - and the one `## Phase $ARGUMENTS`
section. Do not read the other phases: knowing what Phase 4 wants is how Phase 2
grows a reporting layer nobody asked for yet.

The notes under `# Notes added while scaffolding the commands` are context, not
steps. If the phase you are running hits one of the open questions listed there,
raise it before you build on either answer.

## Before the first edit

- **Branch.** Work on `refactor/tax-engine-v2`. If it does not exist, create it
  from `feature/mainprototype`, which is where the real work lives. Never work
  on `main` - it is an unrelated web upload that holds un-redacted tax PDFs.
- **Baseline.** If the phase changes anything the engine computes, record the
  current numbers for the reconciled benchmarks first (CS 2 and Basic 5). A
  diff against a baseline you captured after the change proves nothing.

## While running it

- The plan's numbered steps are the scope. Do every one of them; do not start
  the next phase, and do not fix things the phase did not ask about. Note them
  and move on.
- Where a step says to review something with the user - Phase 1.2 waits on
  approval of `docs/deadcode-report.md`, Phase 6.1 waits on each
  `expected.json` - stop there and wait. That is the point of the step.
- `CLAUDE.md` still governs. The four zones, the egress guard, no PII in a log
  or a commit, no LLM producing a final number, and the traps list, which is a
  record of regressions that already shipped. A phase that contradicts one of
  those is a question for the user, not a judgement call.
- Prefer a flagged result to a refusal. Trap 30 is the whole argument.

## Before reporting the phase done

```
cd backend && python -m pytest -q
cd backend && python -m ruff check app tests
cd backend && python -m mypy app
```

Run the security subset too if the phase touched masking, the guard, the vault
or the audit log: `python -m pytest -m security -q`. A change that breaks one of
those is wrong - the test is not.

## Report

Stop. Do not roll into the next phase. Report, in this order:

1. **Done** - each numbered step, with what changed and where.
2. **Not done** - any step you could not complete, and why. Say it plainly
   rather than reporting a phase green with a hole in it.
3. **Verification** - test, ruff and mypy results as run, and the benchmark
   comparison if the phase moved a figure.
4. **Decisions taken** - anything the plan left open that you resolved, so it
   can be reversed cheaply.
5. **Next** - the one-line name of the next phase, and anything it now needs
   that it did not before.
