"""Authorized read-only audit logging and timeline API endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import Employee, InvestigationRun
from claimsage.db.session import get_db
from claimsage.schemas.audit import AuditEventResponse, AuditTimelineResponse
from claimsage.services.audit import (
    query_claim_audit_events,
    query_enterprise_audit_events,
    query_investigation_audit_events,
)
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Enterprise Audit"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Claim or investigation not found, or access denied.",
    )


def _val(param: Any, default: Any = None) -> Any:
    """Helper to unwrap FastAPI Query default objects if called directly in tests."""
    if hasattr(param, "default"):
        return param.default
    return param if param is not None else default


@router.get(
    "/claims/{claim_id}/audit",
    response_model=AuditTimelineResponse,
)
def get_claim_audit_timeline(
    claim_id: UUID,
    event_category: str | None = Query(default=None),
    actor_type: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> AuditTimelineResponse:
    """Retrieve the append-only audit trail for an authorized claim."""
    clean_limit = int(_val(limit, 50))
    clean_offset = int(_val(offset, 0))
    clean_category = _val(event_category, None)
    clean_actor = _val(actor_type, None)
    clean_outcome = _val(outcome, None)
    clean_since = _val(since, None)
    clean_until = _val(until, None)

    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    events, total_count = query_claim_audit_events(
        session,
        claim_id=claim_id,
        event_category=clean_category,
        actor_type=clean_actor,
        outcome=clean_outcome,
        since=clean_since,
        until=clean_until,
        limit=clean_limit,
        offset=clean_offset,
    )

    return AuditTimelineResponse(
        items=[AuditEventResponse.model_validate(e) for e in events],
        total_count=total_count,
        limit=clean_limit,
        offset=clean_offset,
    )


@router.get(
    "/agent/investigations/{investigation_id}/audit",
    response_model=AuditTimelineResponse,
)
def get_investigation_audit_timeline(
    investigation_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> AuditTimelineResponse:
    """Retrieve chronological audit trail for a specific investigation."""
    clean_limit = int(_val(limit, 50))
    clean_offset = int(_val(offset, 0))

    investigation = session.get(InvestigationRun, investigation_id)
    if investigation is None:
        raise _not_found()

    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=investigation.claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    events, total_count = query_investigation_audit_events(
        session,
        investigation_id=investigation_id,
        limit=clean_limit,
        offset=clean_offset,
    )

    return AuditTimelineResponse(
        items=[AuditEventResponse.model_validate(e) for e in events],
        total_count=total_count,
        limit=clean_limit,
        offset=clean_offset,
    )


@router.get(
    "/audit/events",
    response_model=AuditTimelineResponse,
)
def list_enterprise_audit_events(
    event_category: str | None = Query(default=None),
    actor_type: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> AuditTimelineResponse:
    """Retrieve enterprise audit trail with RBAC authorization and filtering."""
    clean_limit = int(_val(limit, 50))
    clean_offset = int(_val(offset, 0))
    clean_category = _val(event_category, None)
    clean_actor = _val(actor_type, None)
    clean_outcome = _val(outcome, None)
    clean_since = _val(since, None)
    clean_until = _val(until, None)

    events, total_count = query_enterprise_audit_events(
        session,
        employee=employee,
        event_category=clean_category,
        actor_type=clean_actor,
        outcome=clean_outcome,
        since=clean_since,
        until=clean_until,
        limit=clean_limit,
        offset=clean_offset,
    )

    return AuditTimelineResponse(
        items=[AuditEventResponse.model_validate(e) for e in events],
        total_count=total_count,
        limit=clean_limit,
        offset=clean_offset,
    )
