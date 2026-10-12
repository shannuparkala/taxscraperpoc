"""The depreciation calculator: rules, calculation, exports, explanation, additions.

Routes stay thin. All arithmetic is ``services/depreciation``; the model calls
are the optional explanation and, for an imported additions list, the life
(MACRS class) of each asset - both through ``GeminiService``. No model output
is ever used as an amount.

SECURITY/privacy: amounts entered here are never logged. Log lines carry
counts and outcomes only, so nothing ties a figure to the caller's identity.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.api.deps import (
    CurrentPrincipal,
    GeminiDep,
    SettingsDep,
    rate_limit,
    role_required,
)
from app.core.config import Role
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.core.rate_limit import enforce
from app.core.security import DEV_PRINCIPAL_ID, Principal
from app.core.tax_year import resolve_default_year
from app.schemas.depreciation import (
    AdditionReportRequest,
    DepreciationRequest,
    LifeRequest,
    _state_code,
)
from app.services.depreciation import addition_import, addition_report
from app.services.depreciation.engine import (
    METHOD_LABELS,
    InputError,
    UnsupportedYearError,
)
from app.services.depreciation.explanation import DepreciationExplainer
from app.services.depreciation.exports import to_csv, to_pdf
from app.services.depreciation.life_predictor import LifePredictor
from app.services.depreciation.rules import get_rules
from app.services.depreciation.service import calculate as run_calculation
from app.services.llm_meter import MeterScope

logger = get_logger(__name__)

router = APIRouter(prefix="/api/depreciation", tags=["depreciation"])


class UnsupportedYear(ValidationError):
    code = "unsupported_tax_year"


def _burst_limit(request: Request, principal: CurrentPrincipal) -> None:
    """Per-minute limit only.

    A calculation is local arithmetic that spends no model budget, and the
    screen recalculates as the form changes; the daily quota exists for LLM
    and OCR spend and would lock a user out after an afternoon of typing.
    """
    client = principal.user_id if principal.user_id != DEV_PRINCIPAL_ID else (
        request.client.host if request.client else "unknown"
    )
    enforce("depreciation", client)


def _calculate(payload: DepreciationRequest) -> dict[str, Any]:
    try:
        return run_calculation(payload.to_engine())
    except UnsupportedYearError as exc:
        raise UnsupportedYear(str(exc)) from exc
    except InputError as exc:
        raise ValidationError("Some inputs need attention.", details={"errors": exc.errors}) from exc


@router.get("/rules")
def rules_overview(principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    """Everything the form needs, each value with its source."""
    rules = get_rules()
    years = list(rules.supported_years)
    states = []
    for code in rules.state_codes:
        state = rules.state(code) or {}
        states.append({
            "code": code,
            "name": state.get("name", code),
            "business_tax": state.get("business_tax", ""),
            "status_by_year": {y: e.get("status") for y, e in state.get("years", {}).items()},
            # "Recently" means the latest two rule years - the 2025 federal law
            # and the states' responses to it - not every change on record.
            "changed_recently_years": sorted(
                int(y) for y, e in state.get("years", {}).items()
                if e.get("changed_recently") and int(y) >= years[-1] - 1
            ),
            "change_notes": {
                y: e.get("change_note", "") for y, e in state.get("years", {}).items()
                if e.get("changed_recently") and e.get("change_note")
            },
        })
    federal = rules.federal
    return {
        "supported_years": years,
        "default_year": resolve_default_year(years),
        "methods": [{"key": key, "label": label} for key, label in METHOD_LABELS.items()]
        + [{"key": "compare", "label": "Compare all methods"}],
        "asset_classes": [
            {
                "key": c.key,
                "label": c.label,
                "recovery_years": c.recovery_years,
                "allowed_recovery_years": list(c.allowed_recovery_years),
                "section_179_eligible": c.section_179_eligible,
                "bonus_eligible": c.bonus_eligible,
                "listed": c.listed,
                "real_property": c.real_property,
                "suv_cap": c.suv_cap,
                "qpp": c.qpp,
                "note": c.note,
                "source": c.ref.to_dict(),
            }
            for c in rules.classes.values()
        ],
        "states": states,
        "federal": {
            "section_179": federal["section_179"],
            "luxury_auto_caps": {y: v for y, v in federal["luxury_auto_caps"].items() if not y.startswith("_")},
            "bonus_rules": federal["bonus"]["rules"],
            "qualified_production_property": federal["qualified_production_property"],
        },
        "rules_version": federal["version"],
    }


@router.post("/calculate", dependencies=[Depends(_burst_limit)])
def calculate(payload: DepreciationRequest, principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    result = _calculate(payload)
    logger.info("Depreciation calculated: %d asset(s), state=%s", len(payload.assets), payload.state or "-")
    return result


@router.post("/export/csv", dependencies=[Depends(_burst_limit)])
def export_csv(payload: DepreciationRequest, principal: Principal = role_required(Role.READONLY)) -> Response:
    result = _calculate(payload)
    return Response(
        content=to_csv(result).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="depreciation-{payload.tax_year}.csv"'},
    )


@router.post("/export/pdf", dependencies=[Depends(_burst_limit)])
def export_pdf(payload: DepreciationRequest, principal: Principal = role_required(Role.READONLY)) -> Response:
    result = _calculate(payload)
    return Response(
        content=to_pdf(result),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="depreciation-{payload.tax_year}.pdf"'},
    )


@router.post("/explain", dependencies=[rate_limit("chat")])
def explain(
    payload: DepreciationRequest,
    gemini: GeminiDep,
    settings: SettingsDep,
    principal: Principal = role_required(Role.READONLY),
) -> dict[str, Any]:
    """A grounded plain-English explanation of the computed result.

    The result is recomputed here from the same inputs rather than accepted
    from the client, so the model only ever sees numbers the engine produced.
    """
    result = _calculate(payload)
    explanation = DepreciationExplainer(gemini, settings).explain(result)
    logger.info("Depreciation explanation: available=%s produced=%s",
                explanation["available"], bool(explanation["text"]))
    return explanation


# ===========================================================================
# Current-year additions: an asset list in, the firm's summary workbook out
# ===========================================================================


def _report(payload: AdditionReportRequest) -> dict[str, Any]:
    try:
        return addition_report.build(
            payload.to_report_assets(), tax_year=payload.tax_year, state=payload.state, rules=get_rules()
        )
    except UnsupportedYearError as exc:
        raise UnsupportedYear(str(exc)) from exc
    except InputError as exc:
        raise ValidationError("Some assets need attention.", details={"errors": exc.errors}) from exc


@router.post("/additions/import", dependencies=[rate_limit("upload")])
def import_additions(
    gemini: GeminiDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
    tax_year: int = Form(...),
    state: str | None = Form(default=None),
    business_activity: str = Form(default="", max_length=120),
    principal: Principal = role_required(Role.PREPARER),
) -> dict[str, Any]:
    """Read an asset list, predict each asset's life, and compute the report.

    The tax year and jurisdiction come first (the import's first step) and
    are required here: lives are decided for that year and jurisdiction,
    never for one assumed at upload. The model sees redacted descriptions
    only and picks a class; every figure is then the engine's. Rows that
    cannot be computed - no cost, no date, no life the model could pick -
    come back with their problems for the user to fix rather than being
    guessed.
    """
    content = file.file.read(addition_import.MAX_BYTES + 1)
    try:
        rows = addition_import.read(content, file.filename or "")
        state_code = _state_code(state)
    except (addition_import.ImportError_, ValueError) as exc:
        raise ValidationError(str(exc)) from exc

    rules = get_rules()
    year = tax_year
    try:
        rules.require_year(year)
    except UnsupportedYearError as exc:
        raise UnsupportedYear(str(exc)) from exc

    predictions, message = LifePredictor(gemini, settings, rules).predict(
        [r.description for r in rows],
        [r.life for r in rows],
        tax_year=year,
        jurisdiction=state_code,
        business_activity=business_activity,
        meter_scope=MeterScope(stage="depreciation_life"),
    )
    out_rows: list[dict[str, Any]] = []
    for row, prediction in zip(rows, predictions):
        problems = list(row.problems)
        if row.acquired and row.acquired.year != year:
            problems.append(f"acquired in {row.acquired.year}, not a {year} addition")
        out_rows.append({
            "row": row.row,
            "asset_id": row.asset_id,
            "description": row.description,
            "acquired": row.acquired.isoformat() if row.acquired else None,
            "cost": str(row.cost) if row.cost is not None else None,
            "life_in_file": row.life,
            "prediction": prediction.to_dict(),
            "problems": problems,
            # What is wrong with the file itself, by column. Whether an asset
            # belongs to the tax year is not here: the year can change after
            # upload, and the screen checks it against the year chosen then.
            "issues": [issue.to_dict() for issue in row.issues],
        })

    ready = [
        r for r in out_rows
        if not r["problems"] and r["prediction"]["asset_class"]
    ]
    report = None
    report_errors: list[str] = []
    if ready:
        try:
            report = addition_report.build(
                [
                    addition_report.AdditionAsset(
                        asset_id=r["asset_id"], description=r["description"],
                        acquired=date.fromisoformat(r["acquired"]), cost=Decimal(r["cost"]),
                        asset_class=r["prediction"]["asset_class"],
                        recovery_years=r["prediction"]["recovery_years"],
                    )
                    for r in ready
                ],
                tax_year=year, state=state_code, rules=rules,
            )
        except InputError as exc:
            report_errors = exc.errors

    logger.info(
        "Additions imported: %d row(s), %d ready, %d with problems, state=%s",
        len(out_rows), len(ready), sum(1 for r in out_rows if r["problems"]), state_code or "-",
    )
    return {
        "tax_year": year,
        "state": state_code,
        "message": message,
        "rows": out_rows,
        "report": report,
        "report_errors": report_errors,
    }


@router.get("/additions/template")
def additions_template(principal: Principal = role_required(Role.READONLY)) -> Response:
    """An empty upload template with the columns the import reads."""
    return Response(
        content=addition_import.template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Asset-Additions-Template.xlsx"'},
    )


@router.post("/additions/lives", dependencies=[rate_limit("upload")])
def predict_lives(
    payload: LifeRequest,
    gemini: GeminiDep,
    settings: SettingsDep,
    principal: Principal = role_required(Role.PREPARER),
) -> dict[str, Any]:
    """Re-decide lives after the tax year or jurisdiction changed, without a re-upload.

    The browser sends back only the rows whose life the user has not chosen
    themselves; a life the preparer picked is never overwritten.
    """
    rules = get_rules()
    try:
        predictions, message = LifePredictor(gemini, settings, rules).predict(
            [a.description for a in payload.assets],
            [a.life_in_file for a in payload.assets],
            tax_year=payload.tax_year,
            jurisdiction=payload.state,
            business_activity=payload.business_activity,
            meter_scope=MeterScope(stage="depreciation_life"),
        )
    except UnsupportedYearError as exc:
        raise UnsupportedYear(str(exc)) from exc
    logger.info("Additions lives re-predicted: %d asset(s), state=%s", len(payload.assets), payload.state or "-")
    return {"tax_year": payload.tax_year, "state": payload.state, "message": message,
            "predictions": [p.to_dict() for p in predictions]}


@router.post("/additions/report", dependencies=[Depends(_burst_limit)])
def additions_report(
    payload: AdditionReportRequest, principal: Principal = role_required(Role.READONLY)
) -> dict[str, Any]:
    """Recompute the report after the user changed a life or an election."""
    return _report(payload)


@router.post("/additions/export", dependencies=[Depends(_burst_limit)])
def export_additions(
    payload: AdditionReportRequest, principal: Principal = role_required(Role.READONLY)
) -> Response:
    """The report as the firm's "CY Addition Dep Summary" workbook."""
    report = _report(payload)
    logger.info("Additions exported: %d asset(s), state=%s", len(payload.assets), payload.state or "-")
    return Response(
        content=addition_report.to_xlsx(report),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="CY-Addition-Dep-Summary-{payload.tax_year}.xlsx"'
        },
    )
