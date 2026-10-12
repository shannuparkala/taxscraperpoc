"""State Intelligence: one state's profile for one tax year, from versioned data only.

Five sections. Four (apportionment, nexus, rates, filing) come from
``reference_data/state_intel/states/<CODE>.json``; **Federal Conformity**
comes from the depreciation calculator's ``state_conformity.json`` so the
two features share one source of truth and cannot disagree.

SECURITY/correctness - the rule this module exists to keep (CLAUDE.md rule 7):
a field shows for a year only if that state's own file lists the year on the
field. Otherwise the section says "Not yet verified" and links the agency.
Nothing is borrowed from another state, from another year, or from a model.
"""

from __future__ import annotations

from typing import Any

from app.services import reference_data
from app.services.assistant import state_registry
from app.services.depreciation.rules import get_rules
from app.services.reference_data import STATE_SECTIONS, SUPPORTED_YEARS

NOT_VERIFIED = "Not yet verified"
DISCLAIMER = (
    "General information only, not tax advice. Each figure shows its source and the date it was "
    "last checked; confirm against the agency before relying on it."
)

SECTION_ORDER = ("apportionment", "nexus", "conformity", "rates", "filing")
SECTION_LABELS = {
    "apportionment": "Apportionment",
    "nexus": "Nexus",
    "conformity": "Federal Conformity",
    "rates": "Tax Rates",
    "filing": "Filing Requirements",
}

_CONFORMITY_TYPES = {
    "rolling": "Rolling conformity (follows the Internal Revenue Code as currently amended)",
    "fixed": "Fixed-date (static) conformity",
    "static": "Fixed-date (static) conformity",
    "selective": "Selective conformity (adopts specific Code provisions)",
    "n/a": "Not applicable",
    "unknown": "Not determined",
}
_BONUS_MODES = {
    "follow": "Follows federal bonus depreciation",
    "none": "Decouples from federal bonus depreciation (no bonus allowed)",
    "percent": "Allows a percentage of federal bonus depreciation",
    "addback": "Adds back federal bonus and recovers it over later years",
    "not_applicable": "Not applicable",
    "unknown": "Not determined",
}
_179_MODES = {
    "follow": "Follows the federal Section 179 limits",
    "own": "Uses its own Section 179 limits",
    "addback": "Adds back part of federal Section 179",
    "not_applicable": "Not applicable",
    "unknown": "Not determined",
}


def jurisdictions() -> list[dict[str, Any]]:
    """Every state with a State Intelligence file, with per-year coverage counts."""
    out = []
    for code in reference_data.state_intel_codes():
        data = reference_data.state_intel(code)
        if data is None:
            continue
        coverage = {}
        for year in SUPPORTED_YEARS:
            verified = sum(
                1 for name in STATE_SECTIONS for f in data.sections[name].fields if year in f.years
            )
            conformity = _conformity_entry(code, year)
            coverage[year] = {
                "verified_fields": verified,
                "conformity_verified": conformity_is_verified(conformity),
            }
        out.append({"code": code, "name": data.name, "coverage": coverage})
    return out


def conformity_is_verified(entry: dict[str, Any] | None) -> bool:
    """Verified, or no-income-tax, *and* dated. An undated entry was left open on purpose."""
    return bool(entry and entry.get("status") in ("verified", "no_income_tax") and entry.get("last_verified"))


def _conformity_entry(code: str, year: int) -> dict[str, Any] | None:
    try:
        return get_rules().state_entry(code, year)
    except Exception:  # noqa: BLE001 - a missing rule file must not take down the page
        return None


def _agency(code: str) -> dict[str, str]:
    j = state_registry.get(code)
    if j is None:
        return {"name": "", "url": ""}
    return {"name": j.agency.name, "url": j.agency.url}


def _section(name: str, fields: list[reference_data.StateField], year: int, agency: dict[str, str]) -> dict[str, Any]:
    shown = [
        {
            "key": f.key,
            "label": f.label,
            "value": f.value,
            "source_url": str(f.source_url),
            "source_citation": f.source_citation,
            "last_verified": f.last_verified.isoformat(),
            "verification": f.verification,
            "quote": f.quote,
        }
        for f in fields
        if year in f.years
    ]
    return {
        "key": name,
        "label": SECTION_LABELS[name],
        "status": "verified" if shown else "not_verified",
        "message": "" if shown else f"{NOT_VERIFIED} for {year}. Check the agency directly.",
        "as_of": max((f["last_verified"] for f in shown), default=None),
        "fields": shown,
        "agency": agency,
    }


def conformity_section(code: str, year: int, agency: dict[str, str]) -> dict[str, Any]:
    """Federal Conformity, read from the depreciation calculator's own table."""
    entry = _conformity_entry(code, year)
    base = {"key": "conformity", "label": SECTION_LABELS["conformity"], "agency": agency,
            "shared_with": "depreciation_calculator"}
    verified = conformity_is_verified(entry)
    # An entry the researcher read at the state's own source but did not sign
    # off is shown as *provisional* - labelled, with its source - rather than
    # hidden: the content is the state's own, only the confirmation is missing.
    # The calculator makes the same distinction (its "provisional" estimate).
    provisional = entry is not None and not verified and bool(entry.get("source_url")) and bool(entry.get("summary"))
    if entry is None or not (verified or provisional):
        return {**base, "status": "not_verified",
                "message": f"{NOT_VERIFIED} for {year}. Check the agency directly.",
                "as_of": None, "fields": []}

    def field(key: str, label: str, value: str) -> dict[str, Any]:
        return {"key": key, "label": label, "value": value, "source_url": entry["source_url"],
                "source_citation": entry["source_citation"],
                "last_verified": entry.get("last_verified") or entry.get("research_date"),
                "verification": "manual" if verified else "provisional", "quote": None}

    conformity = entry.get("conformity") or {}
    fields = [
        field("type", "Conformity type",
              _CONFORMITY_TYPES.get(str(conformity.get("type")), str(conformity.get("type") or "Not stated"))),
    ]
    if conformity.get("date"):
        fields.append(field("date", "Conformity date (IRC as of)", str(conformity["date"])))
    if entry.get("status") != "no_income_tax":
        bonus_mode = (entry.get("bonus") or {}).get("mode", "")
        fields.append(field("bonus", "Bonus depreciation (Section 168(k))", _BONUS_MODES.get(bonus_mode, bonus_mode)))
        s179 = entry.get("section_179") or {}
        s179_text = _179_MODES.get(s179.get("mode", ""), s179.get("mode", ""))
        if s179.get("mode") == "own" and s179.get("limit"):
            s179_text += f": limit ${int(s179['limit']):,}"
            if s179.get("phaseout_threshold"):
                s179_text += f", phase-out from ${int(s179['phaseout_threshold']):,}"
        fields.append(field("section_179", "Section 179", s179_text))
        if entry.get("decouples_168n") is not None:
            fields.append(field("168n", "Section 168(n) qualified production property",
                                "Decouples" if entry["decouples_168n"] else "Follows federal"))
    fields.append(field("summary", "Summary", entry.get("summary", "")))
    if entry.get("change_note"):
        fields.append(field("recent_change", "Recent change", entry["change_note"]))
    fields.append(field(
        "not_tracked", "Section 163(j) and Section 174",
        "Not tracked in the shared conformity table yet - check the agency or ask the assistant.",
    ))
    if provisional:
        note = entry.get("verify_note") or ""
        return {**base, "status": "provisional",
                "message": (f"Researched from {code}'s own source on {entry.get('research_date')} but not yet confirmed "
                            f"for {year}. Treat it as a lead and check the source. {note}").strip(),
                "as_of": entry.get("research_date"), "fields": fields}
    return {**base, "status": "verified", "message": "", "as_of": entry.get("last_verified"), "fields": fields}


def profile(code: str, year: int) -> dict[str, Any] | None:
    code = code.upper()
    data = reference_data.state_intel(code)
    if data is None or year not in SUPPORTED_YEARS:
        return None
    agency = _agency(code)
    jurisdiction = state_registry.get(code)
    sections = {name: _section(name, data.sections[name].fields, year, agency) for name in STATE_SECTIONS}
    sections["conformity"] = conformity_section(code, year, agency)
    due_rules = data.sections["filing"].due_rules
    return {
        "code": code,
        "name": data.name,
        "tax_year": year,
        "supported_years": list(SUPPORTED_YEARS),
        "agency": agency,
        # Structural features from the assistant's registry - never figures.
        "quick_facts": jurisdiction.feature_labels if jurisdiction else [],
        "sections": [sections[name] for name in SECTION_ORDER],
        "due_rules": (
            due_rules.model_dump(mode="json") if due_rules and year in due_rules.years else None
        ),
        "disclaimer": DISCLAIMER,
    }
