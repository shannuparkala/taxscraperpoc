"""What each model call cost, recorded where it was made.

``GeminiService`` is the one gateway every model call goes through, and it
hands each call's usage - model, input, output, cached and thinking tokens, as
the API's own usage fields report them - to an ``LlmMeter``. The meter writes a
row to ``llm_calls`` in the caller's database session.

The caller's session, not a fresh one: the pipeline holds SQLite's write lock
for the length of a run, and a meter that opened its own transaction mid-stage
would wait on the very run it was metering.

**Which return, which stage.** The gateway cannot know, and threading two more
arguments through every call site is how one of them gets forgotten. So the
caller declares a scope once - the orchestrator per stage, the report route per
report, chat per session - and every call made inside it is attributed to it:

    with metered(workflow_id=workflow.id, stage="llm_extraction"):
        ...

**Prices** come from ``app/llm_prices.json``, never from code. Cost is fixed at
the moment of the call, with the price book's date beside it, so a later price
change does not silently re-price history. A model the book does not list is
recorded with no cost - "unpriced" - rather than an estimate: a made-up rate in
a cost report reads exactly like a measured one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = get_logger(__name__)

DEFAULT_PRICES_PATH = Path(__file__).resolve().parent.parent / "llm_prices.json"

STUB_SUFFIX = " (stub)"


# ------------------------------------------------------------------ scope


@dataclass(frozen=True, slots=True)
class MeterScope:
    """What the calls made inside a ``metered`` block are for."""

    workflow_id: str | None = None
    chat_session_id: str | None = None
    stage: str = ""


_SCOPE: ContextVar[MeterScope | None] = ContextVar("llm_meter_scope", default=None)


@contextmanager
def metered(
    *,
    workflow_id: str | None = None,
    chat_session_id: str | None = None,
    stage: str | None = None,
) -> Iterator[MeterScope]:
    """Attribute every model call inside this block. Nested scopes inherit."""
    outer = current_scope()
    scope = replace(
        outer,
        workflow_id=workflow_id if workflow_id is not None else outer.workflow_id,
        chat_session_id=(
            chat_session_id if chat_session_id is not None else outer.chat_session_id
        ),
        stage=stage if stage is not None else outer.stage,
    )
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def current_scope() -> MeterScope:
    return _SCOPE.get() or MeterScope()


# ----------------------------------------------------------------- prices


@dataclass(frozen=True, slots=True)
class Rate:
    input: Decimal
    output: Decimal
    cached_input: Decimal


@dataclass(frozen=True, slots=True)
class _Period:
    start: date | None
    end: date | None
    rate: Rate
    long_context_over: int | None = None
    long_context: Rate | None = None


def _rate(entry: Mapping[str, Any]) -> Rate:
    return Rate(
        input=Decimal(str(entry["input"])),
        output=Decimal(str(entry["output"])),
        cached_input=Decimal(str(entry.get("cached_input", entry["input"]))),
    )


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value else None


@dataclass(frozen=True, slots=True)
class PriceBook:
    """Token rates by model and date, as the price file states them."""

    models: Mapping[str, tuple[_Period, ...]]
    per_tokens: Decimal
    #: When the provider's page was last updated, for labelling every figure.
    as_of: str
    source: str
    currency: str = "USD"

    @classmethod
    def from_file(cls, path: Path) -> PriceBook:
        raw = json.loads(path.read_text(encoding="utf-8"))
        models: dict[str, tuple[_Period, ...]] = {}
        for name, periods in (raw.get("models") or {}).items():
            built = []
            for entry in periods:
                long = entry.get("long_context")
                built.append(
                    _Period(
                        start=_day(entry.get("from")),
                        end=_day(entry.get("to")),
                        rate=_rate(entry),
                        long_context_over=int(long["over_prompt_tokens"]) if long else None,
                        long_context=_rate(long) if long else None,
                    )
                )
            models[name] = tuple(built)
        return cls(
            models=models,
            per_tokens=Decimal(str(raw.get("per_tokens", 1_000_000))),
            as_of=str(raw.get("page_updated") or raw.get("retrieved") or ""),
            source=str(raw.get("source") or ""),
            currency=str(raw.get("currency") or "USD"),
        )

    def rate(self, model: str, *, on: date, prompt_tokens: int) -> Rate | None:
        for period in self.models.get(model, ()):
            if period.start is not None and on < period.start:
                continue
            if period.end is not None and on > period.end:
                continue
            if (
                period.long_context is not None
                and period.long_context_over is not None
                and prompt_tokens > period.long_context_over
            ):
                return period.long_context
            return period.rate
        return None

    def cost(
        self,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        thinking_tokens: int = 0,
        on: date,
    ) -> Decimal | None:
        """What one call cost, or None when the book has no rate for it.

        ``input_tokens`` is the API's prompt count, which *includes* the cached
        tokens; those are billed at the cached rate instead. Thinking tokens
        are billed as output.
        """
        if model.endswith(STUB_SUFFIX):
            return Decimal(0)  # an offline stub made no call
        rate = self.rate(model, on=on, prompt_tokens=input_tokens)
        if rate is None:
            return None
        cached = min(max(cached_tokens, 0), max(input_tokens, 0))
        fresh = max(input_tokens, 0) - cached
        billed = (
            Decimal(fresh) * rate.input
            + Decimal(cached) * rate.cached_input
            + Decimal(max(output_tokens, 0) + max(thinking_tokens, 0)) * rate.output
        )
        return billed / self.per_tokens


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> PriceBook:
    return PriceBook.from_file(Path(path))


def price_book(path: Path | None = None) -> PriceBook:
    """The price file, re-read when it changes on disk."""
    target = path or DEFAULT_PRICES_PATH
    return _load(str(target), target.stat().st_mtime)


# ------------------------------------------------------------------ usage


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """One call, as the API reported it."""

    model: str
    tier: str
    task: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thinking_tokens: int = 0
    latency_ms: int = 0
    stub: bool = False
    succeeded: bool = True
    streaming: bool = False


def usage_from_response(response: Any) -> tuple[int, int, int, int]:
    """(input, output, cached, thinking) from a response's ``usage_metadata``."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return (0, 0, 0, 0)

    def read(name: str) -> int:
        return int(getattr(usage, name, 0) or 0)

    return (
        read("prompt_token_count"),
        read("candidates_token_count"),
        read("cached_content_token_count"),
        read("thoughts_token_count"),
    )


class LlmMeter(Protocol):
    def record(self, usage: LlmUsage, scope: MeterScope | None = None) -> None: ...


class DbLlmMeter:
    """Writes one ``llm_calls`` row per call, in the caller's session."""

    def __init__(self, session: Session, *, prices_path: Path | None = None) -> None:
        self._session = session
        self._prices_path = prices_path

    def record(self, usage: LlmUsage, scope: MeterScope | None = None) -> None:
        """``scope`` overrides the ambient one - a stream is consumed after the
        block that started it has exited, so it carries its scope with it."""
        from app.models.database_models import LlmCall

        scope = scope or current_scope()
        now = datetime.now(UTC)
        try:
            book = price_book(self._prices_path)
            cost = book.cost(
                usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=usage.cached_tokens,
                thinking_tokens=usage.thinking_tokens,
                on=now.date(),
            )
            as_of = book.as_of
        except (OSError, ValueError, KeyError) as exc:
            # A broken price file must not break a model call; the row is
            # still written, unpriced, and the reason is logged.
            logger.warning("LLM price file unreadable: %s", type(exc).__name__)
            cost, as_of = None, ""

        # SECURITY: counts, names and ids only. No prompt, no reply.
        self._session.add(
            LlmCall(
                workflow_id=scope.workflow_id,
                chat_session_id=scope.chat_session_id,
                stage=scope.stage or usage.task,
                task=usage.task,
                model=usage.model,
                tier=usage.tier,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=usage.cached_tokens,
                thinking_tokens=usage.thinking_tokens,
                latency_ms=usage.latency_ms,
                stub=usage.stub,
                succeeded=usage.succeeded,
                streaming=usage.streaming,
                cost_usd=None if cost is None else str(cost),
                prices_as_of=as_of,
            )
        )
        self._session.flush()
