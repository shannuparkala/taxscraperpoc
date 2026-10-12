"""Form 1040 (2025), U.S. Individual Income Tax Return - one node per line.

Line wording, ordering and every schedule cross-reference are from
``docs/tax-research/form-1040-2025-line-by-line.md``, which was read off the
primary PDF (Cat. No. 11320B, "Created 9/5/25").

**Rounding.** This form carries cents. Whole-dollar rounding is optional under
"Rounding Off to Whole Dollars" and all-or-nothing across the return and its
schedules, so carrying cents and rounding at presentation is one of the two
conforming choices - and it is the one that keeps a figure checkable against
the schedule that produced it. ``Rounding.DOLLARS`` exists for the forms whose
own instructions round, and for the renderer.

**The arithmetic is not rewritten here.** ``computations`` holds tax math that
is already reconciled against filed returns; nodes call into it and record what
it did. Re-deriving ``taxable_social_security`` to make it look more like a
graph would risk a figure that took a benchmark to get right.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tax_engine.computations import (
    standard_deduction,
    tax_table_lookup,
    taxable_social_security,
)
from app.services.tax_engine.graph.engine import register_form
from app.services.tax_engine.graph.evaluator import Ctx, fmt
from app.services.tax_engine.graph.facts import TaxpayerFacts
from app.services.tax_engine.graph.forms._common import carried
from app.services.tax_engine.graph.nodes import (
    ZERO,
    Node,
    pending_form_node,
)

FORM = "Form 1040"


def _n(
    line: str,
    label: str,
    compute,
    inputs: tuple[str, ...] = (),
    **kw,
) -> Node:
    return Node(
        id=f"f1040.l{line}",
        form=FORM,
        line=line,
        label=label,
        compute=compute,
        inputs=inputs,
        **kw,
    )


def _from_facts(line: str, label: str, field: str) -> Node:
    """A line whose figure is read off a document, not computed."""
    source = f"facts.{field}"

    def compute(ctx: Ctx) -> Decimal:
        amount = ctx[source]
        ctx.explain(f"{fmt(amount)} reported as {field}")
        return amount

    return _n(line, label, compute, (source,))


def _pending(line: str, label: str, source_form: str, *, required: bool) -> Node:
    return pending_form_node(
        f"f1040.l{line}",
        FORM,
        line,
        label,
        source_form=source_form,
        required=required,
    )


#: Every Schedule D or Form 8949 figure that means real detail was supplied.
_SCHEDULE_D_DETAIL = (
    "schd_l1a", "schd_l4", "schd_l5", "schd_l6", "schd_l8a",
    "schd_l12", "schd_l13", "schd_l14",
    *(f"f8949_l2{box}" for box in "abcdefghijkl"),
)


def _line_7a(facts: TaxpayerFacts) -> Node:
    """Schedule D when its detail was supplied, the netted figure when not.

    Running the schedule is strictly better: it is the only path that picks up
    capital gain distributions and prior-year carryovers, and the only one that
    applies the 3,000 loss limit. But a workpaper that gives one netted figure
    and no detail still has to produce a return, so the fallback stays - and
    says out loud which path it took, because the two can differ by the whole
    carryover.
    """
    has_detail = any(facts.money.get(field) for field in _SCHEDULE_D_DETAIL)
    label = "Capital gain or (loss). Attach Schedule D if required"

    if has_detail:
        return carried(FORM, "f1040", "7a", label, "schd.to_1040_l7")

    def compute(ctx: Ctx) -> Decimal:
        amount = ctx["facts.capital_gain_or_loss"]
        if amount != ZERO:
            ctx.flag(
                "entered from an already-netted figure because no Schedule D "
                "or Form 8949 detail was supplied; capital gain distributions, "
                "prior-year carryovers and the annual loss limit were not applied"
            )
        ctx.explain(f"{fmt(amount)} reported as a net capital gain or (loss)")
        return amount

    return _n("7a", label, compute, ("facts.capital_gain_or_loss",))


#: A figure here means part of taxable income is taxed at preferential rates,
#: so Form 1040 line 16 runs the worksheet instead of the Tax Table.
_PREFERENTIAL_INCOME = (
    "qualified_dividends", "schd_l13",
    *(f"f8949_l2{box}" for box in "defjkl"),
)


def _line_16(facts: TaxpayerFacts) -> Node:
    """Form 1040 line 16, which is a worksheet dispatch rather than a formula.

    The form says only "Tax (see instructions)". Which of four computations
    applies depends on what kind of income the return holds, and picking the
    wrong one is invisible on the finished return.
    """
    label = "Tax"
    # A long-term *loss* does not put anyone on the worksheet - the tax is the
    # same either way, but a line that says it ran a worksheet it should not
    # have is provenance that misdescribes the return.
    preferential = any(
        (facts.money.get(field) or ZERO) > ZERO for field in _PREFERENTIAL_INCOME
    )
    if preferential:
        return carried(FORM, "f1040", "16", label, "qdcgtw.l11")

    def compute(ctx: Ctx) -> Decimal:
        taxable = ctx["f1040.l15"]
        if taxable == ZERO:
            ctx.explain("no taxable income, so -0-")
            return ZERO
        # The Tax Table is mandatory below its ceiling and does not agree with
        # the rate schedule: Basic 5 reconciles only through the table.
        amount = tax_table_lookup(taxable, facts.tax_year, facts.filing_status)
        ctx.explain(
            f"tax on {fmt(taxable)} of taxable income for "
            f"{facts.filing_status.value} = {fmt(amount)}"
        )
        return amount

    return _n("16", label, compute, ("f1040.l15",))


def build(facts: TaxpayerFacts) -> list[Node]:
    """Every line of Form 1040, in the order the form prints them."""
    year = facts.tax_year
    status = facts.filing_status

    # Which not-yet-built forms this particular return actually needs. A
    # schedule nobody feeds is a zero; a schedule this taxpayer has figures
    # for is an unsupported line that must not pass as nil.
    nodes: list[Node] = []
    add = nodes.append

    # -- Income ---------------------------------------------------------

    add(_from_facts("1a", "Total amount from Form(s) W-2, box 1", "wages"))
    add(_from_facts("1b", "Household employee wages not reported on Form(s) W-2",
                    "household_employee_wages"))
    add(_from_facts("1c", "Tip income not reported on line 1a", "tip_income"))
    add(_from_facts("1d", "Medicaid waiver payments not reported on Form(s) W-2",
                    "medicaid_waiver_payments"))
    add(_from_facts("1e", "Taxable dependent care benefits from Form 2441, line 26",
                    "dependent_care_benefits"))
    add(_from_facts("1f", "Employer-provided adoption benefits from Form 8839, line 31",
                    "employer_adoption_benefits"))
    add(_from_facts("1g", "Wages from Form 8919, line 6", "wages_from_form_8919"))
    add(_from_facts("1h", "Other earned income", "other_earned_income"))
    add(_from_facts("1i", "Nontaxable combat pay election", "nontaxable_combat_pay"))

    def line_1z(ctx: Ctx) -> Decimal:
        # 1i is deliberately absent. Nontaxable combat pay is an election
        # disclosure, not income; summing it here overstates total income.
        return ctx.total(*(f"f1040.l1{c}" for c in "abcdefgh"))

    add(_n("1z", "Add lines 1a through 1h", line_1z,
           tuple(f"f1040.l1{c}" for c in "abcdefgh")))

    add(_from_facts("2a", "Tax-exempt interest", "tax_exempt_interest"))
    add(carried(FORM, "f1040", "2b", "Taxable interest", "schb.l4"))
    add(_from_facts("3a", "Qualified dividends", "qualified_dividends"))
    add(carried(FORM, "f1040", "3b", "Ordinary dividends", "schb.l6"))
    add(_from_facts("4a", "IRA distributions", "ira_distributions"))
    add(_from_facts("4b", "IRA distributions - taxable amount", "ira_taxable"))
    add(_from_facts("5a", "Pensions and annuities", "pensions_annuities"))
    add(_from_facts("5b", "Pensions and annuities - taxable amount", "pensions_taxable"))
    add(_from_facts("6a", "Social security benefits", "social_security_benefits"))

    # 6b is computed and never read: Form SSA-1099 reports the gross benefit and
    # is silent on the taxable portion, because that depends on the rest of the
    # return. Waiting for a document to supply it left it blank and dropped the
    # whole benefit out of income.
    other_income_lines = (
        "f1040.l1z", "f1040.l2b", "f1040.l3b", "f1040.l4b",
        "f1040.l5b", "f1040.l7a", "f1040.l8",
    )

    def line_6b(ctx: Ctx) -> Decimal:
        benefits = ctx["f1040.l6a"]
        if benefits == ZERO:
            ctx.explain("no benefits reported, so -0-")
            return ZERO
        other = sum((ctx[nid] for nid in other_income_lines), ZERO)
        exempt = ctx["f1040.l2a"]
        taxable = taxable_social_security(
            benefits=benefits,
            other_income=other,
            tax_exempt_interest=exempt,
            year=year,
            status=status,
        )
        ctx.explain(
            f"IRC 86 on {fmt(benefits)} of benefits against {fmt(other)} of "
            f"other income and {fmt(exempt)} of tax-exempt interest "
            f"= {fmt(taxable)}"
        )
        return taxable

    add(_n("6b", "Social security benefits - taxable amount", line_6b,
           ("f1040.l6a", "f1040.l2a", *other_income_lines)))

    add(_line_7a(facts))
    add(carried(FORM, "f1040", "8",
                "Additional income from Schedule 1, line 10", "sch1.l10"))

    total_income_lines = (
        "f1040.l1z", "f1040.l2b", "f1040.l3b", "f1040.l4b",
        "f1040.l5b", "f1040.l6b", "f1040.l7a", "f1040.l8",
    )
    add(_n("9", "Add lines 1z, 2b, 3b, 4b, 5b, 6b, 7a, and 8. This is your total income",
           lambda ctx: ctx.total(*total_income_lines), total_income_lines))

    add(carried(FORM, "f1040", "10",
                "Adjustments to income from Schedule 1, line 26", "sch1.l26"))
    add(_n("11a", "Subtract line 10 from line 9. This is your adjusted gross income",
           lambda ctx: ctx.less("f1040.l9", "f1040.l10"), ("f1040.l9", "f1040.l10")))

    # -- Tax and Credits ------------------------------------------------

    def line_11b(ctx: Ctx) -> Decimal:
        amount = ctx["f1040.l11a"]
        ctx.explain(f"{fmt(amount)} carried from line 11a")
        return amount

    add(_n("11b", "Amount from line 11a (adjusted gross income)", line_11b,
           ("f1040.l11a",)))

    def line_12e(ctx: Ctx) -> Decimal:
        earned = ctx["f1040.l1z"]
        # Read through ctx even though standard_deduction() reaches the same
        # figure: that is what carries the authority onto this line, and this
        # line is the largest single deduction on most returns.
        base = ctx[f"const.standard_deduction.{status.value}"]
        amount = standard_deduction(
            year=year,
            status=status,
            age_65_or_older=facts.seniors,
            blind=facts.blind_count,
            earned_income=earned,
        )
        added = amount - base
        if added > ZERO:
            ctx.explain(
                f"{fmt(base)} for {status.value} + {fmt(added)} for "
                f"{facts.seniors} age and {facts.blind_count} blindness "
                f"entitlement(s) = {fmt(amount)}"
            )
        elif added < ZERO:
            ctx.explain(
                f"{fmt(amount)}, limited below the {fmt(base)} standard "
                "deduction because this taxpayer can be claimed as a dependent"
            )
        else:
            ctx.explain(f"standard deduction for {status.value} = {fmt(amount)}")

        # Itemizing wins only when it is worth more. Taking the standard
        # deduction on a return whose Schedule A is larger is a silent
        # overpayment, and taking a smaller Schedule A is a silent
        # overstatement - the form gives the taxpayer the better of the two
        # unless they elect otherwise on Schedule A line 18.
        itemized = ctx["scha.l17"]
        if itemized > amount:
            ctx.explain(
                f"itemized deductions of {fmt(itemized)} from Schedule A line 17 "
                f"exceed the {fmt(amount)} standard deduction, so the return itemizes"
            )
            return itemized
        if itemized > ZERO:
            ctx.flag(
                f"Schedule A totals {fmt(itemized)}, below the {fmt(amount)} "
                "standard deduction, so the standard deduction was taken"
            )
        return amount

    add(_n("12e", "Standard deduction or itemized deductions (from Schedule A)",
           line_12e,
           ("f1040.l1z", f"const.standard_deduction.{status.value}", "scha.l17")))

    add(_pending("13a", "Qualified business income deduction from Form 8995 or 8995-A",
                 "Form 8995", required=False))
    add(_pending("13b", "Additional deductions from Schedule 1-A, line 38",
                 "Schedule 1-A", required=False))

    deduction_lines = ("f1040.l12e", "f1040.l13a", "f1040.l13b")
    add(_n("14", "Add lines 12e, 13a, and 13b",
           lambda ctx: ctx.total(*deduction_lines), deduction_lines))

    def line_15(ctx: Ctx) -> Decimal:
        taxable = ctx["f1040.l11b"] - ctx["f1040.l14"]
        if taxable <= ZERO:
            return ctx.floor_at_zero(
                taxable,
                because=f"{fmt(ctx['f1040.l11b'])} - {fmt(ctx['f1040.l14'])}",
            )
        ctx.explain(
            f"{fmt(ctx['f1040.l11b'])} - {fmt(ctx['f1040.l14'])} = {fmt(taxable)}"
        )
        return taxable

    add(_n("15", "Subtract line 14 from line 11b. This is your taxable income",
           line_15, ("f1040.l11b", "f1040.l14")))

    add(_line_16(facts))

    add(carried(FORM, "f1040", "17", "Amount from Schedule 2, line 3", "sch2.l3"))
    add(_n("18", "Add lines 16 and 17",
           lambda ctx: ctx.total("f1040.l16", "f1040.l17"),
           ("f1040.l16", "f1040.l17")))

    add(_pending("19", "Child tax credit or credit for other dependents from Schedule 8812",
                 "Schedule 8812", required=bool(facts.dependents)))
    add(carried(FORM, "f1040", "20", "Amount from Schedule 3, line 8", "sch3.l8"))
    add(_n("21", "Add lines 19 and 20",
           lambda ctx: ctx.total("f1040.l19", "f1040.l20"),
           ("f1040.l19", "f1040.l20")))

    def line_22(ctx: Ctx) -> Decimal:
        remaining = ctx["f1040.l18"] - ctx["f1040.l21"]
        if remaining <= ZERO:
            return ctx.floor_at_zero(
                remaining, because=f"{fmt(ctx['f1040.l18'])} - {fmt(ctx['f1040.l21'])}"
            )
        ctx.explain(
            f"{fmt(ctx['f1040.l18'])} - {fmt(ctx['f1040.l21'])} = {fmt(remaining)}"
        )
        return remaining

    add(_n("22", "Subtract line 21 from line 18. If zero or less, enter -0-",
           line_22, ("f1040.l18", "f1040.l21")))

    add(carried(FORM, "f1040", "23",
                "Other taxes, including self-employment tax, from Schedule 2, line 21",
                "sch2.l21"))
    add(_n("24", "Add lines 22 and 23. This is your total tax",
           lambda ctx: ctx.total("f1040.l22", "f1040.l23"),
           ("f1040.l22", "f1040.l23")))

    # -- Payments -------------------------------------------------------

    add(_from_facts("25a", "Federal income tax withheld from Form(s) W-2",
                    "federal_withheld_w2"))
    add(_from_facts("25b", "Federal income tax withheld from Form(s) 1099",
                    "federal_withheld_1099"))
    add(_from_facts("25c", "Federal income tax withheld from other forms",
                    "federal_withheld_other"))
    withheld = ("f1040.l25a", "f1040.l25b", "f1040.l25c")
    add(_n("25d", "Add lines 25a through 25c",
           lambda ctx: ctx.total(*withheld), withheld))

    def line_26(ctx: Ctx) -> Decimal:
        return ctx.total("facts.estimated_tax_payments",
                         "facts.prior_year_overpayment_applied")

    add(_n("26", "2025 estimated tax payments and amount applied from 2024 return",
           line_26,
           ("facts.estimated_tax_payments", "facts.prior_year_overpayment_applied")))

    add(_pending("27a", "Earned income credit (EIC)", "Schedule EIC", required=False))
    add(_pending("27b", "Nontaxable combat pay election for EIC purposes",
                 "Schedule SE", required=False))
    add(_pending("28", "Additional child tax credit from Schedule 8812",
                 "Schedule 8812", required=bool(facts.dependents)))
    add(_pending("29", "American opportunity credit from Form 8863, line 8",
                 "Form 8863", required=False))
    add(_pending("30", "Refundable adoption credit from Form 8839, line 13",
                 "Form 8839", required=False))
    add(carried(FORM, "f1040", "31", "Amount from Schedule 3, line 15", "sch3.l15"))

    other_payments = ("f1040.l27a", "f1040.l28", "f1040.l29", "f1040.l30", "f1040.l31")
    add(_n("32",
           "Add lines 27a, 28, 29, 30, and 31. These are your total other payments "
           "and refundable credits",
           lambda ctx: ctx.total(*other_payments), other_payments))

    payment_lines = ("f1040.l25d", "f1040.l26", "f1040.l32")
    add(_n("33", "Add lines 25d, 26, and 32. These are your total payments",
           lambda ctx: ctx.total(*payment_lines), payment_lines))

    # -- Refund / Amount you owe ----------------------------------------

    def line_34(ctx: Ctx) -> Decimal:
        paid, owed = ctx["f1040.l33"], ctx["f1040.l24"]
        if paid <= owed:
            ctx.explain(
                f"payments of {fmt(paid)} do not exceed total tax of "
                f"{fmt(owed)}, so nothing was overpaid"
            )
            return ZERO
        ctx.explain(f"{fmt(paid)} - {fmt(owed)} = {fmt(paid - owed)}")
        return paid - owed

    add(_n("34", "If line 33 is more than line 24, subtract line 24 from line 33. "
           "This is the amount you overpaid", line_34, ("f1040.l33", "f1040.l24")))

    def line_35a(ctx: Ctx) -> Decimal:
        overpaid, applied = ctx["f1040.l34"], ctx["f1040.l36"]
        refunded = overpaid - applied
        if refunded < ZERO:
            ctx.flag(
                f"more was applied forward ({fmt(applied)}) than was overpaid "
                f"({fmt(overpaid)}); the refund cannot be negative"
            )
            refunded = ZERO
        ctx.explain(f"{fmt(overpaid)} overpaid - {fmt(applied)} applied forward "
                    f"= {fmt(refunded)}")
        return refunded

    add(_n("35a", "Amount of line 34 you want refunded to you", line_35a,
           ("f1040.l34", "f1040.l36")))

    add(_from_facts("36", "Amount of line 34 you want applied to your 2026 estimated tax",
                    "amount_applied_to_next_year"))

    def line_37(ctx: Ctx) -> Decimal:
        owed, paid = ctx["f1040.l24"], ctx["f1040.l33"]
        if owed <= paid:
            ctx.explain(
                f"total tax of {fmt(owed)} does not exceed payments of "
                f"{fmt(paid)}, so nothing is owed"
            )
            return ZERO
        ctx.explain(f"{fmt(owed)} - {fmt(paid)} = {fmt(owed - paid)}")
        return owed - paid

    add(_n("37", "Subtract line 33 from line 24. This is the amount you owe",
           line_37, ("f1040.l24", "f1040.l33")))

    add(_pending("38", "Estimated tax penalty", "Form 2210", required=False))

    return nodes


register_form(FORM, build)
