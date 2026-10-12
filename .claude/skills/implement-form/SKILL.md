---
name: implement-form
description: Build one tax form or worksheet as calculation-graph nodes, one node per line, with constants, tests at every threshold, and a benchmark check.
argument-hint: "[form, e.g. 'Schedule D' or 'Form 8889' or 'IL-1040']"
---

Implement `$ARGUMENTS` as nodes in the calculation graph.

Read the `tax-architecture` skill first. It defines node identity, `NodeResult`,
rounding and `UnsupportedItem`, and this builds against it.

## 1. Research before you write

Run `/research-tax-rule $ARGUMENTS` and work from the note it leaves in
`docs/tax-research/`. It checks the cache before it searches, so this is cheap
when the note already exists.

You need, before the first node: every line of the form in its own order and
wording, every figure with its authority, every threshold and phase-out with its
range endpoints, and the form's own rounding instruction. Implementing from
memory of how a form usually works is how a superseded 2024 figure ships looking
settled.

## 2. Enumerate every line, including the ones you will not compute

Work from the official instructions, top to bottom, and give **every** line a
node - including lines out of scope for now. Those get an `UnsupportedItem` node
naming what is unsupported.

A line that is simply absent from the graph is indistinguishable, on the
rendered return, from a line that computed zero. That is the whole of trap 9 and
trap 32: a well-formed return of zeros reads exactly like a real one, and zero
in a money column is itself a figure.

## 3. Write the nodes

In official form order, one per line, each declaring its `inputs`. Constants
through `tax_authority.py` - never a number in a node body, `verified=False`
until someone has checked the pairing against primary text.

Then invert `inputs` across the graph to fill `feeds_into`, and assert the graph
is still acyclic at assembly.

**If this form consumes a fact the pipeline does not yet extract, that is half
the work, not a detail.** Field names are a contract with two ends: the
extraction prompt names them and the engine consumes them, and when the two
disagree the line is structurally always zero with nothing raising an error.
`federal_withheld` was in neither for a while, so `total_payments` could never
be anything but zero and no return could ever produce a refund. See trap 17.
`ENGINE_MONEY_FIELDS` derives the vocabulary from the engine's own dataclasses
so the two cannot drift - extend it there, and check the form-specific
extraction hint for this document type actually asks for the field.

## 4. Tests, at the edges

In `backend/tests/`, for this form:

- every threshold and phase-out, at the endpoint, one cent either side, and in
  the middle of the range - for **each filing status**, since the endpoints
  differ by status and a single-status test proves the least interesting case;
- each `UnsupportedItem` line: it raises, the flag propagates downstream, and
  the rest of the return still computes;
- rounding, where this form rounds - `ROUND_HALF_UP`, and check a figure ending
  in exactly .50, which is where banker's rounding gives a different answer;
- provenance: every node this form adds returns a formula with substituted
  operands and either an authority or a source fact.

Invented values only. There is no `tests/fixtures/synthetic.py`; write clearly
fake figures inline, and use the reserved surrogate ranges the egress guard
already knows (SSN 666-xx-xxxx, `@example.com`, 555-01xx).

## 5. Check it against the benchmarks

Two cases are reconciled against the filed return and are the first measurement,
not the last:

- **CS 2** - S-corp / K-1, no W-2. Line 6b is correct; the open gaps are Form
  7203, schedule rendering and rounding.
- **Basic 5** - reconciles only through the **Tax Table**, not the rate
  schedule, plus §199A. If a taxable income under $100,000 comes out a few
  dollars off the accountant's figure, this is why: the Tax Table is a bracketed
  lookup and the rate schedule is not, and they do not agree.

If this form moves a figure on either, say so with both numbers. If it moves
neither, say that too - a form that changes nothing on the cases that exercise
it usually is not wired in.

## 6. Before reporting

```
cd backend && python -m pytest -q
cd backend && python -m ruff check app tests
cd backend && python -m mypy app
```

Then run the form's path end to end at least once on a real workpaper. A branch
that has never executed is not tested code whatever it looks like - trap 32 is
the standing example: fixing the bug in front of it let an `AttributeError` on a
non-existent enum member escape for the first time, and the whole output stage
failed where it had previously only logged. Expect the next thing along a
never-run path to be broken too.

## Report

Lines implemented, lines deliberately left `UnsupportedItem`, constants added
and whether each is `verified`, new facts the extractor now has to supply, the
benchmark comparison, and test results as run. Never print a taxpayer value -
identify runs by workflow id and figures by line.
