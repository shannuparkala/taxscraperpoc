"""Regression tests for encryption key stability.

Background
----------
An earlier build derived the development encryption key from a value generated
fresh in each process. Everything worked until the server restarted, at which
point every previously uploaded file became permanently undecryptable. The
symptom appeared far from the cause: the pipeline failed at its *upload* stage
with an opaque ``RuntimeError`` while trying to read a file that had uploaded
successfully minutes earlier.

These tests pin the two properties that prevent a recurrence:

1. The development key is stable across processes.
2. When a key genuinely cannot open the data, the failure is specific and
   actionable rather than a bare ``RuntimeError``.
"""

from __future__ import annotations

import io
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.security import (
    DecryptionKeyMismatchError,
    decrypt_bytes,
    encrypt_bytes,
    file_cipher,
    vault_cipher,
)

pytestmark = pytest.mark.security


def _key_fingerprint() -> str:
    """A stable, non-secret fingerprint of the active file key."""
    import hashlib

    return hashlib.sha256(file_cipher()._signing_key).hexdigest()[:16]


def test_development_key_is_stable_within_a_process() -> None:
    first = _key_fingerprint()
    file_cipher.cache_clear()
    assert _key_fingerprint() == first


def test_development_seed_is_persisted_to_disk() -> None:
    settings = get_settings()
    file_cipher()  # force derivation
    seed_file = settings.data_dir / ".dev_key_seed"
    assert seed_file.exists(), "the development seed must be written to disk"
    assert seed_file.read_text(encoding="utf-8").strip(), "the seed must not be empty"


def test_development_key_survives_a_process_restart(tmp_path: Path) -> None:
    """The exact scenario that broke: encrypt, restart, decrypt.

    A real subprocess is used rather than clearing caches in-process, because
    the original bug lived in module-level state that only a genuinely new
    interpreter reproduces.
    """
    backend_root = Path(__file__).resolve().parents[1]
    settings = get_settings()

    ciphertext_path = tmp_path / "payload.bin"
    ciphertext_path.write_bytes(encrypt_bytes(b"taxpayer document bytes"))

    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(backend_root)!r})
        from app.core.security import decrypt_bytes
        data = open({str(ciphertext_path)!r}, "rb").read()
        sys.stdout.write(decrypt_bytes(data).decode())
        """
    )

    environment = {
        **dict(__import__("os").environ),
        "DATA_DIR": str(settings.data_dir),
        "RAW_ZONE_DIR": str(settings.raw_zone_dir),
        "MASKED_ZONE_DIR": str(settings.masked_zone_dir),
        "OUTPUT_ZONE_DIR": str(settings.output_zone_dir),
        "TMP_ZONE_DIR": str(settings.tmp_zone_dir),
        "VECTOR_STORE_DIR": str(settings.vector_store_dir),
        "DATABASE_URL": settings.database_url,
        "APP_ENV": "development",
    }

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )

    assert result.returncode == 0, (
        "a fresh process could not decrypt data written by this one; the "
        f"development key is not stable.\nstderr:\n{result.stderr}"
    )
    assert result.stdout == "taxpayer document bytes"


def test_wrong_key_raises_a_specific_actionable_error() -> None:
    """A key mismatch must be diagnosable, not an opaque RuntimeError."""
    from cryptography.fernet import Fernet

    foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(b"written under another key")

    with pytest.raises(DecryptionKeyMismatchError) as caught:
        decrypt_bytes(foreign_ciphertext)

    message = str(caught.value)
    assert "FILE_ENCRYPTION_KEY" in message, "the message must name the variable to fix"
    assert "Re-upload" in message, "the message must state the recovery action"


def test_vault_and_file_keys_are_distinct() -> None:
    """Compromising one key must not unlock the other zone."""
    assert file_cipher()._signing_key != vault_cipher()._signing_key

    vault_ciphertext = encrypt_bytes(b"original taxpayer value", vault=True)
    with pytest.raises(DecryptionKeyMismatchError):
        decrypt_bytes(vault_ciphertext, vault=False)


def test_upload_then_process_across_restart_succeeds(client) -> None:  # type: ignore[no-untyped-def]
    """End-to-end guard on the user-visible symptom.

    The cipher caches are cleared between upload and processing to emulate the
    server restart that previously made the file unreadable.
    """
    document = (
        "2025 Form W-2 Wage and Tax Statement\n"
        "a Employee social security number: 412-88-7364\n"
        "1 Wages, tips, other compensation      82,500.00\n"
    )
    response = client.post(
        "/api/files/upload",
        files={"file": ("w2.txt", io.BytesIO(document.encode()), "text/plain")},
    )
    assert response.status_code == 201
    file_id = response.json()["id"]

    # Simulate a restart: drop every cached key.
    file_cipher.cache_clear()
    vault_cipher.cache_clear()

    processed = client.post(f"/api/workflows/{file_id}/process", json={"tax_year": 2025})
    assert processed.status_code == 201, processed.text
    assert processed.json()["status"] in {"completed", "awaiting_review"}


def test_unreadable_file_reports_conflict_not_server_error(client) -> None:  # type: ignore[no-untyped-def]
    """An undecryptable file is a client-actionable 409, never a 500."""
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.database_models import UploadedFile

    response = client.post(
        "/api/files/upload",
        files={"file": ("w2.txt", io.BytesIO(b"wages 100.00 reported"), "text/plain")},
    )
    file_id = response.json()["id"]

    # Corrupt the stored ciphertext so it cannot be opened by any key.
    with session_scope() as db_session:
        record = db_session.execute(
            select(UploadedFile).where(UploadedFile.id == file_id)
        ).scalar_one()
        stored = get_settings().raw_zone_dir / record.stored_filename
    stored.write_bytes(b"not-valid-fernet-ciphertext")

    processed = client.post(f"/api/workflows/{file_id}/process", json={})
    assert processed.status_code == 409
    body = processed.json()["error"]
    assert body["code"] == "file_unreadable"

    # And the file is quarantined so the UI can stop offering "Process".
    listed = client.get("/api/files").json()["items"]
    entry = next(item for item in listed if item["id"] == file_id)
    assert entry["status"] == "quarantined"
    assert entry["validation_notes"]
