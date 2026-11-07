"""Focused tests for source-verified claim policy metadata updates."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from claimsage.api.routes import claims as claim_routes
from claimsage.db.models import AuditEvent, Claim, Employee, EmployeeRole
from claimsage.schemas.claims import ClaimPolicyMetadataUpdate
from claimsage.services.claim_access import ClaimAccessDeniedError


def _employee(role: EmployeeRole = EmployeeRole.CLAIMS_ADJUSTER) -> Employee:
    return Employee(
        id=uuid4(),
        email="aarav.sharma@example.test",
        display_name="Aarav Sharma",
        role=role,
        team_id="property-team",
    )


def _claim() -> Claim:
    return Claim(
        id=uuid4(),
        claim_number="CLM-TEST-POLICY-001",
        claimant_name="Priya Patel",
        claim_type="property",
        status="under_review",
        team_id="property-team",
        summary="Synthetic policy metadata test.",
        created_at=datetime.now(UTC),
    )


def _payload() -> ClaimPolicyMetadataUpdate:
    return ClaimPolicyMetadataUpdate(
        policy_identifier="  SYN-PROP-POL-001  ",
        loss_date=date(2026, 6, 15),
        verified_against_source=True,
    )


def test_update_saves_normalized_verified_metadata_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee = _employee()
    claim = _claim()
    session = MagicMock(spec=Session)
    monkeypatch.setattr(
        claim_routes,
        "get_authorized_claim",
        MagicMock(return_value=claim),
    )

    response = claim_routes.update_claim_policy_metadata(
        claim_id=claim.id,
        payload=_payload(),
        employee=employee,
        session=session,
    )

    assert response.policy_identifier == "SYN-PROP-POL-001"
    assert response.loss_date == date(2026, 6, 15)
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(claim)
    event = session.add.call_args.args[0]
    assert isinstance(event, AuditEvent)
    assert event.actor_employee_id == employee.id
    assert event.action == "claim_policy_metadata_verified"
    assert event.resource_id == str(claim.id)


def test_inaccessible_claim_cannot_update_policy_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee = _employee()
    claim_id = uuid4()
    session = MagicMock(spec=Session)
    monkeypatch.setattr(
        claim_routes,
        "get_authorized_claim",
        MagicMock(
            side_effect=ClaimAccessDeniedError(
                "Claim not found or access denied."
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        claim_routes.update_claim_policy_metadata(
            claim_id=claim_id,
            payload=_payload(),
            employee=employee,
            session=session,
        )

    assert exc_info.value.status_code == 404
    session.commit.assert_not_called()
    session.add.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {
            "policy_identifier": "SYN-PROP-POL-001",
            "loss_date": date(2026, 6, 15),
            "verified_against_source": False,
        },
        {
            "policy_identifier": "   ",
            "loss_date": date(2026, 6, 15),
            "verified_against_source": True,
        },
        {
            "policy_identifier": "SYN-PROP-POL-001",
            "verified_against_source": True,
        },
    ],
)
def test_metadata_requires_nonblank_identity_date_and_source_check(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ClaimPolicyMetadataUpdate.model_validate(values)


def test_health_claim_metadata_requires_insurer_and_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee = _employee()
    claim = _claim()
    claim.claim_type = "health"
    session = MagicMock(spec=Session)
    monkeypatch.setattr(
        claim_routes,
        "get_authorized_claim",
        MagicMock(return_value=claim),
    )

    with pytest.raises(HTTPException) as exc_info:
        claim_routes.update_claim_policy_metadata(
            claim_id=claim.id,
            payload=_payload(),
            employee=employee,
            session=session,
        )

    assert exc_info.value.status_code == 422
    session.commit.assert_not_called()


def test_health_claim_metadata_saves_normalized_insurer_and_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee = _employee()
    claim = _claim()
    claim.claim_type = "health"
    session = MagicMock(spec=Session)
    monkeypatch.setattr(
        claim_routes,
        "get_authorized_claim",
        MagicMock(return_value=claim),
    )
    payload = ClaimPolicyMetadataUpdate(
        policy_identifier="SYN-HEALTH-001",
        insurer_name="  New India Assurance  ",
        product_name="  New India Mediclaim Policy  ",
        loss_date=date(2022, 6, 12),
        verified_against_source=True,
    )

    response = claim_routes.update_claim_policy_metadata(
        claim_id=claim.id,
        payload=payload,
        employee=employee,
        session=session,
    )

    assert response.insurer_name == "New India Assurance"
    assert response.product_name == "New India Mediclaim Policy"
    session.commit.assert_called_once()
