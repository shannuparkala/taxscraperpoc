"""First-run bootstrap: seed rows the application assumes exist."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Role, Settings, get_settings
from app.core.logging import get_logger
from app.core.security import DEV_PRINCIPAL_ID, hash_password, verify_password
from app.models.database_models import User

logger = get_logger(__name__)


def ensure_dev_principal(session: Session, settings: Settings | None = None) -> User | None:
    """Create the development user that ``AUTH_DISABLED`` mode acts as.

    Several tables carry a foreign key to ``users`` (``uploaded_by``,
    ``reviewed_by``, ``approved_by``). With auth disabled the request principal
    is a fixed synthetic id, so that row has to exist or every insert referencing
    it fails.

    SECURITY: this account has no password hash and cannot be authenticated
    against. It is a referential placeholder, not a usable login, and it is only
    created when ``AUTH_DISABLED`` is true — which config refuses in production.
    """
    settings = settings or get_settings()
    if not settings.auth_disabled:
        return None

    existing = session.execute(
        select(User).where(User.id == DEV_PRINCIPAL_ID)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(
        id=DEV_PRINCIPAL_ID,
        username="dev",
        full_name="Development User",
        # No password_hash: verify_password() can never succeed against None.
        password_hash=None,
        role=settings.dev_default_role.value,
        is_active=True,
    )
    session.add(user)
    session.flush()
    logger.info(
        "Seeded the development principal with role '%s' (AUTH_DISABLED=true)",
        settings.dev_default_role.value,
    )
    return user


#: Below this, a password is not worth the process of setting one.
_MIN_PASSWORD_LENGTH = 12


def _parse_bootstrap_users(raw: str) -> list[tuple[str, Role, str]]:
    """Parse ``username:role:password`` triples, skipping anything malformed.

    SECURITY: a malformed entry is skipped with a message naming the position
    and never the value — a log line quoting a bad entry would print a live
    password into the host's log retention.
    """
    accounts: list[tuple[str, Role, str]] = []
    for index, entry in enumerate(raw.split(","), start=1):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3:
            logger.error(
                "BOOTSTRAP_USERS entry %d ignored: expected username:role:password",
                index,
            )
            continue
        username, role_name, password = (p.strip() for p in parts)
        if not username or not password:
            logger.error("BOOTSTRAP_USERS entry %d ignored: empty field", index)
            continue
        try:
            role = Role(role_name.lower())
        except ValueError:
            logger.error(
                "BOOTSTRAP_USERS entry %d ignored: '%s' is not a role", index, role_name
            )
            continue
        if len(password) < _MIN_PASSWORD_LENGTH:
            logger.error(
                "BOOTSTRAP_USERS entry %d ignored: password shorter than %d characters",
                index,
                _MIN_PASSWORD_LENGTH,
            )
            continue
        accounts.append((username, role, password))
    return accounts


def ensure_bootstrap_users(
    session: Session, settings: Settings | None = None
) -> int:
    """Create or reconcile the accounts named in ``BOOTSTRAP_USERS``.

    The environment is the source of truth. An account is created if missing,
    and its stored password is reset whenever the configured one no longer
    verifies — so rotating a tester's credential is an environment change and a
    restart, with no admin UI to build and no reset flow to secure.

    Returns the number of accounts created or changed.
    """
    settings = settings or get_settings()
    accounts = _parse_bootstrap_users(settings.bootstrap_users)
    if not accounts:
        return 0

    changed = 0
    for username, role, password in accounts:
        user = session.execute(
            select(User).where(func.lower(User.username) == username.lower())
        ).scalar_one_or_none()

        if user is None:
            session.add(
                User(
                    username=username,
                    full_name=username,
                    password_hash=hash_password(password),
                    role=role.value,
                    is_active=True,
                )
            )
            changed += 1
            logger.info("Seeded account '%s' with role '%s'", username, role.value)
            continue

        # Reconcile an existing account against the environment.
        updates: list[str] = []
        if not user.password_hash or not verify_password(password, user.password_hash):
            user.password_hash = hash_password(password)
            updates.append("password")
        if user.role != role.value:
            user.role = role.value
            updates.append("role")
        if not user.is_active:
            user.is_active = True
            updates.append("reactivated")
        if updates:
            changed += 1
            logger.info("Updated account '%s' (%s)", username, ", ".join(updates))

    session.flush()
    return changed


def warn_if_unreachable(session: Session, settings: Settings | None = None) -> None:
    """Say so loudly when auth is on and nobody can sign in.

    The failure this catches is silent and total: a deployment with
    ``AUTH_DISABLED=false`` and no account with a password answers 401 to every
    request including the sign-in it needs, and looks from the outside like a
    broken build rather than a missing environment variable.
    """
    settings = settings or get_settings()
    if settings.auth_disabled:
        return

    usable = session.execute(
        select(func.count())
        .select_from(User)
        .where(User.password_hash.is_not(None), User.is_active.is_(True))
    ).scalar_one()

    if not usable:
        logger.error(
            "No account can sign in: AUTH_DISABLED is false and no active user "
            "has a password. Set BOOTSTRAP_USERS (username:role:password, "
            "comma separated) and restart, or every request will be refused."
        )


def bootstrap() -> None:
    """Run all first-run seeding in its own transaction."""
    from app.core.db import session_scope

    with session_scope() as session:
        ensure_dev_principal(session)
        ensure_bootstrap_users(session)
        warn_if_unreachable(session)
