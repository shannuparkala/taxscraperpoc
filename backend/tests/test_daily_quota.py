"""A daily cap that forgets itself is not a cap.

The per-minute limiter in ``core.rate_limit`` lives in process memory, which is
correct for a burst limit and useless for a daily one: the free-tier hosts this
guardrail exists for sleep an idle service and restart it on the next request,
several times a day. Each restart would hand the caller a fresh allowance.

So the tests that matter are about durability and about which ceiling bites
first — not about arithmetic. The global ceiling is the one that bounds
third-party API spend, because a per-client cap times an unknown number of
testers is not a bound.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import RateLimitError
from app.models.database_models import UsageCounter
from app.services.quota_service import (
    GLOBAL_SCOPE,
    QuotaService,
    current_day,
)


def _settings(**overrides) -> Settings:
    base = {
        "daily_quota_enabled": True,
        "daily_quota_default_per_client": 100,
        "daily_quota_default_global": 100,
        "daily_quota_upload_per_client": 3,
        "daily_quota_upload_global": 5,
        "daily_quota_chat_per_client": 10,
        "daily_quota_chat_global": 20,
    }
    base.update(overrides)
    return Settings(**base)


def _service(session, **overrides) -> QuotaService:
    return QuotaService(session, settings=_settings(**overrides))


def _count(session, scope: str, group: str) -> int:
    row = (
        session.query(UsageCounter)
        .filter_by(scope=scope, route_group=group, day=current_day())
        .one_or_none()
    )
    return row.count if row else 0


# ------------------------------------------------------------ the ceilings


def test_client_ceiling_permits_exactly_its_limit(session):
    service = _service(session)

    for _ in range(3):
        service.consume("upload", "alice")

    with pytest.raises(RateLimitError):
        service.consume("upload", "alice")

    assert _count(session, "client:alice", "upload") == 3


def test_global_ceiling_binds_across_clients(session):
    """The cap that actually bounds spend.

    Three testers, each well inside their own allowance, still cannot take the
    deployment past its daily total.
    """
    service = _service(session)

    service.consume("upload", "alice")
    service.consume("upload", "alice")
    service.consume("upload", "bob")
    service.consume("upload", "bob")
    service.consume("upload", "carol")

    # Global limit is 5 and carol has used only one of her own three.
    with pytest.raises(RateLimitError) as caught:
        service.consume("upload", "carol")

    assert "shared test deployment" in str(caught.value)
    assert _count(session, GLOBAL_SCOPE, "upload") == 5


def test_a_blocked_request_does_not_consume_budget(session):
    """Refusal must not advance the counter, or a client polling a closed door
    would keep the global counter climbing and starve everyone else."""
    service = _service(session)
    for _ in range(3):
        service.consume("upload", "alice")

    for _ in range(5):
        with pytest.raises(RateLimitError):
            service.consume("upload", "alice")

    assert _count(session, "client:alice", "upload") == 3
    assert _count(session, GLOBAL_SCOPE, "upload") == 3


def test_groups_are_budgeted_separately(session):
    """Exhausting document runs must not cost anyone the chatbot."""
    service = _service(session)
    for _ in range(3):
        service.consume("upload", "alice")

    service.consume("chat", "alice")  # must not raise
    assert _count(session, "client:alice", "chat") == 1


def test_unknown_group_falls_to_the_default_budget(session):
    service = _service(session, daily_quota_default_per_client=2)

    service.consume("default", "alice")
    service.consume("default", "alice")
    with pytest.raises(RateLimitError):
        service.consume("default", "alice")


# --------------------------------------------------------------- switches


def test_zero_means_unlimited(session):
    service = _service(
        session,
        daily_quota_upload_per_client=0,
        daily_quota_upload_global=0,
    )
    for _ in range(50):
        service.consume("upload", "alice")
    assert _count(session, "client:alice", "upload") == 50


def test_disabled_writes_nothing(session):
    service = _service(session, daily_quota_enabled=False)
    for _ in range(10):
        service.consume("upload", "alice")

    assert _count(session, "client:alice", "upload") == 0
    assert session.query(UsageCounter).count() == 0


# -------------------------------------------------------------- durability


def test_counts_survive_a_new_service_and_session(session):
    """The whole point: a restart must not hand back a fresh allowance.

    A new ``QuotaService`` over the same database stands in for the process
    that a sleeping free-tier host restarts on the next request.
    """
    _service(session).consume("upload", "alice")
    _service(session).consume("upload", "alice")
    session.commit()

    after_restart = _service(session)
    after_restart.consume("upload", "alice")
    with pytest.raises(RateLimitError):
        after_restart.consume("upload", "alice")


def test_status_reports_what_is_left(session):
    service = _service(session)
    service.consume("upload", "alice")

    mine = service.status("client:alice", "upload")
    assert (mine.used, mine.limit, mine.remaining) == (1, 3, 2)
    assert not mine.exhausted

    snapshot = service.snapshot("client:alice")
    assert snapshot["upload"]["remaining"] == 2
    assert snapshot["upload"]["global_remaining"] == 4
    assert snapshot["chat"]["used"] == 0


def test_status_reports_unlimited_as_minus_one(session):
    service = _service(session, daily_quota_upload_per_client=0)
    assert service.status("client:alice", "upload").remaining == -1


# --------------------------------------------------------------- security


@pytest.mark.security
def test_the_ledger_records_no_identity_beyond_an_opaque_scope(session):
    """DERIVED data only: a scope key and a count, never a name or a document.

    The counters outlive the requests that wrote them, so anything recorded
    here is retained well past the workflow's own lifetime.
    """
    _service(session).consume("upload", "user-1234")

    row = session.query(UsageCounter).filter_by(scope="client:user-1234").one()
    columns = {c.name for c in UsageCounter.__table__.columns}

    assert columns == {"id", "scope", "route_group", "day", "count", "updated_at"}
    assert row.scope == "client:user-1234"
    assert isinstance(row.count, int)


@pytest.mark.security
def test_refusal_message_does_not_leak_other_testers_usage(session):
    """A tester learns that the shared budget is gone, not who spent it."""
    service = _service(session)
    for name in ("alice", "bob", "carol", "dave", "erin"):
        service.consume("upload", name)

    with pytest.raises(RateLimitError) as caught:
        service.consume("upload", "frank")

    message = str(caught.value)
    for name in ("alice", "bob", "carol", "dave", "erin"):
        assert name not in message
