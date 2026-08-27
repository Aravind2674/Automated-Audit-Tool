"""
Session-based authentication. Spec Section 1 ("simple session-based auth is
sufficient; do not build SSO/OAuth for MVP") and Section 8 (SSO/OAuth is a non-goal).

Design decisions worth defending:

* **Passwords are bcrypt hashes, never reversible.** The credentials table
  (`secrets_manager`) is deliberately decryptable — the collector needs the actual SSH
  key back. A password store must be the opposite: not recoverable even by the
  application. They are separate tables with separate handling for that reason, and
  conflating them would be the single worst mistake available here.

* **Sessions are server-side rows; the cookie carries only an opaque random id.**
  A self-contained signed token cannot be revoked before it expires without building
  the server-side state this table already is. Deleting the row ends the session
  immediately.

* **Session ids come from `secrets.token_urlsafe`**, i.e. the OS CSPRNG. Never
  `random`, which is seeded and predictable.

* **Login failures are audited.** A failed authentication is at least as interesting
  to an investigator as a successful one, and a brute-force attempt is invisible
  without it.
"""

from __future__ import annotations

import datetime
import json
import secrets as _secrets
import uuid

import bcrypt
from sqlalchemy import text

from models.schema import Session as SessionRow
from models.schema import User

SESSION_COOKIE = "audit_session"
SESSION_TTL = datetime.timedelta(hours=8)


class AuthError(Exception):
    """Raised on failed authentication or an invalid/expired session."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _audit(session, actor: str, event_type: str, result: str, details: dict) -> None:
    session.execute(
        text(
            "INSERT INTO audit_log (event_id, correlation_id, run_id, actor, "
            "event_type, timestamp, result, details) VALUES "
            "(:e, :c, NULL, :a, :et, :t, :r, CAST(:d AS jsonb))"
        ),
        {
            "e": str(uuid.uuid4()),
            "c": str(uuid.uuid4()),
            "a": actor,
            "et": event_type,
            "t": _now(),
            "r": result,
            "d": json.dumps(details),
        },
    )


def create_user(session, username: str, password: str, role: str = "auditor") -> None:
    """Create a local user. The plaintext password is hashed and discarded."""
    if not password or len(password) < 12:
        # Matches the spirit of CIS-5.3.1, which this tool enforces on audited hosts.
        # A compliance tool with a weaker password policy than the one it audits is
        # not a defensible position in a demo.
        raise AuthError("password must be at least 12 characters")

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    existing = session.get(User, username)
    if existing is None:
        session.add(
            User(username=username, password_hash=hashed, role=role,
                 created_at=_now(), disabled=False)
        )
    else:
        existing.password_hash = hashed
        existing.role = role


def login(session, username: str, password: str) -> str:
    """Verify credentials and open a session. Returns the session id."""
    user = session.get(User, username)

    # bcrypt.checkpw is run against a dummy hash even when the user does not exist,
    # so that a missing account and a wrong password take the same time. Otherwise the
    # response time itself enumerates valid usernames.
    dummy = "$2b$12$" + "." * 53
    stored = user.password_hash if user else dummy
    try:
        ok = bcrypt.checkpw(password.encode(), stored.encode())
    except ValueError:
        ok = False

    if user is None or user.disabled or not ok:
        _audit(session, username or "anonymous", "login_failed", "denied",
               {"username": username, "reason": "invalid credentials or disabled"})
        raise AuthError("invalid username or password")

    session_id = _secrets.token_urlsafe(32)
    session.add(
        SessionRow(session_id=session_id, username=username,
                   created_at=_now(), expires_at=_now() + SESSION_TTL)
    )
    _audit(session, username, "login_succeeded", "ok", {"username": username})
    return session_id


def logout(session, session_id: str) -> None:
    row = session.get(SessionRow, session_id)
    if row is not None:
        _audit(session, row.username, "logout", "ok", {"username": row.username})
        session.delete(row)


def resolve_session(session, session_id: str | None) -> User:
    """Return the User for a valid, unexpired session, or raise AuthError."""
    if not session_id:
        raise AuthError("no session")

    row = session.get(SessionRow, session_id)
    if row is None:
        raise AuthError("unknown session")

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    if expires <= _now():
        # Expired sessions are deleted on sight rather than left to accumulate.
        session.delete(row)
        raise AuthError("session expired")

    user = session.get(User, row.username)
    if user is None or user.disabled:
        raise AuthError("user disabled or removed")
    return user
