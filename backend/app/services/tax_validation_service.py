"""Validation of extracted facts against deterministic recomputation.

The contract between the model and this service:

* the model **extracts and proposes**;
* this service **recomputes and decides**.

Whenever an LLM-supplied figure disagrees with the deterministic result beyond
``CALC_TOLERANCE_DOLLARS``, the deterministic value wins and a review item is
raised. The model's number is recorded for the reviewer to see, but it never
silently becomes the answer.

Checks performed:

* schema conformance of the model's JSON payload
* per-document tie-outs (W-2 FICA recomputation, 1099 box arithmetic)
* cross-footing of stated totals against components
* trial balance debits/credits
* depreciation schedule recomputation
* whole-return recomputation of Form 1040
* internal consistency (taxable ≤ gross, withholding plausibility)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.enums import DocumentType, ReviewReason
from app.services.tax_engine.computations import (
    ZERO,
    CrossFootResult,
    DepreciationRow,
    TrialBalanceLine,
    cross_foot,
    money,
    payroll_tax_check,
    recompute_depreciation_schedule,
    to_cents,
    verify_trial_balance,
)
from app.services.tax_engine.form_1040 import Return1040

logger = get_logger(__name__)
D = Decimal


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class ValidationIssue:
    """One problem found during validation.

    SECURITY: ``field_name`` and messages reference tokens and line labels, not
    taxpayer values. Amounts are not PII on their own and are needed by the
    reviewer to act.
    """

    code: str
    message: str
    severity: Severity
    review_reason: ReviewReason
    field_name: str | None = None
    expected: str | None = None
    actual: str | None = None
    document_id: str | None = None
    page_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "review_reason": self.review_reason.value,
            "field": self.field_name,
            "expected": self.expected,
            "actual": self.actual,
            "page": self.page_number,
        }


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    checks_run: int = 0
    checks_passed: int = 0
    recomputed: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def confidence(self) -> float:
        """Overall validation confidence, 0-1."""
        if self.checks_run == 0:
            return 0.0
        base = self.checks_passed / self.checks_run
        # Errors matter far more than warnings.
        penalty = 0.15 * len(self.errors) + 0.03 * len(self.warnings)
        return max(0.0, min(1.0, base - penalty))

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def record_check(self, passed: bool) -> None:
        self.checks_run += 1
        if passed:
            self.checks_passed += 1

    def summary(self) -> dict[str, Any]:
        return {
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "confidence": round(self.confidence, 3),
            "passed": self.passed,
        }


#: Required keys in the model's document-extraction payload.
_REQUIRED_EXTRACTION_KEYS = (
    "extracted_tax_facts",
    "normalized_fields",
    "confidence_scores",
    "review_flags",
)


class TaxValidationService:
    """Recomputes and validates everything the model proposed."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def _tolerance(self) -> Decimal:
        return D(str(self._settings.calc_tolerance_dollars))

    # ------------------------------------------------------ schema checks

    def validate_extraction_schema(self, payload: dict[str, Any]) -> ValidationReport:
        """Check the model returned the structure the pipeline expects."""
        report = ValidationReport()

        for key in _REQUIRED_EXTRACTION_KEYS:
            present = key in payload
            report.record_check(present)
            if not present:
                report.add(
                    ValidationIssue(
                        code="schema.missing_key",
                        message=f"Model response is missing '{key}'.",
                        severity=Severity.ERROR,
                        review_reason=ReviewReason.SCHEMA_VIOLATION,
                        field_name=key,
                    )
                )

        facts = payload.get("extracted_tax_facts")
        if facts is not None and not isinstance(facts, list):
            report.record_check(False)
            report.add(
                ValidationIssue(
                    code="schema.wrong_type",
                    message="'extracted_tax_facts' must be a list.",
                    severity=Severity.ERROR,
                    review_reason=ReviewReason.SCHEMA_VIOLATION,
                    field_name="extracted_tax_facts",
                )
            )

        # A model that reports no confidence for any field cannot be trusted to
        # have been careful; force review rather than accepting silently.
        scores = payload.get("confidence_scores") or {}
        if isinstance(scores, dict) and facts and not scores:
            report.add(
                ValidationIssue(
                    code="schema.no_confidence",
                    message=(
                        "Facts were extracted with no per-field confidence "
                        "scores; all fields require verification."
                    ),
                    severity=Severity.WARNING,
                    review_reason=ReviewReason.LOW_CONFIDENCE,
                )
            )
        return report

    # ------------------------------------------------- per-document checks

    def validate_w2(
        self, fields: dict[str, Any], *, tax_year: int, document_id: str | None = None
    ) -> ValidationReport:
        """Recompute W-2 FICA withholding and check internal consistency."""
        report = ValidationReport()
        wages = money(fields.get("wages"))
        ss_wages = money(fields.get("social_security_wages")) or wages
        medicare_wages = money(fields.get("medicare_wages")) or wages

        check = payroll_tax_check(
            wages=ss_wages,
            withheld_ss=fields.get("social_security_tax_withheld"),
            withheld_medicare=fields.get("medicare_tax_withheld"),
            year=tax_year,
        )
        report.recomputed["w2_fica"] = check

        for label, variance_key, reported_key in (
            ("Social security tax", "social_security_variance", "social_security_tax_withheld"),
            ("Medicare tax", "medicare_variance", "medicare_tax_withheld"),
        ):
            # Only meaningful if the box was actually populated.
            if money(fields.get(reported_key)) == ZERO:
                continue
            variance = abs(D(check[variance_key]))
            ok = variance <= self._tolerance
            report.record_check(ok)
            if not ok:
                report.add(
                    ValidationIssue(
                        code="w2.fica_variance",
                        message=(
                            f"{label} withheld does not match the statutory rate "
                            f"applied to reported wages (variance {variance}). "
                            "Common causes: multiple employers, a mid-year wage "
                            "base crossover, or an OCR misread."
                        ),
                        severity=Severity.WARNING,
                        review_reason=ReviewReason.CALCULATION_MISMATCH,
                        field_name=reported_key,
                        expected=check[
                            "expected_social_security"
                            if "social" in variance_key
                            else "expected_medicare"
                        ],
                        actual=check[
                            "reported_social_security"
                            if "social" in variance_key
                            else "reported_medicare"
                        ],
                        document_id=document_id,
                    )
                )

        # Federal withholding exceeding wages is a certain misread.
        withheld = money(fields.get("federal_tax_withheld"))
        ok = withheld <= wages or wages == ZERO
        report.record_check(ok)
        if not ok:
            report.add(
                ValidationIssue(
                    code="w2.withholding_exceeds_wages",
                    message=(
                        "Federal tax withheld exceeds reported wages, which is "
                        "not possible. The box values were probably misread."
                    ),
                    severity=Severity.ERROR,
                    review_reason=ReviewReason.CALCULATION_MISMATCH,
                    field_name="federal_tax_withheld",
                    expected=f"<= {wages}",
                    actual=str(withheld),
                    document_id=document_id,
                )
            )
        return report

    def validate_1099_div(
        self, fields: dict[str, Any], *, document_id: str | None = None
    ) -> ValidationReport:
        """Qualified dividends cannot exceed total ordinary dividends."""
        report = ValidationReport()
        ordinary = money(fields.get("ordinary_dividends"))
        qualified = money(fields.get("qualified_dividends"))

        ok = qualified <= ordinary or ordinary == ZERO
        report.record_check(ok)
        if not ok:
            report.add(
                ValidationIssue(
                    code="1099div.qualified_exceeds_ordinary",
                    message=(
                        "Qualified dividends (box 1b) exceed total ordinary "
                        "dividends (box 1a). Box 1b is a subset of box 1a."
                    ),
                    severity=Severity.ERROR,
                    review_reason=ReviewReason.SOURCE_CONFLICT,
                    field_name="qualified_dividends",
                    expected=f"<= {ordinary}",
                    actual=str(qualified),
                    document_id=document_id,
                )
            )
        return report

    def validate_1099_b(
        self, fields: dict[str, Any], *, document_id: str | None = None
    ) -> ValidationReport:
        """Proceeds minus basis must equal the reported gain or loss."""
        report = ValidationReport()

        for term in ("short_term", "long_term"):
            proceeds = money(fields.get(f"{term}_proceeds"))
            basis = money(fields.get(f"{term}_cost_basis"))
            stated_gain = money(fields.get(f"{term}_gain_loss"))
            if proceeds == ZERO and basis == ZERO:
                continue

            computed = to_cents(proceeds - basis)
            variance = abs(to_cents(stated_gain - computed))
            ok = variance <= self._tolerance
            report.record_check(ok)
            report.recomputed[f"{term}_gain"] = str(computed)
            if not ok:
                report.add(
                    ValidationIssue(
                        code="1099b.gain_mismatch",
                        message=(
                            f"{term.replace('_', ' ').title()} gain/loss does not "
                            f"equal proceeds minus basis (variance {variance}). "
                            "Wash sale adjustments can explain a difference — "
                            "confirm before accepting."
                        ),
                        severity=Severity.WARNING,
                        review_reason=ReviewReason.CALCULATION_MISMATCH,
                        field_name=f"{term}_gain_loss",
                        expected=str(computed),
                        actual=str(stated_gain),
                        document_id=document_id,
                    )
                )
        return report

    #: Document type -> the validator that knows how to check it.
    #:
    #: Dispatch is a table rather than a chain of ifs because the failure it
    #: fixes was an omission, not a mistake: these validators were written,
    #: tested and then never called. The orchestrator invoked exactly two
    #: methods on this service — the schema check and the return recomputation —
    #: so the live pipeline had no box-level validation of any kind. A W-2
    #: misread that turned 4,920 of withholding into 49,200 was caught only if
    #: it happened to exceed wages.
    def validate_document(
        self,
        document_type: str,
        fields: dict[str, Any],
        *,
        tax_year: int,
        document_id: str | None = None,
    ) -> ValidationReport:
        """Run whichever per-document checks apply to this form type.

        Returns an empty report for a type with no checks, so the caller can
        dispatch unconditionally.
        """
        kind = str(document_type or "").strip().lower()

        if kind == DocumentType.W2.value:
            return self.validate_w2(
                fields, tax_year=tax_year, document_id=document_id
            )
        if kind == DocumentType.FORM_1099_DIV.value:
            return self.validate_1099_div(fields, document_id=document_id)
        if kind == DocumentType.FORM_1099_B.value:
            return self.validate_1099_b(fields, document_id=document_id)
        if kind == DocumentType.DEPRECIATION_SCHEDULE.value:
            rows = fields.get("rows")
            if isinstance(rows, list):
                return self.validate_depreciation(rows, document_id=document_id)
        if kind in {
            DocumentType.TRIAL_BALANCE.value,
            DocumentType.GENERAL_LEDGER.value,
        }:
            rows = fields.get("rows")
            if isinstance(rows, list):
                return self.validate_trial_balance(rows, document_id=document_id)
        return ValidationReport()

    def validate_trial_balance(
        self, rows: list[dict[str, Any]], *, document_id: str | None = None
    ) -> ValidationReport:
        report = ValidationReport()
        lines = [
            TrialBalanceLine(
                account=str(row.get("account", "")),
                debit=money(row.get("debit")),
                credit=money(row.get("credit")),
            )
            for row in rows
        ]
        result = verify_trial_balance(lines, tolerance=self._tolerance)
        report.recomputed["trial_balance"] = result.to_dict()
        report.record_check(result.balanced)

        if not result.balanced:
            report.add(
                ValidationIssue(
                    code="trial_balance.out_of_balance",
                    message=(
                        f"Trial balance is out of balance by "
                        f"{result.out_of_balance} across {result.line_count} "
                        "accounts. The workpaper cannot be relied on until this "
                        "is resolved."
                    ),
                    severity=Severity.ERROR,
                    review_reason=ReviewReason.CALCULATION_MISMATCH,
                    expected=str(result.total_debits),
                    actual=str(result.total_credits),
                    document_id=document_id,
                )
            )
        return report

    def validate_depreciation(
        self, rows: list[dict[str, Any]], *, document_id: str | None = None
    ) -> ValidationReport:
        report = ValidationReport()
        parsed: list[DepreciationRow] = []
        for row in rows:
            try:
                parsed.append(
                    DepreciationRow(
                        description=str(row.get("description", "asset")),
                        basis=money(row.get("basis")),
                        recovery_years=int(row.get("recovery_years", 5)),
                        year_in_service=int(row.get("year_in_service", 1)),
                        method=str(row.get("method", "macrs")),
                        salvage=money(row.get("salvage")),
                        useful_life_years=int(row.get("useful_life_years", 0)),
                        stated_current=row.get("current_depreciation"),
                    )
                )
            except (TypeError, ValueError):
                report.record_check(False)
                report.add(
                    ValidationIssue(
                        code="depreciation.unparseable_row",
                        message=(
                            "A depreciation line could not be parsed; verify the "
                            "asset's basis, method, and recovery period."
                        ),
                        severity=Severity.WARNING,
                        review_reason=ReviewReason.MISSING_REQUIRED_DATA,
                        document_id=document_id,
                    )
                )

        if not parsed:
            return report

        result = recompute_depreciation_schedule(parsed, tolerance=self._tolerance)
        report.recomputed["depreciation"] = result
        report.record_check(result["ok"])
        if not result["ok"]:
            report.add(
                ValidationIssue(
                    code="depreciation.mismatch",
                    message=(
                        f"{result['mismatch_count']} depreciation line(s) do not "
                        f"match a recomputation (total variance "
                        f"{result['variance']})."
                    ),
                    severity=Severity.WARNING,
                    review_reason=ReviewReason.CALCULATION_MISMATCH,
                    expected=result["computed_total"],
                    actual=result["stated_total"],
                    document_id=document_id,
                )
            )
        return report

    # ---------------------------------------------------- cross-footing

    def validate_cross_foot(
        self, label: str, components: list[Any], stated_total: Any
    ) -> tuple[ValidationReport, CrossFootResult]:
        report = ValidationReport()
        result = cross_foot(label, components, stated_total, tolerance=self._tolerance)
        report.record_check(result.ok)
        report.recomputed[label] = result.to_dict()
        if not result.ok:
            report.add(
                ValidationIssue(
                    code="crossfoot.mismatch",
                    message=(
                        f"'{label}' does not cross-foot: components sum to "
                        f"{result.computed} but the stated total is "
                        f"{result.stated} (difference {result.difference})."
                    ),
                    severity=Severity.ERROR,
                    review_reason=ReviewReason.CALCULATION_MISMATCH,
                    field_name=label,
                    expected=str(result.computed),
                    actual=str(result.stated),
                )
            )
        return report, result

    # ------------------------------------------------- whole-return check

    def validate_return(
        self, computed: Return1040, claimed: dict[str, Any] | None = None
    ) -> ValidationReport:
        """Compare a model-proposed return against the deterministic result.

        SECURITY / correctness: on any disagreement the deterministic figure is
        authoritative. This method never rewrites ``computed`` to match the
        model — it raises a review item instead.
        """
        report = ValidationReport()
        report.recomputed["return"] = computed.to_dict()

        # --- Cross-footing: does the form add up as printed? --------------
        # A reviewer reads down the page and adds. If the components printed on
        # the form do not sum to the totals printed beneath them, the return is
        # unsignable however well each individual figure was computed — and
        # this is exactly the class of defect that survives unit tests, because
        # every part is right and only the assembly is wrong.
        lines = {line.number: line.amount for line in computed.lines}

        def line(number: str) -> Decimal:
            return lines.get(number, ZERO)

        footings: tuple[tuple[str, list[Decimal], Decimal], ...] = (
            (
                "Line 9 total income = lines 1a through 8",
                [line("1a"), line("2b"), line("3b"), line("4b"), line("5b"),
                 line("6b"), line("7"), line("8")],
                computed.total_income,
            ),
            (
                "Line 11 AGI = line 9 less line 10",
                [computed.total_income, -line("10")],
                computed.adjusted_gross_income,
            ),
            (
                "Line 14 total deductions = lines 12, 13a and 13b",
                [computed.deduction_taken, line("13a"), computed.additional_deductions],
                line("14") if "14" in lines else computed.deduction_taken,
            ),
            (
                "Line 15 taxable income = line 11 less line 14",
                [computed.adjusted_gross_income, -line("14")],
                computed.taxable_income,
            ),
            (
                "Line 23 other taxes = Schedule 2 components",
                [computed.self_employment_tax, computed.additional_medicare_tax,
                 computed.net_investment_income_tax],
                computed.other_taxes,
            ),
            (
                "Line 24 total tax = line 16 less line 21 plus line 23",
                [computed.tax_before_credits, -computed.total_credits,
                 computed.other_taxes],
                computed.total_tax,
            ),
            (
                "Line 33 total payments = lines 25d, 26, 27, 28, 29",
                [computed.federal_withheld, line("26"), line("27"), line("28"),
                 line("29")],
                computed.total_payments,
            ),
            (
                "Refund and balance reconcile to payments less tax",
                [computed.total_payments, -computed.total_tax,
                 -computed.applied_to_next_year],
                to_cents(computed.refund - computed.amount_owed),
            ),
        )

        for label, components, stated in footings:
            # Line 15 is floored at zero, so a return whose deductions exceed
            # its income legitimately does not foot; the floor is the answer.
            if label.startswith("Line 15") and computed.taxable_income == ZERO:
                continue
            result = cross_foot(label, components, stated, tolerance=self._tolerance)
            report.record_check(result.ok)
            report.recomputed[f"crossfoot.{label[:20]}"] = result.to_dict()
            if not result.ok:
                report.add(
                    ValidationIssue(
                        code="return.does_not_foot",
                        message=(
                            f"{label}: the components sum to {result.computed} "
                            f"but the total shows {result.stated}, a difference "
                            f"of {result.difference}. A form that does not foot "
                            "cannot be signed."
                        ),
                        severity=Severity.ERROR,
                        review_reason=ReviewReason.CALCULATION_MISMATCH,
                        field_name=label,
                        expected=str(result.computed),
                        actual=str(result.stated),
                    )
                )

        # --- Sanity ranges ------------------------------------------------
        # Bounds a real return cannot cross. Each one catches a decimal-shift or
        # sign error that every other check would pass.
        effective_rate = (
            computed.total_tax / computed.total_income
            if computed.total_income > ZERO
            else ZERO
        )
        for label, condition, message in (
            (
                "effective_rate_plausible",
                effective_rate <= Decimal("0.60"),
                f"Total tax is {effective_rate:.0%} of total income, above any "
                "combined statutory rate. Check for a misplaced decimal.",
            ),
            (
                "withholding_plausible",
                computed.federal_withheld <= max(computed.total_income, ZERO)
                or computed.total_income <= ZERO,
                "Federal withholding exceeds total income, which is not "
                "possible. The box values were probably misread.",
            ),
            (
                "deduction_plausible",
                computed.deduction_taken <= max(computed.adjusted_gross_income,
                                                Decimal(50000)),
                "Itemized deductions exceed AGI by a wide margin. Confirm the "
                "Schedule A figures.",
            ),
        ):
            report.record_check(condition)
            if not condition:
                report.add(
                    ValidationIssue(
                        code=f"return.{label}",
                        message=message,
                        severity=Severity.WARNING,
                        review_reason=ReviewReason.CALCULATION_MISMATCH,
                        field_name=label,
                    )
                )

        # Internal consistency of our own computation.
        for label, condition, message in (
            (
                "taxable_income_not_negative",
                computed.taxable_income >= ZERO,
                "Taxable income is negative, which Form 1040 does not permit.",
            ),
            (
                "total_tax_not_negative",
                computed.total_tax >= ZERO,
                "Total tax is negative.",
            ),
            (
                "refund_xor_owed",
                not (computed.refund > ZERO and computed.amount_owed > ZERO),
                "The return shows both a refund and a balance due.",
            ),
        ):
            report.record_check(condition)
            if not condition:
                report.add(
                    ValidationIssue(
                        code=f"return.{label}",
                        message=message,
                        severity=Severity.ERROR,
                        review_reason=ReviewReason.CALCULATION_MISMATCH,
                        field_name=label,
                    )
                )

        if not claimed:
            return report

        # Compare against what the model proposed.
        comparisons = (
            ("total_income", computed.total_income),
            ("adjusted_gross_income", computed.adjusted_gross_income),
            ("taxable_income", computed.taxable_income),
            ("total_tax", computed.total_tax),
            ("total_payments", computed.total_payments),
            ("refund", computed.refund),
            ("amount_owed", computed.amount_owed),
        )
        for key, authoritative in comparisons:
            if key not in claimed:
                continue
            proposed = money(claimed[key])
            variance = abs(to_cents(proposed - authoritative))
            ok = variance <= self._tolerance
            report.record_check(ok)
            if not ok:
                report.add(
                    ValidationIssue(
                        code="return.llm_disagreement",
                        message=(
                            f"The model's '{key}' ({proposed}) disagrees with the "
                            f"deterministic computation ({authoritative}) by "
                            f"{variance}. The computed value has been used; "
                            "review the source documents to explain the gap."
                        ),
                        severity=Severity.ERROR
                        if variance > self._tolerance * 100
                        else Severity.WARNING,
                        review_reason=ReviewReason.CALCULATION_MISMATCH,
                        field_name=key,
                        expected=str(authoritative),
                        actual=str(proposed),
                    )
                )
        return report

    # ------------------------------------------------------ confidence

    def assess_field_confidence(
        self,
        *,
        field_name: str,
        confidence: float,
        document_type: DocumentType | None = None,
        ocr_confidence: float | None = None,
        is_handwritten: bool = False,
    ) -> tuple[bool, ReviewReason | None]:
        """Decide whether a field needs human review.

        Returns ``(requires_review, reason)``.
        """
        if is_handwritten and confidence < 0.95:
            return (True, ReviewReason.HANDWRITING_UNCERTAIN)
        if ocr_confidence is not None and ocr_confidence < (
            self._settings.ocr_min_confidence / 100.0
        ):
            return (True, ReviewReason.LOW_CONFIDENCE)
        if confidence < self._settings.confidence_auto_approve:
            return (True, ReviewReason.LOW_CONFIDENCE)
        return (False, None)

    @staticmethod
    def merge(reports: list[ValidationReport]) -> ValidationReport:
        merged = ValidationReport()
        for report in reports:
            merged.issues.extend(report.issues)
            merged.checks_run += report.checks_run
            merged.checks_passed += report.checks_passed
            merged.recomputed.update(report.recomputed)
        return merged
