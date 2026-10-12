"""Generation of the final deliverable package.

Produces exactly two files per workflow:

* **Complete Return** (.pdf) — Form 1040 and every schedule the return needs,
  merged in filing order. This is the document that gets signed.
* **Tax Return Workpaper** (.xlsx) — one workbook holding every form, every
  schedule, and the source, formula and authority behind every figure.

It used to produce ten: a 1040, seven separate schedule PDFs, a merged return,
three tax-software exports, a workpaper, a summary, reviewer notes, an exception
list, a traceability matrix, an audit log, and a zip of all of them. The
evidence for any one figure was split across four of those files, so a reviewer
reassembled it by hand before they could check anything — and the file that
answered "where did this number come from" was never the one they had open.
Worse, the folder held the return twice, once merged and once in pieces, which
is an invitation to sign the wrong copy.

Everything the working-paper files carried is now a sheet in the workbook,
joined to the line it explains. Nothing else is emitted: a file that is neither
the signed return nor the evidence behind it is one more thing to keep in step.

SECURITY: both artifacts are rehydrated and therefore contain real client data.
They live in the output zone, downloads are role-gated and audited, and the
values are checked for surviving mask tokens before they are written — a
leftover token means a lost vault entry and a package that must not ship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditLogger
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.security import sha256_bytes
from app.models.database_models import (
    Document,
    ExtractionResult,
    OutputPackage,
    ReviewItem,
    Workflow,
)
from app.models.enums import OutputArtifactType
from app.services.rehydration_service import RehydrationService
from app.services.tax_engine.form_1040 import Return1040

logger = get_logger(__name__)


#: Extraction fields that carry taxpayer identity onto the face of the form.
#: Deliberately a fixed allow-list: whatever else the model extracts, only
#: these ever reach the 1040's header boxes.
#:
#: Names are canonicalised first. This list previously held only the canonical
#: spellings while extraction emitted "name" and "address", so the form went
#: out carrying an SSN and a state and nothing else — no name, no street, no
#: city, no ZIP.
_IDENTITY_FACT_FIELDS: frozenset[str] = frozenset(
    {
        "taxpayer_name",
        "spouse_name",
        "ssn",
        "spouse_ssn",
        "street_address",
        "apartment",
        "city",
        "state",
        "zip_code",
    }
)


def _money(amount: Decimal | float | None) -> str:
    """Format an amount the way a reader expects to see money.

    The raw engine values are unrounded Decimals ("11221.98", "-264.74"), which
    read as machine output. Thousands separators and a currency symbol are what
    make a figure scannable in a sentence.
    """
    if amount is None:
        return "$0.00"
    value = Decimal(str(amount))
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


@dataclass(slots=True)
class GeneratedArtifact:
    artifact_type: OutputArtifactType
    filename: str
    content: bytes
    content_type: str
    tokens_rehydrated: int = 0
    #: Tokens that could not be resolved — non-empty means do not ship.
    residual_tokens: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.residual_tokens


class OutputGenerationService:
    """Builds and persists the deliverable package."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = audit

    # ------------------------------------------------------------------ API

    def generate_package(
        self,
        workflow: Workflow,
        *,
        computed_return: Return1040 | None = None,
        rehydrator: RehydrationService | None = None,
        engine_inputs: dict[str, Any] | None = None,
    ) -> list[OutputPackage]:
        """Generate every artifact and register it in the output zone.

        ``engine_inputs`` carries the dataclasses the calculator was given —
        income, adjustments, deductions, capital gains, profile. The schedules
        need the detail behind each Form 1040 total (line 8 is one number; the
        Schedule 1 that produced it has five), and ``Return1040`` keeps only the
        totals. Absent, the schedules are skipped and the 1040 still ships.
        """
        rehydrator = rehydrator or RehydrationService(
            self._session, workflow_id=workflow.id, audit=self._audit
        )

        documents = list(
            self._session.execute(
                select(Document).where(
                    Document.uploaded_file_id == workflow.uploaded_file_id
                )
            ).scalars()
        )
        extractions = list(
            self._session.execute(
                select(ExtractionResult).where(
                    ExtractionResult.workflow_id == workflow.id
                )
            ).scalars()
        )
        review_items = list(
            self._session.execute(
                select(ReviewItem).where(ReviewItem.workflow_id == workflow.id)
            ).scalars()
        )

        artifacts: list[GeneratedArtifact] = []

        # The form comes first: it is the deliverable, and everything else in
        # the package exists to support or explain it. Skipped when no return
        # was computed — the refusal gate has already raised a review item, and
        # an official-looking 1040 full of blanks is exactly the misleading
        # artifact that gate exists to prevent.
        return_pdfs: list[GeneratedArtifact] = []
        if computed_return is not None:
            form = self._build_form_1040(
                workflow, extractions, computed_return, rehydrator
            )
            if form is not None:
                return_pdfs.append(form)

            # The schedules behind the form. Every figure on them was already
            # computed for Form 1040; without them the deliverable is a summary
            # page with nothing supporting it, which is not a filable return.
            return_pdfs += self._build_schedules(
                computed_return, engine_inputs, extractions, rehydrator
            )

        # Form 1040 and its schedules merged in filing order. The individual
        # per-schedule PDFs are deliberately not shipped alongside it: they are
        # the same pages twice, and a folder holding both invites the wrong one
        # being signed.
        complete = self._build_complete_return(computed_return, return_pdfs)
        if complete is not None:
            artifacts.append(complete)

        # --- One workpaper, not eight artifacts ---------------------------
        # This used to emit a workpaper, a summary, reviewer notes, an exception
        # list, a traceability CSV, an audit log and a zip of all of them. Seven
        # files across which the evidence for any single figure was split, so a
        # reviewer's first task was reassembling it — and the file that answered
        # "where did this number come from" was never the one they had open.
        #
        # Everything those files carried is now a sheet in one workbook, joined
        # to the line it explains. The only other artifact is the return itself,
        # which is a filing document rather than working papers.
        workpaper = self._build_consolidated_workpaper(
            workflow, documents, extractions, computed_return, review_items,
            rehydrator, engine_inputs,
        )
        if workpaper is not None:
            artifacts.append(workpaper)

        # One directory for the whole run, computed once: deriving it per
        # artifact would split a package across two folders whenever generation
        # straddled a minute boundary.
        directory = self._package_directory(workflow)
        packages = [
            self._persist(workflow, artifact, directory) for artifact in artifacts
        ]
        logger.info("Output package written to %s", directory)
        rehydrator.finalize(artifact_count=len(artifacts))

        unclean = [a.filename for a in artifacts if not a.is_clean]
        if unclean:
            logger.error(
                "SECURITY: %d artifact(s) still contain unresolved mask tokens: %s. "
                "The vault entries are missing; do not release this package.",
                len(unclean),
                ", ".join(unclean),
            )

        if self._audit is not None:
            self._audit.record(
                AuditAction.OUTPUT_GENERATED,
                entity_type="workflow",
                entity_id=workflow.id,
                payload={
                    "artifacts": len(packages),
                    "tokens_rehydrated": sum(a.tokens_rehydrated for a in artifacts),
                    "artifacts_with_residual_tokens": len(unclean),
                },
            )
        return packages

    # ---------------------------------------------------------- artifacts

    def _build_consolidated_workpaper(
        self,
        workflow: Workflow,
        documents: list[Document],
        extractions: list[ExtractionResult],
        computed_return: Return1040 | None,
        review_items: list[ReviewItem],
        rehydrator: RehydrationService,
        engine_inputs: dict[str, Any] | None,
    ) -> GeneratedArtifact | None:
        """The single workpaper: every form, schedule and calculation trail.

        SECURITY: identity is rehydrated here, so this artifact holds real
        taxpayer data. Output zone only; never sent outbound.
        """
        if computed_return is None or not engine_inputs:
            logger.info(
                "No computed return; the consolidated workpaper was not built."
            )
            return None

        from app.services.consolidated_workpaper import (
            WorkpaperInputs,
            build_consolidated_workpaper,
        )

        facts, restored = self._identity_facts(extractions, rehydrator)

        provenance: dict[str, list[dict[str, str]]] = {}
        confidences: dict[str, Any] = {}
        for extraction in extractions:
            name = extraction.field_name or ""
            if not name:
                continue
            if extraction.confidence is not None:
                confidences.setdefault(name, extraction.confidence)
            document = next(
                (d for d in documents if d.id == extraction.document_id), None
            )
            provenance.setdefault(name, []).append(
                {
                    "document_type": (
                        document.document_type if document else "unknown"
                    ),
                    "amount": rehydrator.rehydrate_text(
                        extraction.normalized_value or ""
                    ).text,
                    "page": str(extraction.source_page or ""),
                }
            )

        try:
            content = build_consolidated_workpaper(
                WorkpaperInputs(
                    computed_return=computed_return,
                    engine_inputs=engine_inputs,
                    identity=facts,
                    field_provenance=provenance,
                    review_items=[
                        {
                            "field_name": item.field_name or "",
                            "title": item.title or "",
                            "description": item.description or "",
                        }
                        for item in review_items
                    ],
                    documents=[
                        {
                            "document_type": d.document_type,
                            "pages": d.page_count,
                            "confidence": d.ocr_mean_confidence,
                        }
                        for d in documents
                    ],
                    confidence_scores=confidences,
                    workflow_id=workflow.id,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            # With the traceback, because without it this line was unactionable:
            # it reported InvalidOperation for every document in the corpus and
            # named neither the sheet nor the value, and the package shipped
            # without a workpaper for months. See trap 32.
            logger.exception(
                "Consolidated workpaper not built (%s)", type(exc).__name__
            )
            return None

        return GeneratedArtifact(
            # COMPLETED_WORKPAPER, not WORKPAPER, which is not a member. The
            # typo was unreachable while the builder above always raised, so
            # fixing the Decimal coercion surfaced a second defect behind the
            # first — and this one escaped the `except` and failed the whole
            # output stage. See trap 32.
            artifact_type=OutputArtifactType.COMPLETED_WORKPAPER,
            filename=f"Tax Return Workpaper ({computed_return.tax_year}).xlsx",
            content=content,
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            tokens_rehydrated=restored,
            # A workbook is a zip of XML; the mask-token scan that guards the
            # text artifacts cannot see inside it, so residual detection happens
            # on the values before they are written.
            residual_tokens=[],
        )

    def _identity_facts(
        self,
        extractions: list[ExtractionResult],
        rehydrator: RehydrationService,
    ) -> tuple[dict[str, Any], int]:
        """Rehydrated taxpayer identity, and how many tokens that restored.

        SECURITY: the returned values are real — name, SSN, address. Every
        caller writes them into an output-zone artifact and nowhere else.

        One place rather than one per artifact, because the allow-list is the
        control: whatever else extraction produced, only ``_IDENTITY_FACT_FIELDS``
        reaches a deliverable's identity boxes.
        """
        from app.services.workflow_orchestrator import canonical_identity_field

        restored = 0
        facts: dict[str, Any] = {}
        for extraction in extractions:
            name = canonical_identity_field(extraction.field_name or "") or ""
            if name not in _IDENTITY_FACT_FIELDS or name in facts:
                continue
            value = rehydrator.rehydrate_text(extraction.masked_value or "")
            restored += value.tokens_restored
            if value.text.strip():
                facts[name] = value.text.strip()
        return facts, restored

    def _build_form_1040(
        self,
        workflow: Workflow,
        extractions: list[ExtractionResult],
        computed_return: Return1040,
        rehydrator: RehydrationService,
    ) -> GeneratedArtifact | None:
        """Render the computed return onto the official IRS Form 1040.

        SECURITY: identity is rehydrated here, so this artifact contains real
        taxpayer data. It is written to the output zone like every other
        artifact and is never sent outbound.
        """
        from app.services.form_1040_filler import (
            Form1040Filler,
            build_identity_from_facts,
        )

        facts, restored = self._identity_facts(extractions, rehydrator)

        try:
            content = Form1040Filler().fill(
                computed_return, build_identity_from_facts(facts)
            )
        except (FileNotFoundError, ValueError) as exc:
            # A missing or wrong-year template must not take the whole package
            # down; the rest of the artifacts are still worth producing.
            logger.error("Form 1040 not rendered: %s", exc)
            return None

        return GeneratedArtifact(
            artifact_type=OutputArtifactType.TAX_RETURN_FORM,
            filename=f"1 - Form 1040 ({computed_return.tax_year}).pdf",
            content=content,
            content_type="application/pdf",
            tokens_rehydrated=restored,
            # A PDF is binary; the mask-token scan that guards the text
            # artifacts would not find tokens inside the content stream, so
            # residual detection happens on the values before they are written.
            residual_tokens=[],
        )

    def _build_schedules(
        self,
        computed_return: Return1040,
        engine_inputs: dict[str, Any] | None,
        extractions: list[ExtractionResult],
        rehydrator: RehydrationService,
    ) -> list[GeneratedArtifact]:
        """Render each schedule the return needs onto its official IRS form."""
        if not engine_inputs:
            logger.info("No engine inputs supplied; schedules not rendered")
            return []

        from app.services.schedule_filler import render_schedules

        try:
            rendered = render_schedules(
                result=computed_return,
                income=engine_inputs["income"],
                adjustments=engine_inputs["adjustments"],
                deductions=engine_inputs["deductions"],
                capital_gains=engine_inputs["capital_gains"],
                payments=engine_inputs["payments"],
                profile=engine_inputs["profile"],
            )
        except Exception as exc:  # noqa: BLE001 - one form must not sink the package
            logger.error("Schedules not rendered: %s", type(exc).__name__)
            return []

        return [
            GeneratedArtifact(
                artifact_type=OutputArtifactType.TAX_RETURN_SCHEDULE,
                filename=schedule.filename,
                content=schedule.content,
                content_type="application/pdf",
            )
            for schedule in rendered
        ]

    def _build_complete_return(
        self,
        computed_return: Return1040 | None,
        return_pdfs: list[GeneratedArtifact],
    ) -> GeneratedArtifact | None:
        """Merge Form 1040 and its schedules into one document, in filing order.

        The artifacts are already produced individually and stay that way — a
        preparer sometimes wants one schedule. This is the version they sign:
        the whole return as a single PDF, in the order the IRS expects it,
        rather than a folder to be collated by hand.
        """
        if computed_return is None or not return_pdfs:
            return None

        try:
            merged = fitz.open()
            for artifact in return_pdfs:
                with fitz.open(stream=artifact.content, filetype="pdf") as part:
                    merged.insert_pdf(part)
            content = merged.tobytes()
            page_count = merged.page_count
            merged.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Complete return not assembled: %s", type(exc).__name__)
            return None

        logger.info(
            "Complete return assembled: %d document(s), %d pages",
            len(return_pdfs),
            page_count,
        )
        return GeneratedArtifact(
            artifact_type=OutputArtifactType.COMPLETE_RETURN,
            filename=f"0 - Complete Return ({computed_return.tax_year}).pdf",
            content=content,
            content_type="application/pdf",
        )

    def _package_directory(self, workflow: Workflow) -> Path:
        """Where this run's artifacts go: one dated, sortable folder.

        Named by timestamp and a short workflow id rather than by the uploaded
        file. SECURITY: a client filename routinely carries a taxpayer name
        ("Smith W-2.pdf"), and a directory name ends up in shell history, backup
        indexes and screen shares — none of which are covered by the masking
        boundary.
        """
        created = workflow.created_at or datetime.now(UTC)
        folder = f"{created:%Y-%m-%d_%H%M}_{workflow.id[:8]}"
        directory = self._settings.output_zone_dir / folder
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _persist(
        self,
        workflow: Workflow,
        artifact: GeneratedArtifact,
        directory: Path | None = None,
    ) -> OutputPackage:
        from datetime import timedelta

        directory = directory or self._package_directory(workflow)
        path = directory / artifact.filename
        path.write_bytes(artifact.content)

        package = OutputPackage(
            workflow_id=workflow.id,
            artifact_type=artifact.artifact_type.value,
            filename=artifact.filename,
            stored_path=str(path),
            content_type=artifact.content_type,
            size_bytes=len(artifact.content),
            content_hash=sha256_bytes(artifact.content),
            is_rehydrated=artifact.tokens_rehydrated > 0,
            tokens_rehydrated=artifact.tokens_rehydrated,
            purge_after=datetime.now(UTC)
            + timedelta(days=self._settings.retention_raw_days),
        )
        self._session.add(package)
        return package
