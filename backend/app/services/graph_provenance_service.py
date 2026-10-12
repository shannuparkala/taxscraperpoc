"""A workflow's extracted figures, as the calculation graph's typed facts.

The graph engine sits beside the pipeline's calculator rather than inside it,
so for a real workflow its return is computed here, on demand, from what the
pipeline already stored: the engine inputs in the explanation store (amounts,
per-document contributions, the household) and the ``ExtractionResult`` rows
(which document, which page, how confidently, where on the page). Nothing is
re-extracted and nothing leaves the process.

Two vocabularies meet here and they do not match. The pipeline's field names
come from the old engine's dataclasses; the graph's come from the form lines.
Field names are a contract with two ends, and a figure that falls between them
is structurally absent from the return with nothing raising an error - trap 17.
So every pipeline field is either mapped to a graph field or listed in
``NOT_PLACED`` with the reason, a test holds that to be exhaustive, and a figure
that was read but could not be placed is returned as ``unplaced`` for the screen
to show, never dropped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database_models import Document, ExtractionResult, Workflow
from app.services.explanation_service import ExplanationStore
from app.services.tax_engine.graph import (
    Dependent,
    ReturnResult,
    SourceFact,
    TaxpayerFacts,
    compute_return,
)
from app.services.tax_engine.graph.forms import STATES_WITH_FORMS
from app.services.tax_engine.tax_authority import available_years
from app.services.tax_engine.tax_tables import FilingStatusTax

ZERO = Decimal(0)

#: Pipeline field -> graph field, where the two mean the same figure.
FIELD_MAP: dict[str, str] = {
    "wages": "wages",
    "taxable_interest": "taxable_interest",
    "tax_exempt_interest": "tax_exempt_interest",
    "ordinary_dividends": "ordinary_dividends",
    "qualified_dividends": "qualified_dividends",
    "ira_distributions": "ira_distributions",
    "ira_taxable": "ira_taxable",
    "pensions": "pensions_annuities",
    "pensions_taxable": "pensions_taxable",
    "social_security": "social_security_benefits",
    "estimated_payments": "estimated_tax_payments",
    "prior_year_overpayment_applied": "prior_year_overpayment_applied",
    "apply_overpayment_to_next_year": "amount_applied_to_next_year",
    # Schedule 1
    "other_gains": "sch1_l4",
    "other_income": "sch1_l8z",
    "educator_expenses": "sch1_l11",
    "self_employed_retirement": "sch1_l16",
    "self_employed_health_insurance": "sch1_l17",
    "ira_deduction": "sch1_l20",
    "student_loan_interest": "sch1_l21",
    "other_adjustments": "sch1_l24z",
    # Schedule A
    "medical_expenses": "scha_l1",
    "state_local_income_tax": "scha_l5a",
    "real_estate_tax": "scha_l5b",
    "personal_property_tax": "scha_l5c",
    "mortgage_interest": "scha_l8a",
    "investment_interest": "scha_l9",
    "charitable_cash": "scha_l11",
    "charitable_noncash": "scha_l12",
    "casualty_losses": "scha_l15",
    "other_itemized": "scha_l16",
    # Schedule D
    "short_term_from_k1": "schd_l5",
    "short_term_loss_carryover": "schd_l6",
    "long_term_from_k1": "schd_l12",
    "capital_gain_distributions": "schd_l13",
    "long_term_loss_carryover": "schd_l14",
    # Schedule 3
    "other_nonrefundable_credits": "sch3_l6z",
}

#: Schedule D says "enter as a negative"; the pipeline stores the carryover as
#: the size of the loss.
NEGATED: frozenset[str] = frozenset(
    {"short_term_loss_carryover", "long_term_loss_carryover"}
)

#: Split across Form 1040 lines 25a/25b/25c by the document that reported each
#: contribution. The pipeline keeps one total; the form does not.
WITHHOLDING = "federal_withheld"

#: Pipeline fields the graph does not take as an input, and why. A read figure
#: in this list is surfaced as unplaced, never silently dropped.
NOT_PLACED: dict[str, str] = {
    "social_security_taxable": "computed by the graph (Form 1040 line 6b)",
    "self_employment_tax_deduction": "computed from Schedule SE, not entered",
    "hsa_deduction": "computed by Form 8889, whose inputs are its own lines",
    "earned_income_credit": "computed by the EIC worksheet, not entered",
    "additional_child_tax_credit": "computed by Schedule 8812, not entered",
    "american_opportunity_credit": "Form 8863 is not built in the graph yet",
    "business_income": "Schedule C is not built in the graph yet",
    "rental_income": "Schedule E is not built in the graph yet",
    "short_term_gain": "needs the Form 8949 box (basis reported or not)",
    "long_term_gain": "needs the Form 8949 box (basis reported or not)",
    "capital_gain_loss": "a net figure; the graph builds it from Form 8949",
    "state_local_sales_tax": "Schedule A 5a takes income or sales tax, not both",
    "other_payments": "no single Form 1040 payment line matches it",
    "car_loan_interest": "Schedule 1-A is not built in the graph yet",
    "qualified_tips": "Schedule 1-A is not built in the graph yet",
    "qualified_overtime": "Schedule 1-A is not built in the graph yet",
    "loan_balance_begin": "shareholder basis (Form 7203), not a 1040 input",
    "loan_balance_end": "shareholder basis (Form 7203), not a 1040 input",
    "stock_basis_begin": "shareholder basis (Form 7203), not a 1040 input",
    "debt_basis_begin": "shareholder basis (Form 7203), not a 1040 input",
    "distributions": "shareholder basis (Form 7203), not a 1040 input",
    "nondeductible_expenses": "shareholder basis (Form 7203), not a 1040 input",
}

#: Unplaced fields that leave the graph's return complete: the graph computes
#: the figure itself, or it is not a Form 1040 input at all. Every other
#: unplaced figure is money the return is missing, so it cannot be fileable -
#: a return that silently omits business income looks finished, and that is
#: trap 9 and trap 17 at once.
COMPLETE_WITHOUT: frozenset[str] = frozenset(
    {
        "social_security_taxable",
        "loan_balance_begin",
        "loan_balance_end",
        "stock_basis_begin",
        "debt_basis_begin",
        "distributions",
        "nondeductible_expenses",
    }
)


@dataclass(frozen=True, slots=True)
class ExtractionRow:
    """What one ``ExtractionResult`` row says about where a figure came from."""

    extraction_id: str
    field_name: str
    document_id: str
    document_type: str
    page: int | None
    confidence: float
    bbox: Sequence[Any] | None = None
    requires_review: bool = False


@dataclass(frozen=True, slots=True)
class DocumentRow:
    document_id: str
    document_type: str
    page_start: int
    page_end: int
    ocr_mean_confidence: float | None = None
    is_handwritten: bool = False


@dataclass(frozen=True, slots=True)
class UnplacedFigure:
    """A figure the pipeline read that no graph line takes."""

    field: str
    amount: Decimal
    reason: str

    @property
    def blocks_filing(self) -> bool:
        return self.field not in COMPLETE_WITHOUT

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "amount": str(self.amount),
            "reason": self.reason,
            "blocks_filing": self.blocks_filing,
        }


@dataclass(frozen=True, slots=True)
class WorkflowFacts:
    facts: TaxpayerFacts
    unplaced: tuple[UnplacedFigure, ...] = ()
    #: How the adapter read something it had to interpret, in plain words.
    notes: tuple[str, ...] = ()


def _amount(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _withholding_line(document_type: str) -> str:
    """Form 1040 line 25a, 25b or 25c, by the form that reported the tax."""
    kind = document_type.lower()
    if kind == "w2":
        return "federal_withheld_w2"
    if kind.startswith(("1099", "ssa")):
        return "federal_withheld_1099"
    # W-2G is 25c by the instructions; an organizer's recap cannot say which
    # form it is recapping, and 25c is the line that does not claim to know.
    return "federal_withheld_other"


class _Sources:
    """Matches a contribution to the row and the page it was read from."""

    def __init__(
        self,
        extractions: Sequence[ExtractionRow],
        documents: Sequence[DocumentRow],
        confidence_scores: Mapping[str, Any],
    ) -> None:
        self._rows = extractions
        self._documents = documents
        self._confidence = confidence_scores

    def _document(self, document_type: str, page: int | None) -> DocumentRow | None:
        candidates = [d for d in self._documents if d.document_type == document_type]
        if page is not None:
            for candidate in candidates:
                if candidate.page_start <= page <= candidate.page_end:
                    return candidate
        return candidates[0] if candidates else None

    def _row(self, field: str, document_type: str, page: int | None) -> ExtractionRow | None:
        candidates = [
            r
            for r in self._rows
            if r.field_name == field and (not document_type or r.document_type == document_type)
        ]
        if page is not None:
            for row in candidates:
                if row.page == page:
                    return row
        return candidates[0] if candidates else None

    def fact(
        self,
        *,
        graph_field: str,
        pipeline_field: str,
        document_type: str,
        page: int | None,
        amount: Decimal | None,
    ) -> SourceFact:
        row = self._row(pipeline_field, document_type, page)
        if row is not None:
            bbox = None
            if row.bbox and len(row.bbox) == 4:
                bbox = (
                    Decimal(str(row.bbox[0])),
                    Decimal(str(row.bbox[1])),
                    Decimal(str(row.bbox[2])),
                    Decimal(str(row.bbox[3])),
                )
            return SourceFact(
                field=graph_field,
                document_id=row.document_id,
                document_type=row.document_type,
                page=row.page or page or 0,
                confidence=Decimal(str(round(row.confidence, 4))),
                bbox=bbox,
                amount=amount,
                extraction_id=row.extraction_id,
            )
        # No row for this contribution: still name the document of that type
        # covering the page, which is where a reviewer would look.
        document = self._document(document_type, page)
        confidence = _amount(self._confidence.get(pipeline_field))
        return SourceFact(
            field=graph_field,
            document_id=document.document_id if document else "",
            document_type=document_type or (document.document_type if document else ""),
            page=page or (document.page_start if document else 0),
            confidence=confidence if confidence is not None else Decimal(0),
            amount=amount,
        )

    def unattributed(self, graph_field: str, pipeline_field: str) -> tuple[SourceFact, ...]:
        """A figure with no recorded contributions: its extraction rows, if any."""
        rows = [r for r in self._rows if r.field_name == pipeline_field]
        return tuple(
            self.fact(
                graph_field=graph_field,
                pipeline_field=pipeline_field,
                document_type=row.document_type,
                page=row.page,
                amount=None,
            )
            for row in rows[:1]
        )


def build_facts(
    stored: Mapping[str, Any],
    extractions: Sequence[ExtractionRow],
    documents: Sequence[DocumentRow],
) -> WorkflowFacts:
    """The graph's input for one workflow. Pure: no session, no files."""
    normalized: Mapping[str, Any] = stored.get("normalized") or {}
    provenance: Mapping[str, Any] = stored.get("field_provenance") or {}
    profile: Mapping[str, Any] = stored.get("profile") or {}
    sources = _Sources(extractions, documents, stored.get("confidence_scores") or {})

    money: dict[str, Decimal] = {}
    facts_sources: dict[str, list[SourceFact]] = {}
    unplaced: list[UnplacedFigure] = []
    notes: list[str] = []

    def contributions(field: str) -> list[tuple[str, int | None, Decimal | None]]:
        out: list[tuple[str, int | None, Decimal | None]] = []
        for entry in provenance.get(field) or []:
            if not isinstance(entry, dict):
                continue
            page = entry.get("page")
            out.append(
                (
                    str(entry.get("document_type") or ""),
                    _safe_int(page),
                    _amount(entry.get("amount")),
                )
            )
        return out

    def add(graph_field: str, amount: Decimal, found: Sequence[SourceFact]) -> None:
        money[graph_field] = money.get(graph_field, ZERO) + amount
        facts_sources.setdefault(graph_field, []).extend(found)

    # Walk the pipeline's money vocabulary, not the whole mapping: counts and
    # codes sit beside the figures and "2" children parses as a number.
    from app.services.workflow_orchestrator import ENGINE_MONEY_FIELDS

    for name in ENGINE_MONEY_FIELDS:
        amount = _amount(normalized.get(name))
        if amount is None:
            continue

        if name == WITHHOLDING:
            placed = ZERO
            for document_type, page, part in contributions(name):
                if part is None:
                    continue
                line = _withholding_line(document_type)
                add(
                    line,
                    part,
                    [
                        sources.fact(
                            graph_field=line,
                            pipeline_field=name,
                            document_type=document_type,
                            page=page,
                            amount=part,
                        )
                    ],
                )
                placed += part
            if placed != amount:
                add(
                    "federal_withheld_other",
                    amount - placed,
                    sources.unattributed("federal_withheld_other", name)
                    if placed == ZERO
                    else (),
                )
                notes.append(
                    "Federal withholding of "
                    f"{amount - placed:,} could not be tied to the form that "
                    "reported it, so it is entered on line 25c."
                )
            continue

        graph_field = FIELD_MAP.get(name)
        if graph_field is None:
            if amount != ZERO:
                unplaced.append(
                    UnplacedFigure(
                        name,
                        amount,
                        NOT_PLACED.get(name, "no graph line takes this field"),
                    )
                )
            continue

        sign = Decimal(-1) if name in NEGATED else Decimal(1)
        parts = [c for c in contributions(name) if c[2] is not None]
        if parts:
            found = [
                sources.fact(
                    graph_field=graph_field,
                    pipeline_field=name,
                    document_type=document_type,
                    page=page,
                    amount=None if part is None else sign * abs(part),
                )
                for document_type, page, part in parts
            ]
        else:
            found = list(sources.unattributed(graph_field, name))
        add(graph_field, sign * abs(amount) if name in NEGATED else amount, found)

    try:
        status = FilingStatusTax(profile.get("filing_status", "single"))
    except ValueError:
        status = FilingStatusTax.SINGLE
        notes.append("The recorded filing status was not recognised; single is shown.")

    taxpayer_age = _safe_int(profile.get("taxpayer_age"))
    spouse_age = _safe_int(profile.get("spouse_age"))
    seniors = _safe_int(profile.get("age_65_or_older")) or 0
    if taxpayer_age is None and spouse_age is None and seniors:
        # A run recorded before ages were stored kept only the count. 65 is the
        # floor the count already asserts, not a guess at anyone's age.
        taxpayer_age = 65
        spouse_age = 65 if seniors > 1 else None
        notes.append(
            "Ages were not recorded for this run; the count of people 65 or "
            "older is used instead."
        )

    dependents = tuple(
        Dependent(
            name_token=f"DEPENDENT_{index:03d}",
            relationship="child",
            qualifies_for_child_tax_credit=True,
        )
        for index in range(1, (_safe_int(profile.get("qualifying_children")) or 0) + 1)
    ) + tuple(
        Dependent(
            name_token=f"OTHER_DEPENDENT_{index:03d}",
            relationship="other",
            qualifies_for_other_dependent_credit=True,
        )
        for index in range(1, (_safe_int(profile.get("other_dependents")) or 0) + 1)
    )

    state = str(profile.get("state_code") or "").upper() or None
    if state is not None and state not in STATES_WITH_FORMS:
        state = None

    facts = TaxpayerFacts(
        tax_year=int(profile.get("tax_year") or 0),
        filing_status=status,
        taxpayer_age=taxpayer_age,
        spouse_age=spouse_age,
        dependents=dependents,
        resident_state=state,
        money=money,
        provenance={name: tuple(found) for name, found in facts_sources.items()},
    )
    return WorkflowFacts(facts=facts, unplaced=tuple(unplaced), notes=tuple(notes))


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class WorkflowReturn:
    result: ReturnResult
    unplaced: tuple[UnplacedFigure, ...]
    notes: tuple[str, ...]
    #: What the run read, per document - for the report's source index.
    documents: tuple[DocumentRow, ...] = ()
    extractions: tuple[ExtractionRow, ...] = ()

    @property
    def fileable(self) -> bool:
        """The graph's own verdict, and no read figure left off the return."""
        return self.result.fileable and not any(u.blocks_filing for u in self.unplaced)


class GraphProvenanceService:
    """Computes the graph return for a stored workflow and explains its lines."""

    def __init__(self, session: Session, *, output_zone_dir: Path) -> None:
        self._session = session
        self._store = ExplanationStore(output_zone_dir / "explanations")

    def load(self, workflow: Workflow) -> WorkflowReturn | None:
        """None when the run never recorded engine inputs for a year we have."""
        stored = self._store.load(workflow.id)
        if not stored:
            return None
        year = _safe_int((stored.get("profile") or {}).get("tax_year"))
        if year not in available_years():
            return None

        documents = list(
            self._session.execute(
                select(Document).where(
                    Document.uploaded_file_id == workflow.uploaded_file_id
                )
            ).scalars()
        )
        by_id = {d.id: d for d in documents}
        rows = self._session.execute(
            select(ExtractionResult).where(ExtractionResult.workflow_id == workflow.id)
        ).scalars()
        extractions = [
            ExtractionRow(
                extraction_id=row.id,
                field_name=row.field_name,
                document_id=row.document_id,
                document_type=(
                    by_id[row.document_id].document_type if row.document_id in by_id else ""
                ),
                page=row.source_page,
                confidence=float(row.confidence or 0.0),
                bbox=row.source_bbox,
                requires_review=bool(row.requires_review),
            )
            for row in rows
        ]
        document_rows = [
            DocumentRow(
                d.id,
                d.document_type,
                d.page_start,
                d.page_end,
                ocr_mean_confidence=d.ocr_mean_confidence,
                is_handwritten=bool(d.is_handwritten),
            )
            for d in sorted(documents, key=lambda d: d.page_start)
        ]
        built = build_facts(stored, extractions, document_rows)
        return WorkflowReturn(
            result=compute_return(built.facts),
            unplaced=built.unplaced,
            notes=built.notes,
            documents=tuple(document_rows),
            extractions=tuple(extractions),
        )
