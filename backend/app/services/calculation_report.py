"""The calculation report: the whole return, and how every figure on it was reached.

Built from the calculation graph's evaluated ``ReturnResult`` - the same records
``explain(node_id)`` walks - so the report cannot say something different from
what ran. Four parts, in the order a reviewer checks a return:

1. **Forms**, in official order, line by line: value, formula, inputs, sources.
2. **Worksheets** the return actually used, in full.
3. **Source documents**: what was read off each one, and which lines used it.
4. **Validation**: the cross-checks run and what they found, low-confidence
   reads, and every line the engine would not compute.

Pure: no session, no network, no clock. The route gathers the inputs, this
arranges them, and ``calculation_report_pdf`` renders the result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.graph_provenance_service import (
    NOT_PLACED,
    ExtractionRow,
    WorkflowReturn,
)
from app.services.tax_engine.graph import LeafKind, NodeResult, SourceFact
from app.services.tax_engine.graph.evaluator import CONST_PREFIX, FACT_PREFIX

ZERO = Decimal(0)

#: The figures a reader looks for first, and the pipeline summary key each is
#: cross-checked against. None where the pipeline records no counterpart.
HEADLINE: tuple[tuple[str, str, str | None], ...] = (
    ("Total income", "f1040.l9", "total_income"),
    ("Adjusted gross income", "f1040.l11a", "adjusted_gross_income"),
    ("Taxable income", "f1040.l15", "taxable_income"),
    ("Total tax", "f1040.l24", "total_tax"),
    ("Total payments", "f1040.l33", "payments"),
    ("Refunded to you", "f1040.l35a", "refund"),
    ("Amount you owe", "f1040.l37", "amount_owed"),
)


def is_worksheet(form: str) -> bool:
    return "worksheet" in form.lower()


def _money(amount: Decimal | None) -> str | None:
    return None if amount is None else str(amount)


# ---------------------------------------------------------------- lines


@dataclass(frozen=True, slots=True)
class InputRef:
    """One figure a line read, named the way a reader can find it."""

    node_id: str
    label: str
    amount: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "label": self.label, "amount": _money(self.amount)}


@dataclass(frozen=True, slots=True)
class Explanation:
    """The plain-English sentence beside a line, and who wrote it."""

    text: str
    #: "model" when a model wrote it and it passed the validator; "engine"
    #: when it is the deterministic wording.
    by: str = "engine"
    #: Numbers or words a rejected model explanation tried to introduce.
    rejected: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "by": self.by, "rejected": list(self.rejected)}


@dataclass(frozen=True, slots=True)
class ReportLine:
    node_id: str
    form: str
    line: str
    label: str
    amount: Decimal | None
    formula: str
    inputs: tuple[InputRef, ...]
    sources: tuple[SourceFact, ...]
    reference: str
    authority_url: str
    basis: str
    flags: tuple[str, ...]
    explanation: Explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "form": self.form,
            "line": self.line,
            "label": self.label,
            "amount": _money(self.amount),
            "formula": self.formula,
            "inputs": [i.to_dict() for i in self.inputs],
            "sources": [s.to_dict() for s in self.sources],
            "reference": self.reference,
            "authority_url": self.authority_url,
            "basis": self.basis,
            "flags": list(self.flags),
            "explanation": self.explanation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FormSection:
    form: str
    #: False when every line is -0- and nothing on the return feeds the form.
    #: Such a form is named, not printed: thirty blank lines bury the eight
    #: that carry the return.
    used: bool
    lines: tuple[ReportLine, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "used": self.used,
            "lines": [line.to_dict() for line in self.lines],
        }


# ------------------------------------------------------------ documents


@dataclass(frozen=True, slots=True)
class FieldUse:
    """One figure read off a document, and where the return used it."""

    field: str
    page: int | None
    amount: Decimal | None
    confidence: Decimal
    located: bool
    requires_review: bool
    used_on: tuple[str, ...]
    #: Why a read figure is on no line, when it is not.
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "page": self.page,
            "amount": _money(self.amount),
            "confidence": str(self.confidence),
            "located": self.located,
            "requires_review": self.requires_review,
            "used_on": list(self.used_on),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class DocumentEntry:
    document_id: str
    document_type: str
    page_start: int
    page_end: int
    ocr_confidence: float | None
    handwritten: bool
    fields: tuple[FieldUse, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_type": self.document_type,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "ocr_confidence": self.ocr_confidence,
            "handwritten": self.handwritten,
            "fields": [f.to_dict() for f in self.fields],
        }


# ----------------------------------------------------------- validation


@dataclass(frozen=True, slots=True)
class Check:
    """One cross-check. ``passed`` is None when it could not be run."""

    name: str
    passed: bool | None
    detail: str
    findings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "findings": list(self.findings),
        }


@dataclass(frozen=True, slots=True)
class LowConfidenceRead:
    field: str
    document_type: str
    page: int | None
    confidence: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "document_type": self.document_type,
            "page": self.page,
            "confidence": str(self.confidence),
        }


@dataclass(frozen=True, slots=True)
class Validation:
    checks: tuple[Check, ...]
    low_confidence: tuple[LowConfidenceRead, ...]
    #: (node id, label, reason) for every line the engine would not compute.
    unsupported: tuple[tuple[str, str, str], ...]
    unplaced: tuple[dict[str, Any], ...]
    unverified_authorities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "low_confidence": [r.to_dict() for r in self.low_confidence],
            "unsupported": [
                {"node_id": n, "label": label, "reason": reason}
                for n, label, reason in self.unsupported
            ],
            "unplaced": list(self.unplaced),
            "unverified_authorities": list(self.unverified_authorities),
        }


# --------------------------------------------------------------- report


@dataclass(frozen=True, slots=True)
class CalculationReport:
    workflow_id: str
    tax_year: int
    filing_status: str
    fileable: bool
    generated_at: str
    headline: tuple[tuple[str, str, Decimal | None], ...]
    forms: tuple[FormSection, ...]
    worksheets: tuple[FormSection, ...]
    documents: tuple[DocumentEntry, ...]
    validation: Validation
    notes: tuple[str, ...] = ()
    #: Which model wrote explanations, or why none did.
    explanations_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "tax_year": self.tax_year,
            "filing_status": self.filing_status,
            "fileable": self.fileable,
            "generated_at": self.generated_at,
            "headline": [
                {"label": label, "node_id": node_id, "amount": _money(amount)}
                for label, node_id, amount in self.headline
            ],
            "forms": [f.to_dict() for f in self.forms],
            "worksheets": [w.to_dict() for w in self.worksheets],
            "documents": [d.to_dict() for d in self.documents],
            "validation": self.validation.to_dict(),
            "notes": list(self.notes),
            "explanations_note": self.explanations_note,
        }


# ------------------------------------------------------------ building


def engine_explanation(result: NodeResult) -> str:
    """The deterministic wording: what the engine did, in its own numbers."""
    if result.amount is None:
        return f"Not computed. {result.formula.removeprefix('not computed: ')}"
    return f"Worked out as {result.formula}."


def explained_lines(loaded: WorkflowReturn) -> tuple[NodeResult, ...]:
    """The lines worth a plain-English sentence: non-zero, on a used form.

    Worksheets are excluded - they are the arithmetic behind a line, and the
    line they feed is the one the reader asks about.
    """
    used = _used_forms(loaded)
    return tuple(
        line
        for line in loaded.result.lines
        if line.form in used
        and not is_worksheet(line.form)
        and line.amount is not None
        and line.amount != ZERO
    )


def _used_forms(loaded: WorkflowReturn) -> set[str]:
    result = loaded.result
    used = {"Form 1040"}
    for line in result.lines:
        if line.amount is None or (line.amount != ZERO):
            used.add(line.form)
    # A worksheet is used when a line outside it read one of its lines.
    for line in result.lines:
        for input_id, _ in line.inputs:
            source = result.get(input_id)
            if source is not None and source.form != line.form and is_worksheet(source.form):
                used.add(source.form)
    return used


def _input_label(result: NodeResult) -> str:
    if result.node_id.startswith(FACT_PREFIX):
        return f"{result.label.replace('_', ' ')} (read from documents)"
    if result.node_id.startswith(CONST_PREFIX):
        return f"{result.label} (statutory)"
    return f"{result.form} line {result.line}"


def _report_line(result: NodeResult, lookup: Mapping[str, NodeResult], text: Explanation) -> ReportLine:
    seen: dict[str, InputRef] = {}
    for input_id, amount in result.inputs:
        found = lookup.get(input_id)
        if input_id in seen or found is None:
            continue
        seen[input_id] = InputRef(input_id, _input_label(found), amount)
    return ReportLine(
        node_id=result.node_id,
        form=result.form,
        line=result.line,
        label=result.label,
        amount=result.amount,
        formula=result.formula,
        inputs=tuple(seen.values()),
        sources=result.sources,
        reference=result.reference,
        authority_url=result.authority.url if result.authority else "",
        basis=result.basis.value,
        flags=result.flags,
        explanation=text,
    )


def _consumers(results: Mapping[str, NodeResult], order: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Fact leaf id -> the lines that read it."""
    out: dict[str, list[str]] = {}
    for node_id in order:
        for input_id, _ in results[node_id].inputs:
            if input_id.startswith(FACT_PREFIX):
                out.setdefault(input_id, [])
                if node_id not in out[input_id]:
                    out[input_id].append(node_id)
    return {key: tuple(value) for key, value in out.items()}


def _document_index(loaded: WorkflowReturn) -> tuple[DocumentEntry, ...]:
    result = loaded.result
    consumers = _consumers(result.results, result.order)
    unplaced = {u.field: u.reason for u in loaded.unplaced}

    # Every source fact the graph used, keyed the two ways a row can match.
    used_by_extraction: dict[str, tuple[SourceFact, tuple[str, ...]]] = {}
    unmatched: list[tuple[SourceFact, tuple[str, ...]]] = []
    for node_id, node in result.results.items():
        if not node_id.startswith(FACT_PREFIX):
            continue
        for source in node.sources:
            entry = (source, consumers.get(node_id, ()))
            if source.extraction_id:
                used_by_extraction.setdefault(source.extraction_id, entry)
            else:
                unmatched.append(entry)

    fields_by_document: dict[str, list[FieldUse]] = {}

    def note_for(row: ExtractionRow) -> str:
        if row.field_name in unplaced:
            return f"read, on no line: {unplaced[row.field_name]}"
        if row.field_name in NOT_PLACED:
            return NOT_PLACED[row.field_name]
        return "read, not a figure this return uses"

    for row in loaded.extractions:
        matched = used_by_extraction.get(row.extraction_id)
        if matched is not None:
            source, used_on = matched
            use = FieldUse(
                field=row.field_name,
                page=row.page,
                amount=source.amount,
                confidence=source.confidence,
                located=source.bbox is not None,
                requires_review=row.requires_review,
                used_on=used_on,
            )
        else:
            # SECURITY: no value for an unused row. It may be an identity field
            # (a name, a date of birth), and a report is a deliverable.
            use = FieldUse(
                field=row.field_name,
                page=row.page,
                amount=None,
                confidence=_decimal(row.confidence),
                located=bool(row.bbox),
                requires_review=row.requires_review,
                used_on=(),
                note=note_for(row),
            )
        fields_by_document.setdefault(row.document_id, []).append(use)

    for source, used_on in unmatched:
        fields_by_document.setdefault(source.document_id, []).append(
            FieldUse(
                field=source.field,
                page=source.page,
                amount=source.amount,
                confidence=source.confidence,
                located=source.bbox is not None,
                requires_review=False,
                used_on=used_on,
                note="no extraction row recorded; attributed by document type",
            )
        )

    entries = [
        DocumentEntry(
            document_id=doc.document_id,
            document_type=doc.document_type,
            page_start=doc.page_start,
            page_end=doc.page_end,
            ocr_confidence=doc.ocr_mean_confidence,
            handwritten=doc.is_handwritten,
            fields=tuple(
                sorted(
                    fields_by_document.pop(doc.document_id, []),
                    key=lambda f: (f.page or 0, f.field),
                )
            ),
        )
        for doc in loaded.documents
    ]
    # Facts attributed to no known document still belong in the index.
    for document_id, orphaned in fields_by_document.items():
        entries.append(
            DocumentEntry(
                document_id=document_id,
                document_type="unknown document",
                page_start=0,
                page_end=0,
                ocr_confidence=None,
                handwritten=False,
                fields=tuple(orphaned),
            )
        )
    return tuple(entries)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(round(float(value), 4)))
    except (TypeError, ValueError, InvalidOperation):
        return ZERO


def _validation(
    loaded: WorkflowReturn,
    *,
    pipeline_summary: Mapping[str, Any] | None,
    tolerance: Decimal,
    confidence_floor: float,
    explanations: Mapping[str, Explanation],
) -> Validation:
    result = loaded.result
    checks: list[Check] = []

    # 1. The two engines, on the figures a reader checks first.
    if pipeline_summary:
        disagreements: list[str] = []
        compared = 0
        for label, node_id, key in HEADLINE:
            if key is None or key not in pipeline_summary:
                continue
            graph_amount = result.amount(node_id)
            try:
                pipeline_amount = Decimal(str(pipeline_summary[key]))
            except InvalidOperation:
                continue
            compared += 1
            if graph_amount is None:
                disagreements.append(f"{label} ({node_id}): not computed by the graph")
            elif abs(graph_amount - pipeline_amount) > tolerance:
                disagreements.append(
                    f"{label} ({node_id}): graph {graph_amount:,} vs pipeline "
                    f"{pipeline_amount:,}"
                )
        checks.append(
            Check(
                "The graph engine agrees with the pipeline's calculator",
                not disagreements,
                f"{compared} headline figures compared, tolerance {tolerance:,}",
                tuple(disagreements),
            )
        )
    else:
        checks.append(
            Check(
                "The graph engine agrees with the pipeline's calculator",
                None,
                "no pipeline figures were recorded for this run",
            )
        )

    # 2. Every figure bottoms out in a document, an authority or a stated nil.
    untraced: dict[str, str] = {}
    for node_id in result.order:
        for leaf in result.explain(node_id).untraced():
            if leaf.leaf is LeafKind.UNSUPPORTED:
                continue  # reported under unsupported lines
            untraced.setdefault(leaf.node_id, leaf.leaf.value if leaf.leaf else "")
    checks.append(
        Check(
            "Every figure traces to a document, an authority or a stated nil",
            not untraced,
            f"{len(result.order)} lines walked with explain()",
            tuple(f"{node_id}: {kind}" for node_id, kind in sorted(untraced.items())),
        )
    )

    # 3. Each figure's per-document contributions add up to it.
    unbalanced = tuple(
        f"{node.label}: {flag}"
        for node_id, node in sorted(result.results.items())
        if node_id.startswith(FACT_PREFIX)
        for flag in node.flags
        if flag.startswith("sources account for")
    )
    checks.append(
        Check(
            "Each figure's documents add up to it",
            not unbalanced,
            "per-document contributions summed against each extracted figure",
            unbalanced,
        )
    )

    # 4. Nothing read was left off the return.
    missing = tuple(
        f"{u.field} ({u.amount:,}): {u.reason}" for u in loaded.unplaced if u.blocks_filing
    )
    checks.append(
        Check(
            "Every figure read is on a line",
            not missing,
            "extracted figures against the lines that take them",
            missing,
        )
    )

    # 5. Model explanations stayed inside the provenance.
    rejected = tuple(
        f"{node_id}: introduced {', '.join(e.rejected)}"
        for node_id, e in sorted(explanations.items())
        if e.rejected
    )
    by_model = sum(1 for e in explanations.values() if e.by == "model")
    checks.append(
        Check(
            "Explanations use only numbers from the calculation",
            None if not by_model and not rejected else not rejected,
            f"{by_model} model explanations accepted, {len(rejected)} rejected "
            "and replaced with the engine's wording",
            rejected,
        )
    )

    low = tuple(
        LowConfidenceRead(
            field=row.field_name,
            document_type=row.document_type,
            page=row.page,
            confidence=_decimal(row.confidence),
        )
        for row in loaded.extractions
        if row.requires_review or row.confidence < confidence_floor
    )
    unsupported = tuple(
        (line.node_id, line.label, line.formula.removeprefix("not computed: "))
        for line in result.unsupported
    )
    return Validation(
        checks=tuple(checks),
        low_confidence=low,
        unsupported=unsupported,
        unplaced=tuple(u.to_dict() for u in loaded.unplaced),
        unverified_authorities=result.unverified_authorities,
    )


def build_report(
    loaded: WorkflowReturn,
    *,
    workflow_id: str,
    generated_at: str,
    explanations: Mapping[str, Explanation] | None = None,
    pipeline_summary: Mapping[str, Any] | None = None,
    tolerance: Decimal = Decimal(1),
    confidence_floor: float = 0.90,
    explanations_note: str = "",
) -> CalculationReport:
    result = loaded.result
    explanations = dict(explanations or {})
    used = _used_forms(loaded)

    def text_for(line: NodeResult) -> Explanation:
        return explanations.get(line.node_id) or Explanation(engine_explanation(line))

    sections: list[FormSection] = []
    worksheets: list[FormSection] = []
    for form in result.forms:
        lines = result.form(form)
        section = FormSection(
            form=form,
            used=form in used,
            lines=tuple(_report_line(line, result.results, text_for(line)) for line in lines)
            if form in used
            else (),
        )
        if is_worksheet(form):
            if section.used:
                worksheets.append(section)
        else:
            sections.append(section)

    return CalculationReport(
        workflow_id=workflow_id,
        tax_year=result.facts.tax_year,
        filing_status=result.facts.filing_status.value,
        fileable=loaded.fileable,
        generated_at=generated_at,
        headline=tuple((label, node_id, result.amount(node_id)) for label, node_id, _ in HEADLINE),
        forms=tuple(sections),
        worksheets=tuple(worksheets),
        documents=_document_index(loaded),
        validation=_validation(
            loaded,
            pipeline_summary=pipeline_summary,
            tolerance=tolerance,
            confidence_floor=confidence_floor,
            explanations=explanations,
        ),
        notes=loaded.notes,
        explanations_note=explanations_note,
    )

