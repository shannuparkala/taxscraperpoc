"""Workflow execution, inspection, and output download."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from sqlalchemy import select

from app.api.deps import (
    AuditDep,
    DbSession,
    GeminiDep,
    rate_limit,
    role_required,
)
from app.core.audit import AuditAction, AuditLogger
from app.core.config import Role, get_settings
from app.core.db import session_scope
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import Principal
from app.models.database_models import (
    AuditEvent,
    Document,
    ExtractionResult,
    OutputPackage,
    UploadedFile,
    Workflow,
    WorkflowStageRun,
)
from app.models.enums import FileStatus, WorkflowStatus
from app.schemas.api import (
    AuditEventOut,
    AuditListResponse,
    DocumentOut,
    ExplainNodeOut,
    ExplanationOut,
    ExtractionOut,
    FigureBoxOut,
    GraphReturnOut,
    MaskedPreviewOut,
    OutputPackageOut,
    ProcessRequest,
    SourcePageOut,
    StageRunOut,
    WorkflowCostOut,
    WorkflowDetailOut,
    WorkflowOut,
)
from app.services.calculation_report import (
    CalculationReport,
    build_report,
    explained_lines,
)
from app.services.calculation_report_pdf import render_pdf
from app.services.explanation_service import build_for_workflow
from app.services.gemini_service import GeminiService
from app.services.graph_provenance_service import GraphProvenanceService
from app.services.llm_cost_service import workflow_cost
from app.services.llm_meter import metered
from app.services.report_explainer import ReportExplainer
from app.services.report_html_service import render_return_report, report_filename
from app.services.workflow_orchestrator import WorkflowOrchestrator

logger = get_logger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post(
    "/{file_id}/process",
    response_model=WorkflowDetailOut,
    status_code=status.HTTP_201_CREATED,
    # Counted against the "upload" budget, not the upload endpoint's: storing a
    # file is cheap, and this is the call that spends OCR CPU and model tokens.
    dependencies=[rate_limit("upload")],
)
def process_file(
    file_id: str,
    payload: ProcessRequest,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.PREPARER),
) -> WorkflowDetailOut:
    """Run the full nine-stage pipeline over an uploaded file.

    Synchronous by design: the review-driven workflow needs the result before it
    can proceed, and a preparer watching the timeline expects it to finish. For
    bulk processing, move this onto a task queue and return the workflow id
    immediately.
    """
    uploaded = session.get(UploadedFile, file_id)
    if uploaded is None:
        raise NotFoundError("No such file.")
    if uploaded.status == FileStatus.PURGED.value:
        raise ConflictError("This file has been purged under the retention policy.")

    orchestrator = WorkflowOrchestrator(session, audit=audit)
    result = orchestrator.run(
        uploaded, actor_id=principal.user_id, tax_year=payload.tax_year
    )
    uploaded.status = (
        FileStatus.PROCESSED.value
        if result.status is not WorkflowStatus.FAILED
        else FileStatus.FAILED.value
    )
    session.flush()

    workflow = session.get(Workflow, result.workflow_id)
    if workflow is None:  # pragma: no cover - defensive
        raise NotFoundError("The workflow could not be loaded after processing.")
    return _detail(session, workflow)


@router.post(
    "/{file_id}/process/stream",
    dependencies=[rate_limit("upload")],
)
def process_file_streaming(
    file_id: str,
    payload: ProcessRequest,
    principal: Principal = role_required(Role.PREPARER),
) -> StreamingResponse:
    """Run the pipeline, streaming each stage as it happens.

    Same work as ``/process``, but the caller sees it happening. Reading a
    scanned workpaper takes minutes, and a spinner with nothing behind it is
    indistinguishable from a hang.

    The pipeline runs on a worker thread with its **own** database session.
    Sharing this request's session across threads is not safe, and the audit log
    is a hash chain that a second concurrent writer would corrupt — one session
    owned by one thread keeps both guarantees.
    """
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def worker() -> None:
        try:
            with session_scope() as session:
                uploaded = session.get(UploadedFile, file_id)
                if uploaded is None:
                    events.put({"type": "error", "message": "No such file."})
                    return
                if uploaded.status == FileStatus.PURGED.value:
                    events.put(
                        {
                            "type": "error",
                            "message": "This file has been purged under the "
                            "retention policy.",
                        }
                    )
                    return

                audit = AuditLogger(session)
                orchestrator = WorkflowOrchestrator(
                    session,
                    audit=audit,
                    progress=lambda event: events.put({"type": "stage", **event}),
                )
                result = orchestrator.run(
                    uploaded, actor_id=principal.user_id, tax_year=payload.tax_year
                )
                uploaded.status = (
                    FileStatus.PROCESSED.value
                    if result.status is not WorkflowStatus.FAILED
                    else FileStatus.FAILED.value
                )
                events.put(
                    {
                        "type": "done",
                        "workflow_id": result.workflow_id,
                        "status": result.status.value,
                        "documents": result.documents_detected,
                        "facts": result.facts_extracted,
                        "review_items": result.review_items,
                        "packages": result.packages_generated,
                    }
                )
        except AppError as exc:
            events.put({"type": "error", "message": exc.message})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Streaming pipeline failed")
            # SECURITY: the message may carry document content; send the type.
            events.put(
                {
                    "type": "error",
                    "message": f"Processing failed ({type(exc).__name__}).",
                }
            )
        finally:
            events.put(None)

    def stream() -> Iterator[str]:
        thread = threading.Thread(target=worker, daemon=True, name="pipeline")
        thread.start()
        while True:
            event = events.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("", response_model=list[WorkflowOut])
def list_workflows(
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
    workflow_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WorkflowOut]:
    stmt = select(Workflow).order_by(Workflow.created_at.desc()).limit(limit)
    if workflow_status:
        stmt = stmt.where(Workflow.status == workflow_status)
    workflows = list(session.execute(stmt).scalars())

    # Resolve the source filenames in one query rather than one per row.
    names = dict(
        session.execute(
            select(UploadedFile.id, UploadedFile.original_filename).where(
                UploadedFile.id.in_({w.uploaded_file_id for w in workflows})
            )
        ).all()
    )

    result: list[WorkflowOut] = []
    for workflow in workflows:
        out = WorkflowOut.model_validate(workflow)
        out.source_filename = names.get(workflow.uploaded_file_id)
        result.append(out)
    return result


@router.get("/{workflow_id}", response_model=WorkflowDetailOut)
def get_workflow(
    workflow_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> WorkflowDetailOut:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")
    return _detail(session, workflow)


@router.get("/{workflow_id}/explanation", response_model=ExplanationOut)
def get_explanation(
    workflow_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> ExplanationOut:
    """How every Form 1040 line on this return was arrived at.

    Rebuilt from the engine inputs recorded during validation, so the account a
    reviewer reads is always produced by the tax logic currently in force
    rather than a snapshot taken when the return first ran.
    """
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")

    explanation = build_for_workflow(
        workflow_id, output_zone_dir=get_settings().output_zone_dir
    )
    if explanation is None:
        raise NotFoundError(
            "No computed return was recorded for this run, so there is nothing "
            "to explain yet."
        )
    return ExplanationOut.model_validate(explanation.to_dict())


@router.get("/{workflow_id}/report.html", response_class=HTMLResponse)
def download_report(
    workflow_id: str,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.READONLY),
) -> HTMLResponse:
    """The whole result screen as one standalone HTML file.

    Archived beside the workpaper, it answers "where did this figure come
    from" without re-running the pipeline. Same data and same role gate as
    ``/explanation``; recorded because a copy leaves the platform.
    """
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")

    explanation = build_for_workflow(
        workflow_id, output_zone_dir=get_settings().output_zone_dir
    )
    if explanation is None:
        raise NotFoundError(
            "No computed return was recorded for this run, so there is nothing "
            "to report on yet."
        )

    uploaded = session.get(UploadedFile, workflow.uploaded_file_id)
    source_filename = uploaded.original_filename if uploaded else "workpaper"
    filename = report_filename(explanation, source_filename)

    audit.record(
        AuditAction.FILE_DOWNLOADED,
        actor_id=principal.user_id,
        actor_role=principal.role.value,
        entity_type="workflow",
        entity_id=workflow_id,
        payload={"artifact_type": "calculation_report_html", "contains_pii": True},
    )
    return HTMLResponse(
        content=render_return_report(
            explanation,
            source_filename=source_filename,
            workflow_id=workflow_id,
            generated_at=datetime.now(UTC),
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{workflow_id}/masked-preview", response_model=list[MaskedPreviewOut])
def masked_preview(
    workflow_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.PREPARER),
) -> list[MaskedPreviewOut]:
    """Show exactly what the language model received.

    SECURITY: this is the transparency surface. It reads the masked zone only —
    there is no endpoint anywhere that returns the unmasked document text.
    """
    from app.models.database_models import MaskingMap

    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")

    vault = list(
        session.execute(
            select(MaskingMap).where(MaskingMap.workflow_id == workflow_id)
        ).scalars()
    )
    # token -> surrogate. Never the original value.
    token_map = {entry.token: entry.surrogate_value for entry in vault}

    documents = session.execute(
        select(Document)
        .where(Document.uploaded_file_id == workflow.uploaded_file_id)
        .order_by(Document.page_start)
    ).scalars()

    previews: list[MaskedPreviewOut] = []
    for document in documents:
        text = ""
        if document.masked_text_path:
            path = Path(document.masked_text_path)
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
        previews.append(
            MaskedPreviewOut(
                document_id=document.id,
                document_type=document.document_type,
                page_start=document.page_start,
                page_end=document.page_end,
                masked_text=text[:50_000],
                token_count=len(token_map),
                token_map=token_map,
            )
        )
    return previews


def _graph_return(session: Any, workflow_id: str) -> Any:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")
    loaded = GraphProvenanceService(
        session, output_zone_dir=get_settings().output_zone_dir
    ).load(workflow)
    if loaded is None:
        raise NotFoundError(
            "No engine inputs were recorded for this run, so there is no "
            "calculation to trace yet."
        )
    return loaded


@router.get("/{workflow_id}/cost", response_model=WorkflowCostOut)
def workflow_llm_cost(
    workflow_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> WorkflowCostOut:
    """What this return's model calls cost, by stage and by model.

    Summed from the ``llm_calls`` ledger at the rates in force when each call
    was made. Calls the price file has no rate for are counted, not priced.
    """
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")
    return WorkflowCostOut.model_validate(workflow_cost(session, workflow).to_dict())


@router.get("/{workflow_id}/graph", response_model=GraphReturnOut)
def get_graph_return(
    workflow_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> GraphReturnOut:
    """Every line the calculation graph computes for this run, with provenance.

    Computed on request from the stored engine inputs, beside the pipeline's
    own calculator rather than instead of it.
    """
    loaded = _graph_return(session, workflow_id)
    return GraphReturnOut.model_validate(
        {
            **loaded.result.to_dict(),
            "fileable": loaded.fileable,
            "unplaced": [u.to_dict() for u in loaded.unplaced],
            "notes": list(loaded.notes),
        }
    )


@router.get("/{workflow_id}/graph/explain/{node_id}", response_model=ExplainNodeOut)
def explain_graph_line(
    workflow_id: str,
    node_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> ExplainNodeOut:
    """``explain(node_id)``: the full tree under one figure, to its sources."""
    loaded = _graph_return(session, workflow_id)
    if loaded.result.get(node_id) is None:
        raise NotFoundError(f"This return has no line {node_id!r}.")
    return ExplainNodeOut.model_validate(loaded.result.explain(node_id).to_dict())


def _calculation_report(
    session: Any, workflow_id: str, gemini: GeminiService
) -> CalculationReport:
    """Phase 4's report: the graph return, explained, indexed and cross-checked."""
    settings = get_settings()
    loaded = _graph_return(session, workflow_id)
    with metered(workflow_id=workflow_id, stage="calculation_report"):
        batch = ReportExplainer(
            gemini, settings.output_zone_dir / "report_explanations"
        ).explain(workflow_id, explained_lines(loaded), loaded.result.facts.tax_year)
    pipeline = build_for_workflow(workflow_id, output_zone_dir=settings.output_zone_dir)
    return build_report(
        loaded,
        workflow_id=workflow_id,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        explanations=batch.explanations,
        pipeline_summary=pipeline.summary if pipeline is not None else None,
        tolerance=Decimal(str(settings.calc_tolerance_dollars)),
        confidence_floor=settings.confidence_auto_approve,
        explanations_note=batch.note,
    )


def _record_report_download(
    audit: AuditLogger, principal: Principal, workflow_id: str, artifact: str
) -> None:
    audit.record(
        AuditAction.FILE_DOWNLOADED,
        actor_id=principal.user_id,
        actor_role=principal.role.value,
        entity_type="workflow",
        entity_id=workflow_id,
        # Figures and document references, no names - but a client's figures
        # all the same. Rule 4: when unsure, treat it as sensitive.
        payload={"artifact_type": artifact, "contains_pii": True},
    )


@router.get("/{workflow_id}/graph/report.json")
def calculation_report_json(
    workflow_id: str,
    session: DbSession,
    audit: AuditDep,
    gemini: GeminiDep,
    principal: Principal = role_required(Role.READONLY),
) -> Response:
    """The calculation report as JSON: every section, machine-readable."""
    report = _calculation_report(session, workflow_id, gemini)
    _record_report_download(audit, principal, workflow_id, "calculation_report_json")
    return Response(
        content=json.dumps(report.to_dict(), indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="calculation-report-{report.tax_year}-'
                f'{workflow_id[:8]}.json"'
            )
        },
    )


@router.get("/{workflow_id}/graph/report.pdf")
def calculation_report_pdf(
    workflow_id: str,
    session: DbSession,
    audit: AuditDep,
    gemini: GeminiDep,
    principal: Principal = role_required(Role.READONLY),
) -> Response:
    """The calculation report as a PDF a reviewer can sign against."""
    report = _calculation_report(session, workflow_id, gemini)
    _record_report_download(audit, principal, workflow_id, "calculation_report_pdf")
    return Response(
        content=render_pdf(report),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="calculation-report-{report.tax_year}-'
                f'{workflow_id[:8]}.pdf"'
            )
        },
    )


@router.get(
    "/{workflow_id}/documents/{document_id}/pages/{page}",
    response_model=SourcePageOut,
)
def source_page(
    workflow_id: str,
    document_id: str,
    page: int,
    session: DbSession,
    principal: Principal = role_required(Role.PREPARER),
) -> SourcePageOut:
    """One source page for the drill-down: masked text and figure boxes.

    SECURITY: masked zone only, the same boundary as ``/masked-preview``. The
    figure boxes are money-shaped words the PII detector did not flag - see
    ``figure_boxes``. Nothing here decrypts the raw zone.
    """
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")
    document = session.get(Document, document_id)
    if document is None or document.uploaded_file_id != workflow.uploaded_file_id:
        raise NotFoundError("No such document in this workflow.")
    if not document.page_start <= page <= document.page_end:
        raise NotFoundError(
            f"Page {page} is outside this document (pages "
            f"{document.page_start}-{document.page_end})."
        )

    layout_page: dict[str, Any] = {}
    for entry in (document.layout or {}).get("pages") or []:
        if isinstance(entry, dict) and entry.get("page") == page:
            layout_page = entry
            break

    text, whole = "", False
    if document.masked_text_path:
        path = Path(document.masked_text_path)
        pages_path = path.with_name(f"{document.id}.pages.json")
        if pages_path.exists():
            try:
                by_page = json.loads(pages_path.read_text(encoding="utf-8"))
                text = str(by_page.get(str(page), ""))
            except (OSError, ValueError):
                text = ""
        elif path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            whole = document.page_start != document.page_end

    return SourcePageOut(
        document_id=document.id,
        document_type=document.document_type,
        page=page,
        page_start=document.page_start,
        page_end=document.page_end,
        width=float(layout_page.get("width") or 0.0),
        height=float(layout_page.get("height") or 0.0),
        masked_text=text[:50_000],
        whole_document=whole,
        figures=[
            FigureBoxOut(text=str(f.get("text", "")), bbox=list(f.get("bbox") or []))
            for f in layout_page.get("figures") or []
            if isinstance(f, dict) and len(f.get("bbox") or []) == 4
        ],
    )


@router.get("/{workflow_id}/audit", response_model=AuditListResponse)
def workflow_audit(
    workflow_id: str,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.READONLY),
) -> AuditListResponse:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise NotFoundError("No such workflow.")

    events = list(
        session.execute(
            select(AuditEvent)
            .where(AuditEvent.entity_id == workflow_id)
            .order_by(AuditEvent.sequence.asc())
        ).scalars()
    )
    chain_valid, broken = audit.verify_chain()
    return AuditListResponse(
        items=[AuditEventOut.model_validate(e) for e in events],
        total=len(events),
        chain_valid=chain_valid,
        broken_sequences=broken,
    )


@router.get("/{workflow_id}/outputs", response_model=list[OutputPackageOut])
def list_outputs(
    workflow_id: str,
    session: DbSession,
    principal: Principal = role_required(Role.READONLY),
) -> list[OutputPackageOut]:
    packages = session.execute(
        select(OutputPackage).where(OutputPackage.workflow_id == workflow_id)
    ).scalars()
    return [OutputPackageOut.model_validate(p) for p in packages]


@router.get("/{workflow_id}/download")
def download_output(
    workflow_id: str,
    session: DbSession,
    audit: AuditDep,
    principal: Principal = role_required(Role.PREPARER),
    artifact_type: str = Query(default="full_package"),
) -> FileResponse:
    """Download a generated artifact.

    SECURITY: rehydrated artifacts contain real taxpayer data. Access requires
    at least the preparer role and every download is recorded, so who took a
    copy of a client's return is answerable from the audit log.
    """
    package = session.execute(
        select(OutputPackage)
        .where(
            OutputPackage.workflow_id == workflow_id,
            OutputPackage.artifact_type == artifact_type,
        )
        .order_by(OutputPackage.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if package is None:
        raise NotFoundError(
            f"No '{artifact_type}' artifact exists for this workflow."
        )

    path = Path(package.stored_path)
    if not path.exists():
        raise NotFoundError("The artifact is no longer available on disk.")

    package.download_count = (package.download_count or 0) + 1
    audit.record(
        AuditAction.FILE_DOWNLOADED,
        actor_id=principal.user_id,
        actor_role=principal.role.value,
        entity_type="output_package",
        entity_id=package.id,
        payload={
            "artifact_type": package.artifact_type,
            "contains_pii": package.is_rehydrated,
            "size_bytes": package.size_bytes,
        },
    )
    return FileResponse(
        path=path, filename=package.filename, media_type=package.content_type
    )


def _detail(session, workflow: Workflow) -> WorkflowDetailOut:
    stages = session.execute(
        select(WorkflowStageRun)
        .where(WorkflowStageRun.workflow_id == workflow.id)
        .order_by(WorkflowStageRun.stage_index)
    ).scalars()
    documents = session.execute(
        select(Document)
        .where(Document.uploaded_file_id == workflow.uploaded_file_id)
        .order_by(Document.page_start)
    ).scalars()
    extractions = session.execute(
        select(ExtractionResult)
        .where(ExtractionResult.workflow_id == workflow.id)
        .order_by(ExtractionResult.confidence.asc())
    ).scalars()
    packages = session.execute(
        select(OutputPackage).where(OutputPackage.workflow_id == workflow.id)
    ).scalars()

    detail = WorkflowDetailOut.model_validate(workflow)
    detail.stages = [StageRunOut.model_validate(s) for s in stages]
    detail.documents = [DocumentOut.model_validate(d) for d in documents]
    detail.extractions = [ExtractionOut.model_validate(e) for e in extractions]
    detail.output_packages = [OutputPackageOut.model_validate(p) for p in packages]
    return detail
