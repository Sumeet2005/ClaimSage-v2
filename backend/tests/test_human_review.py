"""Unit and integration tests for Phase 3: Human Review and Finding Revisions."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from claimsage.api.routes import investigations as investigations_route
from claimsage.db.models import (
    AuditEvent,
    Claim,
    Employee,
    EmployeeRole,
    InvestigationFinding,
    InvestigationFindingEdit,
    InvestigationReview,
    InvestigationRun,
)
from claimsage.schemas.human_review import (
    FindingEditRequest,
    InvestigationReviewRequest,
)
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.services.human_review import (
    HumanReviewError,
    create_finding_edit,
    list_finding_edits,
    record_human_review,
)


@pytest.fixture
def admin_employee() -> Employee:
    return Employee(
        id=uuid4(),
        email="admin@claimsage.local",
        display_name="Admin Reviewer",
        role=EmployeeRole.ADMIN,
        team_id=None,
    )


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
def mock_claim(adjuster_employee: Employee) -> Claim:
    return Claim(
        id=uuid4(),
        claim_number="CLM-HEALTH-001",
        claimant_name="Jane Doe",
        claim_type="Health",
        policy_identifier="POL-H-999",
        status="under_review",
        assigned_employee_id=adjuster_employee.id,
    )


@pytest.fixture
def completed_investigation(mock_claim: Claim, adjuster_employee: Employee) -> InvestigationRun:
    return InvestigationRun(
        id=uuid4(),
        claim_id=mock_claim.id,
        claim_domain="health",
        initiated_by_employee_id=adjuster_employee.id,
        task="Audit hospital inpatient charges",
        status="completed",
        current_stage="completed",
        human_review_status="pending",
    )


def test_claims_analyst_cannot_submit_human_review(
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Claims Analysts cannot submit consequential human review decisions."""
    session = MagicMock()
    req = InvestigationReviewRequest(decision="approved", notes="Analyst attempting approval")
    with pytest.raises(HumanReviewError, match="not authorized to submit human reviews"):
        record_human_review(
            session,
            investigation=completed_investigation,
            employee=adjuster_employee,
            request=req,
        )


def test_api_submit_review_rejects_claims_analyst(
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """The submit_investigation_review API endpoint returns 403 Forbidden for Claims Analysts."""
    session = MagicMock()
    background_tasks = MagicMock()
    req = InvestigationReviewRequest(decision="approved", notes="Analyst attempting approval")
    with pytest.raises(HTTPException) as exc_info:
        investigations_route.submit_investigation_review(
            investigation_id=completed_investigation.id,
            request=req,
            background_tasks=background_tasks,
            employee=adjuster_employee,
            session=session,
        )
    assert exc_info.value.status_code == 403


def test_record_human_review_rejects_running_investigation(
    admin_employee: Employee,
    adjuster_employee: Employee,
    mock_claim: Claim,
) -> None:
    """Human review cannot be submitted while the investigation is still actively running."""
    session = MagicMock()
    running_inv = InvestigationRun(
        id=uuid4(),
        claim_id=mock_claim.id,
        claim_domain="health",
        initiated_by_employee_id=adjuster_employee.id,
        task="Audit hospital inpatient charges",
        status="running",
        current_stage="medical_coding",
        human_review_status="pending",
    )

    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        req = InvestigationReviewRequest(decision="approved", notes="Looks fine")
        with pytest.raises(HumanReviewError, match="must finish before human review"):
            record_human_review(
                session,
                investigation=running_inv,
                employee=admin_employee,
                request=req,
            )


def test_record_human_review_rejects_duplicate_approval(
    admin_employee: Employee,
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Cannot re-approve an already approved investigation."""
    session = MagicMock()
    completed_investigation.human_review_status = "approved"

    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        req = InvestigationReviewRequest(decision="approved", notes="Approving again")
        with pytest.raises(HumanReviewError, match="already approved"):
            record_human_review(
                session,
                investigation=completed_investigation,
                employee=admin_employee,
                request=req,
            )


def test_record_human_review_approved_success(
    admin_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Approving an investigation updates status, appends review and records an audit event."""
    session = MagicMock()

    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        req = InvestigationReviewRequest(decision="approved", notes="All findings verified against medical bills.")
        review, email_draft = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req,
        )

        assert completed_investigation.human_review_status == "approved"
        assert review.decision == "approved"
        assert review.reviewer_employee_id == admin_employee.id
        assert review.notes == "All findings verified against medical bills."
        assert email_draft is None
        assert session.add.call_count >= 2  # Review and AuditEvent


def test_record_human_review_returned_for_investigation_requeues(
    admin_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Returning an investigation for analysis transitions status to running/queued to trigger PostgreSQL worker claiming."""
    session = MagicMock()
    completed_investigation.worker_id = "worker-1"
    completed_investigation.lease_expires_at = datetime.now(UTC)

    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        req = InvestigationReviewRequest(
            decision="returned_for_investigation",
            notes="Please re-run policy clause cross-referencing with newly uploaded operative notes.",
        )
        review, _ = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req,
        )

        assert completed_investigation.human_review_status == "returned_for_investigation"
        assert completed_investigation.status == "running"
        assert completed_investigation.current_stage == "queued"
        assert completed_investigation.worker_id is None
        assert completed_investigation.lease_expires_at is None
        assert review.decision == "returned_for_investigation"


def test_record_human_review_needs_additional_documents_creates_draft_email(
    admin_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Requesting additional documents updates review status and auto-drafts a customer email with secure upload URL."""
    session = MagicMock()

    with (
        patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim),
        patch("claimsage.services.human_review.create_email_draft") as mock_draft,
    ):
        mock_draft.return_value = MagicMock(status="drafted")

        req = InvestigationReviewRequest(
            decision="needs_additional_documents",
            notes="Need itemized pharmacy invoices.",
            requested_documents=["Itemized pharmacy receipts", "Discharge summary"],
        )
        review, email_draft = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req,
        )

        assert completed_investigation.human_review_status == "needs_additional_documents"
        assert review.decision == "needs_additional_documents"
        mock_draft.assert_called_once()
        _, kwargs = mock_draft.call_args
        assert kwargs["event_type"] == "additional_evidence_required"
        assert "Itemized pharmacy receipts" in kwargs["requested_documents"]


def test_record_human_review_escalated(
    admin_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Escalating an investigation records the escalated human review status."""
    session = MagicMock()

    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        req = InvestigationReviewRequest(
            decision="escalated",
            notes="Suspicion of duplicate billing across provider networks. Escalating to SIU.",
        )
        review, _ = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req,
        )

        assert completed_investigation.human_review_status == "escalated"
        assert review.decision == "escalated"


def test_create_finding_edit_preserves_original_ai_finding(
    admin_employee: Employee,
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Editing a finding leaves the original AI finding_data completely immutable and persists an edit version."""
    session = MagicMock()

    original_finding_data = {
        "claimed_amount": 54000.0,
        "recommended_deduction": 12000.0,
        "rationale": "High room rent tariff exceeds policy limit.",
    }

    finding = InvestigationFinding(
        id=uuid4(),
        investigation_id=completed_investigation.id,
        specialist="medical_bill_analyst",
        finding_type="room_rent_capping",
        finding_data=dict(original_finding_data),
        severity="medium",
        confidence="high",
        evidence_references=[],
        policy_references=[],
    )

    session.scalar.side_effect = [finding, completed_investigation]

    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        req = FindingEditRequest(
            edited_data={
                "claimed_amount": 54000.0,
                "recommended_deduction": 6000.0,
                "rationale": "Adjuster confirmed policy rider 2B increases room rent cap by 50%.",
            },
            reason="Adjuster verified active room-rent waiver endorsement rider.",
        )

        edit = create_finding_edit(
            session,
            finding_id=finding.id,
            employee=adjuster_employee,
            request=req,
        )

        # Original finding data must remain untouched!
        assert finding.finding_data == original_finding_data
        # Edit record captures original and revised data
        assert edit.original_data == original_finding_data
        assert edit.edited_data == req.edited_data
        assert edit.reason == req.reason
        assert edit.editor_employee_id == adjuster_employee.id


def test_create_finding_edit_validates_reason() -> None:
    """Edit reason must be descriptive (at least 5 characters)."""
    with pytest.raises(ValueError, match="at least 5 characters"):
        FindingEditRequest(
            edited_data={"fee": 100},
            reason="bad",
        )


def test_api_submit_review_conflict_for_running(
    admin_employee: Employee,
    adjuster_employee: Employee,
    mock_claim: Claim,
) -> None:
    """API endpoint returns 409 Conflict when submitting review for a running investigation."""
    session = MagicMock()
    running_inv = InvestigationRun(
        id=uuid4(),
        claim_id=mock_claim.id,
        claim_domain="health",
        initiated_by_employee_id=adjuster_employee.id,
        task="Test task",
        status="running",
        human_review_status="pending",
    )

    with (
        patch.object(investigations_route, "_get_authorized_investigation", return_value=running_inv),
        patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim),
    ):
        req = InvestigationReviewRequest(decision="approved", notes="Should fail")
        background_tasks = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            investigations_route.submit_investigation_review(
                investigation_id=running_inv.id,
                request=req,
                background_tasks=background_tasks,
                employee=admin_employee,
                session=session,
            )

        assert exc_info.value.status_code == 409
        assert "must finish before human review" in exc_info.value.detail


def test_list_investigation_notifications_includes_customer_email_drafts(
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
) -> None:
    """Notifications endpoint retrieves both employee outbox events and unsent customer email drafts."""
    from claimsage.db.models import CustomerEmail, NotificationDelivery

    delivery = NotificationDelivery(
        id=uuid4(),
        event_type="human_review_required",
        status="pending",
        recipient_employee_id=adjuster_employee.id,
        resource_id=str(completed_investigation.id),
        attempt_count=0,
        last_error_type=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    email_draft = CustomerEmail(
        id=uuid4(),
        claim_id=completed_investigation.claim_id,
        investigation_id=completed_investigation.id,
        event_type="additional_evidence_required",
        recipient_email="policyholder@example.com",
        recipient_name="Jane Doe",
        sender_email="claims@claimsage.local",
        subject="Additional Information Required for Claim CLM-HEALTH-001",
        body_text="Please upload itemized hospital bill via secure portal.",
        body_html="<p>Please upload itemized hospital bill via secure portal.</p>",
        template_key="additional_evidence_required",
        status="drafted",
        secure_upload_url="https://portal.claimsage.local/claims/upload?token=mock123",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    session = MagicMock()
    # First call returns notification deliveries, second call returns customer emails
    session.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[delivery])),
        MagicMock(all=MagicMock(return_value=[email_draft])),
    ]

    with patch.object(
        investigations_route,
        "_get_authorized_investigation",
        return_value=completed_investigation,
    ):
        items = investigations_route.list_investigation_notifications(
            investigation_id=completed_investigation.id,
            employee=adjuster_employee,
            session=session,
        )

        assert len(items) == 2
        # First item is internal notification delivery
        assert items[0].id == delivery.id
        assert items[0].event_type == "human_review_required"
        assert items[0].is_draft is False
        assert items[0].secure_upload_url is None

        # Second item is customer email draft
        assert items[1].id == email_draft.id
        assert items[1].event_type == "additional_evidence_required"
        assert items[1].status == "drafted"
        assert items[1].is_draft is True
        assert items[1].recipient_email == "policyholder@example.com"
        assert items[1].subject == "Additional Information Required for Claim CLM-HEALTH-001"
        assert items[1].secure_upload_url == "https://portal.claimsage.local/claims/upload?token=mock123"

