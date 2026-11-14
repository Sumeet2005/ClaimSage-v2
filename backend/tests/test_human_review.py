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
    CustomerEmail,
    Employee,
    EmployeeRole,
    InvestigationFinding,
    InvestigationFindingEdit,
    InvestigationReview,
    InvestigationRun,
    NotificationDelivery,
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



def test_list_investigation_notifications_authorized_admin_sees_all_deliveries(
    admin_employee: Employee,
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Administrators can view all notifications delivered for an authorized investigation."""
    delivery_for_adjuster = NotificationDelivery(
        id=uuid4(),
        idempotency_key="test:key:1",
        event_type="investigation_completed",
        recipient_employee_id=adjuster_employee.id,
        resource_id=str(completed_investigation.id),
        application_path="/claims/mock",
        status="sandboxed",
        attempt_count=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session = MagicMock()
    session.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[delivery_for_adjuster])),
        MagicMock(all=MagicMock(return_value=[])),
    ]

    with patch.object(
        investigations_route,
        "_get_authorized_investigation",
        return_value=completed_investigation,
    ):
        items = investigations_route.list_investigation_notifications(
            investigation_id=completed_investigation.id,
            employee=admin_employee,
            session=session,
        )
        assert len(items) == 1
        assert items[0].id == delivery_for_adjuster.id
        assert items[0].event_type == "investigation_completed"


def test_list_investigation_notifications_assigned_adjuster_sees_own_deliveries(
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Assigned adjusters see notifications delivered to their own recipient ID."""
    delivery = NotificationDelivery(
        id=uuid4(),
        idempotency_key="test:key:2",
        event_type="human_review_required",
        recipient_employee_id=adjuster_employee.id,
        resource_id=str(completed_investigation.id),
        application_path="/claims/mock",
        status="sandboxed",
        attempt_count=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session = MagicMock()
    session.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[delivery])),
        MagicMock(all=MagicMock(return_value=[])),
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
        assert len(items) == 1
        assert items[0].id == delivery.id


def test_list_investigation_notifications_unauthorized_employee_rejected(
    completed_investigation: InvestigationRun,
) -> None:
    """Employees without authorization to the claim receive 404 access denied."""
    unauthorized_employee = Employee(
        id=uuid4(),
        email="unauthorized@claimsage.local",
        display_name="Other Employee",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="unrelated-team",
    )
    session = MagicMock()
    session.scalar.return_value = completed_investigation

    with patch("claimsage.api.routes.investigations.get_authorized_claim", side_effect=ClaimAccessDeniedError):
        with pytest.raises(HTTPException) as exc_info:
            investigations_route.list_investigation_notifications(
                investigation_id=completed_investigation.id,
                employee=unauthorized_employee,
                session=session,
            )
        assert exc_info.value.status_code == 404


def test_list_investigation_notifications_cross_claim_access_denial(
    adjuster_employee: Employee,
    completed_investigation: InvestigationRun,
) -> None:
    """Cross-claim access is strictly denied when the claim does not match employee authority."""
    session = MagicMock()
    session.scalar.return_value = completed_investigation

    with patch("claimsage.api.routes.investigations.get_authorized_claim", side_effect=ClaimAccessDeniedError):
        with pytest.raises(HTTPException) as exc_info:
            investigations_route.list_investigation_notifications(
                investigation_id=completed_investigation.id,
                employee=adjuster_employee,
                session=session,
            )
        assert exc_info.value.status_code == 404


# ==============================================================================
# Comprehensive Regression Tests: Rationale Validation & 6 Review Decisions
# ==============================================================================

def test_record_human_review_escalated_requires_rationale(
    admin_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Escalating requires at least 5 characters of rationale via notes or escalate_reason."""
    session = MagicMock()
    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        # Empty notes and empty reason
        req_empty = InvestigationReviewRequest(decision="escalated", notes=None, escalate_reason=None)
        with pytest.raises(HumanReviewError, match="mandatory rationale of at least 5 characters"):
            record_human_review(session, investigation=completed_investigation, employee=admin_employee, request=req_empty)

        # Whitespace-only notes
        req_short = InvestigationReviewRequest(decision="escalated", notes="   hi   ")
        with pytest.raises(HumanReviewError, match="mandatory rationale of at least 5 characters"):
            record_human_review(session, investigation=completed_investigation, employee=admin_employee, request=req_short)

        # Valid escalate_reason populates review.notes
        req_reason = InvestigationReviewRequest(
            decision="escalated",
            escalate_reason="Possible fraudulent duplicate claim detected across systems.",
        )
        review, _ = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req_reason,
        )
        assert review.decision == "escalated"
        assert review.notes == "Possible fraudulent duplicate claim detected across systems."


def test_record_human_review_returned_for_investigation_requires_rationale(
    admin_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Returning for investigation requires at least 5 characters of explanation in notes."""
    session = MagicMock()
    with patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim):
        req_empty = InvestigationReviewRequest(decision="returned_for_investigation", notes=None)
        with pytest.raises(HumanReviewError, match="mandatory rationale of at least 5 characters"):
            record_human_review(session, investigation=completed_investigation, employee=admin_employee, request=req_empty)

        req_short = InvestigationReviewRequest(decision="returned_for_investigation", notes="redo")
        with pytest.raises(HumanReviewError, match="mandatory rationale of at least 5 characters"):
            record_human_review(session, investigation=completed_investigation, employee=admin_employee, request=req_short)

        req_valid = InvestigationReviewRequest(
            decision="returned_for_investigation",
            notes="Please re-evaluate ICD-10 diagnostic coding against policy exclusions.",
        )
        review, _ = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req_valid,
        )
        assert review.decision == "returned_for_investigation"
        assert completed_investigation.status == "running"
        assert completed_investigation.current_stage == "queued"


def test_record_human_review_needs_additional_documents_requires_rationale_or_docs(
    admin_employee: Employee,
    completed_investigation: InvestigationRun,
    mock_claim: Claim,
) -> None:
    """Requesting additional documents requires either specified documents or explanatory notes."""
    session = MagicMock()
    with (
        patch("claimsage.services.human_review.get_authorized_claim", return_value=mock_claim),
        patch("claimsage.services.human_review.create_email_draft") as mock_draft,
    ):
        mock_draft.return_value = MagicMock()

        # Both empty -> error
        req_empty = InvestigationReviewRequest(
            decision="needs_additional_documents",
            notes=None,
            requested_documents=None,
        )
        with pytest.raises(HumanReviewError, match="Specific requested documents or a mandatory explanation"):
            record_human_review(session, investigation=completed_investigation, employee=admin_employee, request=req_empty)

        # Empty docs list and empty notes -> error
        req_empty_list = InvestigationReviewRequest(
            decision="needs_additional_documents",
            notes="   ",
            requested_documents=["   "],
        )
        with pytest.raises(HumanReviewError, match="Specific requested documents or a mandatory explanation"):
            record_human_review(session, investigation=completed_investigation, employee=admin_employee, request=req_empty_list)

        # Specified documents only -> success
        req_docs_only = InvestigationReviewRequest(
            decision="needs_additional_documents",
            requested_documents=["Itemized pharmacy bill"],
        )
        review_docs, _ = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req_docs_only,
        )
        assert review_docs.decision == "needs_additional_documents"

        # Explanatory notes only -> success
        req_notes_only = InvestigationReviewRequest(
            decision="needs_additional_documents",
            notes="Please upload the official hospital discharge summary report.",
        )
        review_notes, _ = record_human_review(
            session,
            investigation=completed_investigation,
            employee=admin_employee,
            request=req_notes_only,
        )
        assert review_notes.decision == "needs_additional_documents"


# ==============================================================================
# PostgreSQL Integration & API Tests for All 6 Human Review Actions
# ==============================================================================

from fastapi.testclient import TestClient
from sqlalchemy import delete
from claimsage.db.session import SessionLocal
from claimsage.main import app
from claimsage.services.auth import create_access_token, hash_password

TEST_PASSWORD = "ClaimSageTestPassword2026!"


def test_postgres_all_six_review_decisions_persisted() -> None:
    """Verify all 6 review decisions are successfully accepted by PostgreSQL constraints and persisted."""
    suffix = uuid4().hex[:8]
    password_hash = hash_password(TEST_PASSWORD)

    admin = Employee(
        email=f"review-admin-{suffix}@claimsage.local",
        display_name="Review Admin",
        password_hash=password_hash,
        role=EmployeeRole.ADMIN,
        team_id=None,
    )
    adjuster = Employee(
        email=f"review-adj-{suffix}@claimsage.local",
        display_name="Review Adjuster",
        password_hash=password_hash,
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"health-{suffix}",
    )

    with SessionLocal.begin() as session:
        session.add_all([admin, adjuster])
        session.flush()

        test_claim = Claim(
            claim_number=f"CLM-SYNTH-{suffix}",
            claimant_name="Synthetic Review Claimant",
            claim_type="health",
            status="under_review",
            assigned_employee_id=adjuster.id,
            team_id=adjuster.team_id,
            summary="Synthetic claim for testing all 6 review decisions.",
        )
        session.add(test_claim)
        session.flush()

        claim_id = test_claim.id
        admin_id = admin.id
        adj_id = adjuster.id

    inv_ids = []
    try:
        decisions_to_test = [
            ("reviewed", "Standard claim audit passed.", None),
            ("needs_follow_up", "Requires supervisor consultation.", None),
            ("escalated", "Suspicion of duplicate procedure billing.", None),
            ("approved", "Final claim assessment approved without reservations.", None),
            ("needs_additional_documents", "Requesting missing operative notes.", ["Operative report"]),
            ("returned_for_investigation", "Re-run vector search with complete clinical notes.", None),
        ]

        for decision, notes, requested_docs in decisions_to_test:
            with SessionLocal.begin() as session:
                inv = InvestigationRun(
                    claim_id=claim_id,
                    claim_domain="health",
                    initiated_by_employee_id=adj_id,
                    task=f"Test run for decision {decision}",
                    status="completed",
                    current_stage="completed",
                    human_review_status="pending",
                )
                session.add(inv)
                session.flush()
                inv_id = inv.id
                inv_ids.append(inv_id)

                db_admin = session.get(Employee, admin_id)
                db_inv = session.get(InvestigationRun, inv_id)

                req = InvestigationReviewRequest(
                    decision=decision,
                    notes=notes,
                    requested_documents=requested_docs,
                )
                review, _ = record_human_review(
                    session,
                    investigation=db_inv,
                    employee=db_admin,
                    request=req,
                )
                session.flush()

                # Verify fields persisted in session
                assert review.decision == decision
                assert review.notes == notes
                assert db_inv.human_review_status == decision
                if decision == "returned_for_investigation":
                    assert db_inv.status == "running"
                    assert db_inv.current_stage == "queued"

            # Query back in a new session from PostgreSQL to verify constraint acceptance and commit
            with SessionLocal() as verify_session:
                persisted_inv = verify_session.get(InvestigationRun, inv_id)
                assert persisted_inv is not None
                assert persisted_inv.human_review_status == decision

                persisted_review = verify_session.query(InvestigationReview).filter_by(
                    investigation_id=inv_id,
                    decision=decision,
                ).first()
                assert persisted_review is not None
                assert persisted_review.notes == notes

                persisted_audit = verify_session.query(AuditEvent).filter_by(
                    investigation_id=inv_id,
                    event_category="human_review",
                ).first()
                assert persisted_audit is not None
                assert persisted_audit.outcome == "success"

    finally:
        with SessionLocal.begin() as session:
            if inv_ids:
                session.execute(delete(InvestigationReview).where(InvestigationReview.investigation_id.in_(inv_ids)))
                session.execute(delete(CustomerEmail).where(CustomerEmail.investigation_id.in_(inv_ids)))
                session.execute(delete(AuditEvent).where(AuditEvent.investigation_id.in_(inv_ids)))
                session.execute(delete(InvestigationRun).where(InvestigationRun.id.in_(inv_ids)))
            session.execute(delete(Claim).where(Claim.id == claim_id))
            session.execute(delete(AuditEvent).where(AuditEvent.actor_employee_id.in_([admin_id, adj_id])))
            session.execute(delete(Employee).where(Employee.id.in_([admin_id, adj_id])))


def test_api_submit_review_all_six_actions_end_to_end() -> None:
    """Test API endpoint POST /api/v1/agent/investigations/{id}/reviews for all 6 decisions."""
    client = TestClient(app)
    suffix = uuid4().hex[:8]
    password_hash = hash_password(TEST_PASSWORD)

    admin = Employee(
        email=f"api-admin-{suffix}@claimsage.local",
        display_name="API Admin",
        password_hash=password_hash,
        role=EmployeeRole.ADMIN,
        team_id=None,
    )
    adjuster = Employee(
        email=f"api-adj-{suffix}@claimsage.local",
        display_name="API Adjuster",
        password_hash=password_hash,
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"health-{suffix}",
    )

    with SessionLocal.begin() as session:
        session.add_all([admin, adjuster])
        session.flush()

        test_claim = Claim(
            claim_number=f"CLM-API-{suffix}",
            claimant_name="API Review Claimant",
            claim_type="health",
            status="under_review",
            assigned_employee_id=adjuster.id,
            team_id=adjuster.team_id,
            summary="API claim test for human review actions.",
        )
        session.add(test_claim)
        session.flush()

        claim_id = test_claim.id
        admin_id = admin.id
        adj_id = adjuster.id

    admin_token = create_access_token(admin_id)
    adj_token = create_access_token(adj_id)
    headers = {"Authorization": f"Bearer {admin_token}"}

    inv_ids = []
    try:
        decisions_to_test = [
            ("reviewed", {"decision": "reviewed", "notes": "Reviewed and verified."}),
            ("needs_follow_up", {"decision": "needs_follow_up", "notes": "Requires second-level review."}),
            ("escalated", {"decision": "escalated", "notes": "Potential fraud pattern flagged."}),
            ("approved", {"decision": "approved", "notes": "Approved for settlement."}),
            ("needs_additional_documents", {"decision": "needs_additional_documents", "requested_documents": ["Pharmacy bills"]}),
            ("returned_for_investigation", {"decision": "returned_for_investigation", "notes": "Please re-check policy coverage."}),
        ]

        for decision, payload in decisions_to_test:
            with SessionLocal.begin() as session:
                inv = InvestigationRun(
                    claim_id=claim_id,
                    claim_domain="health",
                    initiated_by_employee_id=adj_id,
                    task=f"API run for {decision}",
                    status="completed",
                    current_stage="completed",
                    human_review_status="pending",
                )
                session.add(inv)
                session.flush()
                inv_id = inv.id
                inv_ids.append(inv_id)

            resp = client.post(
                f"/api/v1/agent/investigations/{inv_id}/reviews",
                json=payload,
                headers=headers,
            )
            assert resp.status_code == 201, f"Failed for {decision}: {resp.text}"
            data = resp.json()
            assert data["decision"] == decision
            assert data["reviewer_employee_id"] == str(admin_id)

    finally:
        with SessionLocal.begin() as session:
            if inv_ids:
                session.execute(delete(InvestigationReview).where(InvestigationReview.investigation_id.in_(inv_ids)))
                session.execute(delete(CustomerEmail).where(CustomerEmail.investigation_id.in_(inv_ids)))
                session.execute(delete(NotificationDelivery).where(NotificationDelivery.recipient_employee_id.in_([admin_id, adj_id])))
                session.execute(delete(AuditEvent).where(AuditEvent.investigation_id.in_(inv_ids)))
                session.execute(delete(InvestigationRun).where(InvestigationRun.id.in_(inv_ids)))
            session.execute(delete(Claim).where(Claim.id == claim_id))
            session.execute(delete(AuditEvent).where(AuditEvent.actor_employee_id.in_([admin_id, adj_id])))
            session.execute(delete(Employee).where(Employee.id.in_([admin_id, adj_id])))


def test_api_submit_review_validation_and_conflict_errors() -> None:
    """Test 400, 403, 409, and 422 error cases in the review submission API."""
    client = TestClient(app)
    suffix = uuid4().hex[:8]
    password_hash = hash_password(TEST_PASSWORD)

    admin = Employee(
        email=f"err-admin-{suffix}@claimsage.local",
        display_name="Error Admin",
        password_hash=password_hash,
        role=EmployeeRole.ADMIN,
        team_id=None,
    )
    adjuster = Employee(
        email=f"err-adj-{suffix}@claimsage.local",
        display_name="Error Adjuster",
        password_hash=password_hash,
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"health-{suffix}",
    )

    with SessionLocal.begin() as session:
        session.add_all([admin, adjuster])
        session.flush()

        test_claim = Claim(
            claim_number=f"CLM-ERR-{suffix}",
            claimant_name="Error Test Claimant",
            claim_type="health",
            status="under_review",
            assigned_employee_id=adjuster.id,
            team_id=adjuster.team_id,
            summary="API error tests.",
        )
        session.add(test_claim)
        session.flush()

        claim_id = test_claim.id
        admin_id = admin.id
        adj_id = adjuster.id

    admin_token = create_access_token(admin_id)
    adj_token = create_access_token(adj_id)

    inv_ids = []
    try:
        with SessionLocal.begin() as session:
            inv_completed = InvestigationRun(
                claim_id=claim_id,
                claim_domain="health",
                initiated_by_employee_id=adj_id,
                task="Completed investigation for error test",
                status="completed",
                current_stage="completed",
                human_review_status="pending",
            )
            inv_running = InvestigationRun(
                claim_id=claim_id,
                claim_domain="health",
                initiated_by_employee_id=adj_id,
                task="Running investigation for error test",
                status="running",
                current_stage="medical_coding",
                human_review_status="pending",
            )
            session.add_all([inv_completed, inv_running])
            session.flush()
            inv_ids.extend([inv_completed.id, inv_running.id])
            comp_id = inv_completed.id
            run_id = inv_running.id

        # 1. 403 Forbidden for non-admin
        resp_403 = client.post(
            f"/api/v1/agent/investigations/{comp_id}/reviews",
            json={"decision": "approved", "notes": "Adjuster trying to approve"},
            headers={"Authorization": f"Bearer {adj_token}"},
        )
        assert resp_403.status_code == 403

        # 2. 422 Unprocessable Entity for invalid decision
        resp_422 = client.post(
            f"/api/v1/agent/investigations/{comp_id}/reviews",
            json={"decision": "rejected_bad_decision", "notes": "Invalid decision enum"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_422.status_code == 422

        # 3. 409 Conflict for running investigation
        resp_409_run = client.post(
            f"/api/v1/agent/investigations/{run_id}/reviews",
            json={"decision": "approved", "notes": "Premature approval attempt"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_409_run.status_code == 409

        # 4. 400 Bad Request for escalated without mandatory rationale
        resp_400_esc = client.post(
            f"/api/v1/agent/investigations/{comp_id}/reviews",
            json={"decision": "escalated", "notes": "   "},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_400_esc.status_code == 400
        assert "mandatory rationale" in resp_400_esc.json()["detail"]

        # 5. 400 Bad Request for returned_for_investigation without mandatory rationale
        resp_400_ret = client.post(
            f"/api/v1/agent/investigations/{comp_id}/reviews",
            json={"decision": "returned_for_investigation", "notes": None},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_400_ret.status_code == 400
        assert "mandatory rationale" in resp_400_ret.json()["detail"]

        # 6. 400 Bad Request for needs_additional_documents without docs or notes
        resp_400_docs = client.post(
            f"/api/v1/agent/investigations/{comp_id}/reviews",
            json={"decision": "needs_additional_documents"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_400_docs.status_code == 400

        # 7. Approve successfully, then test 409 Conflict on duplicate approval
        resp_app = client.post(
            f"/api/v1/agent/investigations/{comp_id}/reviews",
            json={"decision": "approved", "notes": "First approval verified."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_app.status_code == 201

        resp_dup = client.post(
            f"/api/v1/agent/investigations/{comp_id}/reviews",
            json={"decision": "approved", "notes": "Second duplicate approval attempt."},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_dup.status_code == 409
        assert "already approved" in resp_dup.json()["detail"]

    finally:
        with SessionLocal.begin() as session:
            if inv_ids:
                session.execute(delete(InvestigationReview).where(InvestigationReview.investigation_id.in_(inv_ids)))
                session.execute(delete(CustomerEmail).where(CustomerEmail.investigation_id.in_(inv_ids)))
                session.execute(delete(NotificationDelivery).where(NotificationDelivery.recipient_employee_id.in_([admin_id, adj_id])))
                session.execute(delete(AuditEvent).where(AuditEvent.investigation_id.in_(inv_ids)))
                session.execute(delete(InvestigationRun).where(InvestigationRun.id.in_(inv_ids)))
            session.execute(delete(Claim).where(Claim.id == claim_id))
            session.execute(delete(AuditEvent).where(AuditEvent.actor_employee_id.in_([admin_id, adj_id])))
            session.execute(delete(Employee).where(Employee.id.in_([admin_id, adj_id])))
