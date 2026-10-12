"""Reference data for the dashboard, forms library and State Intelligence.

Read-only and thin: every value comes from ``services.reference_data`` (the
versioned JSON files) or ``services.state_intel_service``. The frontend
computes dates from these rules in the user's own time zone; nothing here
returns a date as a fact that the files do not state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import role_required
from app.core.config import Role
from app.core.errors import NotFoundError, ValidationError
from app.core.security import Principal
from app.core.tax_year import resolve_default_year
from app.services import reference_data, state_intel_service
from app.services.assistant import state_registry

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/calendar")
def calendar_rules(principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    """Legal holidays and federal due-date rules, with sources."""
    return {
        "holidays": reference_data.holidays().model_dump(mode="json"),
        "due_dates": reference_data.due_dates().model_dump(mode="json"),
    }


@router.get("/dashboard")
def dashboard_config(principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    return {
        "quick_links": reference_data.quick_links().model_dump(mode="json")["links"],
        "motivation": reference_data.motivation().model_dump(mode="json"),
        # The year the shared year selector opens on (``Settings.default_tax_year``,
        # clamped to the years the reference data covers).
        "default_tax_year": resolve_default_year(reference_data.SUPPORTED_YEARS),
        "supported_years": list(reference_data.SUPPORTED_YEARS),
    }


@router.get("/forms")
def forms(principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    """The whole library. It is small (~120 entries); search and filters run in the browser."""
    federal = reference_data.federal_forms()
    state = reference_data.state_forms()
    covered = sorted({f.state for f in state.forms if f.state})
    agencies = {
        j.code: {"name": j.name, "agency": j.agency.name, "agency_url": j.agency.url}
        for j in state_registry.JURISDICTIONS
        if j.kind in ("state", "district")
    }
    return {
        "version": federal.version,
        "categories": [c.model_dump() for c in federal.categories],
        "forms": [f.model_dump(mode="json") for f in federal.forms],
        "state_forms": [f.model_dump(mode="json") for f in state.forms],
        "states_with_forms": covered,
        "state_agencies": agencies,
        "supported_years": list(reference_data.SUPPORTED_YEARS),
    }


@router.get("/states")
def state_list(principal: Principal = role_required(Role.READONLY)) -> dict[str, Any]:
    return {
        "supported_years": list(reference_data.SUPPORTED_YEARS),
        "states": state_intel_service.jurisdictions(),
        "disclaimer": state_intel_service.DISCLAIMER,
    }


@router.get("/states/{code}")
def state_profile(
    code: str,
    year: int = Query(...),
    principal: Principal = role_required(Role.READONLY),
) -> dict[str, Any]:
    if year not in reference_data.SUPPORTED_YEARS:
        raise ValidationError(f"Tax year {year} is not covered. Supported: {list(reference_data.SUPPORTED_YEARS)}.")
    result = state_intel_service.profile(code, year)
    if result is None:
        raise NotFoundError(f"{code.upper()} is not a state this section covers.")
    return result
