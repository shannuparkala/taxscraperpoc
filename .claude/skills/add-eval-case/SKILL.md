---
name: add-eval-case
description: Add one workpaper/return pair to the benchmark suite as an eval case, with an expected.json the user verifies line by line.
argument-hint: "[case id, e.g. 'basic-5' or 'cs-2' or 'adv-rotated-1099b']"
disable-model-invocation: true
---

Add eval case `$ARGUMENTS`.

## The PII boundary, before anything is written

The workpaper/return pairs are real client documents. `Files/` is gitignored and
stays that way; nothing is copied out of it. The expected figures are taken off
a real filed return, so they are client data too.

**First run only** - confirm `.gitignore` carries these, and add them if not:

```
# Eval cases built from the real client corpus.
evals/cases/
evals/REPORT.md
```

Then keep to the split:

- `evals/cases/<id>/` - **gitignored.** `expected.json`, the source filenames,
  everything with a figure in it.
- `evals/CASES.md` - **committed.** One row per case: id, tax year, forms
  exercised, what it is for, adversarial condition if any. No amounts, no
  filenames, no names. This is how the repo records that the suite has teeth
  without carrying a byte of anyone's return.
- `evals/irs_ats/` - published IRS MeF ATS scenarios are synthetic test data,
  not client data, and may be committed.

In chat: figures on a line are fine, because the user has to verify them and it
is their own data in their own session. **Identity fields are not** - no name,
SSN, address, account number or date of birth, in chat or in any file. Refer to
the case by its id.

`make eval` (`python -m evals.run`) scores the cases. This command builds them.

## Do not build expected.json with our own extractor

Running the app's extractor over the accountant copy and saving what it returns
produces a case the app scores 100% on while measuring nothing at all. It is
circular, and it fails silently and permanently - the suite looks green
precisely where the extractor is wrong.

The expected figures come from **reading the filed return**, line by line, and
the user confirms each one. Where a figure is read off the PDF to save typing,
it is a proposal shown for confirmation, never an expectation until confirmed.

## Build the case

1. **Identify the pair.** The workpaper (input) and the accountant copy (the
   filed return, the truth). Confirm with the user which files these are.

2. **Read the filed return** and record, per line actually used: node id, form,
   line, label, amount. Node ids follow the `tax-architecture` convention -
   `f1040.l11`, `scha.l5e`, `qdcgtw.l25`.

3. **Show the user the proposed expectations** in form order, in batches they
   can actually check, and mark each `"verified": true` only on their say-so. An
   unverified line is carried but does not score - it cannot fail the suite and
   it cannot pass it.

4. **Write `evals/cases/<id>/expected.json`.** The harness (`evals/harness.py`)
   scores three layers from it, so it holds three things:

   - `inputs` - the figures **as the documents state them**, in the graph's
     fact vocabulary (`MONEY_FIELDS`: `wages`, `taxable_interest`,
     `federal_withheld_w2`, `scha_l5b`, ...). Extraction is scored against
     these. Read them off the source documents, not off the return.
   - `household` - filing status and ages; never a name or a date of birth.
   - `lines` - the filed return, per line. Calculation (the engine fed the
     verified `inputs`) and end-to-end (the pipeline) are scored against these.

   Calculation runs only when **every** input is verified - a guessed input
   would score the engine against the wrong question.

```json
{
  "id": "basic-5",
  "tax_year": 2025,
  "kind": "reconciled",
  "source": { "workpaper": "Files/<workpaper>.pdf", "filed_return": "Files/<copy>.pdf" },
  "household": {
    "filing_status": "married_joint",
    "taxpayer_age": 71, "spouse_age": 68,
    "resident_state": null,
    "dependents": [ { "relationship": "child", "age": 9, "ctc": true } ]
  },
  "inputs": [
    { "field": "wages", "amount": "0.00", "verified": true }
  ],
  "lines": [
    { "node": "f1040.l11a", "amount": "0.00", "verified": true }
  ],
  "expected_flags": [
    { "kind": "review_item", "match": "Confirm filing status before filing" }
  ],
  "tolerance": null,
  "notes": "Reconciles through the Tax Table, not the rate schedule, plus §199A."
}
```

   Flag kinds: `review_item` (regex over title and description), `unsupported`
   (`node`), `unplaced` (`field`), `layout_warning` (regex), `not_fileable`.
   `tolerance` defaults to `CALC_TOLERANCE_DOLLARS`.

5. **Record the row in `evals/CASES.md`.** No amounts.

## Adversarial cases

For a case whose point is a failure mode - rotated pages, a poor scan,
duplicates, a W-2c, another person's document in the bundle, missing pages -
**the expected result is a correct flag, not a number.** Use `"kind":
"adversarial"` and put the requirement in `expected_flags`: which review item
must be raised, on which line or document. A case that expects the pipeline to
guess correctly through a defect is scoring the wrong thing.

Two of these already have history and should say so in `notes`: rotated pages
are trap 12 (five 1099-B pages at 90° with `/Rotate` set to 0), and a prior-year
return in the bundle is trap 11 (its figures inform comparison and must never
reach the merge - a doubled wage or withholding figure is the signature).

## Cases whose expectation is not a clean return

Some pairs are worth adding precisely because the pipeline used to refuse them.
CS 2 has no W-2, Basic 4's identity came off 1099s, Basic 9 has one
uncorroborated spouse name. The expectation for each is a **computed return with
a named flag** - filing status inferred, review item present, and at or below
the flagged threshold the item titled "Confirm filing status before filing" -
not a refusal, and not a joint return. Trap 30.

## Report

Case id, which pair, lines recorded and how many the user verified, expected
flags, the `CASES.md` row, and the gitignore state. Confirm no committed file
gained a figure, a filename or a name.
