# Eval cases

One row per case. **No amounts, no filenames, no names** - the real cases are
built from client returns and live under `evals/cases/`, which is gitignored.
This file is how the repository records that the suite exists and what it
covers, without carrying a byte of anyone's return.

Run with `python -m evals.run` (or `make eval`); see `evals/run.py`.
Real cases are added with `/add-eval-case <id>`, and a line scores only once the
user has verified it against the filed return.

## Real workpaper/return pairs (gitignored)

| Case | Tax year | Forms exercised | What it is for | Adversarial condition |
|---|---|---|---|---|
| _none yet - add with `/add-eval-case`_ | | | | |

## Synthetic adversarial cases (committed, invented values)

Built at run time by `evals/synthetic/build.py`. The expectation is a correct
flag, not a guess through the defect.

| Case | Tax year | Forms exercised | What it is for | Adversarial condition |
|---|---|---|---|---|
| adv-rotated-1099b | 2025 | W-2, 1099-B | Trap 12: the turned page is read, and the rotation recorded | Page turned 90 degrees, /Rotate 0, no text layer |
| adv-poor-scan | 2025 | W-2 | Low OCR confidence raises a review item | Low-resolution speckled scan |
| adv-duplicate-w2 | 2025 | W-2 | Counted once, and the duplicate surfaced | The same W-2 twice |
| adv-w2c | 2025 | W-2, W-2c | The corrected figure, once, and the correction flagged | A W-2c correcting box 1 |
| adv-other-person | 2025 | W-2 | Another person's form never reaches the return, and is flagged | A W-2 issued to someone else |
| adv-missing-pages | 2025 | 1099-B | The gap in a paginated statement is flagged | Page 2 of 3 absent |
| adv-prior-year | 2025 | W-2, prior-year 1040 | Trap 11: last year's figures never summed in | Prior-year return in the bundle |

## IRS MeF ATS scenarios

None placed in `evals/irs_ats/`. Step 6.5 applies when they are.
