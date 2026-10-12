"""HTTP: reference data, State Intelligence, clients, custom deadlines, updates.

No network: the news service is replaced with one whose fetcher is a fake.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.services import news_service


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def client_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Example Holdings LLC",
        "entity_type": "s_corp",
        "fiscal_year_end_month": 12,
        "states": ["ca", "NY"],
        "extension_status": "not_extended",
        "notes": "Invented test client",
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------- reference


def test_calendar_and_dashboard_reference_endpoints(client: TestClient) -> None:
    calendar = client.get("/api/reference/calendar").json()
    assert len(calendar["due_dates"]["countdown_tiles"]) == 4
    assert calendar["holidays"]["holidays"]
    dashboard = client.get("/api/reference/dashboard").json()
    assert dashboard["quick_links"][0]["path"].startswith("/")
    assert len(dashboard["motivation"]["general"]) > 30


def test_forms_endpoint_lists_state_agencies_for_the_fallback(client: TestClient) -> None:
    data = client.get("/api/reference/forms").json()
    assert len(data["forms"]) >= 60
    assert "CA" in data["states_with_forms"]
    assert "WY" not in data["states_with_forms"]
    assert data["state_agencies"]["WY"]["agency_url"].startswith("https://")
    assert "PR" not in data["state_agencies"], "territories are not in the State tab"


def test_state_profile_endpoint(client: TestClient) -> None:
    profile = client.get("/api/reference/states/ca", params={"year": 2026}).json()
    assert profile["code"] == "CA"
    assert client.get("/api/reference/states/CA", params={"year": 2019}).status_code == 422
    assert client.get("/api/reference/states/ZZ", params={"year": 2026}).status_code == 404
    listing = client.get("/api/reference/states").json()
    assert len(listing["states"]) == 51


def test_me_includes_a_first_name(client: TestClient) -> None:
    me = client.get("/api/auth/me").json()
    assert me["first_name"]


def test_the_development_login_is_greeted_by_its_configured_name(client: TestClient) -> None:
    """Not "Development", the first word of the seeded "Development User"."""
    assert client.get("/api/auth/me").json()["first_name"] == "Varun"


# ----------------------------------------------------------------- clients


def test_client_crud_round_trip(client: TestClient) -> None:
    created = client.post("/api/workspace/clients", json=client_body())
    assert created.status_code == 201
    row = created.json()
    assert row["states"] == ["CA", "NY"]
    assert client.get("/api/workspace/clients").json() == [row]

    updated = client.put(f"/api/workspace/clients/{row['id']}",
                         json=client_body(extension_status="extended", fiscal_year_end_month=6))
    assert updated.json()["extension_status"] == "extended"
    assert updated.json()["fiscal_year_end_month"] == 6

    assert client.delete(f"/api/workspace/clients/{row['id']}").status_code == 204
    assert client.get("/api/workspace/clients").json() == []
    assert client.put(f"/api/workspace/clients/{row['id']}", json=client_body()).status_code == 404


@pytest.mark.parametrize("bad", [
    {"entity_type": "llc_disregarded"},
    {"fiscal_year_end_month": 13},
    {"states": ["XX"]},
    {"name": ""},
    {"name": "Client 666-12-3456"},   # an SSN is refused, not stored
    {"name": "Client 00-1234567"},     # so is an EIN
    {"ssn": "666-12-3456"},            # and there is no field for one
])
def test_client_validation(client: TestClient, bad: dict[str, object]) -> None:
    assert client.post("/api/workspace/clients", json=client_body(**bad)).status_code == 422


def test_client_name_and_notes_are_encrypted_at_rest_and_not_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client.post("/api/workspace/clients", json=client_body(name="Zebulon Testcase", notes="Secret note"))
    from app.core.db import session_scope
    from app.models.database_models import WorkspaceClient

    with session_scope() as session:
        row = session.scalars(select(WorkspaceClient)).one()
        assert "Zebulon" not in row.name_encrypted
        assert "Secret" not in (row.notes_encrypted or "")
    assert "Zebulon" not in caplog.text
    assert "Secret note" not in caplog.text


def test_clients_are_scoped_to_their_owner(client: TestClient) -> None:
    row = client.post("/api/workspace/clients", json=client_body()).json()
    from app.core.db import session_scope
    from app.models.database_models import WorkspaceClient

    with session_scope() as session:
        session.get(WorkspaceClient, row["id"]).owner_id = "someone-else"
    assert client.get("/api/workspace/clients").json() == []
    assert client.delete(f"/api/workspace/clients/{row['id']}").status_code == 404


def test_custom_deadlines_crud_and_cascade(client: TestClient) -> None:
    owner = client.post("/api/workspace/clients", json=client_body()).json()
    made = client.post("/api/workspace/deadlines",
                       json={"title": "Send organizer", "due_date": "2027-01-20", "client_id": owner["id"], "kind": "task"})
    assert made.status_code == 201
    deadline = made.json()
    assert deadline["due_date"] == "2027-01-20"
    done = client.put(f"/api/workspace/deadlines/{deadline['id']}",
                      json={"title": "Send organizer", "due_date": "2027-01-21", "client_id": owner["id"],
                            "kind": "task", "done": True}).json()
    assert done["done"] is True and done["due_date"] == "2027-01-21"
    assert client.post("/api/workspace/deadlines",
                       json={"title": "x", "due_date": "2027-01-20", "client_id": "nope"}).status_code == 404
    client.delete(f"/api/workspace/clients/{owner['id']}")
    assert client.get("/api/workspace/deadlines").json() == []


# ----------------------------------------------------------------- updates


@pytest.fixture()
def fake_news(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEWS_ENABLED", "true")
    get_settings.cache_clear()

    payload = {"homepagePressReleases": [
        {"categorySlug": "press-releases", "date": "2026-10-06", "title": "Treasury proposes regulations",
         "url": "/news/press-releases/sb0651/", "description": "Proposed rule with 3 changes."},
    ]}

    def fetch(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        if url.startswith("https://home.treasury.gov/"):
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
        raise httpx.ConnectError("down")

    service = news_service.NewsService(get_settings(), fetch=fetch, today=lambda: date(2026, 10, 7))
    service.refresh_all(force=True)
    news_service.reset_news_service(service)
    yield service
    news_service.reset_news_service()
    get_settings.cache_clear()


def test_updates_feed_reports_each_source(client: TestClient, fake_news) -> None:
    data = client.get("/api/updates").json()
    assert [i["title"] for i in data["items"]] == ["Treasury proposes regulations"]
    states = {s["key"]: s["state"] for s in data["sources"]}
    assert states == {"irs": "error", "treasury": "ok", "bloomberg_tax": "not_connected",
                      "thomson_reuters": "not_connected"}
    assert data["last_updated"]
    assert client.get("/api/updates", params={"source": "irs"}).json()["items"] == []


def test_bookmarks(client: TestClient, fake_news) -> None:
    item = client.get("/api/updates").json()["items"][0]
    first = client.post("/api/updates/bookmarks", json={"item_id": item["id"]}).json()
    again = client.post("/api/updates/bookmarks", json={"item_id": item["id"]}).json()
    assert first["id"] == again["id"], "bookmarking twice keeps one row"
    assert [b["title"] for b in client.get("/api/updates/bookmarks").json()] == ["Treasury proposes regulations"]
    assert client.delete(f"/api/updates/bookmarks/{first['id']}").status_code == 204
    assert client.post("/api/updates/bookmarks", json={"item_id": "missing"}).status_code == 404


def test_summary_is_unavailable_without_gemini_and_still_links_the_original(client: TestClient, fake_news) -> None:
    item = client.get("/api/updates").json()["items"][0]
    summary = client.post(f"/api/updates/{item['id']}/summary").json()
    assert summary["available"] is False
    assert summary["label"] == "AI-generated summary"
    assert summary["source_url"] == item["url"]


def test_summary_number_check() -> None:
    from app.api.routes_updates import unsupported_numbers

    assert unsupported_numbers("Three changes were proposed.", "Proposed rule with 3 changes.") == set()
    assert unsupported_numbers("It saves $5,000.", "Proposed rule with 3 changes.") == {"5000"}
