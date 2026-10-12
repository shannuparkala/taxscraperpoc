"""Operational settings and health reporting.

SECURITY: this router never returns a secret. API keys are reported as a
boolean only — not masked, not truncated, not partially shown. A partially
revealed key is still a leaked key.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import (
    CurrentPrincipal,
    DbSession,
    SettingsDep,
    client_scope_for,
    role_required,
)
from app.core.config import Role
from app.core.logging import get_logger
from app.core.security import Principal
from app.schemas.api import HealthOut, QuotaOut, SettingsOut
from app.services.ocr_service import OcrService
from app.services.pii_detection_service import PiiDetectionService
from app.services.tax_engine.tax_tables import SUPPORTED_YEARS, VERIFIED_YEARS

logger = get_logger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings_view(
    settings: SettingsDep,
    principal: Principal = role_required(Role.READONLY),
) -> SettingsOut:
    ocr = OcrService(settings)
    detector = PiiDetectionService()

    return SettingsOut(
        app_env=settings.app_env.value,
        app_version=settings.app_version,
        # SECURITY: presence only — the key itself is never serialized.
        gemini_configured=bool(settings.gemini_api_key),
        gemini_enabled=settings.gemini_enabled,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
        model_flash_lite=settings.gemini_model_flash_lite,
        assistant_model=settings.assistant_model,
        egress_guard_enabled=settings.llm_egress_guard_enabled,
        egress_guard_mode=settings.llm_egress_guard_mode.value,
        ocr_available=ocr.tesseract_available,
        ocr_engine_path_configured=bool(settings.tesseract_cmd),
        allow_cloud_ocr_fallback=settings.allow_cloud_ocr_fallback,
        spacy_ner_available=detector.ner_available,
        tax_files_dir=str(settings.tax_files_dir),
        max_upload_mb=settings.max_upload_mb,
        allowed_extensions=sorted(settings.allowed_extension_set),
        confidence_auto_approve=settings.confidence_auto_approve,
        confidence_escalate=settings.confidence_escalate,
        calc_tolerance_dollars=settings.calc_tolerance_dollars,
        retention_raw_days=settings.retention_raw_days,
        retention_masked_days=settings.retention_masked_days,
        retention_audit_days=settings.retention_audit_days,
        rate_limit_enabled=settings.rate_limit_enabled,
        auth_disabled=settings.auth_disabled,
        supported_tax_years=list(SUPPORTED_YEARS),
        verified_tax_years=sorted(VERIFIED_YEARS),
    )


@router.get("/health", response_model=HealthOut)
def health(session: DbSession, settings: SettingsDep) -> HealthOut:
    """Readiness report with actionable warnings.

    Unauthenticated so that a load balancer can probe it. It exposes only
    capability booleans — no configuration values, no counts, no client data.
    """
    warnings: list[str] = []

    database_ok = True
    try:
        from sqlalchemy import text

        session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        database_ok = False
        warnings.append(f"Database unreachable ({type(exc).__name__}).")

    ocr_ok = OcrService(settings).tesseract_available
    if not ocr_ok:
        warnings.append(
            "Tesseract OCR is not installed. Scanned documents cannot be read "
            "and will be routed to human review. Install with: "
            "winget install --id UB-Mannheim.TesseractOCR"
        )

    ner_ok = PiiDetectionService().ner_available
    if not ner_ok:
        warnings.append(
            "spaCy NER model is missing, so person and organisation names "
            "cannot be detected for masking. Install with: "
            "python -m spacy download en_core_web_sm"
        )

    # Configuration alone is not health. This reported llm=True whenever a key
    # was set, while every actual call fell back to deterministic stubs because
    # google-genai was not installed in the environment the server runs from —
    # so the one place an operator would look to diagnose "why is the chatbot
    # not answering" confidently told them the LLM was fine. Probe the import
    # the runtime path actually depends on.
    llm_configured = bool(settings.gemini_api_key) and settings.gemini_enabled
    llm_importable = True
    if llm_configured:
        try:
            from google import genai  # noqa: F401
        except Exception:
            llm_importable = False

    llm_ok = llm_configured and llm_importable
    if not llm_configured:
        warnings.append(
            "Gemini is not configured; the pipeline and chatbot run on "
            "deterministic stubs. Set GEMINI_API_KEY to enable AI processing."
        )
    elif not llm_importable:
        warnings.append(
            "Gemini is configured but the google-genai package is missing from "
            "this environment, so every answer falls back to a deterministic "
            "stub. Install it into the interpreter running this server: "
            "python -m pip install google-genai"
        )

    if settings.auth_disabled:
        warnings.append(
            "AUTH_DISABLED is true — every caller is treated as "
            f"'{settings.dev_default_role.value}'. Development only."
        )
    if not settings.llm_egress_guard_enabled:
        warnings.append(
            "The LLM egress guard is DISABLED. Unmasked data could leave the "
            "host. Re-enable LLM_EGRESS_GUARD_ENABLED."
        )
    if settings.allow_cloud_ocr_fallback:
        warnings.append(
            "Cloud OCR fallback is enabled: unmasked page images may be sent "
            "to a third-party model."
        )

    # Degraded means usable-but-limited; only a database failure is unhealthy.
    status = "healthy" if database_ok else "unhealthy"
    if status == "healthy" and (not ocr_ok or not ner_ok or not llm_ok):
        status = "degraded"

    return HealthOut(
        status=status,
        version=settings.app_version,
        database=database_ok,
        ocr=ocr_ok,
        ner=ner_ok,
        llm=llm_ok,
        warnings=warnings,
    )


@router.get("/quota", response_model=QuotaOut)
def quota(
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
) -> QuotaOut:
    """Today's usage against the daily ceilings.

    Readable by any authenticated caller, because the person it most needs to
    inform is the tester who was just turned away. It reports counts and limits
    only — never who consumed them.
    """
    from app.services.quota_service import QuotaService, current_day

    service = QuotaService(session)
    return QuotaOut(
        day=current_day(),
        groups=service.snapshot(client_scope_for(request, principal)),
    )
