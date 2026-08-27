"""
Fernet-based credential store. Spec Section 6.

**This is the ONLY module in the project permitted to decrypt a credential.**
Collectors call `get_credential(target_id)`; they never read the credentials table,
never touch a Fernet key, and never see ciphertext. That is enforceable by review
because the decryption primitive appears exactly once, here.

Three rules from Section 6, implemented rather than described:

1.  The Fernet key comes from `os.environ["SECRETS_KEY"]` and is never hardcoded and
    never committed. `.env` is gitignored; `.env.example` carries a placeholder.
2.  The credentials table stores **only ciphertext**. Plaintext is never written,
    never logged, and never returned in an audit record.
3.  Every call to `get_credential()` writes an `audit_log` row with
    `event_type='credential_used'` carrying the `target_id` — and never the credential
    value itself.

On key custody: the weakness of this design is not the cipher. Fernet is AES-128-CBC
with HMAC-SHA256 and is fine. The weakness is that the key sits in an environment
variable on the same host as the ciphertext, so anyone who can read the process
environment can decrypt the store. Production would delegate to Vault or a cloud KMS,
which moves the key out of the application's blast radius and adds rotation and
per-use audit logging. Building that is an explicit non-goal (Section 8); documenting
precisely what is being traded away is not. See architecture.md §4.
"""

from __future__ import annotations

import datetime
import os
import uuid

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from models.schema import Credential


class SecretsError(Exception):
    """Raised when the key is absent/invalid or a credential cannot be resolved."""


def _fernet() -> Fernet:
    key = os.environ.get("SECRETS_KEY")
    if not key:
        raise SecretsError(
            "SECRETS_KEY is not set. Copy .env.example to .env and generate a key "
            "with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise SecretsError(f"SECRETS_KEY is not a valid Fernet key: {exc}") from exc


def _audit(session, target_id: str, actor: str, result: str, detail: str | None = None,
           correlation_id=None, run_id=None) -> None:
    """Write the credential_used row.

    `details` carries the target_id and never the credential. There is deliberately no
    code path here that could place a secret in an audit record.
    """
    session.execute(
        text(
            "INSERT INTO audit_log (event_id, correlation_id, run_id, actor, "
            "event_type, timestamp, result, details) VALUES "
            "(:e, :c, :r, :a, 'credential_used', :t, :res, CAST(:d AS jsonb))"
        ),
        {
            "e": str(uuid.uuid4()),
            "c": str(correlation_id or uuid.uuid4()),
            "r": str(run_id) if run_id else None,
            "a": actor,
            "t": datetime.datetime.now(datetime.timezone.utc),
            "res": result,
            "d": __import__("json").dumps(
                {"target_id": target_id, **({"detail": detail} if detail else {})}
            ),
        },
    )


def store_credential(
    session,
    target_id: str,
    secret: str,
    credential_type: str = "ssh_private_key",
    description: str | None = None,
) -> None:
    """Encrypt and store a credential. Overwrites any existing one for the target.

    The plaintext `secret` is encrypted immediately and is not retained, logged or
    echoed. No audit row is written for storage itself — Section 6 requires auditing
    credential *use*, and a store event carrying a target_id adds nothing that the
    row's existence does not already show.
    """
    ciphertext = _fernet().encrypt(secret.encode()).decode()

    existing = session.get(Credential, target_id)
    if existing is None:
        session.add(
            Credential(
                target_id=target_id,
                credential_type=credential_type,
                ciphertext=ciphertext,
                description=description,
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )
    else:
        existing.credential_type = credential_type
        existing.ciphertext = ciphertext
        existing.description = description


def get_credential(
    session,
    target_id: str,
    actor: str = "system",
    correlation_id=None,
    run_id=None,
) -> str:
    """Decrypt and return the credential for `target_id`.

    Writes a `credential_used` audit row on every call — including failed lookups and
    failed decryptions, because an attempt to use a credential that does not exist or
    cannot be decrypted is at least as interesting to an investigator as a successful
    one.
    """
    row = session.get(Credential, target_id)
    if row is None:
        _audit(session, target_id, actor, "not_found", correlation_id=correlation_id,
               run_id=run_id)
        raise SecretsError(f"no credential stored for target_id {target_id!r}")

    try:
        plaintext = _fernet().decrypt(row.ciphertext.encode()).decode()
    except InvalidToken as exc:
        # Wrong key, or tampered ciphertext. Both are security events.
        _audit(session, target_id, actor, "decrypt_failed", correlation_id=correlation_id,
               run_id=run_id)
        raise SecretsError(
            f"could not decrypt credential for {target_id!r}: wrong SECRETS_KEY or "
            f"the stored ciphertext has been tampered with"
        ) from exc

    _audit(session, target_id, actor, "ok", correlation_id=correlation_id, run_id=run_id)
    return plaintext


def has_credential(session, target_id: str) -> bool:
    """Whether a credential exists, WITHOUT decrypting it.

    Deliberately separate from `get_credential` so that an existence check never
    triggers a decryption or a `credential_used` audit row — auditing a use that did
    not happen is as misleading as failing to audit one that did.
    """
    return session.get(Credential, target_id) is not None
