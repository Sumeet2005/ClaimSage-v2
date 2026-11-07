"""Centralized, append-only enterprise audit logging and activity tracking service."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from claimsage.db.models import AuditEvent, Claim, Employee, EmployeeRole

logger = logging.getLogger(__name__)

# Keys whose values must always be redacted in audit metadata
SENSITIVE_KEY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"password",
        r"token",
        r"secret",
        r"auth",
        r"cookie",
        r"credential",
        r"api_key",
        r"upload_token",
        r"jwt",
        r"ssn",
        r"credit_card",
        r"card_number",
        r"cvv",
        r"pan",
        r"account_number",
        r"pin",
        r"private_key",
    ]
]

SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")


class AuditActorType(StrEnum):
    EMPLOYEE = "employee"
    SYSTEM = "system"
    AI_AGENT = "ai_agent"


class AuditEventCategory(StrEnum):
    AUTH = "auth"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    INVESTIGATION = "investigation"
    AGENT_EXECUTION = "agent_execution"
    FINDING = "finding"
    HUMAN_REVIEW = "human_review"
    CUSTOMER_EMAIL = "customer_email"
    POLICY = "policy"
    ADMIN = "admin"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


def sanitize_metadata(data: Any, max_depth: int = 4) -> Any:
    """Recursively sanitize metadata: redacts sensitive keys and truncates long strings."""
    if max_depth <= 0:
        return "<depth_limit_reached>"

    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            key_str = str(key)
            if any(pattern.search(key_str) for pattern in SENSITIVE_KEY_PATTERNS):
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = sanitize_metadata(value, max_depth=max_depth - 1)
        return sanitized

    if isinstance(data, (list, tuple, set)):
        return [sanitize_metadata(item, max_depth=max_depth - 1) for item in list(data)[:100]]

    if isinstance(data, str):
        # Redact sensitive PII/PCI patterns in string values
        clean = SSN_REGEX.sub("[REDACTED_SSN]", data)
        clean = CARD_REGEX.sub("[REDACTED_CARD]", clean)
        # Truncate overly long text fields to avoid database bloat
        return clean[:2000] if len(clean) > 2000 else clean

    if isinstance(data, (int, float, bool)) or data is None:
        return data

    if isinstance(data, UUID):
        return str(data)

    if isinstance(data, datetime):
        return data.isoformat()

    return str(data)[:500]


def record_audit_event(
    session: Session,
    *,
    action: str,
    event_category: AuditEventCategory | str,
    resource_type: str,
    actor_type: AuditActorType | str = AuditActorType.EMPLOYEE,
    actor_id: str | None = None,
    actor_employee_id: UUID | None = None,
    claim_id: UUID | None = None,
    investigation_id: UUID | None = None,
    resource_id: str | None = None,
    outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
    details: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Append a tamper-resistant, sanitized audit event record.
    
    This function is strictly append-only. No updates or deletions are supported.
    """
    clean_metadata = sanitize_metadata(metadata or {})
    category_val = (
        event_category.value
        if isinstance(event_category, AuditEventCategory)
        else str(event_category)
    )
    actor_val = (
        actor_type.value
        if isinstance(actor_type, AuditActorType)
        else str(actor_type)
    )
    outcome_val = (
        outcome.value
        if isinstance(outcome, AuditOutcome)
        else str(outcome)
    )

    event = AuditEvent(
        actor_type=actor_val,
        actor_id=actor_id or (str(actor_employee_id) if actor_employee_id else None),
        actor_employee_id=actor_employee_id,
        claim_id=claim_id,
        investigation_id=investigation_id,
        event_category=category_val,
        action=action[:100],
        outcome=outcome_val[:20],
        resource_type=resource_type[:100],
        resource_id=resource_id[:100] if resource_id else None,
        request_id=request_id[:100] if request_id else None,
        correlation_id=correlation_id[:100] if correlation_id else None,
        details=details,
        event_metadata=clean_metadata,
    )

    session.add(event)
    return event


def record_employee_action(
    session: Session,
    *,
    employee: Employee,
    action: str,
    event_category: AuditEventCategory | str,
    resource_type: str,
    claim_id: UUID | None = None,
    investigation_id: UUID | None = None,
    resource_id: str | None = None,
    outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
    details: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """Record an action performed by an authenticated human employee."""
    return record_audit_event(
        session,
        action=action,
        event_category=event_category,
        resource_type=resource_type,
        actor_type=AuditActorType.EMPLOYEE,
        actor_id=employee.display_name,
        actor_employee_id=employee.id,
        claim_id=claim_id,
        investigation_id=investigation_id,
        resource_id=resource_id,
        outcome=outcome,
        details=details,
        metadata=metadata,
        correlation_id=correlation_id,
    )


def record_ai_agent_action(
    session: Session,
    *,
    agent_name: str,
    action: str,
    claim_id: UUID,
    investigation_id: UUID,
    resource_type: str = "investigation_agent",
    resource_id: str | None = None,
    outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
    details: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """Record an action performed by a LangGraph specialist AI agent."""
    return record_audit_event(
        session,
        action=action,
        event_category=AuditEventCategory.AGENT_EXECUTION,
        resource_type=resource_type,
        actor_type=AuditActorType.AI_AGENT,
        actor_id=agent_name,
        actor_employee_id=None,
        claim_id=claim_id,
        investigation_id=investigation_id,
        resource_id=resource_id,
        outcome=outcome,
        details=details,
        metadata=metadata,
        correlation_id=correlation_id,
    )


def record_system_action(
    session: Session,
    *,
    worker_id: str,
    action: str,
    event_category: AuditEventCategory | str,
    resource_type: str,
    claim_id: UUID | None = None,
    investigation_id: UUID | None = None,
    resource_id: str | None = None,
    outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
    details: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """Record an automated system or background worker activity."""
    return record_audit_event(
        session,
        action=action,
        event_category=event_category,
        resource_type=resource_type,
        actor_type=AuditActorType.SYSTEM,
        actor_id=worker_id,
        actor_employee_id=None,
        claim_id=claim_id,
        investigation_id=investigation_id,
        resource_id=resource_id,
        outcome=outcome,
        details=details,
        metadata=metadata,
        correlation_id=correlation_id,
    )


def query_claim_audit_events(
    session: Session,
    *,
    claim_id: UUID,
    event_category: str | None = None,
    actor_type: str | None = None,
    outcome: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    """Retrieve filtered, paginated audit records for an authorized claim."""
    base_conditions = [AuditEvent.claim_id == claim_id]

    if event_category:
        base_conditions.append(AuditEvent.event_category == event_category)
    if actor_type:
        base_conditions.append(AuditEvent.actor_type == actor_type)
    if outcome:
        base_conditions.append(AuditEvent.outcome == outcome)
    if since:
        base_conditions.append(AuditEvent.created_at >= since)
    if until:
        base_conditions.append(AuditEvent.created_at <= until)

    total_count = session.scalar(
        select(func.count(AuditEvent.id)).where(and_(*base_conditions))
    ) or 0

    events = session.scalars(
        select(AuditEvent)
        .options(selectinload(AuditEvent.actor_employee))
        .where(and_(*base_conditions))
        .order_by(desc(AuditEvent.created_at))
        .offset(offset)
        .limit(limit)
    ).all()

    return list(events), total_count


def query_investigation_audit_events(
    session: Session,
    *,
    investigation_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    """Retrieve audit timeline records for a specific investigation."""
    base_conditions = [AuditEvent.investigation_id == investigation_id]

    total_count = session.scalar(
        select(func.count(AuditEvent.id)).where(and_(*base_conditions))
    ) or 0

    events = session.scalars(
        select(AuditEvent)
        .options(selectinload(AuditEvent.actor_employee))
        .where(and_(*base_conditions))
        .order_by(desc(AuditEvent.created_at))
        .offset(offset)
        .limit(limit)
    ).all()

    return list(events), total_count


def query_enterprise_audit_events(
    session: Session,
    *,
    employee: Employee,
    event_category: str | None = None,
    actor_type: str | None = None,
    outcome: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    """Retrieve audit timeline records across enterprise operations with employee visibility scoping."""
    base_conditions = []

    # If employee is not an admin, scope to claims visible to employee or actions performed by employee
    if employee.role != EmployeeRole.ADMIN:
        claim_subquery = select(Claim.id).where(
            or_(
                Claim.assigned_employee_id == employee.id,
                Claim.team_id == employee.team_id,
            )
        )
        base_conditions.append(
            or_(
                AuditEvent.claim_id.in_(claim_subquery),
                AuditEvent.actor_employee_id == employee.id,
            )
        )

    if event_category:
        base_conditions.append(AuditEvent.event_category == event_category)
    if actor_type:
        base_conditions.append(AuditEvent.actor_type == actor_type)
    if outcome:
        base_conditions.append(AuditEvent.outcome == outcome)
    if since:
        base_conditions.append(AuditEvent.created_at >= since)
    if until:
        base_conditions.append(AuditEvent.created_at <= until)

    where_clause = and_(*base_conditions) if base_conditions else True

    total_count = session.scalar(
        select(func.count(AuditEvent.id)).where(where_clause)
    ) or 0

    events = session.scalars(
        select(AuditEvent)
        .options(selectinload(AuditEvent.actor_employee))
        .where(where_clause)
        .order_by(desc(AuditEvent.created_at))
        .offset(offset)
        .limit(limit)
    ).all()

    return list(events), total_count
