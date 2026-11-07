"""Unit tests for explicit human verification of source clauses."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from claimsage.api.routes.policies import review_policy_clause
from claimsage.db.models import (
    AuditEvent,
    Employee,
    EmployeeRole,
    PolicyClause,
)
from claimsage.schemas.policies import PolicyClauseVerificationRequest


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
