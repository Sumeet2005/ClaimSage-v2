"""Unit tests for Phase 5.1: Policy Administration Database Foundation (PolicyCoverage and PolicyExclusion)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index

from claimsage.db.models import (
    Employee,
    EmployeeRole,
    PolicyChunk,
    PolicyClause,
    PolicyCoverage,
    PolicyDocument,
    PolicyDocumentAccess,
    PolicyDocumentApplicability,
    PolicyExclusion,
)


@pytest.fixture
def mock_employee() -> Employee:
    return Employee(
        id=uuid4(),
        email="specialist@claimsage.local",
        display_name="Policy Specialist",
        role=EmployeeRole.POLICY_SPECIALIST,
        team_id="health-team",
    )


@pytest.fixture
def mock_policy_document(mock_employee: Employee) -> PolicyDocument:
    return PolicyDocument(
        id=uuid4(),
        filename="star_health_optima.pdf",
        checksum_sha256="a" * 64,
        mime_type="application/pdf",
        file_size_bytes=1024 * 500,
        insurer_name="Star Health Insurance",
        product_name="Family Health Optima",
        policy_identifier="STAR-FHO-2026",
        insurance_type="health",
        policy_version="v2.1",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        uploaded_by_employee_id=mock_employee.id,
        status="uploaded",
    )


def test_policy_coverage_model_instantiation(mock_policy_document: PolicyDocument):
    """Verify PolicyCoverage instantiation, types, and defaults."""
    coverage = PolicyCoverage(
        id=uuid4(),
        document_id=mock_policy_document.id,
        coverage_name="Inpatient Hospitalization",
        coverage_category="inpatient",
        benefit_limit=Decimal("500000.00"),
        deductible=Decimal("10000.00"),
        co_pay_percentage=Decimal("10.00"),
        waiting_period_days=30,
        description="Room rent, boarding, and nursing expenses up to 1% of Sum Insured.",
        is_optional=False,
    )

    assert coverage.coverage_name == "Inpatient Hospitalization"
    assert coverage.coverage_category == "inpatient"
    assert isinstance(coverage.benefit_limit, Decimal)
    assert coverage.benefit_limit == Decimal("500000.00")
    assert isinstance(coverage.deductible, Decimal)
    assert coverage.deductible == Decimal("10000.00")
    assert isinstance(coverage.co_pay_percentage, Decimal)
    assert coverage.co_pay_percentage == Decimal("10.00")
    assert coverage.waiting_period_days == 30
    assert coverage.is_optional is False
    assert coverage.document_id == mock_policy_document.id


def test_policy_exclusion_model_instantiation(mock_policy_document: PolicyDocument):
    """Verify PolicyExclusion instantiation and properties."""
    exclusion = PolicyExclusion(
        id=uuid4(),
        document_id=mock_policy_document.id,
        exclusion_code="EXCL-PED-48",
        title="Pre-Existing Diseases Waiting Period",
        description="Any condition, ailment, or injury diagnosed within 48 months prior to policy inception.",
        waiting_period_months=48,
        exclusion_type="waiting_period",
    )

    assert exclusion.exclusion_code == "EXCL-PED-48"
    assert exclusion.title == "Pre-Existing Diseases Waiting Period"
    assert exclusion.waiting_period_months == 48
    assert exclusion.exclusion_type == "waiting_period"
    assert exclusion.document_id == mock_policy_document.id


def test_policy_document_relationships_bidirectional(mock_policy_document: PolicyDocument):
    """Verify bidirectional relationships between PolicyDocument, PolicyCoverage, and PolicyExclusion."""
    coverage1 = PolicyCoverage(
        id=uuid4(),
        document_id=mock_policy_document.id,
        coverage_name="Day Care Procedures",
        coverage_category="daycare",
        benefit_limit=Decimal("200000.00"),
        is_optional=False,
    )
    coverage2 = PolicyCoverage(
        id=uuid4(),
        document_id=mock_policy_document.id,
        coverage_name="AYUSH Treatment",
        coverage_category="add_on",
        benefit_limit=Decimal("50000.00"),
        is_optional=True,
    )

    exclusion = PolicyExclusion(
        id=uuid4(),
        document_id=mock_policy_document.id,
        exclusion_code="EXCL-COSMETIC",
        title="Cosmetic or Aesthetic Surgery",
        description="Surgery performed to alter appearance without functional impairment.",
        waiting_period_months=None,
        exclusion_type="permanent",
    )

    # Attach to document
    mock_policy_document.coverages = [coverage1, coverage2]
    mock_policy_document.exclusions = [exclusion]

    assert len(mock_policy_document.coverages) == 2
    assert mock_policy_document.coverages[0].coverage_name == "Day Care Procedures"
    assert mock_policy_document.coverages[1].is_optional is True

    assert len(mock_policy_document.exclusions) == 1
    assert mock_policy_document.exclusions[0].title == "Cosmetic or Aesthetic Surgery"

    # Reverse link
    assert coverage1.document == mock_policy_document
    assert exclusion.document == mock_policy_document


def test_policy_coverage_table_constraints():
    """Verify check constraints and indexes on policy_coverages table metadata."""
    table = PolicyCoverage.__table__
    constraint_names = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}

    assert "ck_policy_coverages_benefit_limit_nonnegative" in constraint_names
    assert "ck_policy_coverages_deductible_nonnegative" in constraint_names
    assert "ck_policy_coverages_co_pay_percentage_range" in constraint_names
    assert "ck_policy_coverages_waiting_period_nonnegative" in constraint_names
    assert "ck_policy_coverages_name_nonempty" in constraint_names

    index_names = {idx.name for idx in table.indexes}
    assert "ix_policy_coverages_document_id" in index_names
    assert "ix_policy_coverages_category" in index_names

    # Foreign key check
    fk_constraints = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert len(fk_constraints) >= 1
    fk = fk_constraints[0]
    assert fk.elements[0].column.table.name == "policy_documents"
    assert fk.ondelete == "CASCADE"


def test_policy_exclusion_table_constraints():
    """Verify check constraints and indexes on policy_exclusions table metadata."""
    table = PolicyExclusion.__table__
    constraint_names = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}

    assert "ck_policy_exclusions_waiting_period_nonnegative" in constraint_names
    assert "ck_policy_exclusions_title_nonempty" in constraint_names
    assert "ck_policy_exclusions_description_nonempty" in constraint_names
    assert "ck_policy_exclusions_type_valid" in constraint_names

    index_names = {idx.name for idx in table.indexes}
    assert "ix_policy_exclusions_document_id" in index_names
    assert "ix_policy_exclusions_code" in index_names

    # Foreign key check
    fk_constraints = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert len(fk_constraints) >= 1
    fk = fk_constraints[0]
    assert fk.elements[0].column.table.name == "policy_documents"
    assert fk.ondelete == "CASCADE"


def test_backward_compatibility_existing_policy_models(mock_policy_document: PolicyDocument):
    """Verify existing PolicyDocument, PolicyClause, PolicyChunk, and PolicyDocumentAccess remain intact."""
    # 1. Existing PolicyDocument attributes
    assert mock_policy_document.filename == "star_health_optima.pdf"
    assert mock_policy_document.policy_identifier == "STAR-FHO-2026"
    assert mock_policy_document.insurance_type == "health"

    # 2. Existing PolicyChunk
    chunk = PolicyChunk(
        id=uuid4(),
        document_id=mock_policy_document.id,
        page_number=1,
        chunk_index=0,
        chunk_id="chunk_test_01",
        text="Section 3: Hospitalization expenses.",
        extraction_method="native",
    )
    assert chunk.document_id == mock_policy_document.id
    assert chunk.extraction_method == "native"

    # 3. Existing PolicyClause
    clause = PolicyClause(
        id=uuid4(),
        document_id=mock_policy_document.id,
        source_chunk_id=chunk.id,
        clause_identifier="SEC-3.1",
        clause_category="coverage",
        title="Inpatient Treatment",
        clause_text="Expenses incurred for hospitalization are covered up to the Sum Insured.",
        source_page_number=1,
        verification_status="verified",
    )
    assert clause.clause_identifier == "SEC-3.1"
    assert clause.verification_status == "verified"

    # 4. Existing PolicyDocumentAccess
    access = PolicyDocumentAccess(
        id=uuid4(),
        document_id=mock_policy_document.id,
        team_id="health-team",
        granted_by_employee_id=uuid4(),
    )
    assert access.team_id == "health-team"
    assert access.claim_id is None
