"""In-process rate limiting.

A fixed-window counter keyed by client identity and route group. Adequate for a
single-process deployment; a multi-worker deployment needs a shared store
(Redis) so that limits are global rather than per worker.

SECURITY: rate limits protect the expensive and abusable paths — uploads (disk
and CPU), chat (LLM spend), and knowledge ingestion (outbound fetching) — and
blunt brute-force attempts against authenticated routes.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import RateLimitError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


class RateLimiter:
    """Fixed-window limiter with periodic cleanup of idle buckets."""

    _WINDOW_SECONDS = 60.0
    #: Drop buckets untouched for this long, so memory does not grow unbounded.
    _IDLE_EVICTION_SECONDS = 600.0

    def __init__(self) -> None:
        self._buckets: dict[str, _Window] = defaultdict(
            lambda: _Window(time.monotonic(), 0)
        )
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def check(self, key: str, limit_per_minute: int) -> None:
        """Consume one unit, raising ``RateLimitError`` when exhausted."""
        if limit_per_minute <= 0:
            return

        now = time.monotonic()
        with self._lock:
            self._maybe_sweep(now)
            window = self._buckets[key]
            if now - window.started_at >= self._WINDOW_SECONDS:
                window.started_at = now
                window.count = 0

            window.count += 1
            if window.count > limit_per_minute:
                retry_after = int(
                    self._WINDOW_SECONDS - (now - window.started_at)
                ) + 1
                # SECURITY: the key contains a client identifier; log the route
                # group only, so the log does not become an access record.
                group = key.split(":", 1)[0]
                logger.info("Rate limit exceeded for route group '%s'", group)
                raise RateLimitError(
                    f"Rate limit exceeded. Try again in {retry_after} seconds."
                )

    def _maybe_sweep(self, now: float) -> None:
        if now - self._last_sweep < self._IDLE_EVICTION_SECONDS:
            return
        stale = [
            key
            for key, window in self._buckets.items()
            if now - window.started_at > self._IDLE_EVICTION_SECONDS
        ]
        for key in stale:
            del self._buckets[key]
        self._last_sweep = now

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter


def enforce(group: str, client_id: str, limit_per_minute: int | None = None) -> None:
    """Apply the configured limit for ``group`` to ``client_id``."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    if limit_per_minute is None:
        limit_per_minute = {
            "upload": settings.rate_limit_upload_per_minute,
            "chat": settings.rate_limit_chat_per_minute,
        }.get(group, settings.rate_limit_default_per_minute)

    _limiter.check(f"{group}:{client_id}", limit_per_minute)
