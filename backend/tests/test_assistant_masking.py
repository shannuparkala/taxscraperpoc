"""Masking in the assistant: opt-in with ``/mask``, and precise when used.

Masking every question by default replaced title-case phrases and case names
with invented people ("Progress in Preventing Fraud" became "Progress in
<a surrogate>"), so the model answered a question nobody asked. Masking is now
the user's choice; without it the egress guard still blocks identifiers.

Invented values only: the SSN is the fabricated one the security suite uses.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.assistant.assistant_service import AssistantService
from app.services.assistant.masking import (
    QuestionMasker,
    chat_spans,
    parse_mask_command,
)
from app.services.pii_detection_service import DetectionConfig, PiiDetectionService

TODAY = date(2026, 10, 5)
FAKE_SSN = "412-88-7364"


@pytest.mark.parametrize(
    ("question", "requested", "rest"),
    [
        ("/mask My client John Smith", True, "My client John Smith"),
        ("  /MASK: what about Maria?", True, "what about Maria?"),
        ("/mask", True, ""),
        ("What does /mask do?", False, "What does /mask do?"),
        ("/masking is not a command", False, "/masking is not a command"),
    ],
)
def test_the_mask_command_is_a_leading_prefix_only(question: str, requested: bool, rest: str) -> None:
    assert parse_mask_command(question) == (requested, rest)


@pytest.mark.parametrize(
    ("text", "keep"),
    [
        ("Summarize the Treasury release Progress in Preventing Fraud and what it means.",
         "Progress in Preventing Fraud"),
        ("Is Moore v. United States relevant to my Subpart F income?", "Moore"),
        ("What does the Taxpayer Bill of Rights say about Collection Due Process?",
         "Taxpayer Bill of Rights"),
        ("In re Estate of Holmes, what did the Tax Court decide?", "Holmes"),
        ('Read "Understanding Your CP2000 Notice" for me.', "Understanding Your CP2000 Notice"),
        ("See https://www.irs.gov/newsroom/Johnson-Amendment-guidance today.",
         "https://www.irs.gov/newsroom/Johnson-Amendment-guidance"),
    ],
)
def test_mask_leaves_public_titles_and_case_names_alone(session, text: str, keep: str) -> None:
    assert keep in QuestionMasker(session).mask(text).text


@pytest.mark.security
@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("My client John Smith got a CP2000 notice, what now?", ["John Smith"]),
        ("My wife Maria and I file jointly; can Maria deduct her teacher expenses?", ["Maria"]),
        ("Mr. Patel received a levy notice last week.", ["Patel"]),
        ("My clients Maria and John Smith moved to Ohio.", ["Maria", "John Smith"]),
        (f"Email jane.doe@example-mail.com or call 302-555-1234; my SSN is {FAKE_SSN}.",
         ["jane.doe@example-mail.com", "302-555-1234", FAKE_SSN]),
    ],
)
def test_mask_replaces_people_and_identifiers(session, text: str, values: list[str]) -> None:
    masked = QuestionMasker(session).mask(text)
    assert masked.was_masked
    for value in values:
        assert value not in masked.text


def test_a_relation_followed_by_a_form_is_not_a_name() -> None:
    text = "My client Form 1040 shows a refund."
    spans, _ = chat_spans(text, [])
    assert spans == []


def test_masking_decisions_are_logged_as_counts_never_values(session, caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="app.services.assistant.masking")
    QuestionMasker(session).mask(f"My client John Smith has SSN {FAKE_SSN}.")
    lines = [r.getMessage() for r in caplog.records if "assistant.mask" in r.getMessage()]
    assert lines and "John" not in lines[0] and FAKE_SSN not in lines[0]
    assert "mask_ssn" in lines[0]


def test_chat_profile_skips_the_form_layout_detectors() -> None:
    detector = PiiDetectionService(
        DetectionConfig(mask_organizations=False, enable_columnar=False, recase_all_caps=False)
    )
    # A capitalised heading is not a block-capital name field.
    assert not detector.detect("WHAT IS THE STANDARD DEDUCTION FOR HEAD OF HOUSEHOLD")


# ---------------------------------------------------------------------------
# Through the service, with the real gateway and its egress guard
# ---------------------------------------------------------------------------


def _service_with_client(session, monkeypatch, reply: str) -> tuple[AssistantService, list[dict[str, Any]]]:
    from app.core.config import get_settings
    from app.services.gemini_service import GeminiService

    monkeypatch.setenv("GEMINI_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    captured: list[dict[str, Any]] = []

    def generate_content(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return SimpleNamespace(text=reply, candidates=[], usage_metadata=None)

    def generate_content_stream(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return iter([SimpleNamespace(text=reply, candidates=[], usage_metadata=None)])

    gemini = GeminiService()
    monkeypatch.setattr(gemini, "_get_client", lambda: SimpleNamespace(
        models=SimpleNamespace(
            generate_content=generate_content, generate_content_stream=generate_content_stream
        )
    ))
    return AssistantService(session, gemini=gemini, resolver=None, today=lambda: TODAY), captured


def test_without_mask_the_question_is_sent_as_typed(session, monkeypatch) -> None:
    service, captured = _service_with_client(session, monkeypatch, json.dumps({}))
    question = "Summarize the Treasury release Progress in Preventing Fraud."
    result = service.answer(question=question)
    assert captured
    assert question in str(captured[0]["contents"])
    assert not result["was_masked"]


@pytest.mark.security
def test_an_unmasked_identifier_is_blocked_and_the_user_is_told_about_mask(session, monkeypatch) -> None:
    service, captured = _service_with_client(session, monkeypatch, json.dumps({}))
    result = service.answer(question=f"My SSN is {FAKE_SSN}. Can I claim my mother?")
    assert captured == [], "the guard must stop the call before the client"
    assert result["status"] == "unavailable"
    assert "/mask" in result["quick_answer"]
