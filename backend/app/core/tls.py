"""Outbound TLS trust configuration.

SECURITY: this module exists to make certificate verification *work* on
networks that intercept TLS — never to weaken it. It resolves the trust anchors
outbound HTTPS should use; verification always stays on.

Precedence:
1. ``CA_BUNDLE_PATH`` — an explicit PEM bundle (e.g. an exported corporate root).
2. ``USE_OS_TRUSTSTORE`` — verify against the operating-system trust store,
   which on a managed machine already trusts the proxy's root CA.
3. Otherwise the library default (certifi).
"""

from __future__ import annotations

import ssl
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_injected = False


def build_ssl_context(settings: Settings | None = None) -> ssl.SSLContext | str | bool:
    """Return an httpx-compatible ``verify`` value that keeps verification on.

    * ``str``          -> path to a PEM CA bundle.
    * ``ssl.SSLContext`` -> OS-trust-store-backed context.
    * ``True``         -> library default (certifi).
    """
    settings = settings or get_settings()

    if settings.ca_bundle_path:
        return settings.ca_bundle_path

    if settings.use_os_truststore:
        try:
            import truststore

            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception as exc:  # pragma: no cover - depends on platform/deps
            logger.warning(
                "OS truststore unavailable (%s); falling back to the default "
                "CA bundle. Set CA_BUNDLE_PATH if outbound HTTPS fails.",
                type(exc).__name__,
            )

    return True


def configure_global_tls(settings: Settings | None = None) -> None:
    """Patch the stdlib default SSL context to use the OS trust store.

    Called once at startup so libraries that build their own clients
    (google-genai, requests) also trust the corporate root. Idempotent.
    """
    global _injected
    settings = settings or get_settings()

    if _injected or not settings.use_os_truststore or settings.ca_bundle_path:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
        _injected = True
        logger.info("Outbound TLS is using the OS trust store.")
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Could not enable the OS trust store (%s).", type(exc).__name__
        )


def httpx_verify(settings: Settings | None = None) -> Any:
    """Convenience alias for the value to pass as httpx ``verify=``."""
    return build_ssl_context(settings)
