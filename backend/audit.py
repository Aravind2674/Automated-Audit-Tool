"""
Append-only audit log sink.

The evaluator takes a sink object rather than importing the database directly, so
that engine/ stays free of persistence concerns and can be unit-tested without a
server. This module is the only place audit rows are written.

APPEND-ONLY: this file contains INSERT and nothing else. There is deliberately no
update or delete method, so that "never UPDATE, never DELETE" is enforced by the
absence of an API rather than by everyone remembering the rule.
"""

from __future__ import annotations

import datetime
import uuid

from models.schema import AuditLog


def _as_uuid(value):
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


class AuditSink:
    """Writes audit_log rows through a SQLAlchemy session."""

    def __init__(self, session, correlation_id, run_id=None, actor: str = "system"):
        self.session = session
        self.correlation_id = _as_uuid(correlation_id)
        self.run_id = _as_uuid(run_id)
        self.actor = actor

    def write(self, row: dict) -> None:
        self.session.add(
            AuditLog(
                event_id=_as_uuid(row.get("event_id")) or uuid.uuid4(),
                correlation_id=_as_uuid(row.get("correlation_id")) or self.correlation_id,
                run_id=_as_uuid(row.get("run_id")) or self.run_id,
                actor=row.get("actor") or self.actor,
                event_type=row["event_type"],
                timestamp=row.get("timestamp")
                or datetime.datetime.now(datetime.timezone.utc),
                result=row.get("result", "ok"),
                details=row.get("details"),
            )
        )

    def event(self, event_type: str, result: str = "ok", details: dict | None = None):
        """Convenience for lifecycle events (scan_started, scan_completed, ...)."""
        self.write(
            {
                "event_type": event_type,
                "result": result,
                "details": details,
            }
        )


class NullAuditSink:
    """Collects rows in memory. For tests and for runs without a database."""

    def __init__(self):
        self.rows: list[dict] = []

    def write(self, row: dict) -> None:
        self.rows.append(row)

    def event(self, event_type: str, result: str = "ok", details: dict | None = None):
        self.write({"event_type": event_type, "result": result, "details": details})
