"""Running a case: the engine alone, and the whole pipeline.

``calculate`` feeds a case's verified inputs straight into the calculation
graph - no documents, no model, no network - so it runs anywhere, CI included.

``run_pipeline`` puts the case's workpaper through the real pipeline: OCR,
classification, masking, the model, validation. It needs the corpus (for a real
case), Tesseract and, for extraction, a Gemini key; its spend lands on the
``llm_calls`` ledger and is reported with the case. It runs against the eval
database under ``data/evals/``, never the working one, so a benchmark run does
not add a thousand items to anybody's review queue (trap 31).
"""

from __future__ import annotations

import re
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from evals.harness import (
    Case,
    CaseResult,
    Observations,
    score_flags,
    score_inputs,
    score_lines,
)

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "Files"

#: The titles the pipeline gives a refusal to compute a return (trap 31).
REFUSAL = re.compile(r"not computed|could not be computed", re.IGNORECASE)


def _tolerance(case: Case) -> Decimal:
    if case.tolerance is not None:
        return case.tolerance
    from app.core.config import get_settings

    return Decimal(str(get_settings().calc_tolerance_dollars))


def facts_for(case: Case) -> Any:
    """The case's verified figures and household, as the engine's input."""
    from app.services.tax_engine.graph import Dependent, TaxpayerFacts
    from app.services.tax_engine.tax_tables import FilingStatusTax

    household = case.household
    dependents = tuple(
        Dependent(
            name_token=f"DEPENDENT_{index:03d}",
            relationship=str(d.get("relationship", "")),
            age=d.get("age"),
            qualifies_for_child_tax_credit=bool(d.get("ctc")),
            qualifies_for_other_dependent_credit=bool(d.get("odc")),
        )
        for index, d in enumerate(household.get("dependents") or [], start=1)
    )
    return TaxpayerFacts(
        tax_year=case.tax_year,
        filing_status=FilingStatusTax(household["filing_status"]),
        taxpayer_age=household.get("taxpayer_age"),
        spouse_age=household.get("spouse_age"),
        taxpayer_blind=bool(household.get("taxpayer_blind")),
        spouse_blind=bool(household.get("spouse_blind")),
        dependents=dependents,
        resident_state=household.get("resident_state"),
        money={i.field: i.amount for i in case.inputs},
    )


def _computed(result: Any, nodes: list[str]) -> tuple[dict[str, Decimal | None], set[str]]:
    computed: dict[str, Decimal | None] = {}
    for node in nodes:
        line = result.get(node)
        if line is not None:
            computed[node] = line.amount
    flagged = {line.node_id for line in result.lines if line.flags or line.unsupported}
    return computed, flagged


def calculate(case: Case, result: CaseResult) -> None:
    """The calculation layer: right inputs in, is the right return out?"""
    from app.services.tax_engine.graph import compute_return

    if not case.lines:
        result.calculation.skipped_reason = "no expected lines"
        return
    if not case.calculable:
        unverified = sum(1 for i in case.inputs if not i.verified)
        result.calculation.skipped_reason = (
            "no household or inputs recorded"
            if not case.household or not case.inputs
            else f"{unverified} input(s) not verified"
        )
        return
    returned = compute_return(facts_for(case))
    computed, flagged = _computed(returned, [line.node for line in case.lines])
    result.calculation = score_lines(
        case.lines, computed, flagged=flagged, tolerance=_tolerance(case)
    )


# ---------------------------------------------------------------- pipeline


def _workpaper(case: Case, scratch: Path) -> Path:
    source = str(case.source.get("workpaper", ""))
    if source.startswith("synthetic:"):
        from evals.synthetic.build import build

        return build(source.removeprefix("synthetic:"), scratch)
    path = (ROOT / source) if not Path(source).is_absolute() else Path(source)
    if not path.exists():
        raise FileNotFoundError(f"workpaper for {case.id} is not in the corpus")
    return path


def run_pipeline(case: Case, result: CaseResult) -> None:
    """The extraction and end-to-end layers, plus flags, cost and time."""
    from sqlalchemy import select

    from app.core.audit import AuditLogger
    from app.core.config import get_settings
    from app.core.db import session_scope
    from app.models.database_models import Document, ReviewItem, UploadedFile, Workflow
    from app.services.graph_provenance_service import GraphProvenanceService
    from app.services.ingestion_service import IngestionService
    from app.services.llm_cost_service import workflow_cost
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    with tempfile.TemporaryDirectory() as scratch:
        path = _workpaper(case, Path(scratch))
        started = time.monotonic()
        content_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/plain"
        with session_scope() as session, path.open("rb") as stream:
            stored = IngestionService(session, audit=AuditLogger(session)).store(
                filename=path.name, stream=stream, content_type=content_type
            )
            session.flush()
            file_id = stored.id
        with session_scope() as session:
            uploaded = session.get(UploadedFile, file_id)
            run = WorkflowOrchestrator(session, audit=AuditLogger(session)).run(
                uploaded, actor_id=None
            )
            workflow_id = run.workflow_id
        result.seconds = round(time.monotonic() - started, 1)
        result.workflow_id = workflow_id

    tolerance = _tolerance(case)
    with session_scope() as session:
        workflow = session.get(Workflow, workflow_id)
        loaded = GraphProvenanceService(
            session, output_zone_dir=get_settings().output_zone_dir
        ).load(workflow)

        reviews = session.execute(
            select(ReviewItem).where(ReviewItem.workflow_id == workflow_id)
        ).scalars()
        documents = session.execute(
            select(Document).where(Document.uploaded_file_id == workflow.uploaded_file_id)
        ).scalars()
        warnings = [
            str(w)
            for d in documents
            for page in (d.layout or {}).get("pages") or []
            for w in page.get("warnings") or []
        ]
        seen = Observations(
            review_items=tuple(f"{r.title} - {r.description or ''}" for r in reviews),
            unsupported=tuple(line.node_id for line in loaded.result.unsupported)
            if loaded
            else (),
            unplaced=tuple(u.field for u in loaded.unplaced if u.blocks_filing)
            if loaded
            else (),
            layout_warnings=tuple(warnings),
            fileable=bool(loaded and loaded.fileable),
        )
        cost = workflow_cost(session, workflow)
        result.cost_usd = cost.total.cost_usd
        result.unpriced_calls = cost.total.unpriced_calls
        result.llm_calls = cost.total.calls

    result.flags = score_flags(case.expected_flags, seen)
    if loaded is None:
        # Still scored: a run that computed nothing missed every input and
        # every line - skipping it would make a refusal look like a pass. But a
        # refusal that says so ("... not computed", trap 31) is a flagged
        # miss, not a silent one.
        refused = any(REFUSAL.search(item) for item in seen.review_items)
        result.extraction = score_inputs(case.inputs, {}, tolerance=tolerance)
        result.end_to_end = score_lines(
            case.lines, {},
            flagged={line.node for line in case.lines} if refused else set(),
            tolerance=tolerance,
        )
        return
    result.extraction = score_inputs(
        case.inputs, dict(loaded.result.facts.money), tolerance=tolerance
    )
    computed, flagged = _computed(loaded.result, [line.node for line in case.lines])
    result.end_to_end = score_lines(case.lines, computed, flagged=flagged, tolerance=tolerance)
