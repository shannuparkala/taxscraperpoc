"""Turns a computed return into an explanation a human can check.

The tax engine produces numbers. This service produces the account of how each
number came to be: which document supplied each input, what rule required the
treatment, what arithmetic was performed, and how confident the system is.

Three design commitments, each of which cost something:

**The explanation is derived, not narrated.** Every operand is a real value read
back out of the engine's own inputs, and for any line whose operands are simple
addition and subtraction, ``verify()`` recomputes the line from them and
compares. A drifting explanation therefore fails a test rather than quietly
misdescribing a return. An LLM is never involved — a generated narrative that
disagrees with the arithmetic is exactly the failure this feature exists to
prevent.

**Nothing is claimed to be traced when it is not.** A line whose value came from
a taxpayer election, an assumption, or a subtotal says so. ``VERIFIED_FROM_SOURCE``
is reserved for values that genuinely walk back to an uploaded page.

**Line coverage is total.** Every line the engine emits gets an entry. A line
with no spec would otherwise appear on the form with no explanation beside it,
which is the black box this replaces; the ``test_every_line_is_explained`` test
holds the two in step.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from app.services.tax_engine.form_1040 import (
    AdjustmentInputs,
    CapitalGainInputs,
    DeductionInputs,
    IncomeInputs,
    PaymentInputs,
    Return1040,
    TaxpayerProfile,
)
from app.tax_knowledge.rule_citations import RULES, TaxRule

ZERO = Decimal(0)


class FlowSection(str, Enum):
    """The stages of the return, in the order the form walks them."""

    INCOME = "income"
    ADJUSTMENTS = "adjustments"
    AGI = "agi"
    DEDUCTIONS = "deductions"
    TAXABLE_INCOME = "taxable_income"
    TAX = "tax"
    CREDITS = "credits"
    OTHER_TAXES = "other_taxes"
    TOTAL_TAX = "total_tax"
    PAYMENTS = "payments"
    OUTCOME = "outcome"


SECTION_TITLES: dict[FlowSection, str] = {
    FlowSection.INCOME: "Income sources",
    FlowSection.ADJUSTMENTS: "Adjustments to income",
    FlowSection.AGI: "Adjusted gross income",
    FlowSection.DEDUCTIONS: "Deductions",
    FlowSection.TAXABLE_INCOME: "Taxable income",
    FlowSection.TAX: "Tax calculation",
    FlowSection.CREDITS: "Credits",
    FlowSection.OTHER_TAXES: "Other taxes",
    FlowSection.TOTAL_TAX: "Final tax liability",
    FlowSection.PAYMENTS: "Payments and withholding",
    FlowSection.OUTCOME: "Refund or balance due",
}


class Provenance(str, Enum):
    """Where a value came from. Determines the badge the reviewer sees."""

    #: Read from an uploaded document.
    SOURCE_DOCUMENT = "source_document"
    #: Computed from other lines on this return.
    COMPUTED = "computed"
    #: Carried in from a prior year's return or proforma.
    PRIOR_YEAR = "prior_year"
    #: The taxpayer's choice, not derivable from documents.
    ELECTION = "election"
    #: Taken from the taxpayer profile (age, filing status, dependents).
    TAXPAYER_PROFILE = "taxpayer_profile"
    #: A default the system applied because nothing stated the value.
    ASSUMPTION = "assumption"


class ValidationStatus(str, Enum):
    VERIFIED = "verified"
    COMPUTED = "computed"
    REVIEW = "needs_review"


@dataclass(frozen=True, slots=True)
class Operand:
    """One input to a line, with where it came from."""

    label: str
    amount: Decimal
    provenance: Provenance
    #: "add" and "subtract" participate in the arithmetic check; "info" does not.
    role: str = "add"
    #: Engine input field, when one exists — the key into field provenance.
    field_name: str = ""
    #: Documents that contributed, e.g. ["w2", "1099_int"].
    documents: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "amount": str(self.amount),
            "provenance": self.provenance.value,
            "role": self.role,
            "field_name": self.field_name,
            "documents": list(self.documents),
            "detail": self.detail,
        }


@dataclass(slots=True)
class LineExplanation:
    """Everything a reviewer needs to accept or challenge one line."""

    line: str
    label: str
    amount: Decimal
    section: FlowSection
    rule: TaxRule
    formula: str
    narrative: str
    operands: list[Operand] = field(default_factory=list)
    provenance: Provenance = Provenance.COMPUTED
    status: ValidationStatus = ValidationStatus.COMPUTED
    confidence: float | None = None
    #: True when the operands were re-added and matched the engine's amount.
    arithmetic_checked: bool = False
    note: str = ""

    @property
    def source_documents(self) -> list[str]:
        seen: list[str] = []
        for operand in self.operands:
            for doc in operand.documents:
                if doc not in seen:
                    seen.append(doc)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "label": self.label,
            "amount": str(self.amount),
            "section": self.section.value,
            "section_title": SECTION_TITLES[self.section],
            "rule": self.rule.to_dict(),
            "formula": self.formula,
            "narrative": self.narrative,
            "operands": [o.to_dict() for o in self.operands],
            "provenance": self.provenance.value,
            "status": self.status.value,
            "confidence": self.confidence,
            "arithmetic_checked": self.arithmetic_checked,
            "source_documents": self.source_documents,
            "note": self.note,
        }


@dataclass(slots=True)
class ReturnExplanation:
    """The full explainability payload for one computed return."""

    tax_year: int
    filing_status: str
    deduction_method: str
    summary: dict[str, str]
    lines: list[LineExplanation]
    assumptions: list[str]
    warnings: list[str]
    unverified_citations: list[str]

    def section(self, section: FlowSection) -> list[LineExplanation]:
        return [line for line in self.lines if line.section is section]

    @property
    def rules_applied(self) -> list[TaxRule]:
        seen: dict[str, TaxRule] = {}
        for line in self.lines:
            seen.setdefault(line.rule.id, line.rule)
        return sorted(seen.values(), key=lambda r: r.title)

    def to_dict(self) -> dict[str, Any]:
        sections = []
        for section in FlowSection:
            lines = self.section(section)
            if not lines:
                continue
            sections.append(
                {
                    "key": section.value,
                    "title": SECTION_TITLES[section],
                    "lines": [line.to_dict() for line in lines],
                }
            )
        return {
            "tax_year": self.tax_year,
            "filing_status": self.filing_status,
            "deduction_method": self.deduction_method,
            "summary": self.summary,
            "sections": sections,
            "lines": [line.to_dict() for line in self.lines],
            "rules_applied": [r.to_dict() for r in self.rules_applied],
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "unverified_citations": self.unverified_citations,
        }


# --- Context ---------------------------------------------------------------


@dataclass(slots=True)
class ExplanationContext:
    """The engine's own inputs and output, plus extraction provenance."""

    result: Return1040
    profile: TaxpayerProfile
    income: IncomeInputs
    adjustments: AdjustmentInputs
    deductions: DeductionInputs
    payments: PaymentInputs
    capital_gains: CapitalGainInputs
    #: engine field -> [{"document_type": ..., "amount": ...}], from the merge.
    field_provenance: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    #: engine field -> 0..1 extraction confidence.
    confidence_scores: dict[str, float] = field(default_factory=dict)

    def documents_for(self, *fields: str) -> tuple[str, ...]:
        seen: list[str] = []
        for name in fields:
            for entry in self.field_provenance.get(name, ()):
                doc = str(entry.get("document_type") or "").strip()
                if doc and doc not in seen:
                    seen.append(doc)
        return tuple(seen)

    def confidence_for(self, *fields: str) -> float | None:
        """The weakest confidence among the contributing fields.

        Weakest, not average: a line is only as trustworthy as its shakiest
        input, and averaging lets one confident figure hide a doubtful one.
        """
        scores: list[float] = []
        for name in fields:
            raw = self.confidence_scores.get(name)
            if raw is None:
                continue
            # Confidence originates in an LLM payload, so it can be anything.
            # A malformed score must not take down the explanation.
            try:
                scores.append(float(raw))
            except (TypeError, ValueError):
                continue
        return min(scores) if scores else None

    def amount(self, line: str) -> Decimal:
        found = self.result.line(line)
        return found.amount if found else ZERO


def _money(value: Decimal) -> str:
    """Whole dollars where exact, cents otherwise. Matches how a preparer reads."""
    quantized = value.quantize(Decimal("0.01"))
    if quantized == quantized.to_integral_value():
        return f"{quantized.to_integral_value():,}"
    return f"{quantized:,.2f}"


def _sum_operands(operands: Sequence[Operand]) -> Decimal:
    total = ZERO
    for operand in operands:
        if operand.role == "add":
            total += operand.amount
        elif operand.role == "subtract":
            total -= operand.amount
    return total


def _from_documents(
    ctx: ExplanationContext, *fields: str
) -> tuple[Provenance, tuple[str, ...]]:
    docs = ctx.documents_for(*fields)
    return (Provenance.SOURCE_DOCUMENT if docs else Provenance.ASSUMPTION, docs)


def _doc_operand(
    ctx: ExplanationContext,
    label: str,
    amount: Decimal,
    field_name: str,
    role: str = "add",
) -> Operand:
    provenance, docs = _from_documents(ctx, field_name)
    if amount == ZERO and not docs:
        provenance = Provenance.ASSUMPTION
    return Operand(
        label=label,
        amount=amount,
        provenance=provenance,
        role=role,
        field_name=field_name,
        documents=docs,
        detail=(
            "Read from " + ", ".join(_humanize(d) for d in docs)
            if docs
            else "No document reported this value; treated as zero."
        ),
    )


def _line_operand(
    ctx: ExplanationContext, line: str, label: str, role: str = "add"
) -> Operand:
    return Operand(
        label=f"Line {line} — {label}",
        amount=ctx.amount(line),
        provenance=Provenance.COMPUTED,
        role=role,
        detail=f"Carried from line {line}.",
    )


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().title()


# --- Line specifications ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class LineSpec:
    section: FlowSection
    rule_id: str
    operands: Callable[[ExplanationContext], list[Operand]]
    formula: Callable[[ExplanationContext], str]
    narrative: Callable[[ExplanationContext], str]
    #: When True, the operands are re-added and must equal the engine's amount.
    checkable: bool = True
    provenance: Provenance = Provenance.COMPUTED


def _simple_income_spec(
    label: str, field_name: str, rule_id: str
) -> LineSpec:
    """A line that is one extracted figure, reported as-is."""
    return LineSpec(
        section=FlowSection.INCOME,
        rule_id=rule_id,
        operands=lambda ctx: [
            _doc_operand(ctx, label, getattr(ctx.income, field_name), field_name)
        ],
        formula=lambda ctx: f"{label} as reported = {_money(getattr(ctx.income, field_name))}",
        narrative=lambda ctx: (
            f"We took the {label.lower()} reported on your documents"
            + (
                " (" + ", ".join(_humanize(d) for d in ctx.documents_for(field_name)) + ")"
                if ctx.documents_for(field_name)
                else ""
            )
            + f" and put ${_money(getattr(ctx.income, field_name))} on this line."
        ),
        provenance=Provenance.SOURCE_DOCUMENT,
    )


def _income_total_operands(ctx: ExplanationContext) -> list[Operand]:
    """Line 9's addends — exactly the lines the form tells you to add."""
    parts = [
        ("1a", "Wages"),
        ("2b", "Taxable interest"),
        ("3b", "Ordinary dividends"),
        ("4b", "Taxable IRA distributions"),
        ("5b", "Taxable pensions"),
        ("6b", "Taxable Social Security"),
        ("7", "Capital gain or loss"),
        ("8", "Additional income"),
    ]
    return [
        _line_operand(ctx, number, label)
        for number, label in parts
        if ctx.result.line(number) is not None
    ]


def _social_security_narrative(ctx: ExplanationContext) -> str:
    benefits = ctx.amount("6a")
    taxable = ctx.amount("6b")
    if benefits <= ZERO:
        return "No Social Security benefits were reported, so nothing is taxable."
    if taxable <= ZERO:
        return (
            f"You received ${_money(benefits)} in Social Security. We added your "
            "other income to half of your benefits, and the total stayed under "
            "the amount where benefits start being taxed — so none of it is "
            "taxable this year."
        )
    share = (taxable / benefits * 100).quantize(Decimal("0.1"))
    return (
        f"You received ${_money(benefits)} in Social Security. The IRS decides how "
        "much of that is taxable by adding your other income to half your "
        f"benefits. On that test, ${_money(taxable)} became taxable — {share}% of "
        "what you received. The law never taxes more than 85%, no matter how "
        "high your income."
    )


def _deduction_narrative(ctx: ExplanationContext) -> str:
    method = ctx.result.deduction_method
    taken = ctx.result.deduction_taken
    if method == "standard":
        extra = ""
        if ctx.profile.age_65_or_older or ctx.profile.blind:
            extra = (
                " This includes the extra amount for being 65 or older or blind."
            )
        return (
            f"You can either take a flat deduction or add up specific expenses. "
            f"The flat amount of ${_money(taken)} was larger, so we used it and "
            f"you did not need receipts.{extra}"
        )
    return (
        f"Adding up your specific deductible expenses came to ${_money(taken)}, "
        "which is more than the flat amount — so itemizing saves you money and "
        "that is what we used."
    )


def _outcome_narrative(ctx: ExplanationContext) -> str:
    result = ctx.result
    if result.amount_owed > ZERO:
        return (
            f"Your tax for the year was ${_money(result.total_tax)} and you had "
            f"already paid ${_money(result.total_payments)}. That leaves "
            f"${_money(result.amount_owed)} still to pay."
        )
    parts = [
        (
            f"Your tax for the year was ${_money(result.total_tax)} and you had "
            f"already paid ${_money(result.total_payments)}, so you overpaid by "
            f"${_money(result.total_payments - result.total_tax)}."
        )
    ]
    if result.applied_to_next_year > ZERO:
        parts.append(
            f"You chose to leave ${_money(result.applied_to_next_year)} with the "
            "IRS toward next year rather than take it back now."
        )
    if result.refund > ZERO:
        parts.append(f"${_money(result.refund)} comes back to you as a refund.")
    return " ".join(parts)


SPECS: dict[str, LineSpec] = {
    "1a": _simple_income_spec("Wages, salaries and tips", "wages", "wages"),
    "2b": _simple_income_spec("Taxable interest", "taxable_interest", "taxable_interest"),
    "3b": _simple_income_spec(
        "Ordinary dividends", "ordinary_dividends", "ordinary_dividends"
    ),
    "4a": _simple_income_spec(
        "IRA distributions", "ira_distributions", "ira_distributions"
    ),
    "4b": _simple_income_spec(
        "Taxable IRA distributions", "ira_taxable", "ira_distributions"
    ),
    "5a": _simple_income_spec("Pensions and annuities", "pensions", "pensions"),
    "5b": _simple_income_spec("Taxable pensions", "pensions_taxable", "pensions"),
    "6a": _simple_income_spec(
        "Social security benefits", "social_security", "social_security_taxable"
    ),
    "2a": LineSpec(
        section=FlowSection.INCOME,
        rule_id="tax_exempt_interest",
        operands=lambda ctx: [
            _doc_operand(
                ctx,
                "Tax-exempt interest",
                ctx.income.tax_exempt_interest,
                "tax_exempt_interest",
                role="info",
            )
        ],
        formula=lambda ctx: "Reported, not added to income",
        narrative=lambda ctx: (
            "This interest is not taxed, so it is not added to your income. It "
            "is still shown because a few other calculations look at it — "
            "including how much of your Social Security becomes taxable."
        ),
        checkable=False,
        provenance=Provenance.SOURCE_DOCUMENT,
    ),
    "3a": LineSpec(
        section=FlowSection.INCOME,
        rule_id="qualified_dividends",
        operands=lambda ctx: [
            _doc_operand(
                ctx,
                "Qualified dividends",
                ctx.income.qualified_dividends,
                "qualified_dividends",
                role="info",
            )
        ],
        formula=lambda ctx: "Shown separately; already inside line 3b",
        narrative=lambda ctx: (
            "These dividends qualify for lower tax rates. They are already "
            "counted inside your ordinary dividends on line 3b — shown here "
            "separately so the lower rate can be applied later."
        ),
        checkable=False,
        provenance=Provenance.SOURCE_DOCUMENT,
    ),
    "6b": LineSpec(
        section=FlowSection.INCOME,
        rule_id="social_security_taxable",
        operands=lambda ctx: [
            Operand(
                "Social security benefits received",
                ctx.amount("6a"),
                _from_documents(ctx, "social_security")[0],
                role="info",
                field_name="social_security",
                documents=ctx.documents_for("social_security"),
                detail="Form SSA-1099 box 5 — the net benefit, not the amount deposited.",
            ),
            Operand(
                "Half of your benefits",
                (ctx.amount("6a") / 2).quantize(Decimal("0.01")),
                Provenance.COMPUTED,
                role="info",
                detail="The worksheet starts from half of what you received.",
            ),
            Operand(
                "Your other income",
                ctx.result.total_income - ctx.amount("6b"),
                Provenance.COMPUTED,
                role="info",
                detail="Everything on lines 1z, 2b, 3b, 4b, 5b, 7 and 8.",
            ),
            Operand(
                "Tax-exempt interest",
                ctx.income.tax_exempt_interest,
                # Derived, not asserted: with no 1099 reporting muni interest
                # this operand is zero, and labelling it "from your documents"
                # would claim a source that does not exist.
                _from_documents(ctx, "tax_exempt_interest")[0],
                role="info",
                field_name="tax_exempt_interest",
                documents=ctx.documents_for("tax_exempt_interest"),
                detail="Counted in the test even though it is not taxed.",
            ),
        ],
        formula=lambda ctx: (
            "Provisional income = half of benefits + other income + tax-exempt "
            "interest, then the §86 worksheet tiers at 50% and 85%"
        ),
        narrative=_social_security_narrative,
        checkable=False,
    ),
    "7": LineSpec(
        section=FlowSection.INCOME,
        rule_id="capital_gains",
        operands=lambda ctx: (
            [
                _line_operand(ctx, "D-7", "Net short-term gain or loss"),
                _line_operand(ctx, "D-15", "Net long-term gain or loss"),
            ]
            if ctx.result.schedule_d is not None
            else [
                _doc_operand(
                    ctx,
                    "Capital gain or loss",
                    ctx.income.capital_gain_loss,
                    "capital_gain_loss",
                )
            ]
        ),
        formula=lambda ctx: (
            "Short-term net + long-term net, limited to a 3,000 loss per year"
            if ctx.result.schedule_d is not None
            else "As reported"
        ),
        narrative=lambda ctx: (
            (
                "We combined your short-term and long-term investment results. "
                + (
                    "The loss is larger than the law allows in one year, so "
                    f"${_money(ctx.amount('7'))} is used now and the rest carries "
                    "to next year."
                    if ctx.amount("7") < ZERO
                    else f"That leaves a gain of ${_money(ctx.amount('7'))}."
                )
            )
            if ctx.result.schedule_d is not None
            else f"Your net investment result of ${_money(ctx.amount('7'))} was reported directly."
        ),
        checkable=False,
    ),
    "D-7": LineSpec(
        section=FlowSection.INCOME,
        rule_id="capital_gains",
        operands=lambda ctx: [
            _doc_operand(
                ctx, "Short-term gains and losses", ctx.capital_gains.short_term_gain,
                "short_term_gain",
            ),
            _doc_operand(
                ctx, "Short-term gains from K-1s", ctx.capital_gains.short_term_from_k1,
                "short_term_from_k1",
            ),
            Operand(
                "Short-term loss carried in from last year",
                ctx.capital_gains.short_term_loss_carryover,
                Provenance.PRIOR_YEAR,
                role="subtract",
                field_name="short_term_loss_carryover",
                documents=ctx.documents_for("short_term_loss_carryover"),
                detail=(
                    "Only last year's return states this. It is not on any "
                    "current-year document."
                ),
            ),
        ],
        formula=lambda ctx: "Short-term gains − short-term loss carried forward",
        narrative=lambda ctx: (
            "Investments you held a year or less are netted together, then last "
            "year's unused short-term loss is subtracted."
        ),
    ),
    "D-15": LineSpec(
        section=FlowSection.INCOME,
        rule_id="capital_gains",
        operands=lambda ctx: [
            _doc_operand(
                ctx, "Long-term gains and losses", ctx.capital_gains.long_term_gain,
                "long_term_gain",
            ),
            _doc_operand(
                ctx, "Long-term gains from K-1s", ctx.capital_gains.long_term_from_k1,
                "long_term_from_k1",
            ),
            _doc_operand(
                ctx, "Capital gain distributions", ctx.capital_gains.capital_gain_distributions,
                "capital_gain_distributions",
            ),
            Operand(
                "Long-term loss carried in from last year",
                ctx.capital_gains.long_term_loss_carryover,
                Provenance.PRIOR_YEAR,
                role="subtract",
                field_name="long_term_loss_carryover",
                documents=ctx.documents_for("long_term_loss_carryover"),
                detail="From last year's return only.",
            ),
        ],
        formula=lambda ctx: (
            "Long-term gains + capital gain distributions − long-term loss carried forward"
        ),
        narrative=lambda ctx: (
            "Investments held more than a year are netted together, along with "
            "capital gain distributions your funds paid out."
        ),
    ),
    "D-16": LineSpec(
        section=FlowSection.INCOME,
        rule_id="capital_gains",
        operands=lambda ctx: [
            _line_operand(ctx, "D-7", "Net short-term"),
            _line_operand(ctx, "D-15", "Net long-term"),
        ],
        formula=lambda ctx: "Short-term net + long-term net",
        narrative=lambda ctx: "The two halves of Schedule D added together.",
    ),
    "8": LineSpec(
        section=FlowSection.INCOME,
        rule_id="schedule_1_income",
        operands=lambda ctx: [
            _doc_operand(ctx, "Business income (Schedule C)", ctx.income.business_income, "business_income"),
            _doc_operand(ctx, "Other gains (Form 4797)", ctx.income.other_gains, "other_gains"),
            _doc_operand(ctx, "Rental, partnership and S-corp income (Schedule E)", ctx.income.rental_income, "rental_income"),
            _doc_operand(ctx, "Other income", ctx.income.other_income, "other_income"),
        ],
        formula=lambda ctx: "Schedule 1 line 10 = business + other gains + rental + other",
        narrative=lambda ctx: (
            "Income that does not fit the main lines is totalled on Schedule 1 "
            f"and carried across as one figure of ${_money(ctx.amount('8'))}."
        ),
    ),
    "9": LineSpec(
        section=FlowSection.INCOME,
        rule_id="gross_income",
        operands=_income_total_operands,
        formula=lambda ctx: "Add lines 1a, 2b, 3b, 4b, 5b, 6b, 7 and 8",
        narrative=lambda ctx: (
            f"All of your income for the year adds up to ${_money(ctx.amount('9'))}. "
            "Note that tax-exempt interest and qualified dividends are not added "
            "again here — they are already accounted for."
        ),
    ),
    "10": LineSpec(
        section=FlowSection.ADJUSTMENTS,
        rule_id="adjustments",
        operands=lambda ctx: [
            _doc_operand(ctx, "Educator expenses", ctx.adjustments.educator_expenses, "educator_expenses"),
            _doc_operand(ctx, "Health savings account deduction", ctx.adjustments.hsa_deduction, "hsa_deduction"),
            _doc_operand(ctx, "Deductible part of self-employment tax", ctx.adjustments.self_employment_tax_deduction, "self_employment_tax_deduction"),
            _doc_operand(ctx, "Self-employed retirement plans", ctx.adjustments.self_employed_retirement, "self_employed_retirement"),
            _doc_operand(ctx, "Self-employed health insurance", ctx.adjustments.self_employed_health_insurance, "self_employed_health_insurance"),
            _doc_operand(ctx, "IRA deduction", ctx.adjustments.ira_deduction, "ira_deduction"),
            _doc_operand(ctx, "Student loan interest", ctx.adjustments.student_loan_interest, "student_loan_interest"),
            _doc_operand(ctx, "Other adjustments", ctx.adjustments.other_adjustments, "other_adjustments"),
        ],
        formula=lambda ctx: "Sum of the Schedule 1 Part II adjustments",
        narrative=lambda ctx: (
            "A short list of deductions you get whether or not you itemize. "
            + (
                f"They total ${_money(ctx.amount('10'))} and come off before your AGI."
                if ctx.amount("10") > ZERO
                else "None applied to you this year."
            )
        ),
        # Student loan interest is capped in the engine, so the raw operand can
        # exceed what was actually allowed. Reporting the cap as an arithmetic
        # failure would be wrong — it is the rule working.
        checkable=False,
    ),
    "11": LineSpec(
        section=FlowSection.AGI,
        rule_id="agi",
        operands=lambda ctx: [
            _line_operand(ctx, "9", "Total income"),
            _line_operand(ctx, "10", "Adjustments to income", role="subtract"),
        ],
        formula=lambda ctx: "Line 9 − line 10",
        narrative=lambda ctx: (
            f"Your adjusted gross income is ${_money(ctx.amount('11'))}. This is "
            "the number a lot of other tax rules are measured against, so it "
            "matters well beyond this line."
        ),
    ),
    "12": LineSpec(
        section=FlowSection.DEDUCTIONS,
        rule_id="standard_deduction",
        operands=lambda ctx: [
            Operand(
                "Deduction taken",
                ctx.result.deduction_taken,
                Provenance.COMPUTED,
                detail=f"The {ctx.result.deduction_method} deduction was larger.",
            ),
            Operand(
                "Filing status",
                ZERO,
                Provenance.TAXPAYER_PROFILE,
                role="info",
                detail=_humanize(ctx.result.filing_status),
            ),
            Operand(
                "Aged 65 or older",
                Decimal(ctx.profile.age_65_or_older),
                Provenance.TAXPAYER_PROFILE,
                role="info",
                detail="Each qualifying person increases the deduction.",
            ),
        ],
        formula=lambda ctx: (
            "Greater of the standard deduction or total itemized deductions"
        ),
        narrative=_deduction_narrative,
    ),
    "13b": LineSpec(
        section=FlowSection.DEDUCTIONS,
        rule_id="senior_deduction",
        operands=lambda ctx: [
            Operand(
                "Additional deduction for taxpayers 65+",
                ctx.result.additional_deductions,
                Provenance.TAXPAYER_PROFILE,
                detail="Based on date of birth and adjusted gross income.",
            ),
            Operand(
                "Adjusted gross income used for the phase-out",
                ctx.amount("11"),
                Provenance.COMPUTED,
                role="info",
                detail="The deduction shrinks as income rises.",
            ),
        ],
        formula=lambda ctx: "6,000 per qualifying person, reduced by 6% of income over the threshold",
        narrative=lambda ctx: (
            f"For {ctx.result.tax_year} there is an extra deduction for people aged 65 or older, "
            "on top of the larger standard deduction they already receive. Yours "
            f"is ${_money(ctx.result.additional_deductions)}."
        ),
    ),
    "14": LineSpec(
        section=FlowSection.DEDUCTIONS,
        rule_id="arithmetic",
        operands=lambda ctx: [
            _line_operand(ctx, "12", "Deduction"),
            *(
                [_line_operand(ctx, "13b", "Additional deductions")]
                if ctx.result.line("13b") is not None
                else []
            ),
        ],
        formula=lambda ctx: "Line 12 + line 13b",
        narrative=lambda ctx: (
            f"Your deductions total ${_money(ctx.amount('14'))}, which is the "
            "amount subtracted from your income before tax is worked out."
        ),
    ),
    "15": LineSpec(
        section=FlowSection.TAXABLE_INCOME,
        rule_id="taxable_income",
        operands=lambda ctx: [
            _line_operand(ctx, "11", "Adjusted gross income"),
            _line_operand(ctx, "14", "Total deductions", role="subtract"),
        ],
        formula=lambda ctx: "Line 11 − line 14, but never below zero",
        narrative=lambda ctx: (
            (
                "Your deductions were larger than your income, so your taxable "
                "income is zero. It never goes negative."
            )
            if ctx.amount("15") <= ZERO
            else (
                f"After deductions, ${_money(ctx.amount('15'))} of your income is "
                "actually taxed."
            )
        ),
        # Floors at zero, so the subtraction does not always reproduce the line.
        checkable=False,
    ),
    "16": LineSpec(
        section=FlowSection.TAX,
        rule_id="ordinary_rates",
        operands=lambda ctx: [
            _line_operand(ctx, "15", "Taxable income", role="info"),
            Operand(
                "Income taxed at lower investment rates",
                min(
                    ctx.income.qualified_dividends + max(ctx.amount("7"), ZERO),
                    ctx.result.taxable_income,
                ),
                Provenance.COMPUTED,
                role="info",
                detail="Qualified dividends and long-term gains.",
            ),
        ],
        formula=lambda ctx: (
            "Bracket rates on ordinary income, plus preferential rates on "
            "qualified dividends and long-term gains"
        ),
        narrative=lambda ctx: (
            (
                "There is no tax, because after deductions there was no taxable "
                "income left."
            )
            if ctx.result.tax_before_credits <= ZERO
            else (
                f"Your tax before credits is ${_money(ctx.result.tax_before_credits)}. "
                "Income is taxed in slices: the first slice at the lowest rate, "
                "each later slice a little higher. Investment income held long "
                "term is taxed at lower rates than wages."
            )
        ),
        checkable=False,
    ),
    "19": LineSpec(
        section=FlowSection.CREDITS,
        rule_id="child_tax_credit",
        operands=lambda ctx: [
            Operand(
                "Qualifying children",
                Decimal(ctx.profile.qualifying_children),
                Provenance.TAXPAYER_PROFILE,
                role="info",
            ),
            Operand(
                "Other dependents",
                Decimal(ctx.profile.other_dependents),
                Provenance.TAXPAYER_PROFILE,
                role="info",
            ),
            _line_operand(ctx, "11", "Adjusted gross income", role="info"),
        ],
        formula=lambda ctx: "Per-child credit, reduced once income passes the threshold",
        narrative=lambda ctx: (
            "A credit for each qualifying child comes straight off the tax you "
            "owe."
            if ctx.amount("19") > ZERO
            else "No child tax credit applied, because no qualifying dependents were recorded."
        ),
        checkable=False,
    ),
    "21": LineSpec(
        section=FlowSection.CREDITS,
        rule_id="nonrefundable_credits",
        operands=lambda ctx: [
            _line_operand(ctx, "19", "Child tax credit", role="info"),
            Operand(
                "Other nonrefundable credits",
                ctx.payments.other_nonrefundable_credits,
                Provenance.SOURCE_DOCUMENT,
                role="info",
                field_name="other_nonrefundable_credits",
                documents=ctx.documents_for("other_nonrefundable_credits"),
            ),
        ],
        formula=lambda ctx: "Credits, capped at the tax on line 16",
        narrative=lambda ctx: (
            "These credits can reduce your tax to zero but no further — any "
            "excess is not paid out to you."
        ),
        checkable=False,
    ),
    "23": LineSpec(
        section=FlowSection.OTHER_TAXES,
        rule_id="self_employment_tax",
        operands=lambda ctx: [
            _doc_operand(
                ctx, "Self-employment income", ctx.income.business_income, "business_income",
                role="info",
            )
        ],
        formula=lambda ctx: "15.3% on 92.35% of net self-employment earnings, up to the wage base",
        narrative=lambda ctx: (
            "Working for yourself means paying both halves of Social Security "
            "and Medicare — the employee part and the part an employer would "
            "normally cover. Half of it is deductible on line 10."
        ),
        checkable=False,
    ),
    "24": LineSpec(
        section=FlowSection.TOTAL_TAX,
        rule_id="total_tax",
        operands=lambda ctx: [
            _line_operand(ctx, "16", "Tax"),
            _line_operand(ctx, "21", "Nonrefundable credits", role="subtract"),
            *(
                [_line_operand(ctx, "23", "Self-employment tax")]
                if ctx.result.line("23") is not None
                else []
            ),
        ],
        formula=lambda ctx: "Line 16 − line 21 + other taxes",
        narrative=lambda ctx: (
            f"Your total tax for the year is ${_money(ctx.result.total_tax)}."
        ),
    ),
    "25": LineSpec(
        section=FlowSection.PAYMENTS,
        rule_id="withholding",
        operands=lambda ctx: [
            _doc_operand(
                ctx,
                "Federal income tax already withheld from your pay and accounts",
                ctx.payments.federal_withheld,
                "federal_withheld",
            ),
        ],
        formula=lambda ctx: "Federal income tax withheld, from your W-2s and 1099s",
        narrative=lambda ctx: (
            "This is tax you have already paid during the year — your employer "
            "and your banks sent it to the IRS on your behalf. It counts "
            "against the tax you owe, and is the usual reason a return ends in "
            "a refund rather than a bill."
        ),
    ),
    "26": LineSpec(
        section=FlowSection.PAYMENTS,
        rule_id="estimated_payments",
        operands=lambda ctx: [
            _doc_operand(ctx, "Estimated tax payments you made", ctx.payments.estimated_payments, "estimated_payments"),
            Operand(
                "Last year's overpayment left with the IRS",
                ctx.payments.prior_year_overpayment_applied,
                Provenance.PRIOR_YEAR,
                field_name="prior_year_overpayment_applied",
                documents=ctx.documents_for("prior_year_overpayment_applied"),
                detail="Stated only on last year's return.",
            ),
        ],
        formula=lambda ctx: "Payments you made + last year's overpayment applied",
        narrative=lambda ctx: (
            "This line combines money you paid in during the year with any "
            "refund from last year that you chose to leave with the IRS."
        ),
    ),
    "33": LineSpec(
        section=FlowSection.PAYMENTS,
        rule_id="withholding",
        operands=lambda ctx: [
            _doc_operand(ctx, "Federal income tax withheld", ctx.payments.federal_withheld, "federal_withheld"),
            *(
                [_line_operand(ctx, "26", "Estimated payments and prior-year credit")]
                if ctx.result.line("26") is not None
                else []
            ),
            _doc_operand(ctx, "Earned income credit", ctx.payments.earned_income_credit, "earned_income_credit"),
            _doc_operand(ctx, "Additional child tax credit", ctx.payments.additional_child_tax_credit, "additional_child_tax_credit"),
            _doc_operand(ctx, "American opportunity credit", ctx.payments.american_opportunity_credit, "american_opportunity_credit"),
            _doc_operand(ctx, "Other payments", ctx.payments.other_payments, "other_payments"),
        ],
        formula=lambda ctx: "Withholding + estimated payments + refundable credits",
        narrative=lambda ctx: (
            f"You had already paid ${_money(ctx.result.total_payments)} toward "
            "this year's tax."
        ),
    ),
    "34": LineSpec(
        section=FlowSection.OUTCOME,
        rule_id="overpayment",
        operands=lambda ctx: [
            _line_operand(ctx, "33", "Total payments"),
            _line_operand(ctx, "24", "Total tax", role="subtract"),
        ],
        formula=lambda ctx: "Line 33 − line 24",
        narrative=_outcome_narrative,
    ),
    "35a": LineSpec(
        section=FlowSection.OUTCOME,
        rule_id="overpayment",
        operands=lambda ctx: [
            _line_operand(ctx, "34", "Overpaid"),
            Operand(
                "Applied to next year instead",
                ctx.result.applied_to_next_year,
                Provenance.ELECTION,
                role="subtract",
                detail="Your choice, not something the documents decide.",
            ),
        ],
        formula=lambda ctx: "Overpayment − amount applied to next year",
        narrative=lambda ctx: (
            f"${_money(ctx.result.refund)} is refunded to you."
        ),
    ),
    "36": LineSpec(
        section=FlowSection.OUTCOME,
        rule_id="applied_to_next_year",
        operands=lambda ctx: [
            Operand(
                "Amount you chose to carry forward",
                ctx.result.applied_to_next_year,
                Provenance.ELECTION,
                detail="An election you make, capped at what you actually overpaid.",
            )
        ],
        formula=lambda ctx: "The elected amount, capped at line 34",
        narrative=lambda ctx: (
            f"You chose to leave ${_money(ctx.result.applied_to_next_year)} with "
            "the IRS as a head start on next year's tax rather than take it as a "
            "refund now."
        ),
    ),
    "37": LineSpec(
        section=FlowSection.OUTCOME,
        rule_id="amount_owed",
        operands=lambda ctx: [
            _line_operand(ctx, "24", "Total tax"),
            _line_operand(ctx, "33", "Total payments", role="subtract"),
        ],
        formula=lambda ctx: "Line 24 − line 33",
        narrative=_outcome_narrative,
    ),
}


#: Lines the engine may emit that intentionally have no separate explanation,
#: because another line already explains them in full.
_ALIASED: dict[str, str] = {}


class ExplanationService:
    """Builds the explainability payload for a computed return."""

    def build(self, ctx: ExplanationContext) -> ReturnExplanation:
        lines: list[LineExplanation] = []

        for engine_line in ctx.result.lines:
            spec = SPECS.get(_ALIASED.get(engine_line.number, engine_line.number))
            if spec is None:
                # Fail loudly rather than silently omitting: an unexplained line
                # is the black box this service exists to remove.
                lines.append(self._unspecified(engine_line))
                continue

            operands = [o for o in spec.operands(ctx) if self._keep(o)]
            rule = RULES.get(spec.rule_id) or RULES["arithmetic"]

            checked = False
            if spec.checkable:
                checked = _sum_operands(operands) == engine_line.amount

            fields = tuple(o.field_name for o in operands if o.field_name)
            confidence = ctx.confidence_for(*fields) if fields else None
            provenance = self._provenance(spec, operands)

            lines.append(
                LineExplanation(
                    line=engine_line.number,
                    label=engine_line.label,
                    amount=engine_line.amount,
                    section=spec.section,
                    rule=rule,
                    formula=spec.formula(ctx),
                    narrative=spec.narrative(ctx),
                    operands=operands,
                    provenance=provenance,
                    status=self._status(spec, provenance, checked, confidence),
                    confidence=confidence,
                    arithmetic_checked=checked,
                    note=engine_line.note,
                )
            )

        return ReturnExplanation(
            tax_year=ctx.result.tax_year,
            filing_status=ctx.result.filing_status,
            deduction_method=ctx.result.deduction_method,
            summary=self._summary(ctx),
            lines=lines,
            assumptions=self._assumptions(ctx, lines),
            warnings=list(ctx.result.warnings),
            unverified_citations=sorted(
                {line.rule.title for line in lines if not line.rule.verified}
            ),
        )

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _keep(operand: Operand) -> bool:
        """Drop zero-valued addends so the panel shows what actually applied.

        A reviewer reading line 10 wants the two adjustments that were taken,
        not the six that were not. Informational and non-zero operands stay.
        """
        return operand.amount != ZERO or operand.role == "info"

    @staticmethod
    def _provenance(spec: LineSpec, operands: Sequence[Operand]) -> Provenance:
        """Derived from the operands, never asserted by the spec alone.

        A spec declares what a line *should* be sourced from; only an operand
        carrying an actual document proves it was. Letting the spec's optimistic
        default stand when no document was recorded made every income line
        report "verified from source documents" on a run with no provenance at
        all — the one claim this panel must never make falsely.
        """
        if any(o.provenance is Provenance.SOURCE_DOCUMENT and o.documents for o in operands):
            return Provenance.SOURCE_DOCUMENT
        if any(o.provenance is Provenance.ELECTION for o in operands):
            return Provenance.ELECTION
        if any(o.provenance is Provenance.PRIOR_YEAR for o in operands):
            return Provenance.PRIOR_YEAR
        if spec.provenance is Provenance.SOURCE_DOCUMENT:
            return Provenance.ASSUMPTION
        return spec.provenance

    @staticmethod
    def _status(
        spec: LineSpec,
        provenance: Provenance,
        checked: bool,
        confidence: float | None,
    ) -> ValidationStatus:
        if spec.checkable and not checked:
            return ValidationStatus.REVIEW
        if confidence is not None and confidence < 0.75:
            return ValidationStatus.REVIEW
        if provenance is Provenance.SOURCE_DOCUMENT:
            return ValidationStatus.VERIFIED
        return ValidationStatus.COMPUTED

    @staticmethod
    def _unspecified(engine_line: Any) -> LineExplanation:
        return LineExplanation(
            line=engine_line.number,
            label=engine_line.label,
            amount=engine_line.amount,
            section=FlowSection.INCOME,
            rule=RULES["arithmetic"],
            formula="",
            narrative=(
                "This line has no explanation recorded yet. Review it manually "
                "before relying on the return."
            ),
            status=ValidationStatus.REVIEW,
            note=engine_line.note,
        )

    @staticmethod
    def _summary(ctx: ExplanationContext) -> dict[str, str]:
        result = ctx.result
        return {
            "filing_status": _humanize(result.filing_status),
            "total_income": str(result.total_income),
            "adjusted_gross_income": str(result.adjusted_gross_income),
            "deduction_method": result.deduction_method,
            "deductions": str(result.deduction_taken + result.additional_deductions),
            "taxable_income": str(result.taxable_income),
            "credits": str(result.total_credits),
            "total_tax": str(result.total_tax),
            "payments": str(result.total_payments),
            "refund": str(result.refund),
            "amount_owed": str(result.amount_owed),
            "applied_to_next_year": str(result.applied_to_next_year),
        }

    @staticmethod
    def _assumptions(
        ctx: ExplanationContext, lines: Sequence[LineExplanation]
    ) -> list[str]:
        """Everything the system decided without a document telling it to."""
        notes: list[str] = []

        if not ctx.field_provenance:
            notes.append(
                "No document-level provenance was recorded for this run, so "
                "figures are shown without a source page."
            )
        if ctx.profile.age_65_or_older:
            notes.append(
                f"{ctx.profile.age_65_or_older} taxpayer(s) treated as aged 65 or "
                "older, which increases the standard deduction and adds the "
                "Schedule 1-A deduction."
            )
        if ctx.result.applied_to_next_year > ZERO:
            notes.append(
                "The overpayment was applied to next year rather than refunded. "
                "This is an election and cannot be derived from the documents."
            )
        if ctx.capital_gains.short_term_loss_carryover > ZERO or (
            ctx.capital_gains.long_term_loss_carryover > ZERO
        ):
            notes.append(
                "Capital loss carryovers came from the prior year's return, not "
                "from any current-year document."
            )
        for line in lines:
            if line.status is ValidationStatus.REVIEW:
                notes.append(
                    f"Line {line.line} ({line.label}) is flagged for manual review."
                )
        return notes


# --- Persistence -----------------------------------------------------------


class ExplanationStore:
    """Keeps the engine's *inputs* so the explanation can be rebuilt later.

    Storing the rendered explanation would freeze it: a later fix to the engine
    or to a rule citation would leave every historical return explained by the
    superseded logic, with nothing indicating it. Storing the inputs instead
    means an explanation is always regenerated by the code currently in force,
    and a preparer reopening a return sees today's understanding of it.

    SECURITY: amounts and provenance only. This file lives in the output zone
    and is never sent outbound; identity fields are excluded at write time
    rather than filtered at read time, so a new identity field cannot leak in
    by default.
    """

    #: Written keys. An allow-list, so adding an identity field to the merged
    #: payload upstream cannot silently start persisting it here.
    _KEYS = ("normalized", "field_provenance", "confidence_scores", "profile")

    def __init__(self, directory: Any) -> None:
        from pathlib import Path

        self._directory = Path(directory)

    def _path(self, workflow_id: str) -> Any:
        return self._directory / f"{workflow_id}.json"

    def save(
        self,
        workflow_id: str,
        *,
        normalized: dict[str, Any],
        field_provenance: dict[str, list[dict[str, str]]],
        confidence_scores: dict[str, Any],
        profile: dict[str, Any],
    ) -> None:
        import json

        # Imported inside the method: the orchestrator imports this module, so
        # a module-level import here would close the cycle.
        from app.services.workflow_orchestrator import (
            IDENTITY_FIELD_ALIASES,
            IDENTITY_FIELDS,
        )

        identity = set(IDENTITY_FIELDS) | set(IDENTITY_FIELD_ALIASES)
        payload = {
            "normalized": {
                k: v for k, v in normalized.items() if k not in identity
            },
            "field_provenance": field_provenance,
            "confidence_scores": confidence_scores,
            "profile": profile,
        }
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path(workflow_id).write_text(
            json.dumps({k: payload[k] for k in self._KEYS}, indent=2),
            encoding="utf-8",
        )

    def load(self, workflow_id: str) -> dict[str, Any] | None:
        import json

        path = self._path(workflow_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def build_for_workflow(
    workflow_id: str, *, output_zone_dir: Any
) -> ReturnExplanation | None:
    """Rebuild a workflow's explanation from its stored engine inputs.

    Returns None when no inputs were filed — a run that predates this feature,
    or one that never reached a computed return. The caller reports that as a
    404 rather than inventing an empty explanation, because a blank
    "How We Arrived Here" reads as "nothing to explain" rather than "not
    recorded".
    """
    from app.services.tax_engine.form_1040 import Form1040Calculator
    from app.services.tax_engine.tax_tables import FilingStatusTax
    from app.services.workflow_orchestrator import _build_engine_inputs

    stored = ExplanationStore(output_zone_dir / "explanations").load(workflow_id)
    if not stored:
        return None

    normalized = stored.get("normalized") or {}
    saved_profile = stored.get("profile") or {}

    try:
        status = FilingStatusTax(saved_profile.get("filing_status", "single"))
    except ValueError:
        status = FilingStatusTax.SINGLE

    profile = TaxpayerProfile(
        tax_year=int(saved_profile.get("tax_year") or 0),
        filing_status=status,
        age_65_or_older=int(saved_profile.get("age_65_or_older") or 0),
        qualifying_children=int(saved_profile.get("qualifying_children") or 0),
        other_dependents=int(saved_profile.get("other_dependents") or 0),
        state_code=saved_profile.get("state_code"),
    )
    income = _build_engine_inputs(IncomeInputs, normalized)
    capital_gains = _build_engine_inputs(CapitalGainInputs, normalized)
    adjustments = _build_engine_inputs(AdjustmentInputs, normalized)
    deductions = _build_engine_inputs(DeductionInputs, normalized)
    payments = _build_engine_inputs(PaymentInputs, normalized)

    result = Form1040Calculator().compute(
        profile=profile,
        income=income,
        adjustments=adjustments,
        deductions=deductions,
        payments=payments,
        capital_gains=capital_gains,
    )
    return ExplanationService().build(
        ExplanationContext(
            result=result,
            profile=profile,
            income=income,
            adjustments=adjustments,
            deductions=deductions,
            payments=payments,
            capital_gains=capital_gains,
            field_provenance=stored.get("field_provenance") or {},
            confidence_scores=stored.get("confidence_scores") or {},
        )
    )
