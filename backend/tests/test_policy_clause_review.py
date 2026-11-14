"""Unit tests for explicit human verification of source clauses."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from claimsage.api.routes.policies import (
    list_policy_clauses,
    list_policy_document_clauses,
    review_policy_clause,
)
from claimsage.db.models import (
    AuditEvent,
    Employee,
    EmployeeRole,
    PolicyClause,
    PolicyDocument,
)
from claimsage.schemas.policies import PolicyClauseVerificationRequest
from claimsage.services.policy_admin import (
    PolicyAccessDeniedError,
    get_policy_clauses,
)


def _review_fixture():
    document_id = uuid4()
    clause = PolicyClause(
        id=uuid4(),
        document_id=document_id,
        source_chunk_id=uuid4(),
        clause_identifier="source-page-1-chunk-0",
        clause_category="other",
        clause_text="Synthetic source passage.",
        source_page_number=1,
        verification_status="pending_review",
    )
    employee = Employee(
        id=uuid4(),
        email="policy.reviewer@example.test",
        display_name="Ananya Kulkarni",
        role=EmployeeRole.POLICY_SPECIALIST,
    )
    session = MagicMock(spec=Session)
    session.scalar.return_value = clause
    return document_id, clause, employee, session


def test_policy_specialist_can_explicitly_verify_source_clause():
    document_id, clause, employee, session = _review_fixture()

    response = review_policy_clause(
        document_id=document_id,
        clause_id=clause.id,
        payload=PolicyClauseVerificationRequest(
            verification_status="verified"
        ),
        employee=employee,
        session=session,
    )

    assert response.verification_status == "verified"
    assert response.source_chunk_id == clause.source_chunk_id
    assert clause.verified_by_employee_id == employee.id
    assert clause.verified_at is not None
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(clause)
    audit = session.add.call_args.args[0]
    assert isinstance(audit, AuditEvent)
    assert audit.action == "policy_clause_reviewed"
    assert audit.actor_employee_id == employee.id


def test_review_can_mark_clause_as_needing_review_again():
    document_id, clause, employee, session = _review_fixture()
    clause.verification_status = "verified"
    clause.verified_by_employee_id = employee.id

    response = review_policy_clause(
        document_id=document_id,
        clause_id=clause.id,
        payload=PolicyClauseVerificationRequest(
            verification_status="needs_review"
        ),
        employee=employee,
        session=session,
    )

    assert response.verification_status == "needs_review"
    assert clause.verified_by_employee_id is None
    assert clause.verified_at is None


def test_claims_adjuster_cannot_verify_policy_clause():
    document_id, clause, _, session = _review_fixture()
    employee = Employee(
        id=uuid4(),
        email="adjuster@example.test",
        display_name="Rohan Deshmukh",
        role=EmployeeRole.CLAIMS_ADJUSTER,
    )

    with pytest.raises(HTTPException) as exc_info:
        review_policy_clause(
            document_id=document_id,
            clause_id=clause.id,
            payload=PolicyClauseVerificationRequest(
                verification_status="verified"
            ),
            employee=employee,
            session=session,
        )

    assert exc_info.value.status_code == 403
    session.scalar.assert_not_called()
    session.commit.assert_not_called()


def test_admin_and_policy_specialist_can_read_policy_clauses():
    document_id, clause, specialist, session = _review_fixture()
    doc = PolicyDocument(id=document_id, filename="policy.pdf", checksum_sha256="abc")
    session.get.return_value = doc
    session.scalars.return_value.all.return_value = [clause]

    res_specialist = list_policy_clauses(
        policy_id=document_id,
        employee=specialist,
        session=session,
    )
    assert len(res_specialist) == 1
    assert res_specialist[0].id == clause.id

    admin = Employee(
        id=uuid4(),
        email="admin@example.test",
        display_name="Admin User",
        role=EmployeeRole.ADMIN,
    )
    res_admin = list_policy_document_clauses(
        document_id=document_id,
        employee=admin,
        session=session,
    )
    assert len(res_admin) == 1
    assert res_admin[0].clause_identifier == "source-page-1-chunk-0"


def test_authorized_claims_adjuster_can_read_policy_clauses():
    document_id, clause, _, session = _review_fixture()
    doc = PolicyDocument(id=document_id, filename="policy.pdf", checksum_sha256="abc")
    session.get.return_value = doc

    adjuster = Employee(
        id=uuid4(),
        email="alex.adjuster@claimsage.local",
        display_name="Alex Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="health-claims",
    )

    scalars_first = MagicMock()
    scalars_first.all.return_value = [document_id]
    scalars_second = MagicMock()
    scalars_second.all.return_value = [clause]
    session.scalars.side_effect = [scalars_first, scalars_second, scalars_first, scalars_second]

    res_by_policy = list_policy_clauses(
        policy_id=document_id,
        employee=adjuster,
        session=session,
    )
    assert len(res_by_policy) == 1
    assert res_by_policy[0].id == clause.id

    res_by_doc = list_policy_document_clauses(
        document_id=document_id,
        employee=adjuster,
        session=session,
    )
    assert len(res_by_doc) == 1
    assert res_by_doc[0].id == clause.id


def test_unauthorized_claims_adjuster_cannot_read_ungranted_policy_clauses():
    document_id, _, _, session = _review_fixture()
    doc = PolicyDocument(id=document_id, filename="policy.pdf", checksum_sha256="abc")
    session.get.return_value = doc
    session.scalars.return_value.all.return_value = []  # No policy access grants

    adjuster = Employee(
        id=uuid4(),
        email="other.adjuster@claimsage.local",
        display_name="Other Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="motor-claims",
    )

    with pytest.raises(HTTPException) as exc_info:
        list_policy_clauses(
            policy_id=document_id,
            employee=adjuster,
            session=session,
        )
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_doc_info:
        list_policy_document_clauses(
            document_id=document_id,
            employee=adjuster,
            session=session,
        )
    assert exc_doc_info.value.status_code == 403


def test_unauthorized_role_cannot_read_policy_clauses():
    document_id, _, _, session = _review_fixture()
    doc = PolicyDocument(id=document_id, filename="policy.pdf", checksum_sha256="abc")
    session.get.return_value = doc

    team_lead = Employee(
        id=uuid4(),
        email="lead@claimsage.local",
        display_name="Team Lead",
        role=EmployeeRole.TEAM_LEAD,
        team_id="health-claims",
    )

    with pytest.raises(PolicyAccessDeniedError):
        get_policy_clauses(session, team_lead, document_id)

    with pytest.raises(HTTPException) as exc_info:
        list_policy_clauses(
            policy_id=document_id,
            employee=team_lead,
            session=session,
        )
    assert exc_info.value.status_code == 403
