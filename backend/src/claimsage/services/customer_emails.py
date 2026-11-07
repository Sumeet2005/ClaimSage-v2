"""Service for human-gated customer email communications and lifecycle."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from html import escape
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.core.config import get_settings
from claimsage.db.models import AuditEvent, Claim, CustomerEmail, Employee
from claimsage.services.notifications import (
    EmailTransport,
    SandboxEmailTransport,
    SMTPEmailTransport,
    send_with_bounded_retries,
)

logger = logging.getLogger(__name__)

_EMAIL_REGEX = re.compile(r"^[^@\s\r\n]+@[^@\s\r\n]+\.[^@\s\r\n]+$")


def validate_email_address(email: str) -> str:
    """Validate email syntax and reject malicious control characters."""
    cleaned = email.strip()
    if not cleaned or "\r" in cleaned or "\n" in cleaned or not _EMAIL_REGEX.match(cleaned):
        raise ValueError(f"Invalid recipient email address: '{email}'")
    return cleaned


def render_email_content(
    *,
    event_type: str,
    claimant_name: str,
    claim_number: str,
    requested_documents: list[str] | None = None,
    secure_upload_url: str | None = None,
    custom_notes: str | None = None,
) -> tuple[str, str, str, str]:
    """Generate (template_key, subject, body_text, body_html) for a given event."""
    safe_name = escape(claimant_name)
    safe_claim_no = escape(claim_number)

    if event_type == "claim_received":
        template_key = "claim_received_v1"
        subject = f"ClaimSage: Claim Received - {claim_number}"
        text_body = (
            f"Dear {claimant_name},\n\n"
            f"We have received your claim ({claim_number}). "
            f"Our team is currently reviewing your documentation.\n\n"
            "Thank you,\nClaimSage Operations"
        )
        html_body = (
            f"<p>Dear {safe_name},</p>"
            f"<p>We have received your claim <strong>{safe_claim_no}</strong>. "
            "Our team is currently reviewing your documentation.</p>"
            "<p>Thank you,<br>ClaimSage Operations</p>"
        )

    elif event_type == "investigation_completed":
        template_key = "investigation_completed_v1"
        subject = f"ClaimSage: Investigation Update - {claim_number}"
        text_body = (
            f"Dear {claimant_name},\n\n"
            f"The initial investigation for claim {claim_number} is now complete "
            "and has been transferred for final human adjuster review.\n\n"
            "Thank you,\nClaimSage Operations"
        )
        html_body = (
            f"<p>Dear {safe_name},</p>"
            f"<p>The initial investigation for claim <strong>{safe_claim_no}</strong> is now complete "
            "and has been transferred for final human adjuster review.</p>"
            "<p>Thank you,<br>ClaimSage Operations</p>"
        )

    elif event_type == "human_review_required":
        template_key = "human_review_required_v1"
        subject = f"ClaimSage: Specialist Review in Progress - {claim_number}"
        text_body = (
            f"Dear {claimant_name},\n\n"
            f"Your claim ({claim_number}) is currently under review by a specialized claims examiner.\n\n"
            "Thank you,\nClaimSage Operations"
        )
        html_body = (
            f"<p>Dear {safe_name},</p>"
            f"<p>Your claim <strong>{safe_claim_no}</strong> is currently under review by a specialized claims examiner.</p>"
            "<p>Thank you,<br>ClaimSage Operations</p>"
        )

    elif event_type == "additional_evidence_required":
        template_key = "additional_evidence_required_v1"
        subject = f"ClaimSage: Action Required - Additional Documents Requested for Claim {claim_number}"
        doc_list_text = (
            "\n".join(f"- {doc}" for doc in requested_documents)
            if requested_documents
            else "- Requested medical records or invoices"
        )
        doc_list_html = (
            "<ul>" + "".join(f"<li>{escape(doc)}</li>" for doc in requested_documents) + "</ul>"
            if requested_documents
            else "<ul><li>Requested medical records or invoices</li></ul>"
        )
        url_text = secure_upload_url or "[Secure Upload Link]"
        safe_url = escape(url_text)

        text_body = (
            f"Dear {claimant_name},\n\n"
            f"To continue evaluating claim {claim_number}, we require the following additional documentation:\n\n"
            f"{doc_list_text}\n\n"
            f"Please securely upload the requested documents using the link below:\n"
            f"{url_text}\n\n"
            "For security reasons, do not reply with attachments directly.\n\n"
            "Thank you,\nClaimSage Claims Team"
        )
        html_body = (
            f"<p>Dear {safe_name},</p>"
            f"<p>To continue evaluating claim <strong>{safe_claim_no}</strong>, we require the following additional documentation:</p>"
            f"{doc_list_html}"
            f'<p><a href="{safe_url}" style="display:inline-block;padding:10px 18px;background-color:#2563eb;color:#ffffff;text-decoration:none;border-radius:4px;">Upload Requested Documents Securely</a></p>'
            "<p>For your security and privacy, please do not attach sensitive records to an unencrypted email.</p>"
            "<p>Thank you,<br>ClaimSage Claims Team</p>"
        )

    elif event_type == "review_completed":
        template_key = "review_completed_v1"
        subject = f"ClaimSage: Review Decision Update - {claim_number}"
        notes_text = f"\nNotes: {custom_notes}\n" if custom_notes else ""
        notes_html = f"<p>Notes: {escape(custom_notes)}</p>" if custom_notes else ""
        text_body = (
            f"Dear {claimant_name},\n\n"
            f"The review for claim {claim_number} has concluded.{notes_text}\n"
            "An adjuster will contact you with any necessary next steps.\n\n"
            "Thank you,\nClaimSage Operations"
        )
        html_body = (
            f"<p>Dear {safe_name},</p>"
            f"<p>The review for claim <strong>{safe_claim_no}</strong> has concluded.</p>"
            f"{notes_html}"
            "<p>An adjuster will contact you with any necessary next steps.</p>"
            "<p>Thank you,<br>ClaimSage Operations</p>"
        )

    else:
        template_key = "generic_update_v1"
        subject = f"ClaimSage: Update Regarding Claim {claim_number}"
        text_body = (
            f"Dear {claimant_name},\n\n"
            f"There is an update regarding your claim ({claim_number}).\n\n"
            "Thank you,\nClaimSage Operations"
        )
        html_body = (
            f"<p>Dear {safe_name},</p>"
            f"<p>There is an update regarding your claim <strong>{safe_claim_no}</strong>.</p>"
            "<p>Thank you,<br>ClaimSage Operations</p>"
        )

    return template_key, subject, text_body, html_body


def create_email_draft(
    session: Session,
    *,
    claim: Claim,
    event_type: str,
    recipient_email: str,
    recipient_name: str | None = None,
    investigation_id: UUID | None = None,
    requested_documents: list[str] | None = None,
    follow_up_days: int = 7,
    subject: str | None = None,
    body_text: str | None = None,
    body_html: str | None = None,
    custom_notes: str | None = None,
    created_by_employee: Employee | None = None,
) -> CustomerEmail:
    """Create a new customer email draft. STRICTLY NOT SENT until explicitly human-approved."""
    valid_recipient = validate_email_address(recipient_email)
    name = recipient_name or claim.claimant_name or "Policyholder"

    settings = get_settings()
    sender_email = settings.email_from_address

    secure_token: str | None = None
    secure_url: str | None = None
    deadline: datetime | None = None

    if event_type == "additional_evidence_required":
        secure_token = secrets.token_urlsafe(32)
        base_url = settings.email_app_base_url.rstrip("/")
        secure_url = f"{base_url}/claims/{claim.id}/upload?token={secure_token}"
        deadline = datetime.now(UTC) + timedelta(days=follow_up_days)

    default_template, default_sub, default_txt, default_htm = render_email_content(
        event_type=event_type,
        claimant_name=name,
        claim_number=claim.claim_number,
        requested_documents=requested_documents,
        secure_upload_url=secure_url,
        custom_notes=custom_notes,
    )

    final_subject = subject.strip() if subject and subject.strip() else default_sub
    final_text = body_text if body_text is not None else default_txt
    final_html = body_html if body_html is not None else default_htm

    idempotency_key = f"draft:{event_type}:{claim.id}:{uuid4().hex[:12]}"

    email_record = CustomerEmail(
        claim_id=claim.id,
        investigation_id=investigation_id,
        event_type=event_type,
        recipient_email=valid_recipient,
        recipient_name=name,
        sender_email=sender_email,
        subject=final_subject,
        body_text=final_text,
        body_html=final_html,
        template_key=default_template,
        status="drafted",
        secure_upload_token=secure_token,
        secure_upload_url=secure_url,
        follow_up_deadline=deadline,
        idempotency_key=idempotency_key,
        attempt_count=0,
        max_attempts=3,
    )

    session.add(email_record)
    session.flush()

    actor_id = created_by_employee.id if created_by_employee else None
    session.add(
        AuditEvent(
            actor_type="employee" if created_by_employee else "system",
            actor_id=created_by_employee.display_name if created_by_employee else "system",
            actor_employee_id=actor_id,
            claim_id=claim.id,
            investigation_id=investigation_id,
            event_category="customer_email",
            action="customer_email_drafted",
            outcome="success",
            resource_type="customer_email",
            resource_id=str(email_record.id),
            details=f"Drafted customer email for event '{event_type}' to '{valid_recipient}'. Pending human approval.",
            event_metadata={
                "event_type": event_type,
                "recipient_name": name,
                "template_key": default_template,
                "has_secure_upload_url": bool(secure_url),
            },
        )
    )

    return email_record


def update_email_draft(
    session: Session,
    *,
    email_id: UUID,
    employee: Employee,
    subject: str | None = None,
    body_text: str | None = None,
    body_html: str | None = None,
) -> CustomerEmail:
    """Modify a customer email draft before approval."""
    email_record = session.scalar(
        select(CustomerEmail).where(CustomerEmail.id == email_id)
    )
    if email_record is None:
        raise ValueError(f"Customer email {email_id} not found.")

    if email_record.status != "drafted":
        raise ValueError(
            f"Cannot edit customer email with status '{email_record.status}'. Only drafted emails may be modified."
        )

    if subject is not None:
        cleaned_sub = subject.strip()
        if not cleaned_sub:
            raise ValueError("Email subject cannot be empty.")
        email_record.subject = cleaned_sub

    if body_text is not None:
        email_record.body_text = body_text

    if body_html is not None:
        email_record.body_html = body_html

    session.add(
        AuditEvent(
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=email_record.claim_id,
            investigation_id=email_record.investigation_id,
            event_category="customer_email",
            action="customer_email_draft_updated",
            outcome="success",
            resource_type="customer_email",
            resource_id=str(email_record.id),
            details=f"Employee {employee.display_name} updated drafted customer email.",
            event_metadata={
                "event_type": email_record.event_type,
                "email_id": str(email_record.id),
            },
        )
    )

    return email_record


def approve_email(
    session: Session,
    *,
    email_id: UUID,
    employee: Employee,
) -> CustomerEmail:
    """Human approval gate: explicitly approve a customer email for dispatch."""
    email_record = session.scalar(
        select(CustomerEmail).where(CustomerEmail.id == email_id)
    )
    if email_record is None:
        raise ValueError(f"Customer email {email_id} not found.")

    if email_record.status != "drafted":
        raise ValueError(
            f"Cannot approve email in status '{email_record.status}'. Only drafted emails may be approved."
        )

    email_record.status = "approved"
    email_record.approved_by_employee_id = employee.id
    email_record.approved_at = datetime.now(UTC)

    session.add(
        AuditEvent(
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=email_record.claim_id,
            investigation_id=email_record.investigation_id,
            event_category="customer_email",
            action="customer_email_approved",
            outcome="success",
            resource_type="customer_email",
            resource_id=str(email_record.id),
            details=f"Employee {employee.display_name} approved customer email to '{email_record.recipient_email}'.",
            event_metadata={
                "event_type": email_record.event_type,
                "email_id": str(email_record.id),
                "approved_by": employee.display_name,
            },
        )
    )

    return email_record


def dispatch_approved_email(
    session: Session,
    *,
    email_id: UUID,
    transport: EmailTransport | None = None,
) -> CustomerEmail:
    """Send an email that has passed human approval. Rejects unapproved emails."""
    email_record = session.scalar(
        select(CustomerEmail).where(CustomerEmail.id == email_id)
    )
    if email_record is None:
        raise ValueError(f"Customer email {email_id} not found.")

    # Strict human approval gate check
    if email_record.status not in ("approved", "queued"):
        raise ValueError(
            f"Email {email_id} is not approved for sending (status='{email_record.status}'). "
            "Human approval is strictly required before any customer communication."
        )

    if email_record.attempt_count >= email_record.max_attempts:
        email_record.status = "failed"
        raise ValueError(f"Email {email_id} has exceeded maximum send attempts ({email_record.max_attempts}).")

    settings = get_settings()
    if transport is None:
        if settings.email_backend == "smtp":
            transport = SMTPEmailTransport(settings)
        else:
            transport = SandboxEmailTransport()

    # Build standard EmailMessage
    message = EmailMessage()
    message["From"] = email_record.sender_email
    message["To"] = email_record.recipient_email
    message["Subject"] = email_record.subject
    message.set_content(email_record.body_text)
    message.add_alternative(email_record.body_html, subtype="html")

    email_record.attempt_count += 1

    try:
        send_with_bounded_retries(transport, message, attempts=1)
        email_record.status = "sent"
        email_record.sent_at = datetime.now(UTC)
        email_record.last_error_type = None

        session.add(
            AuditEvent(
                actor_type="employee" if email_record.approved_by else "system",
                actor_id=email_record.approved_by_name or "system",
                actor_employee_id=email_record.approved_by_employee_id,
                claim_id=email_record.claim_id,
                investigation_id=email_record.investigation_id,
                event_category="customer_email",
                action="customer_email_dispatched",
                outcome="success",
                resource_type="customer_email",
                resource_id=str(email_record.id),
                details=f"Dispatched approved customer email to '{email_record.recipient_email}'.",
                event_metadata={
                    "event_type": email_record.event_type,
                    "email_id": str(email_record.id),
                    "attempt_count": email_record.attempt_count,
                },
            )
        )
    except Exception as exc:
        email_record.last_error_type = type(exc).__name__
        if email_record.attempt_count >= email_record.max_attempts:
            email_record.status = "failed"
        logger.error(
            "Failed to send approved customer email %s: %s",
            email_record.id,
            exc,
        )
        raise

    return email_record


def check_overdue_reminders(
    session: Session,
    *,
    claim_id: UUID | None = None,
    now: datetime | None = None,
) -> list[CustomerEmail]:
    """Find overdue document requests and draft reminder emails awaiting human approval."""
    current_time = now or datetime.now(UTC)

    query = select(CustomerEmail).where(
        CustomerEmail.status == "sent",
        CustomerEmail.event_type == "additional_evidence_required",
        CustomerEmail.follow_up_deadline.is_not(None),
        CustomerEmail.follow_up_deadline < current_time,
        CustomerEmail.reminder_sent_at.is_(None),
    )

    if claim_id is not None:
        query = query.where(CustomerEmail.claim_id == claim_id)

    overdue_emails = session.scalars(query).all()
    reminder_drafts: list[CustomerEmail] = []

    for original in overdue_emails:
        claim = original.claim
        # Create a reminder draft
        reminder = create_email_draft(
            session,
            claim=claim,
            event_type="additional_evidence_required",
            recipient_email=original.recipient_email,
            recipient_name=original.recipient_name,
            investigation_id=original.investigation_id,
            subject=f"Reminder: Additional Documents Required for Claim {claim.claim_number}",
            body_text=(
                f"Dear {original.recipient_name},\n\n"
                f"This is a gentle reminder that we are awaiting requested documentation for claim {claim.claim_number}.\n"
                f"Please upload them at your earliest convenience:\n{original.secure_upload_url}\n\n"
                "Thank you,\nClaimSage Claims Team"
            ),
            follow_up_days=5,
        )
        # Mark reminder sent timestamp on original
        original.reminder_sent_at = current_time
        reminder_drafts.append(reminder)

    return reminder_drafts


def handle_document_received(
    session: Session,
    *,
    claim_id: UUID,
) -> int:
    """Resume workflow tracking when customer uploads documents in response to request."""
    pending_emails = session.scalars(
        select(CustomerEmail).where(
            CustomerEmail.claim_id == claim_id,
            CustomerEmail.event_type == "additional_evidence_required",
            CustomerEmail.status == "sent",
        )
    ).all()

    for email_record in pending_emails:
        email_record.status = "replied"
        session.add(
            AuditEvent(
                actor_type="system",
                actor_id="customer_upload_handler",
                actor_employee_id=None,
                claim_id=claim_id,
                investigation_id=email_record.investigation_id,
                event_category="customer_email",
                action="customer_email_replied",
                outcome="success",
                resource_type="customer_email",
                resource_id=str(email_record.id),
                details=f"Customer responded with requested documentation for claim {claim_id}.",
                event_metadata={
                    "event_type": email_record.event_type,
                    "email_id": str(email_record.id),
                },
            )
        )

    return len(pending_emails)
