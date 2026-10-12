"""Versioned reference data: deadlines, holidays, forms, news sources, state intelligence.

Every tax fact the dashboard, forms library and state pages show lives in a
JSON file under ``app/reference_data/`` and is loaded through this module.
Each file is validated against a Pydantic schema on load, so a malformed
edit fails loudly in tests and at startup instead of rendering a blank
tile. Nothing here computes a date or a figure; the frontend's date engine
and the state pages only *read* what these files say.

Rule for editors (CLAUDE.md rules 8 and 9 apply here too): an entry without
``source_url`` and ``last_verified`` does not validate. A state field that
has not been verified for a year is *absent* for that year, which the UI
renders as "Not yet verified" - never another state's value or a guess.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

DATA_ROOT = Path(__file__).resolve().parents[1] / "reference_data"

#: Tax years the state intelligence pages and forms library offer.
SUPPORTED_YEARS: tuple[int, ...] = (2025, 2026)

ENTITY_KEYS = ("individual", "c_corp", "s_corp", "partnership", "trust_estate", "exempt_org")

#: The four State Intelligence sections stored per state. "conformity" is not
#: stored here: it is read from the depreciation calculator's table so the
#: two features cannot disagree.
STATE_SECTIONS = ("apportionment", "nexus", "rates", "filing")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------- calendar


class DueOffset(_Strict):
    """A due date as an offset from the end of the tax year, or a fixed day."""

    months_after_year_end: int | None = Field(default=None, ge=1, le=24)
    #: For a report due on a fixed calendar date in the year after the
    #: accounting year ends (Texas franchise tax).
    fixed_month: int | None = Field(default=None, ge=1, le=12)
    day: int | Literal["last"]

    @model_validator(mode="after")
    def _one_kind(self) -> DueOffset:
        if (self.months_after_year_end is None) == (self.fixed_month is None):
            raise ValueError("give exactly one of months_after_year_end or fixed_month")
        if isinstance(self.day, int) and not 1 <= self.day <= 31:
            raise ValueError("day must be 1-31 or 'last'")
        return self


class HolidayRule(_Strict):
    type: Literal["fixed", "nth_weekday"]
    month: int = Field(ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    weekday: int | None = Field(default=None, ge=0, le=6)  # 0 = Monday
    n: int | None = None  # 1..5, or -1 for last
    every_years: int | None = None
    base_year: int | None = None


class Holiday(_Strict):
    id: str
    name: str
    rule: HolidayRule
    observed: bool | Literal["sunday_only"]
    effective_from: int | None = None
    source_id: str
    note: str = ""


class SourceRef(_Strict):
    id: str
    title: str
    url: HttpUrl


class HolidayFile(BaseModel):
    version: str
    last_verified: date
    sources: list[SourceRef]
    observance: dict[str, str]
    holidays: list[Holiday]

    @model_validator(mode="after")
    def _sources_resolve(self) -> HolidayFile:
        ids = {s.id for s in self.sources}
        for h in self.holidays:
            if h.source_id not in ids:
                raise ValueError(f"holiday {h.id} cites unknown source {h.source_id}")
        return self


class EntityException(_Strict):
    id: str
    when: dict[str, Any]
    due: DueOffset
    extended_due: DueOffset
    note: str
    source_url: HttpUrl
    source_citation: str


class EntityRule(_Strict):
    key: str
    label: str
    return_form: str
    extension_form: str
    due: DueOffset
    extended_due: DueOffset
    exceptions: list[EntityException] = []
    source_url: HttpUrl
    source_citation: str
    extension_source_url: HttpUrl
    last_verified: date

    @field_validator("key")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in ENTITY_KEYS:
            raise ValueError(f"unknown entity type {value}")
        return value


class CountdownTile(_Strict):
    id: str
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    label: str
    represents: str
    entity_keys: list[str]
    form_numbers: list[str]


class DueDateFile(BaseModel):
    version: str
    last_verified: date
    entity_types: list[EntityRule]
    countdown_tiles: list[CountdownTile]
    countdown_note: str


# --------------------------------------------------------------- dashboard


class QuickLink(_Strict):
    id: str
    label: str
    description: str
    path: str
    icon: str


class QuickLinkFile(BaseModel):
    version: str
    links: list[QuickLink]


class MotivationFile(BaseModel):
    version: str
    deadline_window_days: int = Field(ge=0, le=60)
    general: list[str]
    deadline_season: list[str]


# ------------------------------------------------------------------ forms


class FormEntry(_Strict):
    id: str
    form_number: str
    title: str
    one_liner: str = Field(min_length=10, max_length=220)
    one_liner_reviewed: bool
    category: str
    audience: Literal["federal", "business", "state"]
    state: str | None
    state_form_kind: Literal["individual", "business", "extension"] | None = None
    tax_year: int | None = None
    annual: bool
    source_page_url: HttpUrl
    pdf_url: HttpUrl
    prior_year_pdf_pattern: str | None
    latest_revision: str | None
    last_verified: date | None
    link_status: Literal["ok", "broken", "host_refused_check"] | None = None
    verified_by: str | None = None

    @model_validator(mode="after")
    def _state_consistent(self) -> FormEntry:
        if (self.audience == "state") != (self.state is not None):
            raise ValueError(f"{self.id}: state forms need a state, others must not have one")
        return self


class FormCategory(_Strict):
    key: str
    label: str


class FederalFormsFile(BaseModel):
    version: str
    categories: list[FormCategory]
    forms: list[FormEntry]

    @model_validator(mode="after")
    def _categories_resolve(self) -> FederalFormsFile:
        keys = {c.key for c in self.categories}
        seen: set[str] = set()
        for form in self.forms:
            if form.category not in keys:
                raise ValueError(f"{form.id}: unknown category {form.category}")
            if form.id in seen:
                raise ValueError(f"duplicate form id {form.id}")
            seen.add(form.id)
        return self


class StateFormsFile(BaseModel):
    version: str
    forms: list[FormEntry]


# ------------------------------------------------------------------- news


class NewsSourceConfig(_Strict):
    key: str
    name: str
    kind: Literal["public", "licensed"]
    provider: Literal["irs_newsroom", "treasury_json", "licensed_api"]
    homepage: HttpUrl
    urls: list[str] = []
    terms_note: str
    #: Settings attribute names that must be set for a licensed source.
    requires_settings: list[str] = []
    connect_message: str = ""


class NewsTopic(_Strict):
    key: str
    label: str
    keywords: list[str]


class NewsSourcesFile(BaseModel):
    version: str
    sources: list[NewsSourceConfig]
    topics: list[NewsTopic]


# ----------------------------------------------------------- state intel


class StateField(_Strict):
    key: str
    label: str
    value: str = Field(min_length=3)
    years: list[int] = Field(min_length=1)
    source_url: HttpUrl
    source_citation: str = Field(min_length=3)
    last_verified: date
    #: "manual": a person read the source. "automated_page_match":
    #: scripts/research_state_intel fetched the state's own page and found the
    #: value's figures and evidence phrases on it; ``quote`` is the page text
    #: that matched, cut from the page by the script (never written by a model).
    verification: Literal["manual", "automated_page_match"] = "manual"
    quote: str | None = None


class DueRuleEntity(_Strict):
    form: str
    due: DueOffset
    extended_due: DueOffset
    june_30: dict[str, DueOffset] | None = None
    note: str = ""


class DueRules(_Strict):
    years: list[int]
    source_url: HttpUrl
    source_citation: str
    last_verified: date
    entities: dict[str, DueRuleEntity]

    @field_validator("entities")
    @classmethod
    def _known_entities(cls, value: dict[str, DueRuleEntity]) -> dict[str, DueRuleEntity]:
        unknown = set(value) - set(ENTITY_KEYS)
        if unknown:
            raise ValueError(f"unknown entity types {sorted(unknown)}")
        return value


class StateSection(_Strict):
    fields: list[StateField] = []
    due_rules: DueRules | None = None


class StateIntelFile(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{2}$")
    name: str
    sections: dict[str, StateSection]

    @field_validator("sections")
    @classmethod
    def _all_sections(cls, value: dict[str, StateSection]) -> dict[str, StateSection]:
        if set(value) != set(STATE_SECTIONS):
            raise ValueError(f"sections must be exactly {STATE_SECTIONS}")
        return value


# ---------------------------------------------------------------- loaders


def _read(relative: str) -> Any:
    return json.loads((DATA_ROOT / relative).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def holidays() -> HolidayFile:
    return HolidayFile.model_validate(_read("calendar/legal_holidays.json"))


@lru_cache(maxsize=1)
def due_dates() -> DueDateFile:
    return DueDateFile.model_validate(_read("calendar/federal_due_dates.json"))


@lru_cache(maxsize=1)
def quick_links() -> QuickLinkFile:
    return QuickLinkFile.model_validate(_read("dashboard/quick_links.json"))


@lru_cache(maxsize=1)
def motivation() -> MotivationFile:
    return MotivationFile.model_validate(_read("dashboard/motivation.json"))


@lru_cache(maxsize=1)
def federal_forms() -> FederalFormsFile:
    return FederalFormsFile.model_validate(_read("forms/federal_forms.json"))


@lru_cache(maxsize=1)
def state_forms() -> StateFormsFile:
    return StateFormsFile.model_validate(_read("forms/state_forms.json"))


@lru_cache(maxsize=1)
def news_sources() -> NewsSourcesFile:
    return NewsSourcesFile.model_validate(_read("news/sources.json"))


@lru_cache(maxsize=64)
def state_intel(code: str) -> StateIntelFile | None:
    path = DATA_ROOT / "state_intel" / "states" / f"{code.upper()}.json"
    if not path.exists():
        return None
    return StateIntelFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def state_intel_codes() -> list[str]:
    return sorted(p.stem for p in (DATA_ROOT / "state_intel" / "states").glob("*.json"))


def clear_caches() -> None:
    """For tests that rewrite a data file."""
    for loader in (holidays, due_dates, quick_links, motivation, federal_forms, state_forms, news_sources, state_intel):
        loader.cache_clear()
