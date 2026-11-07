"""Tests for POST /claims endpoint."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from claimsage.api.routes import claims as claim_routes
from claimsage.db.models import Claim, Employee, EmployeeRole
from claimsage.schemas.claims import ClaimCreateRequest


def _employee(role: EmployeeRole = EmployeeRole.CLAIMS_ADJUSTER, team_id: str = "health-team") -> Employee:
    return Employee(
        id=uuid4(),
        email="adjuster@claimsage.test",
        display_name="Adjuster User",
        role=role,
        team_id=team_id,
    )


def test_claim_create_request_validation():
    """Verify ClaimCreateRequest validation and field stripping."""
    payload = ClaimCreateRequest(
        claim_number="  CLM-2026-001  ",
        claimant_name="  Aarav Mehta  ",
        claim_type="health",
        policy_identifier="  STAR-HEALTH-001  ",
        loss_date=date(2026, 3, 10),
    )
    assert payload.claim_number == "CLM-2026-001"
    assert payload.claimant_name == "Aarav Mehta"
    assert payload.policy_identifier == "STAR-HEALTH-001"
    assert payload.claim_type == "health"

    # Invalid empty claimant name
    with pytest.raises(ValidationError):
        ClaimCreateRequest(
            claim_number="CLM-001",
            claimant_name="   ",
            claim_type="health",
        )

    # Invalid empty claim number
    with pytest.raises(ValidationError):
        ClaimCreateRequest(
            claim_number="   ",
            claimant_name="Aarav",
            claim_type="health",
        )


def test_create_claim_success():
    """Verify authorized adjuster creates a claim and emits an audit event."""
    employee = _employee()
    session = MagicMock(spec=Session)

    # Mock scalar to return None (no existing claim with this number)
    session.scalar.return_value = None

    payload = ClaimCreateRequest(
        claim_number="CLM-HEALTH-999",
        claimant_name="Sunita Rao",
        claim_type="health",
        policy_identifier="STAR-HEALTH-001",
        loss_date=date(2026, 4, 1),
        summary="Emergency appendectomy",
    )

    result = claim_routes.create_claim(payload=payload, employee=employee, session=session)

    assert result.claim_number == "CLM-HEALTH-999"
    assert result.claimant_name == "Sunita Rao"
    assert result.claim_type == "health"
    assert result.status == "under_review"
    assert result.policy_identifier == "STAR-HEALTH-001"
    assert result.team_id == "health-team"
    assert session.add.call_count == 2  # Claim and AuditEvent
    session.commit.assert_called_once()


def test_create_claim_duplicate_rejected():
    """Verify creating a claim with an existing claim number raises HTTP 409."""
    employee = _employee()
    session = MagicMock(spec=Session)

    existing_claim = Claim(
        id=uuid4(),
        claim_number="CLM-HEALTH-DUP",
        claimant_name="Existing Claimant",
        claim_type="health",
        status="under_review",
        team_id="health-team",
        created_at=datetime.now(UTC),
    )
    session.scalar.return_value = existing_claim

    payload = ClaimCreateRequest(
        claim_number="CLM-HEALTH-DUP",
        claimant_name="Sunita Rao",
        claim_type="health",
    )

    with pytest.raises(HTTPException) as exc_info:
        claim_routes.create_claim(payload=payload, employee=employee, session=session)

    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail


def test_create_claim_unauthorized_role():
    """Verify unauthorized roles (such as POLICY_SPECIALIST) cannot create claims."""
    policy_specialist = _employee(role=EmployeeRole.POLICY_SPECIALIST)
    session = MagicMock(spec=Session)

    payload = ClaimCreateRequest(
        claim_number="CLM-HEALTH-FORBIDDEN",
        claimant_name="Sunita Rao",
        claim_type="health",
    )

    with pytest.raises(HTTPException) as exc_info:
        claim_routes.create_claim(payload=payload, employee=policy_specialist, session=session)

    assert exc_info.value.status_code == 403
    assert "does not have permission" in exc_info.value.detail
