"""Application configuration.

All configuration enters the process here and nowhere else. Services receive a
``Settings`` instance; they never read ``os.environ`` directly. That keeps the
set of tunable knobs discoverable and makes it possible to assert, in tests,
that a production configuration is safe.

SECURITY: ``Settings.validate_production_posture`` runs at import time via
``get_settings()`` and refuses to start the process when a development-only
escape hatch (disabled auth, disabled egress guard, missing encryption keys) is
still enabled while ``APP_ENV=production``.
"""

from __future__ import annotations

import secrets
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class EgressGuardMode(str, Enum):
    BLOCK = "block"
    WARN = "warn"


class Role(str, Enum):
    """RBAC roles, ordered least to most privileged.

    ADMIN      - full access including settings and retention purges
    REVIEWER   - may approve/reject review items and learned templates
    PREPARER   - may upload, run workflows, use the chatbot
    READONLY   - dashboards and audit logs only
    """

    ADMIN = "admin"
    REVIEWER = "reviewer"
    PREPARER = "preparer"
    READONLY = "readonly"


# Privilege ordering used by ``core.security.require_role``.
ROLE_RANK: dict[Role, int] = {
    Role.READONLY: 0,
    Role.PREPARER: 1,
    Role.REVIEWER: 2,
    Role.ADMIN: 3,
}


class Settings(BaseSettings):
    """Typed view over the environment. See ``backend/.env.example``."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_env: AppEnv = AppEnv.DEVELOPMENT
    app_name: str = "TaxScraper"
    app_version: str = "1.0.0"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Tax year ------------------------------------------------------------
    #: The tax year every product opens on when nobody has chosen one: the
    #: shared year selector, the depreciation calculator, the assistant (when
    #: the question names no year) and a workpaper whose documents state none.
    #: The only place the default is set (owner's decision 2026-10-11); each
    #: product clamps it to the years its rule data covers
    #: (``core.tax_year.resolve_default_year``), so a year with no rules is
    #: never offered. Bump it as part of the yearly rule update (README).
    default_tax_year: int = Field(default=2026, ge=2000, le=2100)

    # --- Secrets -----------------------------------------------------------
    secret_key: str = Field(default="")
    file_encryption_key: str = Field(default="")
    vault_encryption_key: str = Field(default="")

    # --- Database ----------------------------------------------------------
    database_url: str = "sqlite:///./data/taxscraper.db"
    database_echo: bool = False

    # --- Storage zones -----------------------------------------------------
    data_dir: Path = Path("./data")
    raw_zone_dir: Path = Path("./data/raw")
    masked_zone_dir: Path = Path("./data/masked")
    output_zone_dir: Path = Path("./data/output")
    tmp_zone_dir: Path = Path("./data/tmp")
    vector_store_dir: Path = Path("./data/vector")

    # --- Sample corpus -----------------------------------------------------
    tax_files_dir: Path = Path("./Files")
    tax_files_output_marker: str = "copy"

    # --- Gemini ------------------------------------------------------------
    gemini_api_key: str = ""
    gemini_model_flash: str = "gemini-3.6-flash"
    gemini_model_pro: str = "gemini-3.1-pro-preview"
    gemini_model_flash_lite: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: int = 120
    gemini_max_retries: int = 3
    #: Attempts allowed once a call has been rate limited. A quota window is a
    #: minute wide, so three attempts inside six seconds cannot outlast one.
    gemini_rate_limit_max_retries: int = 6
    #: Ceiling on cumulative waiting across rate-limited attempts of one call.
    gemini_rate_limit_max_wait_seconds: float = 180.0
    #: Floor on the gap between outbound calls. 0 disables; a 429 engages
    #: pacing automatically regardless.
    gemini_min_request_interval_seconds: float = 0.0
    gemini_temperature: float = 0.1
    gemini_enabled: bool = True

    # --- Egress guard ------------------------------------------------------
    llm_egress_guard_enabled: bool = True
    llm_egress_guard_mode: EgressGuardMode = EgressGuardMode.BLOCK

    # --- OCR ---------------------------------------------------------------
    tesseract_cmd: str = ""
    ocr_dpi: int = 300
    ocr_language: str = "eng"
    ocr_min_confidence: float = 60.0
    allow_cloud_ocr_fallback: bool = False

    # --- Uploads -----------------------------------------------------------
    max_upload_mb: int = 50
    allowed_upload_extensions: str = (
        ".pdf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.docx,.xlsx,.xls,.csv,.txt"
    )

    # --- Tax & audit assistant ---------------------------------------------
    #: The model that answers assistant questions, in one streamed call with
    #: Google Search grounding. Change it here or with ASSISTANT_MODEL;
    #: nothing else names the answering model.
    assistant_model: str = "gemini-3.8-flash"
    #: Gemini thinking level for the answer call ("low", "high"); empty uses
    #: the model's default. Thinking runs before the first token appears.
    #: "low" was chosen by an A/B on the 51-case eval (2026-10-09): same
    #: correctness (50/50), median first text 9.2 s vs 18.4 s, no withdrawn
    #: drafts vs 4, and about a fifth of the billed output tokens.
    assistant_thinking_level: str = "low"
    #: The small model that classifies a question before it is answered:
    #: answer type, scope, and whether it depends on state law. Empty turns
    #: routing off (every answer gets the general policy and the selected
    #: state always applies).
    assistant_router_model: str = "gemini-3.5-flash-lite"
    assistant_router_thinking_level: str = "minimal"
    #: The model that predicts an imported asset's life (its MACRS class)
    #: from its description. It never computes an amount; the depreciation
    #: engine does all the arithmetic from the class it picks.
    depreciation_life_model: str = "gemini-3.8-flash"
    depreciation_life_thinking_level: str = "low"
    #: Replay a checked answer to the same general question asked again the
    #: same day (per process, in memory). 0 entries or 0 seconds turns it off.
    assistant_cache_max_entries: int = 500
    assistant_cache_ttl_seconds: float = 6 * 3600.0
    #: Low on purpose: the same question should get the same facts.
    assistant_temperature: float = 0.2
    #: Prior (question, answer) pairs replayed for follow-ups.
    assistant_history_turns: int = 4
    #: Grounding returns Google redirect links that expire. When true the
    #: assistant reads one redirect hop (Location header only, never the page)
    #: so a stored citation still opens next month and shows the real domain.
    assistant_resolve_source_urls: bool = True
    assistant_resolve_timeout_seconds: float = 3.0
    #: Ceiling on attached-document text included in one prompt.
    assistant_max_attachment_chars: int = 12000
    #: User agent for the state updates panel's fetches.
    outbound_user_agent: str = "TaxScraperResearchBot/1.0"
    outbound_fetch_delay_seconds: float = 1.0
    outbound_cache_ttl_seconds: float = 900.0
    outbound_cache_max_entries: int = 128

    # --- State tax updates panel -------------------------------------------
    #: How long a state's fetched updates are reused. An agency newsroom
    #: changes a few times a month; refetching per page load would make this
    #: app a nuisance on fifty state government websites for no benefit.
    state_updates_cache_ttl_seconds: float = 1800.0
    #: Off switch for the panel. With this false the UI shows the agency's own
    #: links instead of fetched headlines, which is the correct behaviour on a
    #: deployment with no outbound network rather than a broken panel.
    state_updates_enabled: bool = True

    # --- Industry Updates feed --------------------------------------------
    #: Public sources (IRS, Treasury) are fetched by a background refresh and
    #: cached; ``false`` shows the sources' own links instead of items.
    news_enabled: bool = True
    #: How long a fetched feed stays fresh before the next background refresh.
    news_refresh_seconds: float = 1800.0
    #: Minimum gap between two fetches of the same source, whoever asks.
    news_min_fetch_interval_seconds: float = 300.0
    # Licensed sources. SECURITY: credentials come only from the environment
    # and never reach the browser; the sources stay disabled while unset.
    bloomberg_tax_api_url: str = ""
    bloomberg_tax_api_key: str = ""
    thomson_reuters_api_url: str = ""
    thomson_reuters_api_key: str = ""

    # --- Outbound TLS ------------------------------------------------------
    # SECURITY: on networks that inspect TLS (corporate proxies), outbound
    # fetches fail cert verification because the proxy re-signs traffic with a
    # private root the bundled CA list does not trust. Using the OS trust store
    # (which already trusts that root — the browser works) fixes it WITHOUT
    # disabling verification. Never disable verification to work around this.
    use_os_truststore: bool = True
    #: Optional explicit PEM bundle; overrides the OS store when set.
    ca_bundle_path: str = ""

    # --- Confidence --------------------------------------------------------
    confidence_auto_approve: float = 0.90
    confidence_escalate: float = 0.75
    calc_tolerance_dollars: float = 1.00

    # --- Retention ---------------------------------------------------------
    retention_raw_days: int = 2555
    retention_masked_days: int = 365
    retention_tmp_days: int = 7
    retention_audit_days: int = 2555

    # --- Rate limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_default_per_minute: int = 120
    rate_limit_upload_per_minute: int = 20
    rate_limit_chat_per_minute: int = 30

    # --- Daily quotas ------------------------------------------------------
    # Burst limits above bound how fast; these bound how much in a day, and
    # survive the restarts a sleeping free-tier service does several times a
    # day. Zero or below means unlimited for that dimension.
    #
    # The *_global values are the ones that bound third-party API spend: a
    # per-client cap multiplied by an unknown number of testers is not a bound.
    # Defaults are sized for a small shared test deployment, not for a firm.
    daily_quota_enabled: bool = True
    daily_quota_default_per_client: int = 200
    daily_quota_default_global: int = 2000
    daily_quota_upload_per_client: int = 5
    daily_quota_upload_global: int = 40
    daily_quota_chat_per_client: int = 25
    daily_quota_chat_global: int = 200

    # --- Auth --------------------------------------------------------------
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    auth_disabled: bool = True
    dev_default_role: Role = Role.ADMIN
    #: The name the dashboard greets the development principal by
    #: (AUTH_DISABLED only; real accounts use their full name on record).
    dev_display_name: str = "Varun"

    # --- Bootstrap accounts ------------------------------------------------
    #: Accounts to create on start, as ``username:role:password`` separated by
    #: commas. The environment is the source of truth: an account whose stored
    #: password no longer matches the value here is reset to it, so rotating a
    #: tester's credential is an env change and a restart.
    #:
    #: SECURITY: this holds live passwords, so it belongs in the host's secret
    #: store and never in a committed file. It exists because a deployment with
    #: auth enabled and no way to create the first user cannot be signed in to
    #: at all. Values are hashed on read and never logged.
    bootstrap_users: str = ""

    # ----------------------------------------------------------------- utils
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extension_set(self) -> set[str]:
        return {
            e.strip().lower()
            for e in self.allowed_upload_extensions.split(",")
            if e.strip()
        }

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnv.PRODUCTION

    @field_validator("assistant_temperature")
    @classmethod
    def _temperature_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("ASSISTANT_TEMPERATURE must be between 0.0 and 2.0")
        return v

    @field_validator(
        "assistant_thinking_level", "assistant_router_thinking_level", "depreciation_life_thinking_level"
    )
    @classmethod
    def _thinking_level_known(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"", "minimal", "low", "medium", "high"}:
            raise ValueError("ASSISTANT_THINKING_LEVEL must be empty, minimal, low, medium or high")
        return v

    @model_validator(mode="after")
    def _normalise_and_check(self) -> Settings:
        self._anchor_paths_to_project_root()

        if self.confidence_escalate > self.confidence_auto_approve:
            raise ValueError(
                "CONFIDENCE_ESCALATE must be <= CONFIDENCE_AUTO_APPROVE"
            )
        self.validate_production_posture()
        return self

    def _anchor_paths_to_project_root(self) -> None:
        """Resolve relative paths against the repo root, not the CWD.

        Otherwise ``./data`` means ``backend/data`` when uvicorn is started from
        ``backend/`` but ``./data`` when started from the repo root — two
        different storage zones and two different databases depending on how the
        process happened to be launched.
        """
        for field_name in (
            "data_dir",
            "raw_zone_dir",
            "masked_zone_dir",
            "output_zone_dir",
            "tmp_zone_dir",
            "vector_store_dir",
            "tax_files_dir",
        ):
            value: Path = getattr(self, field_name)
            if not value.is_absolute():
                object.__setattr__(self, field_name, (PROJECT_ROOT / value).resolve())

        # Same reasoning for a Tesseract vendored into the repo.
        cmd = self.tesseract_cmd.strip()
        if cmd and not Path(cmd).is_absolute():
            object.__setattr__(
                self, "tesseract_cmd", str((PROJECT_ROOT / cmd).resolve())
            )

        # SQLite URLs carry a path too, and it has the same problem.
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix) :]
            if raw and not raw.startswith(("/", ":memory:")) and not Path(raw).is_absolute():
                resolved = (PROJECT_ROOT / raw).resolve()
                resolved.parent.mkdir(parents=True, exist_ok=True)
                object.__setattr__(
                    self, "database_url", f"{prefix}{resolved.as_posix()}"
                )

    def validate_production_posture(self) -> None:
        """Refuse to run with development escape hatches on in production.

        SECURITY: each of these individually is enough to leak client data.
        Failing closed at startup is far better than discovering it in a log.
        """
        if not self.is_production:
            return

        problems: list[str] = []
        if self.auth_disabled:
            problems.append("AUTH_DISABLED must be false in production")
        if not self.llm_egress_guard_enabled:
            problems.append("LLM_EGRESS_GUARD_ENABLED must be true in production")
        if self.llm_egress_guard_mode is not EgressGuardMode.BLOCK:
            problems.append("LLM_EGRESS_GUARD_MODE must be 'block' in production")
        if not self.file_encryption_key:
            problems.append("FILE_ENCRYPTION_KEY is required in production")
        if not self.vault_encryption_key:
            problems.append("VAULT_ENCRYPTION_KEY is required in production")
        if self.file_encryption_key and (
            self.file_encryption_key == self.vault_encryption_key
        ):
            problems.append(
                "FILE_ENCRYPTION_KEY and VAULT_ENCRYPTION_KEY must differ"
            )
        if not self.secret_key or self.secret_key.startswith("CHANGE_ME"):
            problems.append("SECRET_KEY must be set to a real random value")
        if self.allow_cloud_ocr_fallback:
            problems.append(
                "ALLOW_CLOUD_OCR_FALLBACK sends raw unmasked images off-host; "
                "it must be explicitly reviewed before enabling in production"
            )
        if problems:
            raise RuntimeError(
                "Unsafe production configuration:\n  - " + "\n  - ".join(problems)
            )

    def ensure_directories(self) -> None:
        """Create the storage zones if missing. Idempotent."""
        for path in (
            self.data_dir,
            self.raw_zone_dir,
            self.masked_zone_dir,
            self.output_zone_dir,
            self.tmp_zone_dir,
            self.vector_store_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def effective_secret_key(self) -> str:
        """Return the signing key, generating an ephemeral one in dev.

        An ephemeral key means dev JWTs stop working across restarts, which is
        the correct trade-off: it is impossible to accidentally ship a
        well-known default signing key to production.
        """
        if self.secret_key and not self.secret_key.startswith("CHANGE_ME"):
            return self.secret_key
        if self.is_production:  # pragma: no cover - blocked by validator above
            raise RuntimeError("SECRET_KEY is required in production")
        return _EPHEMERAL_DEV_SECRET


_EPHEMERAL_DEV_SECRET = secrets.token_urlsafe(64)

#: Repository root — the directory containing ``backend/`` and ``frontend/``.
#: config.py lives at ``backend/app/core/config.py``, so three parents up.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that ``Settings`` is constructed (and validated) exactly once.
    Tests clear the cache via ``get_settings.cache_clear()``.
    """
    settings = Settings()
    settings.ensure_directories()
    return settings
