"""Form 1040 assembly.

Builds a complete individual return from extracted facts, following the actual
line ordering of Form 1040 so that each computed figure is traceable to a line a
preparer can point at.

Nothing here consults a language model. Given the same facts this produces the
same return, every time, and the arithmetic can be re-derived by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.services.tax_engine.computations import (
    ZERO,
    EitcResult,
    QbiResult,
    Schedule1A,
    ScheduleD,
    additional_child_tax_credit,
    additional_medicare_tax,
    capital_loss_carryover,
    capital_loss_limitation,
    child_tax_credit,
    earned_income_credit,
    medical_deduction,
    money,
    net_investment_income_tax,
    non_negative,
    qbi_deduction,
    salt_deduction,
    schedule_1a,
    schedule_d,
    self_employment_tax,
    standard_deduction,
    tax_with_capital_gains,
    taxable_social_security,
    to_cents,
    total,
)
from app.services.tax_engine.tax_tables import (
    LIMITS,
    FilingStatusTax,
    require_year,
    verify_tax_year,
)

logger = get_logger(__name__)
D = Decimal


@dataclass(slots=True)
class TaxpayerProfile:
    """Non-monetary facts that drive the computation.

    SECURITY: carries no identity data — no name, SSN, or address. The engine
    needs status and counts, not who the taxpayer is.
    """

    tax_year: int
    filing_status: FilingStatusTax = FilingStatusTax.SINGLE
    age_65_or_older: int = 0
    blind: int = 0
    can_be_claimed_as_dependent: bool = False
    qualifying_children: int = 0
    other_dependents: int = 0
    state_code: str | None = None
    #: Only consulted when filing separately, where it decides whether the
    #: Social Security worksheet applies thresholds at all. Defaults to
    #: False, the higher-tax reading, so an unanswered organizer question
    #: never quietly understates income.
    lived_apart_from_spouse: bool = False
    #: Age at the end of the year. Only the childless earned income credit
    #: needs it (§32 bounds that credit at 25 to 64); None means untested, and
    #: the credit is computed without the age condition rather than refused.
    taxpayer_age: int | None = None
    #: True when every business activity is a specified service trade. Only
    #: consulted above the §199A threshold, where an SSTB phases out.
    specified_service_trade: bool = False


@dataclass(slots=True)
class IncomeInputs:
    """Form 1040 lines 1-8 and Schedule 1 income."""

    wages: Decimal = ZERO                       # line 1a (W-2 box 1)
    tax_exempt_interest: Decimal = ZERO         # line 2a
    taxable_interest: Decimal = ZERO            # line 2b (1099-INT box 1)
    qualified_dividends: Decimal = ZERO         # line 3a (1099-DIV box 1b)
    ordinary_dividends: Decimal = ZERO          # line 3b (1099-DIV box 1a)
    ira_distributions: Decimal = ZERO           # line 4a
    ira_taxable: Decimal = ZERO                 # line 4b
    pensions: Decimal = ZERO                    # line 5a
    pensions_taxable: Decimal = ZERO            # line 5b
    social_security: Decimal = ZERO             # line 6a
    social_security_taxable: Decimal = ZERO     # line 6b
    capital_gain_loss: Decimal = ZERO           # line 7a, if already netted
    business_income: Decimal = ZERO             # Schedule 1 line 3 (Schedule C)
    other_gains: Decimal = ZERO                 # Schedule 1 line 4 (Form 4797)
    rental_income: Decimal = ZERO               # Schedule 1 line 5 (Schedule E)
    other_income: Decimal = ZERO                # Schedule 1 line 9


@dataclass(slots=True)
class CapitalGainInputs:
    """Schedule D detail. Field names carry Schedule D's own line numbers.

    Supplying this computes line 7a instead of taking it as a given. Two of
    these have no other way into the return: capital gain distributions are
    reported only on Form 1099-DIV, and both carryovers exist only on the prior
    year's return.
    """

    short_term_gain: Decimal = ZERO             # lines 1a-3 (Form 1099-B)
    short_term_from_k1: Decimal = ZERO          # line 5
    short_term_loss_carryover: Decimal = ZERO   # line 6, entered positive
    long_term_gain: Decimal = ZERO              # lines 8a-10 (Form 1099-B)
    long_term_from_k1: Decimal = ZERO           # line 12
    capital_gain_distributions: Decimal = ZERO  # line 13 (1099-DIV box 2a)
    long_term_loss_carryover: Decimal = ZERO    # line 14, entered positive

    def supplied(self) -> bool:
        """True when any component was given, so Schedule D should be run."""
        return any(
            money(getattr(self, f)) != ZERO
            for f in (
                "short_term_gain",
                "short_term_from_k1",
                "short_term_loss_carryover",
                "long_term_gain",
                "long_term_from_k1",
                "capital_gain_distributions",
                "long_term_loss_carryover",
            )
        )


@dataclass(slots=True)
class AdjustmentInputs:
    """Schedule 1 Part II — above-the-line deductions."""

    educator_expenses: Decimal = ZERO
    hsa_deduction: Decimal = ZERO
    self_employment_tax_deduction: Decimal = ZERO
    self_employed_retirement: Decimal = ZERO
    self_employed_health_insurance: Decimal = ZERO
    ira_deduction: Decimal = ZERO
    student_loan_interest: Decimal = ZERO
    other_adjustments: Decimal = ZERO


@dataclass(slots=True)
class DeductionInputs:
    """Schedule A itemized deduction components."""

    medical_expenses: Decimal = ZERO
    state_local_income_tax: Decimal = ZERO
    state_local_sales_tax: Decimal = ZERO
    real_estate_tax: Decimal = ZERO
    personal_property_tax: Decimal = ZERO
    mortgage_interest: Decimal = ZERO
    investment_interest: Decimal = ZERO
    charitable_cash: Decimal = ZERO
    charitable_noncash: Decimal = ZERO
    casualty_losses: Decimal = ZERO
    other_itemized: Decimal = ZERO
    force_itemize: bool = False                 # MFS where spouse itemizes


@dataclass(slots=True)
class AdditionalDeductionInputs:
    """Schedule 1-A — the deductions new for 2025 under Pub. L. 119-21.

    These sit on Form 1040 line 13b and are available whether or not the
    taxpayer itemizes, which is why they are their own group rather than part of
    ``DeductionInputs``: the Basic 5 benchmark takes the standard deduction and
    2,905 of overtime deduction on top of it.

    The senior part is not here — it is driven by ``TaxpayerProfile`` ages, not
    by an amount anyone reports.
    """

    qualified_tips: Decimal = ZERO          # Part II, W-2 box 7 / 1099 tips
    qualified_overtime: Decimal = ZERO      # Part III, W-2 box 1 overtime
    car_loan_interest: Decimal = ZERO       # Part IV, qualified vehicle loan


@dataclass(slots=True)
class PaymentInputs:
    federal_withheld: Decimal = ZERO            # line 25a-d
    estimated_payments: Decimal = ZERO          # line 26
    earned_income_credit: Decimal = ZERO        # line 27
    additional_child_tax_credit: Decimal = ZERO # line 28
    american_opportunity_credit: Decimal = ZERO # line 29
    other_payments: Decimal = ZERO
    other_nonrefundable_credits: Decimal = ZERO # Schedule 3 Part I
    #: Also line 26 — the prior year's overpayment carried in. Line 26 reads
    #: "estimated tax payments *and amount applied from* the prior return", so
    #: the two are one figure on the form but arrive from different places, and
    #: only this one has to come from last year's return.
    prior_year_overpayment_applied: Decimal = ZERO
    #: Line 36 — overpayment the taxpayer elects to carry forward rather
    #: than receive. An election, not a computation.
    apply_overpayment_to_next_year: Decimal = ZERO


@dataclass(slots=True)
class Line:
    """One computed return line, carrying its own provenance."""

    number: str
    label: str
    amount: Decimal
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "line": self.number,
            "label": self.label,
            "amount": str(self.amount),
            "note": self.note,
        }


@dataclass(slots=True)
class Return1040:
    """A fully computed individual return."""

    tax_year: int
    filing_status: str
    lines: list[Line] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    deduction_method: str = "standard"

    total_income: Decimal = ZERO
    adjusted_gross_income: Decimal = ZERO
    deduction_taken: Decimal = ZERO
    #: Line 13b — Schedule 1-A deductions, separate from line 12e.
    additional_deductions: Decimal = ZERO
    taxable_income: Decimal = ZERO
    tax_before_credits: Decimal = ZERO
    total_credits: Decimal = ZERO
    other_taxes: Decimal = ZERO
    total_tax: Decimal = ZERO
    total_payments: Decimal = ZERO
    #: Withholding alone. Form 1040 line 25d is *not* total payments — it
    #: excludes estimated payments and refundable credits — and a form
    #: where 25d + 26 does not foot to 33 is one a preparer cannot sign.
    federal_withheld: Decimal = ZERO
    refund: Decimal = ZERO
    amount_owed: Decimal = ZERO
    capital_loss_carryforward: Decimal = ZERO
    #: Next year's Schedule D lines 6 and 14, positive. A loss keeps its
    #: character when it carries, so the two cannot be reported as one number.
    capital_loss_carryforward_short: Decimal = ZERO
    capital_loss_carryforward_long: Decimal = ZERO
    #: Line 36 — the part of an overpayment carried to next year.
    applied_to_next_year: Decimal = ZERO
    #: Schedule D detail, when its components were supplied.
    schedule_d: ScheduleD | None = None
    #: Line 13a — Form 8995 working, when there was business income.
    qbi: QbiResult | None = None
    #: Line 13b — Schedule 1-A working, part by part.
    schedule_1a: Schedule1A | None = None
    #: Schedule EIC working, including why a zero credit is zero.
    eitc: EitcResult | None = None
    #: The components of line 23, so Schedule 2 can be rendered from them.
    self_employment_tax: Decimal = ZERO
    additional_medicare_tax: Decimal = ZERO
    net_investment_income_tax: Decimal = ZERO

    def line(self, number: str) -> Line | None:
        return next((l for l in self.lines if l.number == number), None)

    def to_dict(self) -> dict[str, Any]:
        """Serializable summary.

        SECURITY: amounts only. Identity never enters this structure, so it is
        safe to include in a masked LLM prompt for narrative generation.
        """
        return {
            "tax_year": self.tax_year,
            "filing_status": self.filing_status,
            "deduction_method": self.deduction_method,
            "totals": {
                "total_income": str(self.total_income),
                "adjusted_gross_income": str(self.adjusted_gross_income),
                "deduction_taken": str(self.deduction_taken),
                "additional_deductions": str(self.additional_deductions),
                "taxable_income": str(self.taxable_income),
                "tax_before_credits": str(self.tax_before_credits),
                "total_credits": str(self.total_credits),
                "other_taxes": str(self.other_taxes),
                "total_tax": str(self.total_tax),
                "total_payments": str(self.total_payments),
                "federal_withheld": str(self.federal_withheld),
                "refund": str(self.refund),
                "amount_owed": str(self.amount_owed),
                "capital_loss_carryforward": str(self.capital_loss_carryforward),
                "capital_loss_carryforward_short": str(
                    self.capital_loss_carryforward_short
                ),
                "capital_loss_carryforward_long": str(
                    self.capital_loss_carryforward_long
                ),
                "applied_to_next_year": str(self.applied_to_next_year),
            },
            "lines": [line.to_dict() for line in self.lines],
            "warnings": self.warnings,
        }


def _provisional_income_adjustments(adjustments: AdjustmentInputs) -> Decimal:
    """Worksheet line 7 — Schedule 1 lines 11 through 20, and 23 and 25.

    That range is not "every adjustment". Two boundaries matter and the earlier
    version got both wrong, in opposite directions:

    * **Student loan interest is Schedule 1 line 21, outside the range.** It was
      being subtracted, which understated provisional income and so understated
      the taxable benefit.
    * **The self-employment tax deduction is line 15, inside the range.** It was
      being excluded on the reasoning that it is derived later and the omission
      was "conservative". It is simply outside the worksheet's instruction, and
      excluding it overstated provisional income.
    """
    return total(
        [
            money(adjustments.educator_expenses),              # line 11
            money(adjustments.hsa_deduction),                  # line 13
            money(adjustments.self_employment_tax_deduction),  # line 15
            money(adjustments.self_employed_retirement),       # line 16
            money(adjustments.self_employed_health_insurance), # line 17
            money(adjustments.ira_deduction),                  # line 20
            money(adjustments.other_adjustments),              # lines 23 / 25
            # student_loan_interest is line 21 — deliberately absent.
        ]
    )


class Form1040Calculator:
    """Assembles Form 1040 from extracted facts."""

    def compute(
        self,
        *,
        profile: TaxpayerProfile,
        income: IncomeInputs,
        adjustments: AdjustmentInputs | None = None,
        deductions: DeductionInputs | None = None,
        additional_deductions: AdditionalDeductionInputs | None = None,
        payments: PaymentInputs | None = None,
        capital_gains: CapitalGainInputs | None = None,
    ) -> Return1040:
        require_year(profile.tax_year)
        adjustments = adjustments or AdjustmentInputs()
        deductions = deductions or DeductionInputs()
        additional_deductions = additional_deductions or AdditionalDeductionInputs()
        payments = payments or PaymentInputs()
        capital_gains = capital_gains or CapitalGainInputs()

        year = profile.tax_year
        status = profile.filing_status
        result = Return1040(tax_year=year, filing_status=status.value)

        verified, message = verify_tax_year(year)
        if not verified:
            result.warnings.append(message)

        # --- Income (lines 1-9) ------------------------------------------
        # Schedule D when its detail was supplied, otherwise the already-netted
        # figure. Running the schedule is strictly better: it is the only path
        # that can pick up capital gain distributions and prior-year carryovers.
        detail = capital_gains.supplied()
        if detail:
            sched_d = schedule_d(
                short_term_gain=money(capital_gains.short_term_gain),
                short_term_from_k1=money(capital_gains.short_term_from_k1),
                short_term_loss_carryover=money(
                    capital_gains.short_term_loss_carryover
                ),
                long_term_gain=money(capital_gains.long_term_gain),
                long_term_from_k1=money(capital_gains.long_term_from_k1),
                capital_gain_distributions=money(
                    capital_gains.capital_gain_distributions
                ),
                long_term_loss_carryover=money(
                    capital_gains.long_term_loss_carryover
                ),
                year=year,
                status=status,
            )
            result.schedule_d = sched_d
            capital_gain = sched_d.reportable
            carryforward = to_cents(sched_d.reportable - sched_d.net)
            if money(income.capital_gain_loss) not in (ZERO, sched_d.reportable):
                result.warnings.append(
                    f"Schedule D computes {sched_d.net} for line 7a but "
                    f"{money(income.capital_gain_loss)} was also supplied "
                    "directly. The schedule was used."
                )
        else:
            sched_d = None
            capital_gain, carryforward = capital_loss_limitation(
                money(income.capital_gain_loss), year, status
            )

        result.capital_loss_carryforward = carryforward
        if carryforward < ZERO:
            result.warnings.append(
                f"Capital loss limited this year; {abs(carryforward)} carries "
                "forward. Confirm the carryforward schedule."
            )

        # Business, other gains, rental and other income all reach the 1040
        # through Schedule 1, arriving as a single figure on line 8. They used
        # to be summed into total income without a line of their own, so the
        # form did not foot: the components printed on it added up to less than
        # line 9.
        schedule_1_income = total(
            [
                money(income.business_income),   # Schedule 1 line 3
                money(income.other_gains),       # Schedule 1 line 4
                money(income.rental_income),     # Schedule 1 line 5
                money(income.other_income),      # Schedule 1 line 9
            ]
        )

        income_before_social_security = total(
            [
                money(income.wages),
                money(income.taxable_interest),
                money(income.ordinary_dividends),
                money(income.ira_taxable),
                money(income.pensions_taxable),
                capital_gain,
                schedule_1_income,
            ]
        )

        # --- Social Security taxability (§86) -----------------------------
        # Computed here, not extracted: Form SSA-1099 reports the gross benefit
        # and says nothing about the taxable portion, because that depends on
        # the rest of the return. Waiting for a document to state line 6b meant
        # it was always blank and the benefits contributed nothing.
        #
        # An explicitly supplied taxable amount still wins — a prior-year
        # return or a preparer's worksheet may carry one, and recomputing over
        # the top of it would discard better information.
        social_security_taxable = money(income.social_security_taxable)
        if social_security_taxable <= ZERO and money(income.social_security) > ZERO:
            social_security_taxable = taxable_social_security(
                benefits=money(income.social_security),
                other_income=income_before_social_security,
                tax_exempt_interest=money(income.tax_exempt_interest),
                adjustments=_provisional_income_adjustments(adjustments),
                year=year,
                status=status,
                lived_apart_from_spouse=profile.lived_apart_from_spouse,
            )

        result.total_income = total(
            [income_before_social_security, social_security_taxable]
        )

        result.lines.extend(
            [
                Line("1a", "Wages, salaries, tips", to_cents(money(income.wages))),
                Line("2a", "Tax-exempt interest", to_cents(money(income.tax_exempt_interest)),
                     "Not included in total income"),
                Line("2b", "Taxable interest", to_cents(money(income.taxable_interest))),
                Line("3a", "Qualified dividends", to_cents(money(income.qualified_dividends)),
                     "Taxed at preferential rates"),
                Line("3b", "Ordinary dividends", to_cents(money(income.ordinary_dividends))),
                Line("4a", "IRA distributions", to_cents(money(income.ira_distributions))),
                Line("4b", "IRA distributions - taxable", to_cents(money(income.ira_taxable))),
                Line("5a", "Pensions and annuities", to_cents(money(income.pensions))),
                Line("5b", "Pensions - taxable", to_cents(money(income.pensions_taxable))),
                Line("6a", "Social security benefits", to_cents(money(income.social_security))),
                Line("6b", "Social security - taxable",
                     to_cents(social_security_taxable),
                     "Computed under §86 from provisional income"
                     if money(income.social_security_taxable) <= ZERO
                     and money(income.social_security) > ZERO
                     else ""),
                Line("7", "Capital gain or (loss)", capital_gain,
                     "After §1211(b) limitation" if carryforward < ZERO else ""),
                Line("8", "Additional income from Schedule 1", schedule_1_income,
                     "Business, other gains, rental, and other income"),
                Line("9", "Total income", result.total_income),
            ]
        )

        # Schedule D's own working, so line 7a can be tied back to the two
        # halves of the schedule rather than appearing as an unexplained total.
        if sched_d is not None:
            result.lines.extend(
                [
                    Line("D-7", "Schedule D: net short-term gain or (loss)",
                         sched_d.short_term_net,
                         f"After {money(capital_gains.short_term_loss_carryover)} "
                         "carried in"
                         if money(capital_gains.short_term_loss_carryover) > ZERO
                         else ""),
                    Line("D-15", "Schedule D: net long-term gain or (loss)",
                         sched_d.long_term_net,
                         f"Includes {money(capital_gains.capital_gain_distributions)} "
                         "of capital gain distributions"
                         if money(capital_gains.capital_gain_distributions) > ZERO
                         else ""),
                    Line("D-16", "Schedule D: net gain or (loss)", sched_d.net),
                ]
            )

        # --- Self-employment tax and its deduction ------------------------
        # Wages go in because the Social Security wage base is a ceiling on the
        # person, not on each source: Schedule SE line 8 subtracts wages already
        # taxed through payroll before applying the 12.4%.
        se_tax = ZERO
        se_income = money(income.business_income)
        if se_income > ZERO:
            se_tax, se_deduction = self_employment_tax(
                se_income, year, wages=money(income.wages)
            )
            # Only override when the caller did not supply the figure itself.
            if money(adjustments.self_employment_tax_deduction) == ZERO:
                adjustments.self_employment_tax_deduction = se_deduction

        # --- Adjustments (line 10) ---------------------------------------
        student_loan = min(
            money(adjustments.student_loan_interest),
            LIMITS[year].student_loan_interest_cap,
        )
        if money(adjustments.student_loan_interest) > student_loan:
            result.warnings.append(
                "Student loan interest limited to the statutory maximum."
            )
        educator = min(
            money(adjustments.educator_expenses), LIMITS[year].educator_expense_cap
        )

        total_adjustments = total(
            [
                educator,
                money(adjustments.hsa_deduction),
                money(adjustments.self_employment_tax_deduction),
                money(adjustments.self_employed_retirement),
                money(adjustments.self_employed_health_insurance),
                money(adjustments.ira_deduction),
                student_loan,
                money(adjustments.other_adjustments),
            ]
        )
        result.lines.append(Line("10", "Adjustments to income", total_adjustments))

        # --- AGI (line 11) ------------------------------------------------
        result.adjusted_gross_income = to_cents(result.total_income - total_adjustments)
        result.lines.append(
            Line("11", "Adjusted gross income", result.adjusted_gross_income)
        )

        # --- Deduction (line 12) ------------------------------------------
        itemized = self._itemized_total(
            deductions, result.adjusted_gross_income, year, status, result.warnings
        )
        standard = standard_deduction(
            year=year,
            status=status,
            age_65_or_older=profile.age_65_or_older,
            blind=profile.blind,
            can_be_claimed_as_dependent=profile.can_be_claimed_as_dependent,
            earned_income=money(income.wages) + non_negative(se_income),
        )

        if deductions.force_itemize or itemized > standard:
            result.deduction_taken = itemized
            result.deduction_method = "itemized"
            if deductions.force_itemize and itemized < standard:
                result.warnings.append(
                    "Itemizing was forced even though the standard deduction is "
                    "larger. Confirm this is intended (e.g. MFS where the spouse "
                    "itemizes)."
                )
        else:
            result.deduction_taken = standard
            result.deduction_method = "standard"

        result.lines.append(
            Line(
                "12",
                f"{result.deduction_method.capitalize()} deduction",
                result.deduction_taken,
                f"Standard {standard} vs itemized {itemized}",
            )
        )

        # --- Additional deductions (line 13b) -----------------------------
        # Schedule 1-A, new for 2025, carrying four unrelated deductions to one
        # line: tips, overtime, car loan interest and the senior allowance. All
        # four are available whether or not the taxpayer itemizes, which is the
        # point of them — the Basic 5 benchmark takes the standard deduction and
        # 2,905 of overtime deduction on top of it.
        #
        # Only the senior part used to be computed. A filer with qualified tips
        # or overtime lost that deduction entirely, which is why the benchmark's
        # line 13b came out blank against a stated 2,905.
        #
        # The senior part is also separate from — and on top of — the age-based
        # increase to the standard deduction already in line 12e, so a single
        # 65-year-old receives 2,000 there and 6,000 here.
        result.schedule_1a = schedule_1a(
            qualified_tips=money(additional_deductions.qualified_tips),
            qualified_overtime=money(additional_deductions.qualified_overtime),
            car_loan_interest=money(additional_deductions.car_loan_interest),
            seniors=profile.age_65_or_older,
            modified_agi=result.adjusted_gross_income,
            year=year,
            status=status,
        )
        result.additional_deductions = result.schedule_1a.total
        if result.additional_deductions > ZERO:
            parts = [
                label
                for label, amount in (
                    ("tips", result.schedule_1a.tips),
                    ("overtime", result.schedule_1a.overtime),
                    ("car loan interest", result.schedule_1a.car_loan_interest),
                    ("age 65 or older", result.schedule_1a.seniors),
                )
                if amount > ZERO
            ]
            result.lines.append(
                Line(
                    "13b",
                    "Additional deductions (Schedule 1-A)",
                    result.additional_deductions,
                    "Deduction for " + ", ".join(parts),
                )
            )

        # --- Qualified business income deduction (line 13a) ---------------
        # Form 8995. Twenty percent of pass-through business income, capped at
        # twenty percent of taxable income computed *before* this deduction —
        # which is why it has to be worked here, between line 12 and line 14,
        # rather than alongside the other deductions.
        #
        # The §199A figure is net of the three deductions attributable to the
        # business, so a Schedule C filer's QBI is their profit less the
        # deductible half of SE tax, their self-employed health insurance and
        # their self-employed retirement contributions.
        qbi_deduction_amount = ZERO
        gross_business = total(
            [money(income.business_income), money(income.rental_income)]
        )
        if gross_business > ZERO:
            deductions_against_qbi = total(
                [
                    money(adjustments.self_employment_tax_deduction),
                    money(adjustments.self_employed_health_insurance),
                    money(adjustments.self_employed_retirement),
                ]
            )
            taxable_before_qbi = to_cents(
                result.adjusted_gross_income
                - result.deduction_taken
                - result.additional_deductions
            )
            result.qbi = qbi_deduction(
                qualified_business_income=to_cents(
                    gross_business - deductions_against_qbi
                ),
                taxable_income_before_qbi=taxable_before_qbi,
                # Preferential income is excluded from the cap's base: §199A
                # deducts against ordinary income, not against capital gain.
                net_capital_gain=to_cents(
                    non_negative(capital_gain) + money(income.qualified_dividends)
                ),
                year=year,
                status=status,
            )
            qbi_deduction_amount = result.qbi.deduction
            if qbi_deduction_amount > ZERO:
                result.lines.append(
                    Line(
                        "13a",
                        "Qualified business income deduction (Form 8995)",
                        qbi_deduction_amount,
                        "Limited by taxable income"
                        if result.qbi.limited_by_taxable_income
                        else "",
                    )
                )
            if result.qbi.above_threshold:
                result.warnings.append(
                    "Taxable income exceeds the §199A threshold, where the "
                    "deduction is further limited by the business's W-2 wages "
                    "and property basis and a specified service trade phases "
                    "out. Neither figure is in the documents — the unlimited "
                    "amount is shown and must be confirmed on Form 8995-A."
                )

        total_deductions = to_cents(
            result.deduction_taken
            + qbi_deduction_amount
            + result.additional_deductions
        )
        result.lines.append(
            Line("14", "Total deductions", total_deductions)
        )

        # --- Taxable income (line 15) -------------------------------------
        unfloored_taxable_income = to_cents(
            result.adjusted_gross_income - total_deductions
        )
        result.taxable_income = non_negative(unfloored_taxable_income)
        result.lines.append(Line("15", "Taxable income", result.taxable_income))

        # The carryover to next year depends on taxable income, so it can only
        # be split here — after line 15 — not back where Schedule D was run.
        # That ordering is the form's own: the Capital Loss Carryover Worksheet
        # lives in the instructions and is worked after the return.
        #
        # It takes the *unfloored* figure. Line 15 itself stops at zero, but the
        # worksheet's line 1 says to enclose a loss in parentheses, and that
        # negative is the whole point: it measures how much of the 3,000
        # deduction the return actually had income to absorb. Passing the
        # floored zero instead would consume the deduction on paper and carry
        # 3,000 too little forward, every year, for exactly the taxpayers whose
        # deductions already exceed their income.
        if sched_d is not None:
            (
                result.capital_loss_carryforward_short,
                result.capital_loss_carryforward_long,
            ) = capital_loss_carryover(
                schedule_d=sched_d,
                taxable_income=unfloored_taxable_income,
                year=year,
                status=status,
            )

        # --- Tax (line 16) ------------------------------------------------
        # Only *long-term* gain is preferential. The Qualified Dividends and
        # Capital Gain Tax Worksheet takes line 3 as the smaller of Schedule D
        # line 15 (net long-term) and line 16 (the combined net) — not line 16
        # alone. Using the combined figure taxed short-term gains at 0/15/20%,
        # so a return with 40,000 of short-term gain produced exactly the same
        # tax as one with 40,000 of long-term gain: 10,456.50 against a correct
        # 13,449.00 for a single filer at 84,250 of taxable income.
        if sched_d is not None:
            long_term_preferential = non_negative(
                min(sched_d.long_term_net, sched_d.net)
            )
        else:
            # Without the schedule there is no character split to read, so the
            # netted figure is all there is. It is reported as supplied.
            long_term_preferential = non_negative(capital_gain)

        # Preferential income cannot exceed what actually remains taxable.
        preferential = min(
            to_cents(money(income.qualified_dividends)) + long_term_preferential,
            result.taxable_income,
        )
        result.tax_before_credits = tax_with_capital_gains(
            taxable_income=result.taxable_income,
            qualified_income=preferential,
            year=year,
            status=status,
        )
        result.lines.append(
            Line(
                "16",
                "Tax",
                result.tax_before_credits,
                "Includes preferential rates on qualified income"
                if preferential > ZERO
                else "",
            )
        )

        # --- Credits (lines 19-21) ----------------------------------------
        ctc = child_tax_credit(
            qualifying_children=profile.qualifying_children,
            other_dependents=profile.other_dependents,
            modified_agi=result.adjusted_gross_income,
            year=year,
            status=status,
        )
        nonrefundable = total([ctc, money(payments.other_nonrefundable_credits)])
        # Nonrefundable credits cannot reduce tax below zero.
        result.total_credits = min(nonrefundable, result.tax_before_credits)
        result.lines.append(Line("19", "Child tax credit / other dependents", ctc))
        result.lines.append(Line("21", "Total nonrefundable credits", result.total_credits))

        # --- Other taxes (line 23) ----------------------------------------
        # Three separate charges reach line 23 through Schedule 2, each with its
        # own form and its own base. They were previously one figure — SE tax —
        # so a high earner's Medicare surtax and a high investor's §1411 tax
        # were both simply absent, in both cases understating the tax due.
        result.self_employment_tax = se_tax

        result.additional_medicare_tax = additional_medicare_tax(
            wages=money(income.wages),
            self_employment_earnings=se_income,
            year=year,
            status=status,
        )

        # §1411 net investment income: the passive and portfolio items, not
        # wages or self-employment earnings, which carry the Medicare surtax
        # above instead.
        investment_income = total(
            [
                money(income.taxable_interest),
                money(income.ordinary_dividends),
                non_negative(capital_gain),
                money(income.rental_income),
                money(income.other_gains),
            ]
        )
        result.net_investment_income_tax = net_investment_income_tax(
            net_investment_income=investment_income,
            modified_agi=result.adjusted_gross_income,
            year=year,
            status=status,
        )

        result.other_taxes = total(
            [
                result.self_employment_tax,
                result.additional_medicare_tax,
                result.net_investment_income_tax,
            ]
        )
        if se_tax > ZERO:
            result.lines.append(Line("23a", "Self-employment tax (Schedule SE)", se_tax))
        if result.additional_medicare_tax > ZERO:
            result.lines.append(
                Line("23b", "Additional Medicare tax (Form 8959)",
                     result.additional_medicare_tax)
            )
        if result.net_investment_income_tax > ZERO:
            result.lines.append(
                Line("23c", "Net investment income tax (Form 8960)",
                     result.net_investment_income_tax)
            )
        if result.other_taxes > ZERO:
            result.lines.append(Line("23", "Other taxes (Schedule 2)", result.other_taxes))

        # --- Total tax (line 24) ------------------------------------------
        result.total_tax = non_negative(
            to_cents(result.tax_before_credits - result.total_credits + result.other_taxes)
        )
        result.lines.append(Line("24", "Total tax", result.total_tax))

        # --- Payments (line 33) -------------------------------------------
        line_26 = total(
            [
                money(payments.estimated_payments),
                money(payments.prior_year_overpayment_applied),
            ]
        )
        # --- Refundable credits (lines 27-29) -----------------------------
        # Computed, not extracted. Both of these were previously PaymentInputs,
        # so they could only appear if some document already stated them — which
        # for a first-time filer means never. A single parent earning 20,000 was
        # shown a refund of zero against a correct 6,028.
        #
        # Earned income for both is wages plus net self-employment earnings.
        earned = total([money(income.wages), non_negative(se_income)])

        result.eitc = earned_income_credit(
            earned_income=earned,
            adjusted_gross_income=result.adjusted_gross_income,
            qualifying_children=profile.qualifying_children,
            investment_income=total(
                [
                    money(income.taxable_interest),
                    money(income.tax_exempt_interest),
                    money(income.ordinary_dividends),
                    non_negative(capital_gain),
                ]
            ),
            year=year,
            status=status,
            taxpayer_age=profile.taxpayer_age,
            lived_apart_from_spouse=profile.lived_apart_from_spouse,
        )
        # A figure already on the documents wins — a prior return or a
        # preparer's worksheet may carry one computed on facts we do not have.
        eic = money(payments.earned_income_credit) or result.eitc.credit

        actc = money(payments.additional_child_tax_credit) or additional_child_tax_credit(
            qualifying_children=profile.qualifying_children,
            earned_income=earned,
            child_tax_credit_allowed=ctc,
            child_tax_credit_used=min(ctc, result.total_credits),
            year=year,
        )

        if eic > ZERO:
            result.lines.append(Line("27", "Earned income credit (Schedule EIC)", eic))
        elif result.eitc.ineligible_reason and profile.qualifying_children:
            result.warnings.append(
                f"No earned income credit: {result.eitc.ineligible_reason}"
            )
        if actc > ZERO:
            result.lines.append(
                Line("28", "Additional child tax credit (Schedule 8812)", actc)
            )

        result.federal_withheld = money(payments.federal_withheld)
        result.total_payments = total(
            [
                result.federal_withheld,
                line_26,
                eic,
                actc,
                money(payments.american_opportunity_credit),
                money(payments.other_payments),
            ]
        )
        result.lines.append(
            Line("25", "Federal income tax withheld", result.federal_withheld)
        )
        if line_26 > ZERO:
            carried_in = money(payments.prior_year_overpayment_applied)
            result.lines.append(
                Line(
                    "26",
                    "Estimated tax payments and amount applied from prior return",
                    line_26,
                    f"Includes {carried_in} carried in from the prior year"
                    if carried_in > ZERO
                    else "",
                )
            )
        result.lines.append(Line("33", "Total payments", result.total_payments))

        # --- Refund or balance due (lines 34-37) --------------------------
        difference = to_cents(result.total_payments - result.total_tax)
        if difference >= ZERO:
            result.amount_owed = ZERO
            result.lines.append(Line("34", "Overpaid", difference))

            # An overpayment can be refunded or carried to next year's
            # estimated tax, and that is the taxpayer's election, not something
            # derivable from the documents. Defaulting silently to "refund it"
            # printed 725 on line 35a for a taxpayer who had chosen to apply it
            # forward. Honour a stated election, cap it at what was actually
            # overpaid, and refund only the remainder.
            applied = min(
                non_negative(to_cents(money(payments.apply_overpayment_to_next_year))),
                difference,
            )
            result.applied_to_next_year = applied
            result.refund = to_cents(difference - applied)

            if result.refund > ZERO:
                result.lines.append(Line("35a", "Refunded to you", result.refund))
            if applied > ZERO:
                result.lines.append(
                    Line("36", "Applied to next year's estimated tax", applied)
                )
        else:
            result.refund = ZERO
            result.amount_owed = -difference
            result.lines.append(Line("37", "Amount you owe", -difference))

        return result

    #: State and local tax above this share of AGI is not a real tax bill.
    #:
    #: The highest state income tax rate in the country is around 13%, and local
    #: taxes add a few points at most, so a fifth of AGI is already generous.
    #: Beyond it the figure is a misread — and the cap makes that misread
    #: invisible, because whatever the number is it comes out of the deduction
    #: at exactly the cap. On the Basic 5 sample the engine itemised exactly
    #: 40,000 against an AGI of 92,757: a 43% state tax rate, landing on a round
    #: number that looks deliberate. Flagging the ratio catches it; checking the
    #: deduction against the cap never could.
    _IMPLAUSIBLE_SALT_SHARE_OF_AGI = D("0.20")

    def _itemized_total(
        self,
        deductions: DeductionInputs,
        agi: Decimal,
        year: int,
        status: FilingStatusTax,
        warnings: list[str] | None = None,
    ) -> Decimal:
        """Schedule A total, with the SALT cap and medical floor applied."""
        medical = medical_deduction(money(deductions.medical_expenses), agi, year)

        # A taxpayer elects either income or sales tax, not both.
        elected_tax = max(
            money(deductions.state_local_income_tax),
            money(deductions.state_local_sales_tax),
        )
        # AGI drives the 2025 phase-down of the SALT cap, so it has to go in:
        # above 500,000 the 40,000 cap tapers by 30% of the excess to a 10,000
        # floor (Schedule A line 5e worksheet).
        salt_before_cap = to_cents(
            elected_tax
            + money(deductions.real_estate_tax)
            + money(deductions.personal_property_tax)
        )
        salt = salt_deduction(salt_before_cap, year, status, modified_agi=agi)

        if warnings is not None and non_negative(agi) > ZERO:
            share = salt_before_cap / non_negative(agi)
            if share > self._IMPLAUSIBLE_SALT_SHARE_OF_AGI:
                warnings.append(
                    f"State and local taxes of {salt_before_cap} are "
                    f"{share:.0%} of adjusted gross income, which exceeds any "
                    "combined state and local rate. The deduction was capped at "
                    f"{salt}, so the cap hides the size of the figure — check "
                    "which document supplied it before relying on the itemized "
                    "deduction."
                )

        charitable = total(
            [money(deductions.charitable_cash), money(deductions.charitable_noncash)]
        )
        ceiling = to_cents(non_negative(agi) * LIMITS[year].charitable_agi_ceiling_cash)
        charitable = min(charitable, ceiling)

        return total(
            [
                medical,
                salt,
                money(deductions.mortgage_interest),
                money(deductions.investment_interest),
                charitable,
                money(deductions.casualty_losses),
                money(deductions.other_itemized),
            ]
        )
