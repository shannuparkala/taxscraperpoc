# Depreciation calculator — validation record

Last run: 2026-10-07. Every row below is an automated test. Re-run with:

```bash
cd backend && python -m pytest tests/test_depreciation_validation.py tests/test_depreciation_engine.py -q
```

## Sources compared

1. **IRS Publication 946 (2025) worked examples.** These are the figures the IRS prints. I downloaded the PDF from irs.gov and parsed it with PyMuPDF; page references are in each test's docstring.
2. **IRS Revenue Procedures** for the §280F limits (2021-31, 2022-17, 2023-14, 2024-13, 2025-16, 2026-15) and the §179 limits (the Form 4562 instructions for each year; Rev. Proc. 2025-32 for 2026).
3. **An independent first-principles MACRS computation.** It is written in the test file from the statutory method: declining balance switching to straight line, and the half-year, mid-quarter and mid-month fractions. It shares no code and no table with the engine.

**What was not available:** a commercial depreciation calculator or a CPA-reviewed spreadsheet. Neither could be reached from this environment, so the "second independent source" is source 3. Before relying on the calculator for filed returns, a reviewer should spot-check a handful of the scenarios below against the firm's own depreciation software.

## Scenarios

| # | Scenario | Expected (source) | Calculator | Result |
|---|---|---|---|---|
| 1 | $10,000 7-year office furniture, Aug. 11, 2025, half-year | 1,429 / 2,449 / 1,749 / 1,249 / 893 / 892 / 893 / 446 (Pub. 946 ch. 4, MACRS Worksheet example) | same | ✅ |
| 2 | Building + land $120,000 (land $20,000), March, nonresidential | 2,033 / 2,564 / 2,564; basis $100,000 (Pub. 946 ch. 4 Ex. 1, Table A-7a) | same | ✅ |
| 3 | Machine $4,000 Jan, furniture $1,000 Sept, computer $5,000 Oct — mid-quarter | Year 1: 1,000 / 107 / 250. Year 2: 857 / 255 / 1,900 (Pub. 946 ch. 4 Ex. 2) | same; mid-quarter applied | ✅ |
| 4 | $10,000 5-year, Dec. 2, 2022, only asset — mid-quarter | 500 / 3,800 / 2,280 / 1,368 (Pub. 946 ch. 4) | same | ✅ |
| 5 | $450,000 qualified property, Jan. 7, 2025, acquired before Jan. 20, 2025 | 40% special allowance = $180,000 (Pub. 946 ch. 3) | $180,000; MACRS basis $270,000 | ✅ |
| 6 | $2,500,000 machinery + $25,000 saw, 2025, Section 179 | Maximum deduction $2,500,000; machinery basis $25,000 (Pub. 946 ch. 2) | same | ✅ |
| 7 | $4,050,000 machinery, 2025 | Dollar limit reduced to $2,450,000 (Pub. 946 ch. 2, Jane Ash) | same | ✅ |
| 8 | $6,500,000 Section 179 property, 2025 | No Section 179 deduction (Pub. 946 ch. 2) | dollar limit $0 | ✅ |
| 9 | Heavy SUV, 2025, Section 179 | Capped at $31,300 (Pub. 946 ch. 2) | $31,300 | ✅ |
| 10 | $14,500 car, Apr. 15, 2025, elected out of bonus | $2,900, below the $12,200 limit (Pub. 946 ch. 5) | $2,900 | ✅ |
| 11 | $18,000 pickup over 6,000 lb, June 2021, $10,000 Section 179 | MACRS 2021–2024 totals $6,618 (Pub. 946 ch. 5, Ellen Rye) | $6,618 | ✅ |
| 12–17 | Passenger car first-year cap, with / without bonus, 2021–2026 | 18,200/10,200; 19,200/11,200; 20,200/12,200; 20,400/12,400; 20,200/12,200; 20,300/12,300 (Rev. Procs., Tables 1 and 2) | same, each year | ✅ |
| 18 | $60,000 car, 2026, 100% bonus | Year 1 $20,300; year 2 = (60,000 − 20,300) × 32% = $12,704 (Rev. Proc. 2019-13 method) | same; total recovers $60,000 | ✅ |
| 19 | $100,000 5-year, 2026, 100% bonus | $100,000 in year 1 | same | ✅ |
| 20 | Same asset, election out of bonus | 20 / 32 / 19.2 / 11.52 / 11.52 / 5.76% (Table A-1) | same | ✅ |
| 21 | 2026 Section 179 phase-out at 4,090,000 / 4,090,001 / 5,000,000 / 6,650,000 / 9,000,000 | Limit 2,560,000 / 2,559,999 / 1,650,000 / 0 / 0 (Rev. Proc. 2025-32) | same | ✅ |
| 22 | Residential rental, January, $350,000 incl. $50,000 land | 3.485% then 3.636% of $300,000 (Table A-6) | 10,455 / 10,908 | ✅ |
| 23 | Mid-quarter test: 40.000% vs 40.001% of basis in Q4 | Half-year vs mid-quarter (Pub. 946: "more than 40%") | same | ✅ |
| 24 | California 2026, $100,000 asset, federal 100% bonus | State addback $80,000, recovered exactly $80,000 later (R&TC 17250) | same; reverses to $0 | ✅ |
| 25 | Acquired Jan. 19 vs Jan. 20, 2025 | 40% vs 100% (Notice 2026-11) | same | ✅ |
| 26–55 | First-principles cross-check: 3, 5, 7, 10, 15, 20-year × half-year and mid-quarter Q1–Q4 | Formula schedule | within IRS table rounding (≤0.02% of basis per year) and totals exact | ✅ |
| 56–79 | First-principles cross-check: 27.5- and 39-year × each placed-in-service month | Formula schedule | within IRS table rounding (≤0.004% of basis per year) and totals exact | ✅ |

### Why the first-principles check uses a tolerance

The engine uses the IRS percentage tables, as the IRS instructs. The tables round to two or three decimals and force each column to total exactly 100%, so a single year can differ slightly from the unrounded formula:

- **39-year property (Table A-7a):** years 2–39 are 2.564% (1/39 rounded). The remaining 2.568% is split between year 1 and year 40 by months in service. So a January building's first year is 2.461% printed, against 2.457% exact.
- **7-year property, mid-quarter Q2 (Table A-3):** the final year prints 3.34%, against 3.326% exact.

These differences are 0.004–0.014% of basis. A wrong table or a wrong column would be off by whole percentage points, so the tolerance still catches every real error.

## A note on a competitor's figure

A competitor's calculator shows a $100,000 heavy vehicle placed in service on 12/28/2023 (Section 179 $28,900, 80% bonus) depreciating at the half-year rates 20% / 32% / 19.2%, giving $2,730.24 for 2025. With that as the only asset placed in service in 2023, 100% of the year's depreciable basis was placed in service in the fourth quarter. Pub. 946's 40% test therefore requires the **mid-quarter** convention (Table A-5: 5% / 38% / 22.8%). This calculator gives $711, $5,404 and **$3,242** for 2023–2025. The calculation tape shows each step.

## Property and boundary tests

These are in `tests/test_depreciation_engine.py`. The property tests use 150 seeded random multi-asset, multi-method scenarios. For each one they check that:

- every year's deduction is non-negative;
- total depreciation never exceeds depreciable basis;
- the schedule plus any Section 179 carryforward equals the basis exactly;
- identical inputs give identical outputs.

Forty more seeded cases check that the first-year and total deductions increase with cost.

The boundary tests cover:

- an acquisition on Jan. 19 vs Jan. 20, 2025;
- placement on Dec. 31 vs Jan. 1;
- basis exactly at the Section 179 limit and threshold;
- zero taxable income;
- a mid-year state rule change (Delaware 2026, which keys on acquisition date);
- unsupported tax years.
