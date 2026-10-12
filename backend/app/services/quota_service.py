"""Daily usage quotas, durable across restarts.

``core.rate_limit`` answers "how fast" — a per-minute burst limiter held in
process memory. This answers "how much today", which is a different question
with a different failure mode: a free-tier host sleeps an idle service and
restarts it on the next request, so an in-memory daily counter resets several
times a day and caps nothing. These counters live in the database.

Two ceilings apply to every request, and the lower one wins:

* **per client** — one tester cannot consume the whole day's budget.
* **global** — the deployment as a whole. This is the one that actually bounds
  third-party API spend, because a per-client cap multiplied by an unknown
  number of testers is not a bound at all.

SECURITY: the scope key holds a user id or a client address and never a name or
any document content. Counts are ``DERIVED`` data. Exceeding a quota raises
``RateLimitError``, which the error handler maps to HTTP 429 — the caller is
told to come back tomorrow, not why the budget exists or how much others used.

Single-instance assumption, the same one ``core.rate_limit`` documents: counts
are read, incremented and written without a row lock. Two instances behind a
load balancer would each miss some of the other's increments and the effective
ceiling would drift upward. The free-tier deployments this exists for run one
instance; anything larger wants the counter in Redis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import RateLimitError
from app.core.logging import get_logger
from app.models.database_models import UsageCounter

logger = get_logger(__name__)

#: The scope every request counts against in addition to its own.
GLOBAL_SCOPE = "global"

#: Route groups that carry their own daily ceiling. Anything else falls to the
#: default. These are the two expensive paths: uploads burn CPU and disk on a
#: 512 MB box, and chat burns model spend.
KNOWN_GROUPS = ("upload", "chat", "default")


def current_day() -> str:
    """The UTC calendar day the counters are keyed by."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    """What is left, for one scope and group, today."""

    scope: str
    route_group: str
    day: str
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        if self.limit <= 0:
            return -1  # unlimited
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.limit > 0 and self.used >= self.limit


class QuotaService:
    """Reads and increments the durable daily counters."""

    def __init__(self, session: Session, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    # ------------------------------------------------------------- limits

    def per_client_limit(self, route_group: str) -> int:
        settings = self._settings
        return {
            "upload": settings.daily_quota_upload_per_client,
            "chat": settings.daily_quota_chat_per_client,
        }.get(route_group, settings.daily_quota_default_per_client)

    def global_limit(self, route_group: str) -> int:
        settings = self._settings
        return {
            "upload": settings.daily_quota_upload_global,
            "chat": settings.daily_quota_chat_global,
        }.get(route_group, settings.daily_quota_default_global)

    # ------------------------------------------------------------- reading

    def _row(self, scope: str, route_group: str, day: str) -> UsageCounter | None:
        return self._session.execute(
            select(UsageCounter).where(
                UsageCounter.scope == scope,
                UsageCounter.route_group == route_group,
                UsageCounter.day == day,
            )
        ).scalar_one_or_none()

    def status(self, scope: str, route_group: str) -> QuotaStatus:
        day = current_day()
        row = self._row(scope, route_group, day)
        limit = (
            self.global_limit(route_group)
            if scope == GLOBAL_SCOPE
            else self.per_client_limit(route_group)
        )
        return QuotaStatus(
            scope=scope,
            route_group=route_group,
            day=day,
            used=row.count if row else 0,
            limit=limit,
        )

    def snapshot(self, client_scope: str) -> dict[str, dict[str, int]]:
        """Everything a caller may want to show a tester who hit a wall."""
        report: dict[str, dict[str, int]] = {}
        for group in KNOWN_GROUPS:
            mine = self.status(client_scope, group)
            everyone = self.status(GLOBAL_SCOPE, group)
            report[group] = {
                "used": mine.used,
                "limit": mine.limit,
                "remaining": mine.remaining,
                "global_used": everyone.used,
                "global_limit": everyone.limit,
                "global_remaining": everyone.remaining,
            }
        return report

    # ------------------------------------------------------------ writing

    def _increment(self, scope: str, route_group: str, day: str) -> int:
        """Add one and return the new count, creating the row if needed."""
        row = self._row(scope, route_group, day)
        if row is None:
            row = UsageCounter(scope=scope, route_group=route_group, day=day, count=0)
            self._session.add(row)
            try:
                self._session.flush()
            except IntegrityError:
                # Another request created the same window between the select
                # and the flush. Take theirs.
                self._session.rollback()
                row = self._row(scope, route_group, day)
                if row is None:  # pragma: no cover - defensive
                    raise
        row.count += 1
        self._session.flush()
        return row.count

    def consume(self, route_group: str, client_id: str) -> None:
        """Count one request, raising once either ceiling is reached.

        Checked before incrementing, so a limit of 10 permits exactly 10
        requests rather than 9. Both counters advance together: a request the
        client is allowed to make still consumes global budget.
        """
        if not self._settings.daily_quota_enabled:
            return

        day = current_day()
        client_scope = f"client:{client_id}"

        for scope, limit in (
            (client_scope, self.per_client_limit(route_group)),
            (GLOBAL_SCOPE, self.global_limit(route_group)),
        ):
            if limit <= 0:
                continue  # unlimited
            row = self._row(scope, route_group, day)
            if row is not None and row.count >= limit:
                # SECURITY: the scope key can carry a user id, so log the shape
                # of the refusal and not the identity behind it.
                logger.info(
                    "Daily quota exhausted: group=%s scope=%s limit=%d",
                    route_group,
                    "global" if scope == GLOBAL_SCOPE else "client",
                    limit,
                )
                raise RateLimitError(self._message(scope, route_group, limit))

        self._increment(client_scope, route_group, day)
        self._increment(GLOBAL_SCOPE, route_group, day)

    @staticmethod
    def _message(scope: str, route_group: str, limit: int) -> str:
        what = {
            "upload": "document runs",
            "chat": "chat questions",
        }.get(route_group, "requests")
        if scope == GLOBAL_SCOPE:
            return (
                f"This shared test deployment has used its {limit} {what} for "
                "today. The allowance resets at midnight UTC."
            )
        return (
            f"You have used your {limit} {what} for today. The allowance resets "
            "at midnight UTC."
        )


def enforce_daily_quota(route_group: str, client_id: str) -> None:
    """Module-level entry point, mirroring ``rate_limit.enforce``.

    Runs in its own transaction rather than the request's. The ledger has to
    record the attempt whatever becomes of the request: an upload that fails
    during OCR has already spent the CPU, and one that fails after extraction
    has already spent the model call. Rolling the count back with the request
    would make every failure free and hand a caller an easy way around the cap.
    """
    from app.core.db import session_scope

    with session_scope() as session:
        QuotaService(session).consume(route_group, client_id)
