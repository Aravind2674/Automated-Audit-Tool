"""
SQLAlchemy models mirroring the PostgreSQL DDL in CLAUDE.md Section 3.

Column types, constraints and CHECK clauses are kept deliberately identical to the
spec's DDL so that the schema this code creates and the schema documented in the spec
cannot drift apart.

APPEND-ONLY TABLES: `results` and `audit_log`. No code anywhere in this project may
issue an UPDATE or DELETE against them. Current compliance posture is derived as
"results where run_id = the latest completed run", never stored as mutable state.
The `runs` table is not append-only -- `completed_at` and `status` are set when a scan
finishes, which the spec explicitly contemplates.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Control(Base):
    __tablename__ = "controls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    applies_to: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    framework_mappings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    test_logic: Mapped[dict] = mapped_column(JSONB, nullable=False)
    remediation: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="controls_severity_check",
        ),
    )


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, nullable=False)


class Result(Base):
    """APPEND-ONLY. Never UPDATE. Never DELETE."""

    __tablename__ = "results"

    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.run_id"), nullable=False
    )
    control_id: Mapped[str] = mapped_column(
        String, ForeignKey("controls.id"), nullable=False
    )
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('pass','fail','error','manual_review')",
            name="results_outcome_check",
        ),
    )


class Exception_(Base):
    __tablename__ = "exceptions"

    exception_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    control_id: Mapped[str] = mapped_column(String, ForeignKey("controls.id"))
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String)
    approval_date: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    expiry_date: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    compensating_control: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('accepted_risk','false_positive','pending_review')",
            name="exceptions_status_check",
        ),
    )


class AuditLog(Base):
    """APPEND-ONLY. Never UPDATE. Never DELETE.

    event_type vocabulary — the authoritative list, kept current as events are added.

    CLAUDE.md Section 3's inline comment enumerates
    ``scan_started|scan_completed|control_evaluated|exception_approved|
    credential_used|report_exported``. That list was written before the exception
    workflow was built and is now incomplete: the workflow emits two further events
    that the spec's comment does not mention.

    Currently emitted (verified against both the codebase and the live audit_log):

    ==========================  =======  ====================================
    event_type                  phase    meaning
    ==========================  =======  ====================================
    scan_started                2        a scan began
    scan_completed              2        a scan finished
    control_evaluated           2        one control evaluated against a run
    exception_requested         4        an exception was requested (NOT in
                                         the spec's comment)
    exception_approved          4        an exception was approved
    exception_approval_denied   4        an approval was REFUSED for violating
                                         separation of duties (NOT in the
                                         spec's comment)
    ==========================  =======  ====================================

    ``exception_approval_denied`` is deliberately recorded rather than merely
    refused in memory. An attempted separation-of-duties violation is itself
    security-relevant: it is the audit trail's only record that someone tried to
    self-approve a high or critical finding.

    Declared in the spec but not yet emitted, because the features do not exist yet:

    * ``credential_used``   — arrives with secrets_manager (spec Section 6)
    * ``report_exported``   — arrives with the PDF exporter (Phase 6)

    No CHECK constraint is placed on this column: an audit log that rejects an
    unrecognised event is an audit log that can silently lose evidence when a new
    event type ships ahead of a migration.
    """

    __tablename__ = "audit_log"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
