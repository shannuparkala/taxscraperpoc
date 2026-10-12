---
status: confirmed
figures_as_of: 2026-10-11
figures_source_url: https://www.maine.gov/revenue/sites/maine.gov.revenue/files/2026-05/ind_tax_rate_sched_2026_rev.pdf
---

# Maine 2026: Income Basis in Assistant Answers

Research for the assistant's salary-versus-taxable-income regression cases,
not engine constants or a rule table supplied to the answering model.

## Official Inputs

Maine Revenue Services' [2026 individual income tax schedule, revised May 20,
2026](https://www.maine.gov/revenue/sites/maine.gov.revenue/files/2026-05/ind_tax_rate_sched_2026_rev.pdf)
states these amounts in "Single Individuals and Married Persons Filing
Separate Returns" and the "Personal Exemption" / "Standard Deduction" lines:

| Single filer, tax year 2026 | Official amount |
| --- | --- |
| Taxable income less than $27,400 | 5.8% of taxable income |
| $27,400 to less than $64,850 | $1,589 plus 6.75% of the excess over $27,400 |
| $64,850 or more | $4,117 plus 7.15% of the excess over $64,850 |
| Basic standard deduction | $15,700 |
| Personal exemption | $5,300 |

Every input above is from that revised schedule. Its note (1) also imposes a
2% surcharge on a single filer's taxable income above $1,000,000; neither
regression case reaches it. The schedule expressly says not to use it for
wage withholding. The agency's [2026 forms index](https://www.maine.gov/revenue/tax-return-forms/individual-income-tax-2026)
links the revised schedule.

## Two Different Starting Amounts

For the salary question, assume a full-year resident who is not a dependent,
under age 65 and not blind, with wages equal to federal and Maine AGI, no
adjustments or Maine modifications, the basic standard deduction and personal
exemption, and no credits. The assumed $75,000 AGI is below the statutory
phaseout starting amounts before inflation indexing: $80,000 for the standard
deduction ([36 M.R.S. 5124-C](https://legislature.maine.gov/statutes/36/title36sec5124-C.html))
and $266,700 for the exemption ([36 M.R.S. 5126-A](https://legislature.maine.gov/statutes/36/title36sec5126-A.html));
indexing is governed by [36 M.R.S. 5403](https://legislature.maine.gov/statutes/36/title36sec5403.html).

Derived from the revised schedule's inputs:

1. Maine taxable income: $75,000 - $15,700 - $5,300 = $54,000.
2. Excess over the applicable threshold: $54,000 - $27,400 = $26,600.
3. Tax before credits: $1,589 + ($26,600 x 6.75%) = $3,384.50.
4. Marginal rate: 6.75%; effective rate on the assumed $75,000 gross income:
   $3,384.50 / $75,000, approximately 4.51%.

If the supplied $75,000 is already Maine taxable income, deductions and
exemptions must not be subtracted again:

1. Excess over the applicable threshold: $75,000 - $64,850 = $10,150.
2. Tax before credits: $4,117 + ($10,150 x 7.15%) = $4,842.725,
   displayed as $4,842.73 to the nearest cent (half up).
3. Marginal rate: 7.15%; effective rate on that taxable-income basis is
   approximately 6.46%.

These are conditional pre-credit liability estimates, not withholding or a
balance due. The schedule does not specify return-line whole-dollar rounding;
the displayed cents are not a claim about filing instructions. The live eval
also accepts the nearest whole-dollar estimates, $3,385 and $4,843.

## Regression Risks

Use the schedule's prescribed base tax, not an exact sum of lower brackets.
Summing unrounded brackets gives $3,384.70 or $4,842.80; rounding each bracket
separately gives $4,842.81 in the taxable-income case. Those are different
methods, not additional totals to show beside the prescribed-schedule result.

The reported old answer used a $15,300 deduction, which is not the revised
schedule's amount, and its $3,374.88 headline disagreed with its own steps.
The comparison answer's roughly $3,750 salary estimate is not supported by the
official inputs under the assumptions above. Do not teach the assistant to
repeat either answer. Keep the prompt generic and require live verification
of jurisdiction, tax year, revision, income basis and calculation method.