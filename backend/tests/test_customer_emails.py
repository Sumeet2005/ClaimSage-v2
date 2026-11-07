"""Unit and integration tests for Phase 3: Customer Email Workflows and Human Approval Gates."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from claimsage.db.models import Claim, CustomerEmail, Employee, EmployeeRole
from claimsage.services.customer_emails import (
    approve_email,
    check_overdue_reminders,
    create_email_draft,
    dispatch_approved_email,
    handle_document_received,
    update_email_draft,
    validate_email_address,
)
from claimsage.services.notifications import SandboxEmailTransport


@pytest.fixture
def adjuster_employee() -> Employee:
    return Employee(
        id=uuid4(),
        email="adjuster@claimsage.local",
        display_name="Health Claims Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="health-team",
    )


@pytest.fixture
def mock_claim(adjuster_employee: Employee) -> Claim:
    return Claim(
        id=uuid4(),
        claim_number="CLM-HLTH-2026-0042",
        claimant_name="Sarah Connor",
        claim_type="Health",
        policy_identifier="POL-IND-881",
        status="under_review",
        assigned_employee_id=adjuster_employee.id,
    )


def test_validate_email_address() -> None:
    """Recipient emails are checked for validity and carriage-return injection."""
    assert validate_email_address("sarah@example.com") == "sarah@example.com"
    with pytest.raises(ValueError, match="Invalid recipient email"):
        validate_email_address("invalid-email")
    with pytest.raises(ValueError, match="Invalid recipient email"):
        validate_email_address("sarah@example.com\r\nBcc: evil@attacker.invalid")


def test_create_email_draft_strictly_drafted(
    mock_claim: Claim,
    adjuster_employee: Employee,
) -> None:
    """Drafted emails must NEVER be sent automatically; status must be 'drafted'."""
    session = MagicMock()

    email = create_email_draft(
        session,
        claim=mock_claim,
        event_type="claim_received",
        recipient_email="sarah.connor@example.com",
        recipient_name="Sarah Connor",
        created_by_employee=adjuster_employee,
    )

    assert email.status == "drafted"
    assert email.approved_by_employee_id is None
    assert email.approved_at is None
    assert email.sent_at is None
    assert email.claim_id == mock_claim.id
    assert "CLM-HLTH-2026-0042" in email.subject


def test_create_email_draft_additional_evidence_generates_secure_upload_url(
    mock_claim: Claim,
    adjuster_employee: Employee,
) -> None:
    """Document requests must include a secure upload URL instead of attaching sensitive files directly."""
    session = MagicMock()

    email = create_email_draft(
        session,
        claim=mock_claim,
        event_type="additional_evidence_required",
        recipient_email="sarah.connor@example.com",
        recipient_name="Sarah Connor",
        requested_documents=["Discharge Summary", "Pharmacy Bills"],
        follow_up_days=7,
        created_by_employee=adjuster_employee,
    )

    assert email.status == "drafted"
    assert email.secure_upload_token is not None
    assert email.secure_upload_url is not None
    assert f"/claims/{mock_claim.id}/upload?token=" in email.secure_upload_url
    assert email.follow_up_deadline is not None
    # Verify body text instructs user to use secure link
    assert email.secure_upload_url in email.body_text
    assert "Discharge Summary" in email.body_text
    assert "Pharmacy Bills" in email.body_text


def test_dispatch_unapproved_email_is_strictly_forbidden() -> None:
    """Strict human approval gate: An unapproved email draft CANNOT be dispatched under any circumstance."""
    session = MagicMock()

    unapproved_email = CustomerEmail(
        id=uuid4(),
        claim_id=uuid4(),
        event_type="additional_evidence_required",
        recipient_email="customer@example.com",
        recipient_name="Customer",
        sender_email="noreply@claimsage.com",
        subject="Action Required",
        body_text="Please upload documents.",
        body_html="<p>Please upload documents.</p>",
        template_key="tpl_v1",
        status="drafted",  # Still in draft status!
        idempotency_key="key-1",
        attempt_count=0,
        max_attempts=3,
    )
    session.scalar.return_value = unapproved_email

    with pytest.raises(ValueError, match="Human approval is strictly required"):
        dispatch_approved_email(
            session,
            email_id=unapproved_email.id,
            transport=SandboxEmailTransport(),
        )

    # Status must NOT have transitioned to sent
    assert unapproved_email.status == "drafted"
    assert unapproved_email.sent_at is None


def test_human_approval_gate_lifecycle(
    adjuster_employee: Employee,
) -> None:
    """A human adjuster must explicitly approve the draft before it can be dispatched."""
    session = MagicMock()

    email_record = CustomerEmail(
        id=uuid4(),
        claim_id=uuid4(),
        event_type="investigation_completed",
        recipient_email="customer@example.com",
        recipient_name="Customer",
        sender_email="noreply@claimsage.com",
        subject="Investigation Completed",
        body_text="Your claim investigation has concluded.",
        body_html="<p>Your claim investigation has concluded.</p>",
        template_key="tpl_v1",
        status="drafted",
        idempotency_key="key-2",
        attempt_count=0,
        max_attempts=3,
    )
    session.scalar.return_value = email_record

    # 1. Human Approves
    approved_email = approve_email(
        session,
        email_id=email_record.id,
        employee=adjuster_employee,
    )

    assert approved_email.status == "approved"
    assert approved_email.approved_by_employee_id == adjuster_employee.id
    assert approved_email.approved_at is not None

    # 2. Dispatch Approved Email
    sent_email = dispatch_approved_email(
        session,
        email_id=email_record.id,
        transport=SandboxEmailTransport(),
    )

    assert sent_email.status == "sent"
    assert sent_email.sent_at is not None
    assert sent_email.attempt_count == 1
    assert sent_email.last_error_type is None


def test_update_email_draft_allows_changes_only_before_approval(
    adjuster_employee: Employee,
) -> None:
    """Adjusters can customize draft email text before approval, but not after."""
    session = MagicMock()

    draft = CustomerEmail(
        id=uuid4(),
        claim_id=uuid4(),
        event_type="claim_received",
        recipient_email="customer@example.com",
        recipient_name="Customer",
        sender_email="noreply@claimsage.com",
        subject="Original Subject",
        body_text="Original text",
        body_html="<p>Original text</p>",
        template_key="tpl_v1",
        status="drafted",
        idempotency_key="key-3",
        attempt_count=0,
        max_attempts=3,
    )
    session.scalar.return_value = draft

    # Updating drafted email works
    updated = update_email_draft(
        session,
        email_id=draft.id,
        employee=adjuster_employee,
        subject="Revised Subject",
        body_text="Revised body text",
    )
    assert updated.subject == "Revised Subject"
    assert updated.body_text == "Revised body text"

    # Attempting to edit an approved or sent email is rejected
    draft.status = "approved"
    with pytest.raises(ValueError, match="Only drafted emails may be modified"):
        update_email_draft(
            session,
            email_id=draft.id,
            employee=adjuster_employee,
            subject="Cannot edit after approval",
        )


def test_check_overdue_reminders(
    mock_claim: Claim,
) -> None:
    """Overdue document requests trigger automated reminder drafts."""
    session = MagicMock()

    overdue_email = CustomerEmail(
        id=uuid4(),
        claim_id=mock_claim.id,
        event_type="additional_evidence_required",
        recipient_email="customer@example.com",
        recipient_name="Sarah Connor",
        sender_email="noreply@claimsage.com",
        subject="Initial Document Request",
        body_text="Please provide documents.",
        body_html="<p>Please provide documents.</p>",
        template_key="tpl_v1",
        status="sent",
        follow_up_deadline=datetime.now(UTC) - timedelta(days=2),  # 2 days overdue
        reminder_sent_at=None,
        secure_upload_url="https://app.claimsage.com/claims/123/upload?token=abc",
        idempotency_key="key-4",
        attempt_count=1,
        max_attempts=3,
    )
    overdue_email.claim = mock_claim

    session.scalars.return_value.all.return_value = [overdue_email]

    reminders = check_overdue_reminders(session, claim_id=mock_claim.id)

    assert len(reminders) == 1
    assert reminders[0].status == "drafted"  # Reminders also start in drafted state for human review
    assert overdue_email.reminder_sent_at is not None


def test_handle_document_received_resumes_workflow(
    mock_claim: Claim,
) -> None:
    """When a customer uploads evidence, pending document request emails transition to 'replied'."""
    session = MagicMock()

    sent_req = CustomerEmail(
        id=uuid4(),
        claim_id=mock_claim.id,
        event_type="additional_evidence_required",
        recipient_email="customer@example.com",
        recipient_name="Customer",
        sender_email="noreply@claimsage.com",
        subject="Action Required",
        body_text="Upload documents",
        body_html="<p>Upload documents</p>",
        template_key="tpl_v1",
        status="sent",
        idempotency_key="key-5",
        attempt_count=1,
        max_attempts=3,
    )

    session.scalars.return_value.all.return_value = [sent_req]

    updated_count = handle_document_received(session, claim_id=mock_claim.id)

    assert updated_count == 1
    assert sent_req.status == "replied"
    assert session.add.called
