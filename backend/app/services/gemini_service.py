"""Gemini client abstraction.

Every LLM call in the platform goes through this service. That is deliberate:
it gives exactly one place to enforce the egress guard, one place to record
audit events, and one seam at which to swap providers.

Three behaviours worth knowing:

* **Offline by default when unconfigured.** With no API key, or with
  ``GEMINI_ENABLED=false``, the service returns deterministic stubs instead of
  failing. The whole application — pipeline, chatbot, tests — runs without a
  key, which keeps CI hermetic and makes the demo path reliable.
* **Egress guard before every send.** ``EgressGuard.assert_safe`` inspects the
  serialized request. In ``block`` mode a finding raises and nothing is sent.
* **Structured output.** ``generate_json`` requests JSON, then parses
  defensively — models emit fenced code blocks and trailing prose often enough
  that naive ``json.loads`` is a reliability bug.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlparse

from app.core.audit import AuditAction, AuditLogger
from app.core.config import Settings, get_settings
from app.core.errors import LlmError
from app.core.logging import get_logger
from app.models.enums import ModelTier, TaskKind
from app.services.llm_egress_guard import EgressGuard
from app.services.llm_meter import (
    STUB_SUFFIX,
    LlmMeter,
    LlmUsage,
    MeterScope,
    current_scope,
    usage_from_response,
)
from app.services.model_router import ModelRouter, RoutingDecision, RoutingSignals

logger = get_logger(__name__)

#: How long to stay on stubs after the client fails to initialise, before
#: trying again. Long enough not to hammer a genuinely broken dependency,
#: short enough that fixing the environment takes effect without a restart.
_CLIENT_RETRY_SECONDS = 60.0

#: First backoff interval, and the ceiling a doubled one is clamped to. A model
#: overload clears in tens of seconds, not in one; the previous 1s/2s pair was
#: short enough that three attempts finished inside the same outage.
_BACKOFF_BASE_SECONDS = 2.0
_BACKOFF_CAP_SECONDS = 30.0

#: Rate limiting is not overload and must not share its backoff. A per-minute
#: quota window is 60 seconds wide, so the overload curve — ~1s, ~3s, ~6s —
#: spends its whole attempt budget inside the window that is rejecting it and
#: reports the provider as unavailable. These wait for the window to turn over.
_RATE_LIMIT_BACKOFF_BASE_SECONDS = 20.0
_RATE_LIMIT_BACKOFF_CAP_SECONDS = 75.0

#: How long to keep spacing calls out after a rate limit, and by how much.
#: Extraction runs one call per classified document back to back, so a dozen
#: documents can exhaust a free-tier minute in seconds. Pacing engages only
#: after the provider has actually complained, which leaves a key with real
#: quota running at full speed.
_ADAPTIVE_PACING_SECONDS = 6.0
_ADAPTIVE_PACING_DECAY_SECONDS = 180.0

#: HTTP statuses where a later attempt could plausibly succeed: the provider's
#: own faults, plus rate limiting.
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})

_RATE_LIMITED_STATUS = 429

#: ``retryDelay: "24s"`` inside a google.rpc.RetryInfo detail. Quotes are
#: optional because the detail reaches us as a repr, not as raw JSON.
_RETRY_DELAY_RE = re.compile(
    r"""["']?retry_?delay["']?\s*:\s*["']?(\d+(?:\.\d+)?)s""", re.IGNORECASE
)

#: Google names its quota metrics with the window in the identifier. Matching
#: on the window alone keeps provider text out of anything we store or log.
#: Deliberately narrow: mistaking a per-minute limit for a daily one tells the
#: reviewer to come back tomorrow for something that clears in a minute.
_DAILY_QUOTA_RE = re.compile(r"per[\s_-]*day|daily", re.IGNORECASE)

#: Transport and SDK failures that carry no status code but are still worth
#: another attempt. Matched by class name so this module stays importable when
#: google-genai is absent — the offline stub path must not depend on the SDK.
_TRANSIENT_ERROR_NAMES = frozenset(
    {
        "ServerError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ReadError",
        "RemoteProtocolError",
        "TimeoutError",
        "TimeoutException",
        "ConnectionError",
        "ConnectionResetError",
        "SSLError",
    }
)

#: Strips ```json fences the model sometimes wraps output in.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _status_code_of(exc: BaseException) -> int | None:
    """The HTTP status behind an SDK exception, when it exposes one."""
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    value = getattr(getattr(exc, "response", None), "status_code", None)
    return value if isinstance(value, int) else None


def _is_transient(exc: BaseException) -> bool:
    """Whether another attempt could plausibly succeed.

    Retrying everything is its own bug: a 400 means the request is malformed
    and will be malformed on every further attempt, so the retries only delay
    the review item by the length of the backoff while the log implies the
    provider was at fault. Only the provider's own failures are worth repeating.
    """
    status = _status_code_of(exc)
    if status is not None:
        return status in _TRANSIENT_STATUS_CODES
    causes = (exc, exc.__cause__, exc.__context__)
    return any(
        type(cause).__name__ in _TRANSIENT_ERROR_NAMES
        for cause in causes
        if cause is not None
    )


def _describe(exc: BaseException) -> str:
    """An identifier for logs and audit. SECURITY: never the message body —
    a provider error can echo the request, and the request is masked client
    data we do not want copied into a log line."""
    status = _status_code_of(exc)
    name = type(exc).__name__
    return f"{name} HTTP {status}" if status is not None else name


def _is_rate_limited(exc: BaseException) -> bool:
    return _status_code_of(exc) == _RATE_LIMITED_STATUS


def _error_metadata(exc: BaseException) -> str:
    """The provider's structured error detail, as one searchable string.

    SECURITY: the return value is consumed only by the regexes below and is
    never logged, audited or surfaced. A provider error can quote the request
    back, and the request is masked client data.
    """
    parts: list[str] = []
    for attribute in ("details", "status", "reason"):
        value = getattr(exc, attribute, None)
        if value is not None:
            parts.append(repr(value))
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        parts.append(repr(headers))
    return " ".join(parts)


def _retry_after_seconds(exc: BaseException) -> float | None:
    """How long the provider asked us to wait, when it said so.

    Guessing a backoff against a quota we cannot see is strictly worse than
    using the number the provider already sent. Gemini returns it as a
    ``RetryInfo`` detail; proxies in front of it use a ``Retry-After`` header.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None)
    getter = getattr(headers, "get", None)
    if callable(getter):
        # httpx folds header case; a plain dict does not.
        raw = getter("retry-after") or getter("Retry-After")
        if raw is not None:
            try:
                return max(0.0, float(str(raw).strip()))
            except ValueError:
                pass  # HTTP-date form; fall through to the structured detail

    match = _RETRY_DELAY_RE.search(_error_metadata(exc))
    return float(match.group(1)) if match else None


def _quota_scope(exc: BaseException) -> str | None:
    """``"daily"``, ``"short_window"`` or ``None`` for a rate-limited call.

    The two are the same status code and a completely different instruction to
    the reviewer. A per-minute limit clears while they read the message; a
    per-day one will reject every re-run until midnight Pacific, and telling
    them to "re-run the workflow" wastes the rest of their afternoon.
    """
    if not _is_rate_limited(exc):
        return None
    return "daily" if _DAILY_QUOTA_RE.search(_error_metadata(exc)) else "short_window"


@dataclass(slots=True)
class GroundingSource:
    """One web source Google Search grounding returned for a call."""

    url: str
    title: str


@dataclass(slots=True)
class GroundingSupport:
    """A span of the model's output and the sources Google says support it.

    ``text`` is the supported span exactly as it appears in the raw output,
    so for a JSON response it is a slice of the JSON text, escapes included.
    """

    text: str
    source_indices: list[int] = field(default_factory=list)


@dataclass(slots=True)
class Grounding:
    """What Google Search grounding actually returned - nothing inferred."""

    sources: list[GroundingSource] = field(default_factory=list)
    supports: list[GroundingSupport] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    #: Google's rendered "Search suggestions" chip. Its terms of service
    #: require showing it alongside a grounded answer.
    search_suggestions_html: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.sources


@dataclass(slots=True)
class LlmResponse:
    """Result of one model call."""

    text: str
    data: dict[str, Any] = field(default_factory=dict)
    model_name: str = ""
    tier: ModelTier = ModelTier.FLASH
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: True when produced by the offline stub rather than a real call.
    is_stub: bool = False
    routing_reason: str = ""
    #: Set on calls made with ``google_search=True``; empty when the model
    #: answered without searching, which callers must treat as ungrounded.
    grounding: Grounding = field(default_factory=Grounding)

    def usage_dict(self) -> dict[str, Any]:
        """Audit-safe usage record. SECURITY: no prompt or completion content."""
        return {
            "model": self.model_name,
            "tier": self.tier.value,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "stub": self.is_stub,
        }


@dataclass(slots=True)
class StreamEvent:
    """One step of ``GeminiService.stream_events``.

    Text deltas have ``done=False`` and the new ``text``. The final event has
    ``done=True``, the *whole* text, and the grounding.
    """

    text: str = ""
    done: bool = False
    grounding: Grounding = field(default_factory=Grounding)
    model_name: str = ""


def extract_grounding(response: Any, *, full_text: str | None = None) -> Grounding:
    """Read Google Search grounding metadata off a response, defensively.

    The output text is left untouched. An earlier version spliced ``[n]``
    markers into it, which is fine for prose and corrupts a JSON response -
    so callers now map supports onto their own structure instead.

    Only ``https`` URLs without credentials are kept. Segment offsets are UTF-8
    byte offsets into the candidate's text part, not character offsets.

    ``full_text`` is for a *streamed* response: grounding arrives on the last
    chunk only, whose own text part is empty or a fragment, while the segment
    offsets index the whole answer. Slicing the chunk's part would silently
    pick the wrong span, so the caller passes the concatenated text instead.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return Grounding()
    candidate = candidates[0]
    metadata = getattr(candidate, "grounding_metadata", None)
    if metadata is None:
        return Grounding()

    chunks = getattr(metadata, "grounding_chunks", None) or []
    sources: list[GroundingSource] = []
    index_map: dict[int, int] = {}
    seen: dict[str, int] = {}
    for position, chunk in enumerate(chunks):
        web = getattr(chunk, "web", None)
        url = str(getattr(web, "uri", None) or "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            continue
        if url not in seen:
            seen[url] = len(sources)
            sources.append(
                GroundingSource(
                    url=url,
                    title=str(getattr(web, "title", None) or parsed.hostname),
                )
            )
        index_map[position] = seen[url]

    parts = getattr(getattr(candidate, "content", None), "parts", None) or []
    texts: dict[int, bytes] = {
        index: str(part.text).encode("utf-8")
        for index, part in enumerate(parts)
        if getattr(part, "text", None) and not getattr(part, "thought", False)
    }
    if full_text is not None:
        texts = {0: full_text.encode("utf-8")}

    supports: list[GroundingSupport] = []
    for support in getattr(metadata, "grounding_supports", None) or []:
        segment = getattr(support, "segment", None)
        part_index = getattr(segment, "part_index", None) or 0
        raw = texts.get(part_index, b"")
        start = getattr(segment, "start_index", None) or 0
        end = getattr(segment, "end_index", None)
        text = ""
        if isinstance(end, int) and 0 <= start < end <= len(raw):
            try:
                text = raw[start:end].decode("utf-8")
            except UnicodeDecodeError:
                text = ""
        if not text:
            text = str(getattr(segment, "text", None) or "")
        if not text.strip():
            continue
        indices = sorted(
            {
                index_map[i]
                for i in getattr(support, "grounding_chunk_indices", None) or []
                if isinstance(i, int) and i in index_map
            }
        )
        if indices:
            supports.append(GroundingSupport(text=text, source_indices=indices))

    entry = getattr(metadata, "search_entry_point", None)
    return Grounding(
        sources=sources,
        supports=supports,
        queries=[str(q) for q in getattr(metadata, "web_search_queries", None) or []],
        search_suggestions_html=str(getattr(entry, "rendered_content", None) or ""),
    )


class GeminiService:
    """Provider-agnostic LLM gateway with a mandatory egress guard."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        guard: EgressGuard | None = None,
        audit: AuditLogger | None = None,
        router: ModelRouter | None = None,
        meter: LlmMeter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._router = router or ModelRouter(self._settings)
        self._audit = audit
        #: Where each call's tokens and cost are recorded. See ``llm_meter``.
        self._meter = meter
        # SECURITY: if no guard is supplied we build a strict one rather than
        # skipping the check. Failing open here would defeat the whole design.
        self._guard = guard if guard is not None else EgressGuard(audit=audit)
        self._client: Any | None = None
        #: When the client last failed to initialise, for the retry backoff.
        self._client_failed_at: float | None = None
        #: Adaptive pacing state, engaged by a 429 and decaying on its own.
        self._pace_lock = threading.Lock()
        self._next_call_at = 0.0
        self._paced_interval = 0.0
        self._pacing_until = 0.0

    # ------------------------------------------------------------ client

    @property
    def enabled(self) -> bool:
        """True when real calls are possible and permitted."""
        return bool(
            self._settings.gemini_enabled
            and self._settings.gemini_api_key
            and not self._in_failure_cooldown()
        )

    def _in_failure_cooldown(self) -> bool:
        """Whether a recent client failure should keep us on stubs for now.

        The failure flag used to latch permanently: one failed initialisation
        and the process answered from deterministic stubs for the rest of its
        life, with no retry and nothing in the UI to say why. In practice the
        cause was an environmental one that a later attempt would have survived
        — a missing dependency installed minutes afterwards, a proxy blip — and
        the only cure was a restart nobody knew they needed.

        Backing off is still right; never retrying is not.
        """
        if self._client_failed_at is None:
            return False
        if time.monotonic() - self._client_failed_at >= _CLIENT_RETRY_SECONDS:
            self._client_failed_at = None  # cooldown elapsed; allow one retry
            return False
        return True

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not self.enabled:
            return None
        try:
            from google import genai
            from google.genai import types

            # GEMINI_TIMEOUT_SECONDS was configurable but never applied, so a
            # stalled request hung on the SDK default while the pipeline stage
            # it belonged to had no bound at all. HttpOptions takes ms.
            options = types.HttpOptions(
                timeout=self._settings.gemini_timeout_seconds * 1000
            )
            try:
                self._client = genai.Client(
                    api_key=self._settings.gemini_api_key, http_options=options
                )
            except TypeError:  # SDK too old to accept http_options
                self._client = genai.Client(api_key=self._settings.gemini_api_key)
            logger.info(
                "Gemini client initialised (timeout %ds, %d attempts per call)",
                self._settings.gemini_timeout_seconds,
                self._settings.gemini_max_retries,
            )
            return self._client
        except Exception as exc:  # pragma: no cover - depends on env
            # Back off rather than retrying on every call, but do retry: see
            # _in_failure_cooldown.
            self._client_failed_at = time.monotonic()
            logger.error(
                "Gemini client could not be initialised (%s); falling back to "
                "deterministic stubs and retrying in %ds. If this persists, "
                "check that google-genai is installed in the environment the "
                "server actually runs from.",
                type(exc).__name__,
                _CLIENT_RETRY_SECONDS,
            )
            return None

    # -------------------------------------------------------------- API

    def generate(
        self,
        *,
        prompt: str,
        task: TaskKind,
        signals: RoutingSignals | None = None,
        system_instruction: str | None = None,
        json_mode: bool = False,
        context: str = "llm_request",
        google_search: bool = False,
        meter_scope: MeterScope | None = None,
        model: str | None = None,
        response_json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        thinking_level: str | None = None,
    ) -> LlmResponse:
        """Run one completion, after clearing the egress guard.

        ``meter_scope`` says which return or chat the call is for, when the
        caller cannot use a ``metered`` block - see ``llm_meter``.

        ``model`` overrides the router for a caller that owns its model choice
        as configuration (the assistant). ``response_json_schema`` implies
        JSON mode. With ``google_search`` the response carries ``grounding``.
        """
        decision = self._router.route(task, signals)
        if model:
            decision = replace(decision, model_name=model, reason="caller-configured")
        if response_json_schema is not None:
            json_mode = True
        scope = meter_scope or current_scope()

        payload = {
            "system": system_instruction or "",
            "prompt": prompt,
            "model": decision.model_name,
            "google_search": google_search,
        }

        # SECURITY: the guard runs *before* any network activity. On a blocking
        # finding this raises and nothing is transmitted.
        self._guard.assert_safe(payload, context=context)

        if self._audit is not None:
            self._audit.record(
                AuditAction.LLM_REQUESTED,
                entity_type="llm_request",
                payload={
                    "task": task.value,
                    "tier": decision.tier.value,
                    "model": decision.model_name,
                    "prompt_chars": len(prompt),
                    "json_mode": json_mode,
                    "google_search": google_search,
                },
            )

        client = self._get_client()
        if client is None:
            stubbed = self._stub_response(prompt, task, decision, json_mode)
            self._record_usage(
                LlmUsage(
                    model=stubbed.model_name,
                    tier=decision.tier.value,
                    task=task.value,
                    stub=True,
                ),
                scope,
            )
            return stubbed

        started = time.monotonic()
        try:
            response = self._call_with_retry(
                client=client,
                model=decision.model_name,
                prompt=prompt,
                system_instruction=system_instruction,
                json_mode=json_mode,
                google_search=google_search,
                response_json_schema=response_json_schema,
                temperature=temperature,
                thinking_level=thinking_level,
            )
        except Exception as exc:
            self._record_usage(
                LlmUsage(
                    model=decision.model_name,
                    tier=decision.tier.value,
                    task=task.value,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    succeeded=False,
                ),
                scope,
            )
            raise self._llm_failure(exc, task=task) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        text = self._extract_text(response)
        usage = self._extract_usage(response)
        input_tokens, output_tokens, cached_tokens, thinking_tokens = (
            usage_from_response(response)
        )
        self._record_usage(
            LlmUsage(
                model=decision.model_name,
                tier=decision.tier.value,
                task=task.value,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                thinking_tokens=thinking_tokens,
                latency_ms=latency_ms,
            ),
            scope,
        )

        result = LlmResponse(
            text=text,
            model_name=decision.model_name,
            tier=decision.tier,
            latency_ms=latency_ms,
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            routing_reason=decision.reason,
        )
        if google_search:
            result.grounding = extract_grounding(response)

        if self._audit is not None:
            self._audit.record(
                AuditAction.LLM_COMPLETED,
                entity_type="llm_request",
                payload={"task": task.value, **result.usage_dict()},
            )
        return result

    def generate_json(
        self,
        *,
        prompt: str,
        task: TaskKind,
        signals: RoutingSignals | None = None,
        system_instruction: str | None = None,
        context: str = "llm_json_request",
        meter_scope: MeterScope | None = None,
    ) -> LlmResponse:
        """Run a completion and parse the result as JSON."""
        response = self.generate(
            prompt=prompt,
            task=task,
            signals=signals,
            system_instruction=system_instruction,
            json_mode=True,
            context=context,
            meter_scope=meter_scope,
        )
        response.data = parse_json_response(response.text)
        return response

    def generate_stream(
        self,
        *,
        prompt: str,
        task: TaskKind,
        signals: RoutingSignals | None = None,
        system_instruction: str | None = None,
        context: str = "llm_stream_request",
        meter_scope: MeterScope | None = None,
    ) -> Iterator[str]:
        """Stream a completion as incremental text deltas.

        SECURITY: like every other call, the serialized payload clears the
        egress guard *before* any network activity. On a blocking finding this
        raises and nothing is streamed. When the model is unconfigured the
        deterministic stub text is streamed instead, so the UI degrades
        gracefully offline.
        """
        decision = self._router.route(task, signals)
        payload = {
            "system": system_instruction or "",
            "prompt": prompt,
            "model": decision.model_name,
        }
        self._guard.assert_safe(payload, context=context)
        # A stream is consumed after the caller's ``metered`` block may have
        # exited, so it takes its scope now rather than when it is recorded.
        scope = meter_scope or current_scope()

        if self._audit is not None:
            self._audit.record(
                AuditAction.LLM_REQUESTED,
                entity_type="llm_request",
                payload={
                    "task": task.value,
                    "tier": decision.tier.value,
                    "model": decision.model_name,
                    "prompt_chars": len(prompt),
                    "streaming": True,
                },
            )

        client = self._get_client()
        if client is None:
            self._record_usage(
                LlmUsage(
                    model=f"{decision.model_name}{STUB_SUFFIX}",
                    tier=decision.tier.value,
                    task=task.value,
                    stub=True,
                    streaming=True,
                ),
                scope,
            )
            stub = _STUB_PAYLOADS.get(task, _DEFAULT_STUB)
            for word in str(stub.get("short_answer", "")).split(" "):
                yield word + " "
            return

        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "temperature": self._settings.gemini_temperature,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        started = time.monotonic()
        # The usage fields arrive on the stream's chunks, cumulatively; the
        # last one seen is the call's total. Recorded in ``finally`` so a
        # reader who stops early - or a failure mid-stream - is still metered.
        counts = (0, 0, 0, 0)
        succeeded = False
        try:
            self._pace()
            stream = client.models.generate_content_stream(
                model=decision.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            for chunk in stream:
                if getattr(chunk, "usage_metadata", None) is not None:
                    counts = usage_from_response(chunk)
                piece = getattr(chunk, "text", None)
                if piece:
                    yield piece
            succeeded = True
        except Exception as exc:
            if _is_rate_limited(exc):
                self._engage_pacing()
            raise self._llm_failure(exc, task=task, streaming=True) from exc
        finally:
            self._record_usage(
                LlmUsage(
                    model=decision.model_name,
                    tier=decision.tier.value,
                    task=task.value,
                    input_tokens=counts[0],
                    output_tokens=counts[1],
                    cached_tokens=counts[2],
                    thinking_tokens=counts[3],
                    latency_ms=int((time.monotonic() - started) * 1000),
                    succeeded=succeeded,
                    streaming=True,
                ),
                scope,
            )

    # ---------------------------------------------------------- internals

    def _record_usage(self, usage: LlmUsage, scope: MeterScope | None = None) -> None:
        """Hand one call's usage to the meter. Never fails the call itself.

        The call has already happened and been paid for; losing its reply
        because the ledger could not be written would cost it twice. The
        failure is logged by type so an unmetered stretch is visible - a
        meter that fails silently looks exactly like a cheap month.
        """
        if self._meter is None:
            return
        try:
            self._meter.record(usage, scope)
        except Exception as exc:  # noqa: BLE001 - see docstring
            logger.warning("LLM call not metered: %s", type(exc).__name__)

    def _llm_failure(
        self, exc: BaseException, *, task: TaskKind, streaming: bool = False
    ) -> LlmError:
        """Record a failed call and describe it truthfully to the reviewer.

        "The language model request failed" was the same sentence whether the
        provider was overloaded, the key was rejected, or the prompt was
        malformed — three different things to do about it, and the operator had
        to go and read the server log to tell which had happened.

        Falling back to a stub here would be worse than failing: a stub answer
        is a well-formed one, and a return computed from it looks exactly like
        a real return.
        """
        transient = _is_transient(exc)
        status = _status_code_of(exc)
        quota_scope = _quota_scope(exc)

        if self._audit is not None:
            self._audit.record(
                AuditAction.LLM_FAILED,
                entity_type="llm_request",
                payload={
                    "task": task.value,
                    "error_type": type(exc).__name__,
                    "status_code": status,
                    "transient": transient,
                    "quota_scope": quota_scope,
                    "streaming": streaming,
                },
            )
        logger.error(
            "Gemini %s failed: %s",
            "stream" if streaming else "call",
            _describe(exc),
        )

        if quota_scope == "daily":
            # Retryable in the abstract, but not today — and "re-run the
            # workflow" is the wrong instruction for a window a day wide.
            transient = False
            message = (
                "The model provider's daily quota for this API key is "
                "exhausted. Re-running will fail the same way until the quota "
                "resets (midnight US Pacific for Gemini free tier). Enable "
                "billing on the key, or use a key with remaining quota. "
                "Nothing was computed from partial data."
            )
        elif quota_scope == "short_window":
            message = (
                "The model provider rate-limited this request and was still "
                "limiting it after "
                f"{max(1, self._settings.gemini_rate_limit_max_retries)} "
                "attempts spread over several minutes. The key's "
                "requests-per-minute allowance is too low for a workpaper this "
                "size. Raise GEMINI_MIN_REQUEST_INTERVAL_SECONDS to space the "
                "calls out, or use a key with a higher limit, then re-run. "
                "Nothing was computed from partial data."
            )
        elif transient:
            message = (
                "The model provider did not respond successfully after "
                f"{max(1, self._settings.gemini_max_retries)} attempts "
                f"({_describe(exc)}). This is usually a temporary overload — "
                "re-run the workflow. Nothing was computed from partial data."
            )
        else:
            message = (
                f"The model provider rejected the request ({_describe(exc)}). "
                "Check the API key, quota, and configured model name. The "
                "workflow has been paused rather than continuing with "
                "incomplete data."
            )
        return LlmError(
            message,
            details={
                "error_type": type(exc).__name__,
                "status_code": status,
                "retryable": transient,
                "quota_scope": quota_scope,
            },
        )

    def _call_with_retry(
        self,
        *,
        client: Any,
        model: str,
        prompt: str,
        system_instruction: str | None,
        json_mode: bool,
        google_search: bool = False,
        response_json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        thinking_level: str | None = None,
    ) -> Any:
        from google.genai import types

        config_kwargs = self._config_kwargs(
            system_instruction=system_instruction,
            json_mode=json_mode,
            google_search=google_search,
            response_json_schema=response_json_schema,
            temperature=temperature,
            thinking_level=thinking_level,
        )

        last_error: Exception | None = None
        attempts = max(1, self._settings.gemini_max_retries)
        rate_limit_attempts = max(
            attempts, self._settings.gemini_rate_limit_max_retries
        )
        rate_limit_wait_budget = self._settings.gemini_rate_limit_max_wait_seconds
        waited_on_rate_limit = 0.0
        throttled = False
        attempt = 0

        while True:
            attempt += 1
            self._pace()
            try:
                return client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = exc
                if not _is_transient(exc):
                    logger.error(
                        "Gemini rejected the request (%s); not retrying",
                        _describe(exc),
                    )
                    raise

                if _is_rate_limited(exc):
                    throttled = True
                    self._engage_pacing()
                    if _quota_scope(exc) == "daily":
                        # Waiting cannot help: the window is a day wide.
                        logger.error(
                            "Gemini daily quota is exhausted; not retrying"
                        )
                        raise

                limit = rate_limit_attempts if throttled else attempts
                if attempt >= limit:
                    break

                delay = self._retry_delay(exc, attempt)
                if _is_rate_limited(exc):
                    if waited_on_rate_limit + delay > rate_limit_wait_budget:
                        logger.error(
                            "Gemini rate limit persisted past the %.0fs wait "
                            "budget; giving up",
                            rate_limit_wait_budget,
                        )
                        break
                    waited_on_rate_limit += delay

                logger.warning(
                    "Gemini attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt,
                    limit,
                    _describe(exc),
                    delay,
                )
                time.sleep(delay)

        assert last_error is not None
        raise last_error

    def _config_kwargs(
        self,
        *,
        system_instruction: str | None,
        json_mode: bool = False,
        google_search: bool = False,
        response_json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        thinking_level: str | None = None,
    ) -> dict[str, Any]:
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "temperature": (
                self._settings.gemini_temperature
                if temperature is None
                else temperature
            ),
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        if response_json_schema is not None:
            config_kwargs["response_json_schema"] = response_json_schema
        if google_search:
            config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        if thinking_level:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(thinking_level.upper())
            )
        return config_kwargs

    def stream_events(
        self,
        *,
        prompt: str,
        task: TaskKind,
        system_instruction: str | None = None,
        context: str = "llm_stream_request",
        google_search: bool = False,
        meter_scope: MeterScope | None = None,
        model: str | None = None,
        temperature: float | None = None,
        thinking_level: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream one completion as text deltas, then one ``done`` event.

        The ``done`` event carries the whole text, the model name and - with
        ``google_search`` - the grounding, which the API attaches to the last
        chunk only. Whether the model actually searched is therefore known
        only at the end, and callers must check it then.

        SECURITY: the serialized payload clears the egress guard *before* any
        network activity, exactly as ``generate`` does. A transient failure
        before the first text arrives is retried like a blocking call; once
        text has been yielded a failure raises, because the caller has
        already shown it. There is no stub: with no client this raises
        ``LlmError``, since a stubbed answer would be text from nowhere.
        """
        decision = self._router.route(task, None)
        if model:
            decision = replace(decision, model_name=model, reason="caller-configured")
        payload = {
            "system": system_instruction or "",
            "prompt": prompt,
            "model": decision.model_name,
            "google_search": google_search,
        }
        self._guard.assert_safe(payload, context=context)
        scope = meter_scope or current_scope()

        if self._audit is not None:
            self._audit.record(
                AuditAction.LLM_REQUESTED,
                entity_type="llm_request",
                payload={
                    "task": task.value,
                    "tier": decision.tier.value,
                    "model": decision.model_name,
                    "prompt_chars": len(prompt),
                    "google_search": google_search,
                    "streaming": True,
                },
            )

        client = self._get_client()
        if client is None:
            raise LlmError("The model is not configured.", details={"retryable": False})

        from google.genai import types

        config = types.GenerateContentConfig(
            **self._config_kwargs(
                system_instruction=system_instruction,
                google_search=google_search,
                temperature=temperature,
                thinking_level=thinking_level,
            )
        )
        started = time.monotonic()
        counts = (0, 0, 0, 0)
        succeeded = False
        text = ""
        last_chunk: Any = None
        attempts = max(1, self._settings.gemini_max_retries)
        attempt = 0
        try:
            while True:
                attempt += 1
                self._pace()
                try:
                    for chunk in client.models.generate_content_stream(
                        model=decision.model_name, contents=prompt, config=config
                    ):
                        last_chunk = chunk
                        if getattr(chunk, "usage_metadata", None) is not None:
                            counts = usage_from_response(chunk)
                        piece = getattr(chunk, "text", None)
                        if piece:
                            text += piece
                            yield StreamEvent(text=piece)
                    break
                except Exception as exc:
                    if _is_rate_limited(exc):
                        self._engage_pacing()
                    if text or attempt >= attempts or not _is_transient(exc):
                        raise
                    delay = self._retry_delay(exc, attempt)
                    logger.warning(
                        "Gemini stream attempt %d/%d failed before any text (%s); "
                        "retrying in %.1fs",
                        attempt, attempts, _describe(exc), delay,
                    )
                    time.sleep(delay)
            succeeded = True
        except LlmError:
            raise
        except Exception as exc:
            raise self._llm_failure(exc, task=task, streaming=True) from exc
        finally:
            self._record_usage(
                LlmUsage(
                    model=decision.model_name,
                    tier=decision.tier.value,
                    task=task.value,
                    input_tokens=counts[0],
                    output_tokens=counts[1],
                    cached_tokens=counts[2],
                    thinking_tokens=counts[3],
                    latency_ms=int((time.monotonic() - started) * 1000),
                    succeeded=succeeded,
                    streaming=True,
                ),
                scope,
            )

        grounding = (
            extract_grounding(last_chunk, full_text=text)
            if google_search and last_chunk is not None
            else Grounding()
        )
        if self._audit is not None:
            self._audit.record(
                AuditAction.LLM_COMPLETED,
                entity_type="llm_request",
                payload={
                    "task": task.value,
                    "model": decision.model_name,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "prompt_tokens": counts[0],
                    "completion_tokens": counts[1],
                    "streaming": True,
                },
            )
        yield StreamEvent(done=True, text=text, grounding=grounding, model_name=decision.model_name)

    # ------------------------------------------------------------- pacing

    def _pace(self) -> None:
        """Hold off until the configured minimum gap since the last call.

        Extraction issues one call per classified document with nothing between
        them, so a workpaper can spend a whole minute's quota in a few seconds
        and then fail on document seven — after six successful, billed calls.
        """
        with self._pace_lock:
            interval = self._settings.gemini_min_request_interval_seconds
            now = time.monotonic()
            if now < self._pacing_until:
                interval = max(interval, self._paced_interval)
            elif self._paced_interval:
                self._paced_interval = 0.0
            if interval <= 0:
                return
            wait = self._next_call_at - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_call_at = now + interval

    def _engage_pacing(self) -> None:
        """Slow every subsequent call down for a while after a rate limit."""
        with self._pace_lock:
            self._paced_interval = max(self._paced_interval, _ADAPTIVE_PACING_SECONDS)
            self._pacing_until = time.monotonic() + _ADAPTIVE_PACING_DECAY_SECONDS

    # ------------------------------------------------------------ backoff

    @classmethod
    def _retry_delay(cls, exc: BaseException, attempt: int) -> float:
        """How long to wait before the next attempt at this failure."""
        if not _is_rate_limited(exc):
            return cls._backoff(attempt)
        requested = _retry_after_seconds(exc)
        if requested is not None:
            # Trust the provider, but never busy-loop on a zero and never
            # hand the caller an unbounded sleep.
            return min(max(requested, 1.0), _RATE_LIMIT_BACKOFF_CAP_SECONDS)
        return cls._rate_limit_backoff(attempt)

    @staticmethod
    def _rate_limit_backoff(attempt: int) -> float:
        """Backoff sized to a quota window rather than to an outage.

        Starts above a third of a minute so that two attempts straddle the
        window reset, and keeps the jitter so a workpaper's documents do not
        all come back at the same instant and re-exhaust it together.
        """
        ceiling = min(
            _RATE_LIMIT_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1),
            _RATE_LIMIT_BACKOFF_CAP_SECONDS,
        )
        return ceiling / 2 + random.uniform(0, ceiling / 2)

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential backoff with equal jitter.

        Jitter matters here because extraction runs one call per classified
        document in a tight sequence: without it, every document in a workpaper
        retries in lockstep and re-hits the same overloaded model together.
        """
        ceiling = min(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1), _BACKOFF_CAP_SECONDS)
        return ceiling / 2 + random.uniform(0, ceiling / 2)

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            return text
        # Fall back to walking candidates when .text is unavailable.
        try:
            parts = response.candidates[0].content.parts
            return "".join(getattr(p, "text", "") or "" for p in parts)
        except Exception:  # pragma: no cover
            return ""

    @staticmethod
    def _extract_usage(response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return (0, 0)
        return (
            int(getattr(usage, "prompt_token_count", 0) or 0),
            int(getattr(usage, "candidates_token_count", 0) or 0),
        )

    def _stub_response(
        self,
        prompt: str,
        task: TaskKind,
        decision: RoutingDecision,
        json_mode: bool,
    ) -> LlmResponse:
        """Deterministic offline response.

        Keeps the pipeline runnable with no API key. Stub output is explicitly
        low-confidence so downstream stages route it to human review rather than
        treating placeholder content as a real extraction.
        """
        logger.info(
            "Gemini disabled or unconfigured; returning stub for %s", task.value
        )
        stub = _STUB_PAYLOADS.get(task, _DEFAULT_STUB)
        return LlmResponse(
            text=json.dumps(stub) if json_mode else stub.get("short_answer", ""),
            data=dict(stub) if json_mode else {},
            model_name=f"{decision.model_name} (stub)",
            tier=decision.tier,
            latency_ms=0,
            is_stub=True,
            routing_reason=decision.reason + "; offline stub",
        )


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse a model's JSON output tolerantly.

    Models wrap JSON in fences, prepend "Here is the JSON:", or append a
    closing remark often enough that strict parsing is a reliability problem.
    Returns ``{}`` rather than raising: a malformed response should degrade to
    "no extraction, send to review", not crash the pipeline.
    """
    if not text or not text.strip():
        return {}

    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost balanced {...} block.
    start = cleaned.find("{")
    if start == -1:
        return {}
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : index + 1])
                    return parsed if isinstance(parsed, dict) else {"result": parsed}
                except json.JSONDecodeError:
                    break
    logger.warning("Could not parse model output as JSON (%d chars)", len(text))
    return {}


# ---------------------------------------------------------------------------
# Offline stubs
# ---------------------------------------------------------------------------

_DEFAULT_STUB: dict[str, Any] = {
    "short_answer": (
        "The AI model is not configured, so no generated answer is available."
    ),
    "confidence": 0.0,
    "review_flags": ["llm_unavailable"],
}

_STUB_PAYLOADS: dict[TaskKind, dict[str, Any]] = {
    TaskKind.CLASSIFICATION: {
        "document_type": "unknown_workpaper",
        "confidence": 0.0,
        "reason": "model unavailable",
    },
    TaskKind.DOCUMENT_EXTRACTION: {
        "extracted_tax_facts": [],
        "normalized_fields": {},
        "tax_workpaper_adjustments": [],
        "calculations": [],
        "assumptions": [],
        "missing_information": ["Model unavailable; no extraction performed."],
        "confidence_scores": {},
        "review_flags": ["llm_unavailable"],
        "output_mapping_instructions": [],
    },
    TaskKind.BULK_EXTRACTION: {
        "extracted_tax_facts": [],
        "confidence_scores": {},
        "review_flags": ["llm_unavailable"],
    },
    TaskKind.CHAT_SIMPLE: dict(_DEFAULT_STUB),
    TaskKind.CHAT_COMPLEX: dict(_DEFAULT_STUB),
    TaskKind.TAX_REASONING: dict(_DEFAULT_STUB),
    TaskKind.TEMPLATE_INFERENCE: {"rules": [], "confidence": 0.0},
    # No wording offline: every line keeps its deterministic explanation.
    TaskKind.RETURN_EXPLANATION: {"explanations": {}},
}
