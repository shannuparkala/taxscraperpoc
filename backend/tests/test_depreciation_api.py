"""Depreciation HTTP API, exports, tape and the grounded explanation.

Gemini is faked. No test makes a network call.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from decimal import Decimal as D
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.depreciation.engine import AssetInput, CalculationInput
from app.services.depreciation.explanation import (
    DepreciationExplainer,
    facts_for,
    unsupported_numbers,
)
from app.services.depreciation.exports import schedule_rows, to_csv, to_pdf
from app.services.depreciation.service import calculate
from app.services.gemini_service import (
    Grounding,
    GroundingSource,
    GroundingSupport,
    LlmResponse,
)


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def body(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tax_year": 2026,
        "state": "CA",
        "method": "bonus",
        "assets": [{
            "id": "a1", "description": "Client laptop for Jane Example", "asset_class": "computers",
            "cost": "100000", "placed_in_service": "2026-03-01", "acquired": "2026-02-01",
        }],
    }
    payload.update(overrides)
    return payload


# --- API ---------------------------------------------------------------------------

def test_rules_endpoint_lists_51_jurisdictions_and_supported_years(client: TestClient) -> None:
    data = client.get("/api/depreciation/rules").json()
    assert len(data["states"]) == 51
    assert data["supported_years"] == [2021, 2022, 2023, 2024, 2025, 2026]
    assert all(c["source"]["source_url"] for c in data["asset_classes"])


def test_calculate_returns_schedule_tape_and_sources(client: TestClient) -> None:
    data = client.post("/api/depreciation/calculate", json=body()).json()
    assert data["federal"]["tax_year_deduction"] == "100000"
    assert data["state"]["code"] == "CA" and data["state"]["status"] == "computed"
    assert data["tape"] and data["assets"][0]["tape"]
    assert data["sources"] and all(s["source_citation"] for s in data["sources"])
    assert "not tax advice" in data["disclaimer"]


def test_changing_the_tax_year_recalculates(client: TestClient) -> None:
    payload_2025 = body(method="macrs", state=None, tax_year=2025)
    payload_2025["assets"][0].update(placed_in_service="2025-03-01", acquired="2025-02-01")
    payload_next = {**payload_2025, "tax_year": 2026}
    assert client.post("/api/depreciation/calculate", json=payload_2025).json()["federal"]["tax_year_deduction"] == "20000"
    assert client.post("/api/depreciation/calculate", json=payload_next).json()["federal"]["tax_year_deduction"] == "32000"


@pytest.mark.parametrize("code", ["PR", "ZZ", "California", "C"])
def test_invalid_or_unsupported_state_codes_are_rejected(client: TestClient, code: str) -> None:
    response = client.post("/api/depreciation/calculate", json=body(state=code))
    assert response.status_code == 422


def test_unsupported_year_is_a_clear_422(client: TestClient) -> None:
    payload = body(tax_year=2019)
    payload["assets"][0].update(placed_in_service="2019-03-01", acquired="2019-02-01")
    response = client.post("/api/depreciation/calculate", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_tax_year"
    assert "2021-2026" in response.json()["error"]["message"]


def test_input_errors_come_back_field_by_field(client: TestClient) -> None:
    payload = body()
    payload["assets"][0]["acquired"] = "2026-06-01"
    response = client.post("/api/depreciation/calculate", json=payload)
    assert response.status_code == 422
    assert any("acquisition date" in e for e in response.json()["error"]["details"]["errors"])


@pytest.mark.parametrize("code", ["AL", "CA", "CT", "DC", "FL", "MN", "NC", "NY", "OH", "TX", "WA", "WY"])
def test_each_selected_state_routes_to_its_own_rules(client: TestClient, code: str) -> None:
    state = client.post("/api/depreciation/calculate", json=body(state=code)).json()["state"]
    assert state["code"] == code
    assert state["status"] in ("computed", "provisional", "not_verified", "no_income_tax")
    if state["status"] == "not_verified":
        assert "State rules not yet verified for this year" in state["message"]
        assert state["rows"] == []  # no other state's rules, no federal relabelled as state
    if state["status"] == "no_income_tax":
        assert "no individual income tax" in state["message"]


def test_an_unverified_state_shows_the_fallback_and_the_federal_result_still_stands(client: TestClient) -> None:
    data = client.post("/api/depreciation/calculate", json=body(state="NY")).json()  # NY: researched, unverified
    assert data["state"]["status"] == "not_verified"
    assert data["federal"]["tax_year_deduction"] == "100000"
    provisional = client.post("/api/depreciation/calculate", json=body(state="NY", include_provisional_state=True)).json()
    assert provisional["state"]["status"] == "provisional"
    assert provisional["state"]["message"].startswith("Provisional")


def test_amounts_are_never_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    payload = body()
    payload["assets"][0]["cost"] = "987654"
    client.post("/api/depreciation/calculate", json=payload)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "987654" not in text and "987,654" not in text
    assert "Jane Example" not in text


# --- Exports match the screen ------------------------------------------------------

def _result(**kwargs: Any) -> dict[str, Any]:
    a = AssetInput(id="a", description="Van", asset_class="heavy_vehicle", cost=D(100000),
                   placed_in_service=date(2023, 12, 28), acquired=date(2023, 12, 1))
    return calculate(CalculationInput(tax_year=2025, assets=(a,), method="section_179_bonus", **kwargs))


def test_csv_export_matches_the_on_screen_schedule() -> None:
    result = _result(state="CA", include_provisional_state=True)
    rows = list(csv.reader(io.StringIO(to_csv(result))))
    header = rows.index(next(r for r in rows if r and r[0] == "Year"))
    exported = rows[header + 1: header + 1 + len(result["federal"]["schedule"])]
    for line, screen in zip(exported, result["federal"]["schedule"]):
        assert int(line[0]) == screen["year"]
        assert line[5] == screen["total"]
    assert schedule_rows(result)[0]["federal_total"] == result["federal"]["schedule"][0]["total"]


def test_pdf_export_contains_the_same_totals() -> None:
    import fitz  # type: ignore[import-untyped]

    result = _result()
    pdf = fitz.open(stream=to_pdf(result), filetype="pdf")
    text = "".join(page.get_text() for page in pdf)
    assert "Depreciation schedule - tax year 2025" in text
    for row in result["federal"]["schedule"]:
        assert f"${int(row['total']):,}" in text
    assert "not tax advice" in text


def test_export_endpoints_return_files(client: TestClient) -> None:
    csv_response = client.post("/api/depreciation/export/csv", json=body())
    assert csv_response.status_code == 200 and csv_response.headers["content-type"].startswith("text/csv")
    pdf_response = client.post("/api/depreciation/export/pdf", json=body())
    assert pdf_response.status_code == 200 and pdf_response.content.startswith(b"%PDF")


# --- Calculation tape -------------------------------------------------------------

def test_tape_totals_are_the_engines_numbers() -> None:
    result = _result()
    tape = result["assets"][0]["tape"]
    titled = {section["title"]: section for section in tape}
    year_section = titled["2025 deduction"]
    assert year_section["lines"][-1]["value"] == result["assets"][0]["tax_year_deduction"]
    assert year_section["lines"][-1]["emphasis"] and year_section["lines"][-1]["op"] == "T"
    ending = titled["Ending values 12/31/25"]["lines"][-1]
    assert ending["value"] == result["summary"]["ending_nbv"]["value"]
    assert result["summary"]["current_year"]["value"] == result["federal"]["tax_year_deduction"]


def test_year_rows_carry_rate_cumulative_remaining_and_why() -> None:
    rows = _result()["assets"][0]["schedule"]
    assert rows[2]["rate"] == "22.80"          # Table A-5, 5-year, year 3
    assert rows[-1]["remaining"] == "0"
    assert int(rows[-1]["cumulative"]) == 100000
    assert any("22.8%" in line for line in rows[2]["why"])


# --- Explanation -------------------------------------------------------------------

class FakeGemini:
    enabled = True

    def __init__(self, replies: list[LlmResponse]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def generate(self, *, prompt: str, **kwargs: Any) -> LlmResponse:
        self.prompts.append(prompt)
        assert kwargs["google_search"] is True
        return self.replies.pop(0)


GROUNDED = Grounding(
    sources=[GroundingSource("https://www.irs.gov/publications/p946", "irs.gov")],
    supports=[GroundingSupport("Bonus depreciation lets you deduct the cost in the first year.", [0])],
)


def _reply(text: str, grounding: Grounding = GROUNDED) -> LlmResponse:
    return LlmResponse(text=text, grounding=grounding)


def test_explanation_is_grounded_and_uses_only_computed_numbers() -> None:
    result = calculate(CalculationInput(tax_year=2026, assets=(AssetInput(
        id="a", description="Laptop for Jane Example", asset_class="computers", cost=D(100000),
        placed_in_service=date(2026, 3, 1), acquired=date(2026, 2, 1)),), method="bonus"))
    gemini = FakeGemini([_reply(
        "Bonus depreciation lets you deduct the cost in the first year. Your deduction is $100,000 at a 100% rate. "
        "This is general information, not tax advice.")])
    out = DepreciationExplainer(gemini, get_settings()).explain(result)
    assert out["text"] and out["citations"][0]["url"] == "https://www.irs.gov/publications/p946"
    assert "[1]" in out["text"]
    # The user's free text never reaches the model.
    assert "Jane Example" not in gemini.prompts[0] and "Laptop" not in gemini.prompts[0]


def test_an_explanation_that_invents_a_number_is_withheld() -> None:
    result = _result()
    invented = _reply("Your deduction is $12,345, about 7% of cost.")
    gemini = FakeGemini([invented, _reply("Your deduction is $999,999.")])
    out = DepreciationExplainer(gemini, get_settings()).explain(result)
    assert out["text"] == ""
    assert "did not produce" in out["reason"]
    assert len(gemini.prompts) == 2  # regenerated once, then withheld


def test_an_ungrounded_explanation_is_withheld() -> None:
    result = _result()
    gemini = FakeGemini([_reply("Depreciation spreads cost over time.", Grounding())] * 2)
    out = DepreciationExplainer(gemini, get_settings()).explain(result)
    assert out["text"] == "" and "sources" in out["reason"]


def test_unsupported_numbers_detects_only_new_figures() -> None:
    facts = '{"a": "$3,242", "b": "22.8%"}'
    assert unsupported_numbers("You deduct $3,242 at 22.8%.", facts) == []
    assert unsupported_numbers("You deduct $3,243.", facts) == ["$3243"]


def test_explanation_facts_exclude_descriptions() -> None:
    facts = facts_for(_result())
    assert "Van" not in str(facts)


def test_explanation_endpoint_says_unavailable_without_gemini(client: TestClient) -> None:
    data = client.post("/api/depreciation/explain", json=body()).json()
    assert data["available"] is False and data["text"] == ""
