"""Structured logging with a mandatory PII redaction backstop.

SECURITY: ``PiiRedactionFilter`` is installed on the root logger and rewrites
every record — message, args, and exception text — before a handler can emit it.

This is a *backstop*, not a licence. Code must still avoid passing client data
to a logger in the first place: the filter only catches patterned values, so it
would not save us from logging a taxpayer's name. The rule in CLAUDE.md stands —
log tokens, never values.
"""

from __future__ import annotations

import logging
import logging.config
import re
import sys
from typing import Any

from app.core.pii_patterns import LOG_REDACTION_SPECS

#: What redacted spans are replaced with, e.g. ``[REDACTED:ssn]``.
_REPLACEMENT = "[REDACTED:{kind}]"


class PiiRedactionFilter(logging.Filter):
    """Scrub patterned sensitive data out of log records in place."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        # Pre-pair each compiled pattern with its replacement text so the hot
        # path is a plain loop over tuples.
        self._rules: list[tuple[re.Pattern[str], str]] = [
            (spec.regex, _REPLACEMENT.format(kind=spec.pii_type.value))
            for spec in LOG_REDACTION_SPECS
        ]

    def _scrub(self, text: str) -> str:
        for pattern, replacement in self._rules:
            text = pattern.sub(replacement, text)
        return text

    def _scrub_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._scrub(value)
        if isinstance(value, dict):
            return {k: self._scrub_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            scrubbed = [self._scrub_value(v) for v in value]
            return type(value)(scrubbed) if isinstance(value, list) else tuple(scrubbed)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        # Render lazily-formatted messages first so that "%s" arguments are
        # scrubbed too, then clear args to avoid double formatting downstream.
        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover - malformed format string
            rendered = str(record.msg)
        record.msg = self._scrub(rendered)
        record.args = ()

        if record.exc_text:
            record.exc_text = self._scrub(record.exc_text)

        # Scrub structured extras attached by callers.
        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_RECORD_KEYS:
                continue
            record.__dict__[key] = self._scrub_value(value)

        return True


_RESERVED_RECORD_KEYS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName",
    }
)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line output for local development."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<8}"
        return f"{base} {record.name:<38} {record.getMessage()}"


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Install handlers and the redaction filter on the root logger.

    Safe to call more than once; existing handlers are replaced.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(
            logging.Formatter(
                '{"ts":"%(asctime)s","level":"%(levelname)s",'
                '"logger":"%(name)s","message":"%(message)s"}'
            )
        )
    else:
        handler.setFormatter(ConsoleFormatter())

    # SECURITY: the filter goes on the handler *and* the root logger. Handler
    # filters do not apply to records propagated from child loggers that have
    # their own handlers, so both are needed for full coverage.
    redaction = PiiRedactionFilter()
    handler.addFilter(redaction)
    root.addFilter(redaction)

    root.addHandler(handler)
    root.setLevel(level.upper())

    # Third-party loggers are noisy and occasionally echo request bodies.
    for noisy in ("httpx", "httpcore", "urllib3", "google_genai", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # SECURITY: SQLAlchemy INFO logs full statements *with bound parameters*,
    # which for this schema means taxpayer values. Never below WARNING.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
