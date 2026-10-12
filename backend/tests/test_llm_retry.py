"""How the LLM gateway behaves when the provider misbehaves.

The production failure this pins down: three ``ServerError`` attempts one and
two seconds apart, all inside the same provider overload, then a hard workflow
failure whose message said only "the language model request failed".

Two things have to hold. A transient fault is retried with a backoff long
enough to outlast the outage, and a permanent one is not retried at all —
retrying a malformed request only delays the review item while making the log
read as though the provider were at fault.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.config import Settings
from app.core.errors import EgressBlockedError, LlmError
from app.models.enums import TaskKind
from app.services.gemini_service import (
    _BACKOFF_CAP_SECONDS,
    _RATE_LIMIT_BACKOFF_CAP_SECONDS,
    GeminiService,
    _describe,
    _is_transient,
    _quota_scope,
    _retry_after_seconds,
    _status_code_of,
)


class FakeApiError(Exception):
    """Stands in for google.genai.errors.APIError, which exposes ``.code``."""

    def __init__(self, code: int, details: object | None = None) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code
        if details is not None:
            self.details = details


class ReadTimeout(Exception):
    """Stands in for the httpx transport error of the same name."""


class BadRequest(Exception):
    """A failure of ours, carrying no status at all."""


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_provider_faults_are_retryable(code: int) -> None:
    assert _is_transient(FakeApiError(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413])
def test_rejected_requests_are_not_retryable(code: int) -> None:
    assert not _is_transient(FakeApiError(code))


def test_transport_failures_are_retryable_without_a_status() -> None:
    assert _is_transient(ReadTimeout("connection dropped"))


def test_unrecognised_failures_are_not_retried() -> None:
    assert not _is_transient(BadRequest("we built the payload wrong"))


def test_a_transient_cause_behind_a_wrapper_still_counts() -> None:
    wrapper = RuntimeError("call failed")
    wrapper.__cause__ = ReadTimeout("connection dropped")

    assert _is_transient(wrapper)


def test_status_is_read_from_the_response_when_not_on_the_error() -> None:
    class Response:
        status_code = 503

    class Wrapped(Exception):
        response = Response()

    assert _status_code_of(Wrapped()) == 503


def test_backoff_outlasts_a_brief_overload_and_stays_bounded() -> None:
    delays = [GeminiService._backoff(attempt) for attempt in range(1, 8)]

    # The 1s/2s pair that shipped finished inside the outage it was meant to
    # ride out; by the third attempt the wait must be meaningfully longer.
    assert delays[2] >= 4
    assert all(delay <= _BACKOFF_CAP_SECONDS for delay in delays)
    # Jittered, so a whole workpaper's per-document calls do not retry in step.
    assert len({round(GeminiService._backoff(4), 4) for _ in range(20)}) > 1


def test_outage_and_rejection_are_reported_differently() -> None:
    service = GeminiService()

    outage = service._llm_failure(FakeApiError(503), task=TaskKind.DOCUMENT_EXTRACTION)
    rejected = service._llm_failure(FakeApiError(400), task=TaskKind.DOCUMENT_EXTRACTION)

    assert isinstance(outage, LlmError)
    assert outage.details["retryable"] is True
    assert outage.details["status_code"] == 503
    assert "re-run" in outage.message.lower()

    assert rejected.details["retryable"] is False
    assert "rejected" in rejected.message.lower()
    assert "api key" in rejected.message.lower()


@pytest.mark.security
def test_failure_reporting_never_echoes_the_provider_message() -> None:
    # SECURITY: a provider error can quote the request back, and the request is
    # masked client data. Only the error class and status may be logged.
    service = GeminiService()
    exc = FakeApiError(500)
    exc.args = ("prompt rejected: TAXPAYER_001 wages 125000",)

    failure = service._llm_failure(exc, task=TaskKind.DOCUMENT_EXTRACTION)

    assert "TAXPAYER_001" not in failure.message
    assert "125000" not in failure.message
    assert "TAXPAYER_001" not in _describe(exc)


def test_retry_loop_stops_on_a_permanent_failure() -> None:
    pytest.importorskip("google.genai")
    service = GeminiService()
    attempts = 0

    class Models:
        def generate_content(self, **_: object) -> object:
            nonlocal attempts
            attempts += 1
            raise FakeApiError(400)

    class Client:
        models = Models()

    with pytest.raises(FakeApiError):
        service._call_with_retry(
            client=Client(),
            model="gemini-test",
            prompt="masked text",
            system_instruction=None,
            json_mode=False,
        )

    assert attempts == 1


def test_retry_loop_recovers_from_a_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("google.genai")
    monkeypatch.setattr("app.services.gemini_service.time.sleep", lambda _: None)
    service = GeminiService()
    attempts = 0

    class Models:
        def generate_content(self, **_: object) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise FakeApiError(503)
            return "recovered"

    class Client:
        models = Models()

    result = service._call_with_retry(
        client=Client(),
        model="gemini-test",
        prompt="masked text",
        system_instruction=None,
        json_mode=False,
    )

    assert result == "recovered"
    assert attempts == 2


def test_google_grounding_returns_sources_and_utf8_supports_without_touching_text(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    pytest.importorskip("google.genai")
    text = '{"quick_answer": "Café owners must keep tax records."}'
    supported = "Café owners must keep tax records."
    start = len(text.encode("utf-8")) - len(supported.encode("utf-8")) - 2
    metadata = SimpleNamespace(
        grounding_chunks=[
            SimpleNamespace(web=SimpleNamespace(
                uri="https://www.irs.gov/publications/p583", title="irs.gov"
            )),
            SimpleNamespace(web=SimpleNamespace(uri="http://insecure.example", title="x")),
        ],
        grounding_supports=[SimpleNamespace(
            segment=SimpleNamespace(
                start_index=start,
                end_index=start + len(supported.encode("utf-8")),
                part_index=0,
            ),
            grounding_chunk_indices=[0, 0, 1, 99],
        )],
        web_search_queries=["cafe tax records irs"],
        search_entry_point=SimpleNamespace(rendered_content="<div>Google Search</div>"),
    )
    response = SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(
            content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
            grounding_metadata=metadata,
        )],
    )
    captured: dict[str, object] = {}

    def generate_content(**kwargs):
        captured.update(kwargs)
        return response

    service = GeminiService()
    monkeypatch.setattr(service, "_get_client", lambda: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    ))
    schema = {"type": "object", "properties": {"quick_answer": {"type": "string"}}}
    result = service.generate(
        prompt="What tax records should a cafe keep?",
        task=TaskKind.CHAT_COMPLEX,
        system_instruction="Research US tax guidance.",
        google_search=True,
        response_json_schema=schema,
        model="configured-model",
        temperature=0.2,
    )
    config = captured["config"]
    assert captured["model"] == "configured-model"
    assert config.tools[0].google_search is not None
    assert config.response_json_schema == schema
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0.2
    # The JSON text is untouched - no citation markers spliced into it.
    assert result.text == text
    # Only the https source survives; the out-of-range index is ignored.
    assert [s.url for s in result.grounding.sources] == ["https://www.irs.gov/publications/p583"]
    assert result.grounding.supports[0].text == supported
    assert result.grounding.supports[0].source_indices == [0]
    assert result.grounding.queries == ["cafe tax records irs"]
    assert result.grounding.search_suggestions_html == "<div>Google Search</div>"


def test_google_search_without_grounding_metadata_is_empty_grounding() -> None:
    from types import SimpleNamespace

    from app.services.gemini_service import extract_grounding

    response = SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(text="An unsupported claim [1].")])
    )])
    assert extract_grounding(response).is_empty


@pytest.mark.security
def test_google_search_egress_guard_runs_before_client_access(monkeypatch) -> None:
    service = GeminiService()

    def forbidden_client():
        pytest.fail("Unmasked data must not reach the Google Search client")

    monkeypatch.setattr(service, "_get_client", forbidden_client)
    with pytest.raises(EgressBlockedError):
        service.generate(
            prompt="Email not-a-real-client@example-mail.com about tax forms.",
            task=TaskKind.CHAT_COMPLEX,
            system_instruction="Research US tax guidance.",
            google_search=True,
        )


# --------------------------------------------------------------- rate limits
#
# A 429 is not an outage. The overload curve (~1s, ~3s, ~6s) spends its whole
# attempt budget inside the 60-second window that is rejecting it, so a
# workpaper whose per-document calls exhaust a free-tier minute failed with
# "the provider is temporarily overloaded" when the provider was fine.


_PER_MINUTE_DETAILS = [
    {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}],
    },
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "24s"},
]

_PER_DAY_DETAILS = [
    {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}],
    }
]


def test_rate_limit_backoff_outlasts_a_quota_window() -> None:
    delays = [GeminiService._rate_limit_backoff(attempt) for attempt in range(1, 8)]

    # Two attempts have to straddle a 60-second reset, which the overload
    # curve's ~1s/~3s/~6s never could.
    assert delays[0] >= 10
    assert sum(delays[:3]) >= 60
    assert all(delay <= _RATE_LIMIT_BACKOFF_CAP_SECONDS for delay in delays)


def test_rate_limit_uses_its_own_curve_not_the_outage_one() -> None:
    # The whole bug: a 429 took the overload curve's ~1s first wait and burned
    # three attempts without ever leaving the window that was rejecting it.
    assert GeminiService._retry_delay(FakeApiError(429), 1) >= 10
    assert GeminiService._retry_delay(FakeApiError(503), 1) <= 2


def test_the_providers_own_retry_delay_is_preferred_to_a_guess() -> None:
    exc = FakeApiError(429, details=_PER_MINUTE_DETAILS)

    assert _retry_after_seconds(exc) == 24.0
    assert GeminiService._retry_delay(exc, 1) == 24.0


def test_a_retry_after_header_is_honoured() -> None:
    class Response:
        status_code = 429
        headers: ClassVar[dict[str, str]] = {"retry-after": "42"}

    class Wrapped(Exception):
        code = 429
        response = Response()

    assert _retry_after_seconds(Wrapped()) == 42.0


def test_an_absurd_retry_delay_is_clamped() -> None:
    exc = FakeApiError(429, details=[{"retryDelay": "3600s"}])

    assert GeminiService._retry_delay(exc, 1) == _RATE_LIMIT_BACKOFF_CAP_SECONDS


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (_PER_MINUTE_DETAILS, "short_window"),
        (_PER_DAY_DETAILS, "daily"),
        (None, "short_window"),
    ],
)
def test_quota_windows_are_told_apart(details: object, expected: str) -> None:
    assert _quota_scope(FakeApiError(429, details=details)) == expected


def test_a_non_rate_limit_failure_has_no_quota_scope() -> None:
    assert _quota_scope(FakeApiError(503)) is None


def test_a_daily_quota_is_not_reported_as_a_temporary_overload() -> None:
    service = GeminiService()

    failure = service._llm_failure(
        FakeApiError(429, details=_PER_DAY_DETAILS),
        task=TaskKind.DOCUMENT_EXTRACTION,
    )

    # "Re-run the workflow" is the wrong instruction for a day-wide window.
    assert failure.details["quota_scope"] == "daily"
    assert failure.details["retryable"] is False
    assert "daily quota" in failure.message.lower()


def test_a_per_minute_limit_says_what_to_change() -> None:
    service = GeminiService()

    failure = service._llm_failure(
        FakeApiError(429, details=_PER_MINUTE_DETAILS),
        task=TaskKind.DOCUMENT_EXTRACTION,
    )

    assert failure.details["quota_scope"] == "short_window"
    assert failure.details["retryable"] is True
    assert "per-minute" in failure.message.lower()
    assert "GEMINI_MIN_REQUEST_INTERVAL_SECONDS" in failure.message


def test_a_daily_quota_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("google.genai")
    monkeypatch.setattr("app.services.gemini_service.time.sleep", lambda _: None)
    service = GeminiService()
    attempts = 0

    class Models:
        def generate_content(self, **_: object) -> object:
            nonlocal attempts
            attempts += 1
            raise FakeApiError(429, details=_PER_DAY_DETAILS)

    class Client:
        models = Models()

    with pytest.raises(FakeApiError):
        service._call_with_retry(
            client=Client(),
            model="gemini-test",
            prompt="masked text",
            system_instruction=None,
            json_mode=False,
        )

    assert attempts == 1


def test_a_rate_limit_gets_a_larger_attempt_budget_than_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("google.genai")
    monkeypatch.setattr("app.services.gemini_service.time.sleep", lambda _: None)
    service = GeminiService()
    attempts = 0

    class Models:
        def generate_content(self, **_: object) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 5:
                raise FakeApiError(429, details=_PER_MINUTE_DETAILS)
            return "recovered"

    class Client:
        models = Models()

    result = service._call_with_retry(
        client=Client(),
        model="gemini-test",
        prompt="masked text",
        system_instruction=None,
        json_mode=False,
    )

    # gemini_max_retries is 3; a throttled call must survive past it.
    assert result == "recovered"
    assert attempts == 5


def test_rate_limit_retrying_is_bounded_by_the_wait_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("google.genai")
    slept: list[float] = []
    monkeypatch.setattr(
        "app.services.gemini_service.time.sleep", lambda seconds: slept.append(seconds)
    )
    service = GeminiService()
    service._settings.gemini_rate_limit_max_wait_seconds = 45.0

    class Models:
        def generate_content(self, **_: object) -> object:
            raise FakeApiError(429, details=_PER_MINUTE_DETAILS)

    class Client:
        models = Models()

    with pytest.raises(FakeApiError):
        service._call_with_retry(
            client=Client(),
            model="gemini-test",
            prompt="masked text",
            system_instruction=None,
            json_mode=False,
        )

    assert sum(slept) <= 45.0


def test_a_rate_limit_engages_pacing_for_subsequent_calls() -> None:
    service = GeminiService()
    assert service._paced_interval == 0.0

    service._engage_pacing()

    # Extraction fires one call per document with nothing in between; after a
    # 429 the next document must not sprint back into the same window.
    assert service._paced_interval > 0
    assert service._pacing_until > 0


def test_pacing_waits_out_the_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "app.services.gemini_service.time.sleep", lambda seconds: slept.append(seconds)
    )
    service = GeminiService()
    service._settings.gemini_min_request_interval_seconds = 5.0

    service._pace()  # first call sets the next slot, waits for nothing
    assert slept == []

    service._pace()
    assert slept and 0 < slept[0] <= 5.0


def test_pacing_is_off_by_default() -> None:
    # The class default, not the developer's .env: pacing must cost nothing on
    # a key with real quota.
    field = Settings.model_fields["gemini_min_request_interval_seconds"]
    assert field.default == 0.0


@pytest.mark.security
def test_quota_introspection_never_leaks_into_the_message() -> None:
    # SECURITY: provider error details can echo the request, which is masked
    # client data. They may steer the backoff but must not reach the reviewer.
    service = GeminiService()
    exc = FakeApiError(
        429,
        details=[{"reason": "quota", "echo": "TAXPAYER_001 wages 125000"}],
    )

    failure = service._llm_failure(exc, task=TaskKind.DOCUMENT_EXTRACTION)

    assert "TAXPAYER_001" not in failure.message
    assert "125000" not in failure.message
    assert "125000" not in repr(failure.details)
