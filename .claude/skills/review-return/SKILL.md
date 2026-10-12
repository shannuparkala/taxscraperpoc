---
name: review-return
description: Senior-reviewer pass over a computed return, like a CPA reviewing a preparer's work. Read-only.
argument-hint: "[workflow_id]"
disable-model-invocation: true
context: fork
agent: eval-analyst
background: false
allowed-tools: Read, Grep, Glob, Bash
---

Review the return produced by workflow `$ARGUMENTS` as a senior tax reviewer
would. Read-only: you report, you do not fix.

## Never print a taxpayer value

The database holds real client data. Refer to people by workflow id and to
figures by line and rough magnitude. A review memo containing a name or an SSN
is a breach, not a deliverable.

## Where to get the material

- `GET /api/workflows/{id}` - stages, status, `llm_usage`.
- `GET /api/workflows/{id}/report.html` - the calculation report.
- `GET /api/workflows/{id}/explanation` - the plain-English narrative.
- `GET /api/review/queue?workflow_id={id}` - **pass the workflow id.** The
  endpoint otherwise returns the oldest 100 pending items across the whole
  database and filtering client-side gives you nothing for the run you want.
  See trap 31 in `CLAUDE.md`.
- `calculation_trail.verify(rows, result)` returns a list of complaints, empty
  when every row's formula still reproduces the engine's number. Run it first:
  it separates "the trail drifted" from "the tax is wrong" in one step.

Open a source PDF only to confirm one specific value.

## Check

**Arithmetic and authority**
- `verify` complaints, in full. Any row whose formula no longer reproduces the
  engine's figure.
- Any constant used whose `Authority` pairing is `verified=False` in
  `tax_authority.py`.
- Components that do not add to their own stated subtotal.

**The inferences this pipeline makes rather than reads**
- Filing status: was it stated, carried from a prior year, or *inferred*? An
  inferred single always carries a review item, and at or below the flagged
  threshold the item says "before filing". Confirm the item is present and says
  which weakness drove it. Traps 13 and 30.
- Seniors: the additional amount is per entitlement, not per person over 65 - a
  spouse counts only on a joint return. Check the return's count against its
  filing status. Trap 33.
- Spouse boxes: a single return must not print a spouse name or SSN. Trap 33.
- Prior-year documents: their figures must inform comparison, never the merge.
  A doubled wage or withholding figure is the signature. Trap 11.

**Reasonableness**
- Effective rate, refund against total withholding, and any year-over-year swing
  where a prior year exists.
- Commonly missed: HSA forms, the qualified dividends worksheet, state refund
  taxability, the SALT cap, estimated payments, carryovers.
- Organizer answers implying a form that was not generated.
- Extractions below the confidence floor that move tax by more than $50.
- Coverage, not just confidence: a workpaper read at low page coverage can
  report high confidence on what it did read. Trap 8.

## Output

Three sections: **blocking issues**, **questions for the client**,
**informational notes**. Lead each item with the line id and the dollar impact.
