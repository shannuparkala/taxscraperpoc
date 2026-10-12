"""Phase 5: every model call is metered, priced from the price file, and summed.

The price tests use the real ``app/llm_prices.json``: a rate typed wrongly into
it is exactly what they exist to catch. The gateway tests use a fake SDK client
so no call leaves the process.
"""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from app.models.enums import TaskKind
from app.services.llm_meter import (
    DEFAULT_PRICES_PATH,
    LlmUsage,
    MeterScope,
    PriceBook,
    current_scope,
    metered,
)

BOOK = PriceBook.from_file(DEFAULT_PRICES_PATH)
MILLION = 1_000_000
DAY = date(2026, 9, 23)


# ------------------------------------------------------------------ prices


def test_a_call_is_priced_from_the_file() -> None:
    cost = BOOK.cost(
        "gemini-3.5-flash-lite", input_tokens=MILLION, output_tokens=MILLION, on=DAY
    )
    assert cost == D("0.30") + D("2.50")


def test_cached_input_is_billed_at_the_cached_rate_and_thinking_as_output() -> None:
    cost = BOOK.cost(
        "gemini-3.5-flash-lite",
        input_tokens=MILLION,
        cached_tokens=MILLION // 2,
        output_tokens=0,
        thinking_tokens=MILLION,
        on=DAY,
    )
    assert cost == D("0.15") + D("0.015") + D("2.50")


def test_a_dated_price_change_applies_from_its_date() -> None:
    before = BOOK.cost("gemini-3.6-flash", input_tokens=MILLION, output_tokens=0, on=date(2026, 12, 31))
    after = BOOK.cost("gemini-3.6-flash", input_tokens=MILLION, output_tokens=0, on=date(2027, 1, 1))
    assert (before, after) == (D("0.75"), D("1.50"))


def test_a_long_prompt_takes_the_long_context_rate() -> None:
    short = BOOK.cost("gemini-3.1-pro-preview", input_tokens=200_000, output_tokens=0, on=DAY)
    long = BOOK.cost("gemini-3.1-pro-preview", input_tokens=200_001, output_tokens=0, on=DAY)
    assert short == D("0.4")
    assert long == D(200001) * D("4.00") / MILLION


def test_a_model_without_a_rate_is_unpriced_not_estimated() -> None:
    assert BOOK.cost("gemini-99-ultra", input_tokens=10, output_tokens=10, on=DAY) is None


def test_a_stub_made_no_call_and_costs_nothing() -> None:
    assert BOOK.cost("gemini-99-ultra (stub)", input_tokens=0, output_tokens=0, on=DAY) == 0


def test_every_model_the_app_can_route_to_has_a_price() -> None:
    """Adding a model to the config without a rate makes its spend invisible."""
    from app.core.config import Settings

    settings = Settings()
    for model in (
        settings.gemini_model_flash,
        settings.gemini_model_pro,
        settings.gemini_model_flash_lite,
    ):
        assert BOOK.rate(model, on=DAY, prompt_tokens=1) is not None, model


def test_the_price_file_says_where_its_rates_came_from() -> None:
    assert BOOK.source.startswith("https://")
    assert BOOK.as_of


# ------------------------------------------------------------------- scope


def test_scopes_nest_and_unwind() -> None:
    assert current_scope() == MeterScope()
    with metered(workflow_id="wf-1", stage="llm_processing"):
        with metered(stage="calculation_report"):
            assert current_scope() == MeterScope("wf-1", None, "calculation_report")
        assert current_scope().stage == "llm_processing"
    assert current_scope() == MeterScope()


# ----------------------------------------------------------------- gateway


@dataclass
class Usage:
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    cached_content_token_count: int = 0
    thoughts_token_count: int = 0


@dataclass
class Reply:
    text: str
    usage_metadata: Usage | None = None


@dataclass
class FakeModels:
    fail: bool = False
    stream_chunks: list[Reply] = field(default_factory=list)

    def generate_content(self, **_: Any) -> Reply:
        if self.fail:
            raise ValueError("invalid request")
        return Reply('{"ok": true}', Usage(1200, 300, 200, 50))

    def generate_content_stream(self, **_: Any) -> Iterator[Reply]:
        yield from self.stream_chunks


@dataclass
class FakeClient:
    models: FakeModels = field(default_factory=FakeModels)


@dataclass
class ListMeter:
    calls: list[tuple[LlmUsage, MeterScope | None]] = field(default_factory=list)
    broken: bool = False

    def record(self, usage: LlmUsage, scope: MeterScope | None = None) -> None:
        if self.broken:
            raise RuntimeError("ledger unavailable")
        self.calls.append((usage, scope or current_scope()))


def _service(meter: ListMeter, *, enabled: bool = True, models: FakeModels | None = None) -> Any:
    from app.core.config import Settings
    from app.services.gemini_service import GeminiService

    settings = Settings(
        gemini_enabled=enabled,
        gemini_api_key="test-key" if enabled else "",
        gemini_max_retries=1,
        gemini_rate_limit_max_retries=1,
    )
    service = GeminiService(settings=settings, meter=meter)
    if enabled:
        service._client = FakeClient(models or FakeModels())
    return service


def test_a_call_records_every_usage_field_the_api_reports() -> None:
    meter = ListMeter()
    with metered(workflow_id="wf-1", stage="llm_processing"):
        _service(meter).generate_json(prompt="{}", task=TaskKind.DOCUMENT_EXTRACTION)

    ((usage, scope),) = meter.calls
    assert (usage.input_tokens, usage.output_tokens, usage.cached_tokens, usage.thinking_tokens) == (
        1200, 300, 200, 50,
    )
    assert usage.task == "document_extraction" and usage.succeeded and not usage.stub
    assert scope == MeterScope("wf-1", None, "llm_processing")


def test_an_explicit_scope_beats_the_ambient_one() -> None:
    meter = ListMeter()
    with metered(workflow_id="wf-1", stage="llm_processing"):
        _service(meter).generate(
            prompt="x", task=TaskKind.CHAT_SIMPLE, meter_scope=MeterScope(chat_session_id="c-1", stage="chat")
        )
    assert meter.calls[0][1] == MeterScope(None, "c-1", "chat")


def test_a_failed_call_is_still_on_the_ledger() -> None:
    from app.services.gemini_service import LlmError

    meter = ListMeter()
    with pytest.raises(LlmError):
        _service(meter, models=FakeModels(fail=True)).generate(prompt="x", task=TaskKind.CHAT_SIMPLE)
    ((usage, _),) = meter.calls
    assert not usage.succeeded


def test_an_offline_stub_is_recorded_as_one() -> None:
    meter = ListMeter()
    _service(meter, enabled=False).generate(prompt="x", task=TaskKind.CHAT_SIMPLE)
    ((usage, _),) = meter.calls
    assert usage.stub and usage.model.endswith("(stub)")


def test_a_stream_is_metered_with_the_scope_it_started_in() -> None:
    """Chat streams are iterated after the request's scope has gone."""
    chunks = [Reply("Hel", Usage(900, 1)), Reply("lo", Usage(900, 4, 0, 7))]
    meter = ListMeter()
    service = _service(meter, models=FakeModels(stream_chunks=chunks))
    with metered(chat_session_id="c-1", stage="chat"):
        stream = service.generate_stream(prompt="x", task=TaskKind.CHAT_COMPLEX)
        first = next(stream)
    rest = list(stream)  # consumed outside the block

    assert first + "".join(rest) == "Hello"
    ((usage, scope),) = meter.calls
    assert (usage.input_tokens, usage.output_tokens, usage.thinking_tokens) == (900, 4, 7)
    assert usage.streaming and usage.succeeded
    assert scope == MeterScope(None, "c-1", "chat")


def test_a_stream_abandoned_early_is_still_metered() -> None:
    chunks = [Reply("a", Usage(10, 1)), Reply("b", Usage(10, 2))]
    meter = ListMeter()
    stream = _service(meter, models=FakeModels(stream_chunks=chunks)).generate_stream(
        prompt="x", task=TaskKind.CHAT_COMPLEX
    )
    next(stream)
    stream.close()
    ((usage, _),) = meter.calls
    assert usage.input_tokens == 10 and not usage.succeeded


def test_a_broken_ledger_never_costs_the_reply() -> None:
    reply = _service(ListMeter(broken=True)).generate_json(
        prompt="{}", task=TaskKind.DOCUMENT_EXTRACTION
    )
    assert reply.data == {"ok": True}


def test_every_production_client_is_metered() -> None:
    """A client built without a meter is spend nobody sees."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    unmetered: list[str] = []
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", "")) == "GeminiService"
                and "meter" not in {k.arg for k in node.keywords}
            ):
                unmetered.append(f"{path.relative_to(app_dir)}:{node.lineno}")
    assert not unmetered


# ------------------------------------------------------------------ ledger


@pytest.mark.security
def test_the_ledger_holds_counts_and_ids_never_content() -> None:
    from app.models.database_models import LlmCall

    assert set(LlmCall.__table__.columns.keys()) == {
        "id", "created_at", "workflow_id", "chat_session_id", "stage", "task",
        "model", "tier", "input_tokens", "output_tokens", "cached_tokens",
        "thinking_tokens", "latency_ms", "stub", "succeeded", "streaming",
        "cost_usd", "prices_as_of",
    }


def test_the_db_meter_prices_and_attributes_each_row(session: Any) -> None:
    from app.models.database_models import LlmCall
    from app.services.llm_meter import DbLlmMeter

    meter = DbLlmMeter(session)
    with metered(workflow_id="wf-9", stage="llm_processing"):
        meter.record(LlmUsage("gemini-3.5-flash-lite", "flash_lite", "document_extraction",
                              input_tokens=MILLION, output_tokens=0))
        meter.record(LlmUsage("gemini-99-ultra", "pro", "document_extraction", input_tokens=5))

    rows = {r.model: r for r in session.query(LlmCall).all()}
    assert D(rows["gemini-3.5-flash-lite"].cost_usd) == D("0.30")
    assert rows["gemini-3.5-flash-lite"].prices_as_of == BOOK.as_of
    assert rows["gemini-99-ultra"].cost_usd is None
    assert {r.workflow_id for r in rows.values()} == {"wf-9"}


def test_the_summary_splits_by_stage_and_model_and_counts_unpriced() -> None:
    from app.models.database_models import LlmCall
    from app.services.llm_cost_service import summarize

    def row(stage: str, model: str, cost: str | None) -> LlmCall:
        return LlmCall(stage=stage, task="t", model=model, tier="", input_tokens=10,
                       output_tokens=5, cached_tokens=0, thinking_tokens=0, latency_ms=1,
                       stub=False, succeeded=True, streaming=False, cost_usd=cost,
                       prices_as_of="2026-09-22")

    summary = summarize(
        "wf-1",
        [row("llm_processing", "a", "0.02"), row("llm_processing", "a", "0.01"),
         row("calculation_report", "b", None)],
        pages=10,
    )
    assert summary.total.cost_usd == D("0.03")
    assert summary.total.unpriced_calls == 1
    assert [b.key for b in summary.by_stage] == ["llm_processing", "calculation_report"]
    assert summary.cost_per_page == D("0.003")


def test_the_cost_route_reports_a_processed_return(client) -> None:  # type: ignore[no-untyped-def]
    """End to end with the model off: the extraction stage's stub calls are
    on the ledger, charged to the return and the stage, at zero cost."""
    from tests.test_security_invariants import SENSITIVE_DOCUMENT

    upload = client.post(
        "/api/files/upload",
        files={"file": ("w2.txt", io.BytesIO(SENSITIVE_DOCUMENT.encode()), "text/plain")},
    ).json()
    workflow = client.post(f"/api/workflows/{upload['id']}/process", json={"tax_year": 2025}).json()

    cost = client.get(f"/api/workflows/{workflow['id']}/cost").json()
    assert cost["total"]["calls"] >= 1
    assert cost["total"]["stub_calls"] == cost["total"]["calls"]
    assert D(cost["total"]["cost_usd"]) == 0
    assert [b["key"] for b in cost["by_stage"]] == ["llm_processing"]
    assert cost["prices_source"].startswith("https://")


def test_the_cost_report_script_ranks_savings_by_spend(session: Any) -> None:
    """``/cost-report``'s script, on a ledger of invented calls."""
    from app.models.database_models import LlmCall
    from scripts.cost_report import as_dict, build

    def call(workflow: str | None, chat: str | None, stage: str, tier: str,
             tokens_in: int, cost: str | None) -> LlmCall:
        return LlmCall(workflow_id=workflow, chat_session_id=chat, stage=stage, task="t",
                       model="gemini-3.5-flash-lite", tier=tier, input_tokens=tokens_in,
                       output_tokens=100, cached_tokens=0, thinking_tokens=0, latency_ms=1,
                       stub=False, succeeded=True, streaming=False, cost_usd=cost,
                       prices_as_of="2026-09-22")

    session.add_all([
        call("wf-a", None, "llm_processing", "flash_lite", 900_000, "0.30"),
        call("wf-b", None, "llm_processing", "pro", 100_000, "0.10"),
        call(None, "chat-1", "chat", "flash", 10_000, "0.01"),
        call(None, None, "classification", "flash_lite", 10, None),
    ])
    session.commit()

    body = as_dict(build(None))
    assert body["overall"]["calls"] == 4
    assert body["overall"]["unpriced_calls"] == 1
    assert body["returns"]["count"] == 2
    assert body["returns"]["cost_usd"]["max"] == "0.30"
    assert body["chats"]["count"] == 1
    assert body["unattributed"]["calls"] == 1
    # Largest first, and every idea says what it risks.
    ideas = body["savings"]
    assert ideas and all(idea["risk"] for idea in ideas)
    assert "Crop each page" in ideas[0]["idea"]
