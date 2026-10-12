"""Cryptography, authentication, and role-based access control.

Two encryption contexts exist and are deliberately kept apart:

* ``file_cipher()``  — encrypts uploaded originals at rest in the raw zone.
* ``vault_cipher()`` — encrypts the token vault mapping tokens back to real
  values.

SECURITY: they use different keys on purpose. Compromise of the file key
exposes documents; compromise of the vault key exposes the identity mapping.
Requiring both raises the bar for a full breach, and it means a backup of one
zone is not sufficient to reconstruct client identities.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from jose import JWTError, jwt

from app.core.config import ROLE_RANK, Role, Settings, get_settings
from app.core.errors import AuthenticationError, AuthorizationError
from app.core.logging import get_logger

logger = get_logger(__name__)

_KDF_ITERATIONS = 480_000
#: Fixed salt for deriving a dev-only key from SECRET_KEY. Acceptable *only*
#: because it is never used in production (config.py enforces real keys there).
_DEV_SALT = b"taxscraper-dev-key-derivation-v1"


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def _derive_dev_key(seed: str, context: str) -> bytes:
    """Deterministically derive a Fernet key from a seed, for development."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_DEV_SALT + context.encode(),
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(seed.encode()))


#: Filename holding the persisted development seed, inside DATA_DIR.
_DEV_SEED_FILENAME = ".dev_key_seed"


def _development_seed(settings: Settings) -> str:
    """Return a development key seed that is stable across restarts.

    Why this exists
    ---------------
    Deriving the development key from an in-memory random value looks harmless
    but silently destroys data: a file encrypted before a restart cannot be
    decrypted after one, because the key is gone. The failure surfaces far from
    its cause — as a decryption error when the pipeline later reads the file —
    so the seed is persisted instead.

    Resolution order:
      1. ``SECRET_KEY`` when it is a real configured value.
      2. A generated seed persisted at ``DATA_DIR/.dev_key_seed``.

    SECURITY: the seed file is gitignored (it sits inside ``data/``), created
    with owner-only permissions where the platform supports it, and is only ever
    consulted outside production — ``validate_production_posture`` requires
    explicit keys there.
    """
    configured = settings.secret_key
    if configured and not configured.startswith("CHANGE_ME"):
        return configured

    seed_path = settings.data_dir / _DEV_SEED_FILENAME
    try:
        if seed_path.exists():
            existing = seed_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing

        seed = secrets.token_urlsafe(64)
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(seed, encoding="utf-8")
        try:
            seed_path.chmod(0o600)
        except OSError:
            # Windows without ACL support; the file is still inside the
            # gitignored data directory.
            pass

        logger.warning(
            "Generated a persistent development key seed at %s. Encrypted data "
            "now survives restarts. Set FILE_ENCRYPTION_KEY and "
            "VAULT_ENCRYPTION_KEY before handling real client data.",
            seed_path,
        )
        return seed
    except OSError as exc:
        # Falling back to a process-local seed would resurrect the original bug,
        # so fail loudly instead of silently making data unrecoverable.
        raise RuntimeError(
            f"Could not read or create the development key seed at {seed_path} "
            f"({type(exc).__name__}). Set FILE_ENCRYPTION_KEY and "
            "VAULT_ENCRYPTION_KEY explicitly, or make the data directory "
            "writable."
        ) from exc


def _load_cipher(configured_key: str, context: str, settings: Settings) -> Fernet:
    if configured_key:
        try:
            return Fernet(configured_key.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"Invalid Fernet key for {context}. Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            ) from exc

    if settings.is_production:  # pragma: no cover - blocked by config validator
        raise RuntimeError(f"{context} encryption key is required in production")

    logger.warning(
        "No %s encryption key configured; using a derived development key. "
        "Set %s_ENCRYPTION_KEY before handling client data.",
        context,
        context.upper(),
    )
    return Fernet(_derive_dev_key(_development_seed(settings), context))


@lru_cache(maxsize=1)
def file_cipher() -> Fernet:
    """Cipher for the raw zone (uploaded originals)."""
    settings = get_settings()
    return _load_cipher(settings.file_encryption_key, "file", settings)


@lru_cache(maxsize=1)
def vault_cipher() -> Fernet:
    """Cipher for the token vault (token -> original value)."""
    settings = get_settings()
    return _load_cipher(settings.vault_encryption_key, "vault", settings)


def encrypt_bytes(data: bytes, *, vault: bool = False) -> bytes:
    return (vault_cipher() if vault else file_cipher()).encrypt(data)


class DecryptionKeyMismatchError(RuntimeError):
    """Ciphertext exists but the current key cannot open it.

    Almost always means the encryption key changed after the data was written —
    a key was added to ``.env``, rotated, or (before the seed was persisted) an
    ephemeral development key was lost on restart. The data is not corrupt; it
    is simply unreadable without the original key.
    """


def decrypt_bytes(token: bytes, *, vault: bool = False) -> bytes:
    zone = "token vault" if vault else "raw file"
    variable = "VAULT_ENCRYPTION_KEY" if vault else "FILE_ENCRYPTION_KEY"
    try:
        return (vault_cipher() if vault else file_cipher()).decrypt(token)
    except InvalidToken as exc:
        # Plain ASCII: this string reaches Windows consoles and log files whose
        # encoding is not guaranteed to be UTF-8.
        raise DecryptionKeyMismatchError(
            f"Could not decrypt {zone} data with the current key. This happens "
            f"when {variable} changes after data was written - for example when "
            "a key is added, rotated, or regenerated. Data encrypted under the "
            "previous key cannot be recovered without it. Re-upload the "
            "affected files, or restore the original key."
        ) from exc


def encrypt_text(text: str, *, vault: bool = False) -> str:
    return encrypt_bytes(text.encode("utf-8"), vault=vault).decode("ascii")


def decrypt_text(token: str, *, vault: bool = False) -> str:
    return decrypt_bytes(token.encode("ascii"), vault=vault).decode("utf-8")


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    """Content hash for upload dedupe and audit chain-of-custody."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Any, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def blind_index(value: str) -> str:
    """Keyed one-way index over a sensitive value.

    Lets the vault answer "have I already tokenized this exact value?" without
    storing or comparing plaintext.

    SECURITY: keyed HMAC, not a bare hash. A bare SHA-256 of an SSN is
    trivially reversible — the whole keyspace is 10^9 and fits in a rainbow
    table. The key makes the index useless to anyone who steals only the DB.
    """
    key = get_settings().effective_secret_key().encode()
    normalised = " ".join(value.split()).casefold()
    return hmac.new(key, normalised.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# ---------------------------------------------------------------------------
# Authentication / RBAC
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. Carries no PII beyond a display name."""

    user_id: str
    username: str
    role: Role

    def has_at_least(self, required: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[required]


DEV_PRINCIPAL_ID = "00000000-0000-0000-0000-000000000001"


def create_access_token(
    principal: Principal, *, expires_minutes: int | None = None
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_minutes
    )
    claims = {
        "sub": principal.user_id,
        "username": principal.username,
        "role": principal.role.value,
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(
        claims,
        settings.effective_secret_key(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> Principal:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.effective_secret_key(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        # SECURITY: do not echo the JWT library's reason to the client; it can
        # distinguish "expired" from "bad signature" and aid token forgery.
        logger.info("Rejected access token: %s", type(exc).__name__)
        raise AuthenticationError("Invalid or expired credentials.") from exc

    try:
        role = Role(claims["role"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Token is missing a valid role claim.") from exc

    return Principal(
        user_id=str(claims.get("sub", "")),
        username=str(claims.get("username", "unknown")),
        role=role,
    )


def require_role(principal: Principal, required: Role) -> None:
    """Raise unless ``principal`` meets ``required`` privilege."""
    if not principal.has_at_least(required):
        logger.info(
            "Authorization denied: role=%s required=%s",
            principal.role.value,
            required.value,
        )
        raise AuthorizationError(
            f"This action requires the '{required.value}' role or higher."
        )


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 with a per-password salt, stored as ``salt$hash``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _KDF_ITERATIONS)
    return f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, digest_b64 = stored.split("$", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _KDF_ITERATIONS)
    return hmac.compare_digest(candidate, expected)
