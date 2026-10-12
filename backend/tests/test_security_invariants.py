"""Privacy and security invariants.

A failure in this module means client data is at risk. If a change breaks one of
these, the change is wrong — not the test.

Covers:
  * masking round-trip and surrogate safety
  * the outbound egress guard, including its false-positive behaviour
  * audit payloads and stage records staying free of document content
  * log redaction
"""

from __future__ import annotations

import io

import pytest

from app.core.pii_patterns import (
    PiiType,
    is_valid_aba_routing,
    is_valid_luhn,
    is_valid_ssn,
)
from app.services.llm_egress_guard import EgressGuard

pytestmark = pytest.mark.security


SENSITIVE_DOCUMENT = """2025 Form W-2 Wage and Tax Statement
a Employee social security number: 412-88-7364
b Employer identification number (EIN): 41-2233445
c Employer name, address, and ZIP code
  Lakeside Manufacturing Inc
  1200 Harbor Road
  Portland, ME 04101

e Employee first name and initial   Last name
  DANIEL                            OKONKWO

1 Wages, tips, other compensation      82,500.00
2 Federal income tax withheld          11,240.00
Taxpayer email: daniel.okonkwo@example-mail.com
Daytime phone: (207) 555-0142
Date of birth: 04/22/1988
Routing number: 011200365  Account no: 8847362514
"""

#: Literal values that must never survive masking.
FORBIDDEN_LITERALS = (
    "DANIEL",
    "OKONKWO",
    "412-88-7364",
    "41-2233445",
    "daniel.okonkwo@example-mail.com",
    "011200365",
    "8847362514",
    "Lakeside Manufacturing",
    "1200 Harbor Road",
    "04/22/1988",
)


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def test_masking_removes_every_sensitive_literal(session) -> None:  # type: ignore[no-untyped-def]
    from app.services.masking_service import MaskingService, MaskStyle
    from app.services.pii_detection_service import PiiDetectionService

    detector = PiiDetectionService()
    spans = detector.detect(SENSITIVE_DOCUMENT)
    masker = MaskingService(session, workflow_id=None, style=MaskStyle.SURROGATE)
    masked = masker.mask_text(SENSITIVE_DOCUMENT, spans).masked_text

    leaked = [literal for literal in FORBIDDEN_LITERALS if literal in masked]
    assert not leaked, f"masking leaked: {leaked}"


def test_masking_preserves_form_structure(session) -> None:  # type: ignore[no-untyped-def]
    """Over-masking is a correctness bug: the model must still see the form.

    If the form title or box labels are replaced, extraction quality collapses
    because the model can no longer tell which form it is reading.
    """
    from app.services.masking_service import MaskingService, MaskStyle
    from app.services.pii_detection_service import PiiDetectionService

    spans = PiiDetectionService().detect(SENSITIVE_DOCUMENT)
    masker = MaskingService(session, workflow_id=None, style=MaskStyle.SURROGATE)
    masked = masker.mask_text(SENSITIVE_DOCUMENT, spans).masked_text

    for structural in (
        "Form W-2 Wage and Tax Statement",
        "Wages, tips, other compensation",
        "Employer identification number",
        "82,500.00",  # amounts are tax data, not identity
    ):
        assert structural in masked, f"masking destroyed structure: {structural!r}"


def test_surrogates_cannot_be_real_identifiers(session) -> None:  # type: ignore[no-untyped-def]
    """Generated substitutes must come from never-issued ranges.

    A leaked surrogate should point at nobody, so SSNs use area 666, EINs use
    prefix 00, routing numbers fail the ABA checksum, and cards fail Luhn.
    """
    from app.services.masking_service import generate_surrogate

    ssn = generate_surrogate(PiiType.SSN, "SSN_001", "412-88-7364")
    assert ssn.startswith("666-"), ssn
    assert not is_valid_ssn(ssn), "surrogate SSN must not be a valid SSN"

    ein = generate_surrogate(PiiType.EIN, "EIN_001", "41-2233445")
    assert ein.startswith("00-"), ein

    routing = generate_surrogate(PiiType.ROUTING_NUMBER, "ROUTING_001", "011200365")
    assert not is_valid_aba_routing(routing), "surrogate routing must not route"

    card = generate_surrogate(PiiType.CREDIT_CARD, "CARD_001", "4111111111111111")
    assert not is_valid_luhn(card), "surrogate card must fail Luhn"


def test_vault_round_trip_recovers_the_original(session) -> None:  # type: ignore[no-untyped-def]
    from app.services.masking_service import MaskingService, MaskStyle
    from app.services.pii_detection_service import PiiDetectionService

    spans = PiiDetectionService().detect(SENSITIVE_DOCUMENT)
    masker = MaskingService(session, workflow_id=None, style=MaskStyle.SURROGATE)
    result = masker.mask_text(SENSITIVE_DOCUMENT, spans)

    assert result.token_map, "masking produced no tokens"
    for token in result.token_map:
        original = masker.resolve_token(token)
        assert original, f"vault could not resolve {token}"
        assert original in SENSITIVE_DOCUMENT, "vault returned a value not in the source"


# ---------------------------------------------------------------------------
# Egress guard
# ---------------------------------------------------------------------------


def test_guard_blocks_unmasked_payload() -> None:
    report = EgressGuard().scan({"prompt": SENSITIVE_DOCUMENT})
    assert not report.is_safe
    blocked = {finding.pii_type.value for finding in report.blocking}
    assert {"ssn", "ein", "email"} <= blocked, blocked


def test_guard_accepts_known_surrogates_after_newline() -> None:
    """Regression: JSON escaping used to merge into the adjacent token.

    Serializing with ``json.dumps`` turns a newline into the characters ``\\``
    and ``n``; the ``n`` then joined the following token, so a correctly masked
    ``\\nalice@example.com`` scanned as ``nalice@example.com``, missed the
    surrogate allow-list, and blocked a payload that was properly masked.
    """
    guard = EgressGuard(allowed_surrogates={"steven.sinclair@example.com"})
    payload = {"prompt": "PORTLAND\n04101\nsteven.sinclair@example.com\n\n<<<PAGE 7>>>"}
    report = guard.scan(payload)
    assert report.is_safe, [f.to_dict() for f in report.blocking]


def test_guard_still_blocks_real_values_when_an_allow_list_exists() -> None:
    """The allow-list must exempt only its own surrogates, nothing broader."""
    guard = EgressGuard(allowed_surrogates={"steven.sinclair@example.com"})
    report = guard.scan({"prompt": "write to\nreal.client@theirdomain.com today"})
    assert not report.is_safe
    assert "email" in {finding.pii_type.value for finding in report.blocking}


def test_guard_findings_never_contain_the_matched_value() -> None:
    """A finding must be reportable without re-leaking what it found."""
    report = EgressGuard().scan({"prompt": SENSITIVE_DOCUMENT})
    serialized = str([finding.to_dict() for finding in report.findings])
    for literal in ("412-88-7364", "daniel.okonkwo@example-mail.com"):
        assert literal not in serialized


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def test_audit_rejects_payloads_carrying_raw_pii(session) -> None:  # type: ignore[no-untyped-def]
    from app.core.audit import AuditAction, AuditLogger, AuditPayloadError

    logger = AuditLogger(session)
    with pytest.raises(AuditPayloadError):
        logger.record(
            AuditAction.PII_DETECTED,
            entity_type="document",
            payload={"value": "412-88-7364"},
        )


def test_audit_accepts_token_references(session) -> None:  # type: ignore[no-untyped-def]
    from app.core.audit import AuditAction, AuditLogger

    logger = AuditLogger(session)
    logger.record(
        AuditAction.MASKING_APPLIED,
        entity_type="workflow",
        entity_id="wf-1",
        payload={"token": "SSN_001", "pii_type": "ssn", "masked_count": 4},
    )


def test_audit_accepts_content_hashes(session) -> None:  # type: ignore[no-untyped-def]
    """Regression: a SHA-256 hex digest contains digit runs that look like PII."""
    from app.core.audit import AuditAction, AuditLogger

    AuditLogger(session).record(
        AuditAction.FILE_UPLOADED,
        entity_type="uploaded_file",
        entity_id="file-1",
        payload={
            "content_hash": "7ffd71b3e4c3303905f3bbca863c6a06741868543dff856c2832c0ac01969b3d",
            "size_bytes": 776,
        },
    )


def test_stage_records_never_contain_document_text(client) -> None:  # type: ignore[no-untyped-def]
    """Regression: stage detail was inferred from each stage's return value.

    Masking returns the masked page text and the LLM stage returns extracted
    fields, so both were being written into the stage record and the audit log.
    """
    response = client.post(
        "/api/files/upload",
        files={"file": ("w2.txt", io.BytesIO(SENSITIVE_DOCUMENT.encode()), "text/plain")},
    )
    file_id = response.json()["id"]
    workflow = client.post(
        f"/api/workflows/{file_id}/process", json={"tax_year": 2025}
    ).json()

    for stage in workflow["stages"]:
        blob = str(stage.get("detail") or {})
        assert "Wages, tips" not in blob, f"{stage['stage']} recorded document text"
        for literal in FORBIDDEN_LITERALS:
            assert literal not in blob, f"{stage['stage']} leaked {literal!r}"

    events = client.get("/api/audit/events?limit=500").json()["items"]
    audit_blob = str([event.get("payload") for event in events])
    for literal in FORBIDDEN_LITERALS:
        assert literal not in audit_blob, f"audit log leaked {literal!r}"


def test_audit_chain_detects_tampering(session) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.core.audit import AuditAction, AuditLogger
    from app.models.database_models import AuditEvent

    logger = AuditLogger(session)
    for index in range(4):
        logger.record(
            AuditAction.WORKFLOW_STAGE_STARTED,
            entity_type="workflow",
            entity_id="wf-1",
            payload={"stage": "ocr", "n": index},
        )
    session.flush()

    ok, broken = logger.verify_chain()
    assert ok and not broken

    target = session.execute(
        select(AuditEvent).where(AuditEvent.sequence == 2)
    ).scalar_one()
    target.payload = {"stage": "ocr", "n": 999}
    session.flush()

    ok, broken = AuditLogger(session).verify_chain()
    assert not ok and 2 in broken


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_log_redaction_scrubs_patterned_values(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from app.core.logging import PiiRedactionFilter

    record = logging.LogRecord(
        name="probe",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ssn %s email %s routing %s",
        args=("412-88-7364", "a.b@example-mail.com", "011200365"),
        exc_info=None,
    )
    PiiRedactionFilter().filter(record)

    assert "412-88-7364" not in record.msg
    assert "a.b@example-mail.com" not in record.msg
    assert "REDACTED" in record.msg


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_api_never_returns_secrets_or_vault_values(client) -> None:  # type: ignore[no-untyped-def]
    settings = client.get("/api/settings").json()
    blob = str(settings).lower()
    for forbidden in ("encrypted_value", "gemini_api_key", "secret_key"):
        assert forbidden not in blob

    # Presence is reported as a boolean, never as the value.
    assert isinstance(settings["gemini_configured"], bool)


def test_masked_preview_exposes_surrogates_not_originals(client) -> None:  # type: ignore[no-untyped-def]
    response = client.post(
        "/api/files/upload",
        files={"file": ("w2.txt", io.BytesIO(SENSITIVE_DOCUMENT.encode()), "text/plain")},
    )
    file_id = response.json()["id"]
    workflow = client.post(
        f"/api/workflows/{file_id}/process", json={"tax_year": 2025}
    ).json()

    previews = client.get(f"/api/workflows/{workflow['id']}/masked-preview").json()
    assert previews, "no masked preview returned"

    for preview in previews:
        for literal in FORBIDDEN_LITERALS:
            assert literal not in preview["masked_text"]
            assert literal not in str(preview["token_map"])


# ---------------------------------------------------------------------------
# Retrieved source passages
# ---------------------------------------------------------------------------


def test_source_redaction_strips_contact_details_but_keeps_substance() -> None:
    """Regression: a crawled page with an office email blocked the whole answer.

    Public tax authority routinely lists a contact email or phone. The guard
    cannot tell those from client data and correctly refused to transmit them,
    which broke every answer grounded in such a page.
    """
    from app.services.llm_egress_guard import redact_blocking_patterns

    page = (
        "Contact the IRS at taxpayer.advocate@irs.gov for assistance.\n"
        "Employer identification number 41-2233445 goes on line 1b.\n"
        "The standard deduction for 2024 is $14,600 for single filers.\n"
        "Mail to 1111 Constitution Ave NW, Washington, DC 20224."
    )
    redacted = redact_blocking_patterns(page)

    assert "taxpayer.advocate@irs.gov" not in redacted
    assert "41-2233445" not in redacted
    # Tax substance must survive, or the answer degrades.
    assert "$14,600" in redacted
    assert "standard deduction for 2024" in redacted
    # Advisory patterns are load-bearing in guidance and stay intact.
    assert "Constitution Ave" in redacted

    assert EgressGuard().scan({"prompt": redacted}).is_safe


def test_guard_recognises_reserved_surrogate_ranges_without_an_allow_list() -> None:
    """Regression: the guard blocked our own substitutes on the chat path.

    Chat masks per request, so there is no workflow-scoped surrogate set to hand
    the guard. A client email became a surrogate at ``example.com`` — still
    email-shaped — and the strict guard refused the request. Every surrogate is
    minted from a range that cannot exist in reality, so recognising the range
    is as sound as an allow-list.
    """
    guard = EgressGuard()
    for surrogate in (
        "steven.sinclair@example.com",
        "a.b@example.org",
        "x@sub.example.net",
        "(555) 555-0164",
        "666-91-2286",   # SSN area 666 is never issued
        "00-3457652",    # EIN prefix 00 is never issued
        "913-99-0000",   # ITIN surrogate: group 99 with serial 0000
    ):
        assert guard._is_known_surrogate(surrogate), surrogate


def test_the_guard_does_not_block_its_own_itin_surrogate() -> None:
    """Regression: one workpaper produced no return at all because of this.

    The ITIN surrogate keeps the 9xx-NN-xxxx shape so the model reads it as an
    identification number, and group 99 is inside the IRS-assigned range, so
    ``is_valid_itin`` accepts it. The guard saw a valid ITIN in the outbound
    payload and refused the whole request at llm_processing -- on a payload it
    had masked correctly itself.
    """
    from app.core.pii_patterns import PiiType
    from app.services.masking_service import generate_surrogate

    guard = EgressGuard()
    for original in ("912-70-1234", "998-88-4321", "955-65-0101"):
        surrogate = generate_surrogate(PiiType.ITIN, "ITIN_001", original)
        report = guard.scan({"text": f"Identification number {surrogate}"})
        assert not report.findings, f"{original} -> {surrogate} was blocked"


def test_a_real_itin_is_still_blocked() -> None:
    """The exemption is the surrogate triple, not the ITIN shape."""
    guard = EgressGuard()
    for real in ("912-70-1234", "912-99-1234", "999-88-7777"):
        assert guard.scan({"text": f"ITIN {real}"}).findings, real


def test_reserved_range_recognition_does_not_overmatch() -> None:
    """Look-alike domains are registrable and must not be treated as reserved."""
    guard = EgressGuard()
    for real in (
        "daniel.okonkwo@example-mail.com",  # example-mail.com is registrable
        "victim@examples.com",              # examples.com is registrable
        "someone@clientfirm.com",
        "(207) 555-0142",                   # real area code, not the 555-555 block
    ):
        assert not guard._is_known_surrogate(real), real

    # Emails block outright.
    for real_email in (
        "daniel.okonkwo@example-mail.com",
        "victim@examples.com",
        "someone@clientfirm.com",
    ):
        assert not guard.scan({"prompt": f"contact\n{real_email}"}).is_safe, real_email

    # Phone numbers are advisory by design — reported, but too noisy in tax
    # documents to block a send on their own.
    phone_report = guard.scan({"prompt": "contact\n(207) 555-0142"})
    assert phone_report.findings, "a real phone number should still be reported"
    assert all(finding.advisory for finding in phone_report.findings)


def test_chat_question_containing_client_email_is_transmittable(session) -> None:  # type: ignore[no-untyped-def]
    """End-to-end: masking a client email must not trip the guard."""
    from app.services.masking_service import MaskingService, MaskStyle
    from app.services.pii_detection_service import DetectionConfig, PiiDetectionService

    question = (
        "My client Daniel Okonkwo, email daniel.okonkwo@example-mail.com, "
        "sold stock at a loss. How does the wash sale rule apply?"
    )
    detector = PiiDetectionService(DetectionConfig(mask_organizations=False))
    masker = MaskingService(session, workflow_id=None, style=MaskStyle.SURROGATE)
    masked = masker.mask_text(question, detector.detect(question)).masked_text

    assert "daniel.okonkwo@example-mail.com" not in masked
    # A strict guard with no allow-list must still accept the masked form.
    assert EgressGuard().scan({"prompt": masked}).is_safe


def test_uuid_entity_ids_are_not_mistaken_for_phone_numbers() -> None:
    """A machine-generated id must never be read as taxpayer PII.

    Regression for an intermittent pipeline abort. Almost every audit payload
    carries an entity id, and 1.39% of random UUID4s contain a digit run that
    matches the US phone rule — 2128087569 inside the id below reads as
    212-808-7569. The guard failed closed on data that was never PII, so
    roughly one run in twenty died with a misleading privacy error.

    The frequency is why this test pins specific ids rather than generating
    them: a random UUID passes 98.6% of the time and would have hidden the bug
    exactly as effectively as it hid in production.
    """
    from app.core.audit import _assert_clean

    for entity_id in (
        "fd8d60a0-d05e-494f-aef5-2128087569f8",
        "2ea2c5cf-30b4-406b-b7ee-3c7458976907",
        "904856fa-efda-485e-84d7-9465763441ba",
    ):
        _assert_clean({"uploaded_file_id": entity_id, "workflow_id": entity_id})


def test_the_uuid_exemption_does_not_weaken_the_guard() -> None:
    """Exempting ids must not create a hole a real value can hide in."""
    from app.core.audit import AuditPayloadError, _assert_clean

    for payload in (
        {"note": "reach the client on 212-808-7569"},
        {"note": "ssn 412-88-7364"},
        {"note": "dawn@example-mail.com"},
        # A phone number sitting next to an id is still a phone number.
        {"id": "fd8d60a0-d05e-494f-aef5-2128087569f8", "phone": "415-555-0132"},
    ):
        with pytest.raises(AuditPayloadError):
            _assert_clean(payload)


def test_no_surrogate_reads_as_a_different_identifier() -> None:
    """A surrogate must not be mistakable for some other kind of identifier.

    An unconstrained nine-digit account-number surrogate starts with 9 about a
    tenth of the time, and 44 of every 100 second-pairs fall inside an
    IRS-assigned ITIN group -- so 4.5% of them were valid ITINs. A 1099-B
    carries dozens of account numbers, so one workpaper tripped it on every
    run: the egress guard found an ITIN the masker had itself minted, blocked
    the payload, and that return was never produced.

    This is the same shape as the audit log's UUID-versus-phone collision. The
    invariant is general, so the test is too: no surrogate of any type may
    produce a *blocking* finding of a different type.
    """
    from app.core.pii_patterns import PiiType
    from app.services.masking_service import generate_surrogate

    guard = EgressGuard()
    checked = 0
    for pii_type in (
        PiiType.ACCOUNT_NUMBER,
        PiiType.BANK_ACCOUNT,
        PiiType.SSN,
        PiiType.ITIN,
        PiiType.EIN,
    ):
        for index in range(400):
            original = f"{100000000 + index * 7919}"
            surrogate = generate_surrogate(pii_type, f"{pii_type.value}_{index}", original)
            blocking = [
                finding.pii_type
                for finding in guard.scan({"text": f"Reference {surrogate}"}).findings
                if not finding.advisory and finding.pii_type is not pii_type
            ]
            assert not blocking, (
                f"{pii_type.value} surrogate {surrogate} reads as {blocking}"
            )
            checked += 1
    assert checked == 2000


def test_a_cusip_is_not_blocked_as_an_itin() -> None:
    """Regression: one workpaper produced no return on five consecutive batches.

    A CUSIP is the nine-character public identifier of a security, printed on
    every trade line of a 1099-B. MaskingService deliberately does not mask it
    -- masking it would corrupt the brokerage detail the model has to read --
    but the guard did not know that. All-digit CUSIPs are common, and one
    beginning with 9 whose second pair falls in an IRS-assigned group is a
    well-formed ITIN, so a brokerage statement reliably carried one.

    The masker and the guard now read the same CUSIP_RE, so they cannot drift.
    """
    from app.services.pii_detection_service import PiiDetectionService

    guard = EgressGuard()
    detector = PiiDetectionService()
    cusip = "912705678"  # valid ITIN shape: group 70 is IRS-assigned

    for text in (
        f"CUSIP: {cusip}",
        f"XEROX HOLDINGS_ ABC / CUSIP: {cusip} / STATE: ABC",
        f"cusip {cusip}",
    ):
        blocking = [f for f in guard.scan({"text": text}).findings if not f.advisory]
        assert not blocking, f"{text!r} blocked on {[f.pii_type for f in blocking]}"
        # The masker's judgement and the guard's must agree.
        assert not [s for s in detector.detect(text) if s.pii_type is PiiType.ITIN]


def test_an_itin_outside_a_cusip_label_still_blocks() -> None:
    """The exemption is the CUSIP label, not the nine-digit shape."""
    guard = EgressGuard()
    for text in (
        "ITIN 912705678",
        "Identification number 912705678",
        "Taxpayer 912705678 CUSIP elsewhere on the page",
    ):
        assert guard.scan({"text": text}).findings, text
