---
name: trace-check
description: Verify that every figure on a computed return traces back through the calculation graph to a source document or a cited authority. Read-only.
argument-hint: "[sample | eval case id | workflow id]"
disable-model-invocation: true
context: fork
agent: eval-analyst
background: false
allowed-tools: Read, Grep, Glob, Bash
---

Check the provenance of the return identified by `$ARGUMENTS`. `sample` means
the built-in sample return; anything else is an eval case id or a workflow id.

Read-only. You report; you do not fix.

## Never print a taxpayer value

Figures by line id and rough magnitude, people by workflow id. A trace report
naming a taxpayer is a breach, not a deliverable.

## The property being checked

Every figure on the return terminates, through `explain(node_id)`, in one of
exactly two things: a **source fact** carrying document, page, field and
confidence, or a **statutory constant** carrying an `Authority` with a
resolvable URL. Nothing else is a legitimate leaf. A figure that bottoms out in
neither is either invented or copied from somewhere the report cannot name, and
both look identical on a finished return.

Walk it from every line of Form 1040 and every schedule the return used, not
from a sample of them.

## What to check

**Structure**
- `explain(node_id)` terminates for every line. A node whose tree does not reach
  a leaf is the finding, whatever its amount.
- No cycles.
- Each `NodeResult.inputs` matches its `Node.inputs` exactly. A compute that
  reached a figure it did not declare is the defect the declared-inputs design
  exists to prevent, and the provenance record will say otherwise.
- Every node has a `formula` with **substituted operands** - `"7,410 + 1,236 =
  8,646"`. A formula still carrying symbols is a template that never ran.

**Source facts**
- Document, page and field present. Confidence present. Bounding box present
  where OCR produced one.
- The page is inside that document's page range.
- The document type can actually report that field - a wage figure attributed to
  a brokerage statement is a mis-attribution even when the amount is right.
- **The `documents[0]` signature.** If many facts share one document, or share
  the first document in the workflow, that is trap 34: the persist loop once set
  `document = primary_document` for every fact, which mislabelled provenance and
  then flagged 84 cleanly-read figures on Basic 7 because one handwritten page
  sat at the head of an unordered query. A per-fact flag rate much above ~32% on
  a comparable extraction count is the same bug returning.

**Authorities**
- Every statutory leaf cites one, with an `https://` URL.
- Flag any constant used whose pairing is `verified=False` in
  `tax_authority.py`. Not an error - a list the user needs.

**Agreement with the engine**
- Run `calculation_trail.verify(rows, result)` and report every complaint in
  full. It recomputes each row's formula against the engine, so it separates
  "the trail drifted" from "the tax is wrong" in one step - do this before
  theorising about any figure.

**Unsupported lines**
- Each `UnsupportedItem` line carries a reason, propagated its flag downstream,
  and left the return marked not fileable. A line flagged unsupported whose
  downstream lines are clean is a flag that did not propagate.

## Output

1. **Untraceable figures** - line id, amount magnitude, where the tree stopped.
   Lead with these; this is what the command is for.
2. **Mis-attributed sources** - line id, what it claims, why it cannot be that.
3. **`verify` complaints** - in full.
4. **Unverified authorities** - constant name and line, for the user to confirm.
5. **Counts** - nodes walked, nodes traced clean, facts with a bounding box, and
   the per-fact flag rate.
