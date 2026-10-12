"""Run the pipeline over every workpaper in the dataset and record the result.

This is the half of the comparison that does not depend on OCR of the
accountant's copy: what does our engine actually produce, for each of the nine
real workpapers, when given nothing but the workpaper?

Each case is independent. One that fails is recorded as a failure and the batch
continues — an exception on case three must not cost the six after it, since the
whole run is measured in tens of minutes and real API spend.

    cd backend && python -m scripts.batch_run
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "Files"
OUT = ROOT / "data" / "learning" / "BatchRun.json"

#: Lines worth recording for every case, whatever the return looks like.
REPORTED_LINES = (
    "1a", "2a", "2b", "3a", "3b", "4b", "5b", "6a", "6b", "7", "8", "9",
    "10", "11", "12", "13b", "14", "15", "16", "19", "21", "23", "24",
    "25", "26", "33", "34", "35a", "36", "37",
)


def _workpapers() -> list[Path]:
    return sorted(p for p in FILES.glob("*.pdf") if "workpaper" in p.name.lower())


def run_one(path: Path) -> dict[str, Any]:
    """Upload and process one workpaper, returning everything worth scoring."""
    from sqlalchemy import select

    from app.core.audit import AuditLogger
    from app.core.db import session_scope
    from app.models.database_models import (
        Document,
        OutputPackage,
        ReviewItem,
        UploadedFile,
        Workflow,
    )
    from app.services.ingestion_service import IngestionService
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    started = time.monotonic()

    with session_scope() as session, path.open("rb") as stream:
        stored = IngestionService(session, audit=AuditLogger(session)).store(
            filename=path.name, stream=stream, content_type="application/pdf"
        )
        session.flush()
        file_id = stored.id

    with session_scope() as session:
        uploaded = session.get(UploadedFile, file_id)
        orchestrator = WorkflowOrchestrator(session, audit=AuditLogger(session))
        result = orchestrator.run(uploaded, actor_id=None)
        workflow_id = result.workflow_id

    with session_scope() as session:
        workflow = session.get(Workflow, workflow_id)
        documents = list(
            session.execute(
                select(Document).where(
                    Document.uploaded_file_id == workflow.uploaded_file_id
                )
            ).scalars()
        )
        reviews = list(
            session.execute(
                select(ReviewItem).where(ReviewItem.workflow_id == workflow_id)
            ).scalars()
        )
        packages = list(
            session.execute(
                select(OutputPackage).where(OutputPackage.workflow_id == workflow_id)
            ).scalars()
        )
        record: dict[str, Any] = {
            "workflow_id": workflow_id,
            "status": workflow.status,
            "seconds": round(time.monotonic() - started, 1),
            "documents_detected": workflow.documents_detected,
            "document_types": sorted({d.document_type for d in documents}),
            "overall_confidence": workflow.overall_confidence,
            "review_items": [
                {"reason": r.reason, "title": r.title} for r in reviews
            ],
            "artifacts": sorted(p.artifact_type for p in packages),
            "error": workflow.error_summary,
        }

    # The computed return, rebuilt from the inputs the run filed.
    from app.core.config import get_settings
    from app.services.explanation_service import build_for_workflow

    explanation = build_for_workflow(
        workflow_id, output_zone_dir=get_settings().output_zone_dir
    )
    if explanation is None:
        record["computed_return"] = None
        record["lines"] = {}
    else:
        record["computed_return"] = explanation.summary
        by_line = {line.line: str(line.amount) for line in explanation.lines}
        record["lines"] = {k: by_line[k] for k in REPORTED_LINES if k in by_line}
        record["tax_year"] = explanation.tax_year
        record["filing_status"] = explanation.filing_status
    return record


def main() -> None:
    targets = _workpapers()
    print(f"Batch over {len(targets)} workpapers\n")
    results: dict[str, Any] = {}

    for index, path in enumerate(targets, start=1):
        print(f"[{index}/{len(targets)}] {path.name} ...", flush=True)
        try:
            record = run_one(path)
        except Exception as exc:  # noqa: BLE001 - one case must not sink the batch
            record = {
                "status": "crashed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-1500:],
            }
            print(f"      CRASHED: {type(exc).__name__}: {exc}", flush=True)
        else:
            summary = record.get("computed_return") or {}
            print(
                f"      {record['status']}  {record['documents_detected']} docs, "
                f"{len(record['review_items'])} review items, "
                f"AGI {summary.get('adjusted_gross_income', 'n/a')}, "
                f"{record['seconds']}s",
                flush=True,
            )
        results[path.name] = record

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "cases": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    produced = sum(1 for r in results.values() if r.get("computed_return"))
    print(f"\n{produced}/{len(targets)} produced a computed return -> {OUT.name}")


if __name__ == "__main__":
    main()
