"""Unit and integration tests for Phase 4: Enterprise Audit Logging and Activity Tracking."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from claimsage.api.routes.audit import (
    get_claim_audit_timeline,
    get_investigation_audit_timeline,
    router as audit_router,
)
from claimsage.db.models import (
    AuditEvent,
    Claim,
    Employee,
    EmployeeRole,
    InvestigationRun,
)
from claimsage.services.audit import (
    AuditActorType,
    AuditEventCategory,
    AuditOutcome,
    query_claim_audit_events,
    query_investigation_audit_events,
    record_ai_agent_action,
    record_audit_event,
    record_employee_action,
    record_system_action,
    sanitize_metadata,
)
from claimsage.services.claim_access import ClaimAccessDeniedError


@pytest.fixture
def adjuster_employee() -> Employee:
    return Employee(
        id=uuid4(),
        email="adjuster@claimsage.local",
        display_name="Senior Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="health-team",
    )


@pytest.fixture
def mock_claim() -> Claim:
    return Claim(
        id=uuid4(),
        claim_number="CLM-HEALTH-001",
        claimant_name="Jane Doe",
        claim_type="health",
        team_id="health-team",
    )


@pytest.fixture
def mock_investigation(mock_claim: Claim) -> InvestigationRun:
    return InvestigationRun(
        id=uuid4(),
        claim_id=mock_claim.id,
        claim_domain="health",
        status="running",
    )


def test_metadata_sanitization_redacts_credentials():
    """Verify passwords, tokens, API keys, cookies, credentials, and SSNs are redacted."""
    sensitive_payload = {
        "user_email": "user@example.com",
        "password": "supersecretpassword123",
        "api_key": "live_key_998877",
        "auth_header": "Bearer eyJhbGciOi...",
        "access_token": "token_abc123",
        "session_cookie": "sess_xyz",
        "user_credential": "raw_secret_data",
        "upload_token": "upl_tok_456",
        "nested": {
            "jwt_token": "secret_jwt",
            "claimant_ssn": "000-12-3456",
            "public_id": "PUB-1234",
        },
        "items": [
            {"secret_code": "classified", "item_name": "Crutches"},
        ],
    }

    sanitized = sanitize_metadata(sensitive_payload)

    # Sensitive fields redacted
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["auth_header"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["session_cookie"] == "[REDACTED]"
    assert sanitized["user_credential"] == "[REDACTED]"
    assert sanitized["upload_token"] == "[REDACTED]"
    assert sanitized["nested"]["jwt_token"] == "[REDACTED]"
    assert sanitized["nested"]["claimant_ssn"] == "[REDACTED]"
    assert sanitized["items"][0]["secret_code"] == "[REDACTED]"

    # Non-sensitive fields preserved
    assert sanitized["user_email"] == "user@example.com"
    assert sanitized["nested"]["public_id"] == "PUB-1234"
    assert sanitized["items"][0]["item_name"] == "Crutches"


def test_metadata_sanitization_truncates_large_payloads():
    """Verify long text strings (>2000 chars) are truncated to prevent storage bloat."""
    oversized_text = "A" * 5000
    sanitized = sanitize_metadata({"document_excerpt": oversized_text})

    assert len(sanitized["document_excerpt"]) == 2000
    assert sanitized["document_excerpt"] == "A" * 2000


def test_record_audit_event_all_categories():
    """Verify all 10 enterprise audit event categories can be recorded."""
    session = MagicMock()
    claim_id = uuid4()
    investigation_id = uuid4()

    for category in AuditEventCategory:
        event = record_audit_event(
            session,
            action=f"action_{category.value}",
            event_category=category,
            resource_type="test_resource",
            claim_id=claim_id,
            investigation_id=investigation_id,
            metadata={"test_key": "test_val"},
        )
        assert event.event_category == category.value
        assert event.action == f"action_{category.value}"
        assert event.event_metadata == {"test_key": "test_val"}
        session.add.assert_called_with(event)


def test_record_employee_action(adjuster_employee: Employee, mock_claim: Claim):
    """Verify human employee actions populate employee actor details and attribution."""
    session = MagicMock()

    event = record_employee_action(
        session,
        employee=adjuster_employee,
        action="approve_investigation_report",
        event_category=AuditEventCategory.HUMAN_REVIEW,
        resource_type="investigation_report",
        claim_id=mock_claim.id,
        outcome=AuditOutcome.SUCCESS,
        details="Adjuster approved the findings",
        metadata={"decision": "approved"},
    )

    assert event.actor_type == "employee"
    assert event.actor_id == "Senior Adjuster"
    assert event.actor_employee_id == adjuster_employee.id
    assert event.event_category == "human_review"
    assert event.action == "approve_investigation_report"
    assert event.outcome == "success"
    assert event.details == "Adjuster approved the findings"
    assert event.event_metadata == {"decision": "approved"}
    session.add.assert_called_once_with(event)


def test_record_ai_agent_action(mock_claim: Claim, mock_investigation: InvestigationRun):
    """Verify AI agent actions set actor_type='ai_agent' and agent name attribution."""
    session = MagicMock()

    event = record_ai_agent_action(
        session,
        agent_name="MedicalSpecialist",
        action="medical_necessity_assessed",
        claim_id=mock_claim.id,
        investigation_id=mock_investigation.id,
        details="Analyzed surgical necessity and procedure codes",
        metadata={"confidence": "high", "flags_count": 0},
    )

    assert event.actor_type == "ai_agent"
    assert event.actor_id == "MedicalSpecialist"
    assert event.actor_employee_id is None
    assert event.event_category == "agent_execution"
    assert event.action == "medical_necessity_assessed"
    assert event.claim_id == mock_claim.id
    assert event.investigation_id == mock_investigation.id
    assert event.event_metadata == {"confidence": "high", "flags_count": 0}
    session.add.assert_called_once_with(event)


def test_record_system_action(mock_claim: Claim):
    """Verify automated system activities record actor_type='system' and worker ID."""
    session = MagicMock()

    event = record_system_action(
        session,
        worker_id="investigation-worker-node-1",
        action="investigation_stale_lease_recovered",
        event_category=AuditEventCategory.INVESTIGATION,
        resource_type="investigation_run",
        claim_id=mock_claim.id,
        outcome=AuditOutcome.SUCCESS,
        details="Recovered abandoned lock lease after 15m timeout",
    )

    assert event.actor_type == "system"
    assert event.actor_id == "investigation-worker-node-1"
    assert event.actor_employee_id is None
    assert event.event_category == "investigation"
    assert event.action == "investigation_stale_lease_recovered"
    session.add.assert_called_once_with(event)


def test_query_claim_audit_events_filters_and_pagination(mock_claim: Claim):
    """Verify query filtering by category, actor_type, outcome and pagination."""
    session = MagicMock()
    mock_events = [MagicMock(spec=AuditEvent), MagicMock(spec=AuditEvent)]
    session.scalar.return_value = 42
    session.scalars.return_value.all.return_value = mock_events

    events, total = query_claim_audit_events(
        session,
        claim_id=mock_claim.id,
        event_category="human_review",
        actor_type="employee",
        outcome="success",
        limit=10,
        offset=20,
    )

    assert events == mock_events
    assert total == 42
    session.scalar.assert_called_once()
    session.scalars.assert_called_once()


def test_query_investigation_audit_events(mock_investigation: InvestigationRun):
    """Verify investigation-level audit timeline query and pagination."""
    session = MagicMock()
    mock_events = [MagicMock(spec=AuditEvent)]
    session.scalar.return_value = 5
    session.scalars.return_value.all.return_value = mock_events

    events, total = query_investigation_audit_events(
        session,
        investigation_id=mock_investigation.id,
        limit=25,
        offset=0,
    )

    assert events == mock_events
    assert total == 5


def test_api_claim_audit_requires_claim_authorization(adjuster_employee: Employee, mock_claim: Claim):
    """Verify GET /claims/{claim_id}/audit enforces claim authorization check."""
    session = MagicMock()

    # Unauthorized employee
    with patch(
        "claimsage.api.routes.audit.get_authorized_claim",
        side_effect=ClaimAccessDeniedError("Access denied"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            get_claim_audit_timeline(
                claim_id=mock_claim.id,
                employee=adjuster_employee,
                session=session,
            )
        assert exc_info.value.status_code == 404

    # Authorized employee
    with patch("claimsage.api.routes.audit.get_authorized_claim", return_value=mock_claim):
        with patch("claimsage.api.routes.audit.query_claim_audit_events", return_value=([], 0)):
            response = get_claim_audit_timeline(
                claim_id=mock_claim.id,
                employee=adjuster_employee,
                session=session,
            )
            assert response.total_count == 0
            assert response.items == []


def test_api_investigation_audit_requires_authorization(
    adjuster_employee: Employee,
    mock_claim: Claim,
    mock_investigation: InvestigationRun,
):
    """Verify GET /agent/investigations/{investigation_id}/audit enforces investigation and claim authorization."""
    session = MagicMock()

    # 1. Investigation not found
    session.get.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        get_investigation_audit_timeline(
            investigation_id=mock_investigation.id,
            employee=adjuster_employee,
            session=session,
        )
    assert exc_info.value.status_code == 404

    # 2. Investigation exists but claim access denied
    session.get.return_value = mock_investigation
    with patch(
        "claimsage.api.routes.audit.get_authorized_claim",
        side_effect=ClaimAccessDeniedError("Access denied"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            get_investigation_audit_timeline(
                investigation_id=mock_investigation.id,
                employee=adjuster_employee,
                session=session,
            )
        assert exc_info.value.status_code == 404

    # 3. Authorized access succeeds
    session.get.return_value = mock_investigation
    with patch("claimsage.api.routes.audit.get_authorized_claim", return_value=mock_claim):
        with patch("claimsage.api.routes.audit.query_investigation_audit_events", return_value=([], 0)):
            response = get_investigation_audit_timeline(
                investigation_id=mock_investigation.id,
                employee=adjuster_employee,
                session=session,
            )
            assert response.total_count == 0
            assert response.items == []


def test_append_only_immutability():
    """Verify no delete or update endpoints or service functions exist for audit logs."""
    import claimsage.services.audit as audit_module

    # Confirm no mutation/deletion methods in audit service module
    for attr in dir(audit_module):
        assert not attr.startswith("delete_audit"), f"Found prohibited delete method: {attr}"
        assert not attr.startswith("update_audit"), f"Found prohibited update method: {attr}"
        assert not attr.startswith("remove_audit"), f"Found prohibited remove method: {attr}"

    # Confirm audit router has only GET methods (read-only)
    for route in audit_router.routes:
        methods = getattr(route, "methods", set())
        assert methods.issubset({"GET", "HEAD", "OPTIONS"}), (
            f"Route {route.path} exposes prohibited modifying methods: {methods}"
        )
