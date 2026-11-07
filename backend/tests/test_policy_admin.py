"""Unit and integration tests for Phase 5.2: Backend Policy Administration Services & Schemas."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from claimsage.db.models import (
    Claim,
    Employee,
    EmployeeRole,
    PolicyCoverage,
    PolicyDocument,
    PolicyDocumentAccess,
    PolicyDocumentApplicability,
    PolicyExclusion,
)
from claimsage.schemas.policy_admin import (
    PolicyClaimLinkRequest,
    PolicyCoverageCreateRequest,
    PolicyCoverageResponse,
    PolicyCreateRequest,
    PolicyDetailResponse,
    PolicyExclusionCreateRequest,
    PolicyExclusionResponse,
    PolicySummaryResponse,
    PolicyUpdateRequest,
)
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.services.policy_admin import (
    PolicyAccessDeniedError,
    PolicyClaimIncompatibleError,
    PolicyCoverageNotFoundError,
    PolicyDuplicateError,
    PolicyExclusionNotFoundError,
    PolicyNotFoundError,
    add_policy_coverage,
    add_policy_exclusion,
    create_policy_record,
    get_policy_claims,
    get_policy_detail,
    link_policy_to_claim,
    list_policies,
    remove_policy_coverage,
    remove_policy_exclusion,
    update_policy_record,
)


@pytest.fixture
def policy_specialist() -> Employee:
    return Employee(
        id=uuid4(),
        email="specialist@claimsage.local",
        display_name="Policy Specialist Dr. Rao",
        role=EmployeeRole.ADMIN,
        team_id="policy-team",
    )


@pytest.fixture
def adjuster_employee() -> Employee:
    return Employee(
        id=uuid4(),
        email="adjuster@claimsage.local",
        display_name="Claims Adjuster John",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="health-team",
    )


@pytest.fixture
def sample_policy_doc(policy_specialist: Employee) -> PolicyDocument:
    doc = PolicyDocument(
        id=uuid4(),
        filename="star_health_optima_v1.pdf",
        checksum_sha256="placeholder:test_hash_001",
        mime_type="application/pdf",
        file_size_bytes=1,
        insurer_name="Star Health Insurance",
        product_name="Family Health Optima",
        policy_identifier="STAR-FHO-2026",
        insurance_type="health",
        policy_version="v1.0",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        uploaded_by_employee_id=policy_specialist.id,
        status="uploaded",
        created_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    doc.chunks = []
    doc.clauses = []
    doc.coverages = []
    doc.exclusions = []
    doc.supported_claim_types = [
        PolicyDocumentApplicability(document_id=doc.id, claim_type="health")
    ]
    return doc


@pytest.fixture
def sample_health_claim(adjuster_employee: Employee) -> Claim:
    return Claim(
        id=uuid4(),
        claim_number="CLM-HEALTH-999",
        claimant_name="Alice Smith",
        claim_type="health",
        status="under_review",
        team_id="health-team",
        assigned_employee_id=adjuster_employee.id,
        loss_date=date(2026, 5, 15),
    )


# ---------------------------------------------------------------------------
# Pydantic Schema Validation Tests
# ---------------------------------------------------------------------------

def test_policy_schema_date_validation():
    """Verify PolicyCreateRequest and PolicyUpdateRequest enforce effective_to >= effective_from."""
    with pytest.raises(ValidationError):
        PolicyCreateRequest(
            policy_identifier="STAR-FHO-001",
            insurer_name="Star Health",
            product_name="Optima",
            insurance_type="health",
            effective_from=date(2026, 6, 1),
            effective_to=date(2026, 1, 1),  # Invalid: before effective_from
        )

    with pytest.raises(ValidationError):
        PolicyUpdateRequest(
            effective_from=date(2026, 6, 1),
            effective_to=date(2026, 1, 1),  # Invalid
        )


def test_coverage_schema_monetary_and_percentage_validation():
    """Verify monetary values cannot be negative and co_pay must be <= 100."""
    # Negative benefit limit
    with pytest.raises(ValidationError):
        PolicyCoverageCreateRequest(
            coverage_name="Inpatient",
            benefit_limit=Decimal("-100.00"),
        )

    # Negative deductible
    with pytest.raises(ValidationError):
        PolicyCoverageCreateRequest(
            coverage_name="Inpatient",
            deductible=Decimal("-50.00"),
        )

    # Co-pay > 100
    with pytest.raises(ValidationError):
        PolicyCoverageCreateRequest(
            coverage_name="Inpatient",
            co_pay_percentage=Decimal("105.00"),
        )

    # Valid coverage
    cov = PolicyCoverageCreateRequest(
        coverage_name="Inpatient Care",
        benefit_limit=Decimal("500000.00"),
        deductible=Decimal("10000.00"),
        co_pay_percentage=Decimal("15.00"),
        waiting_period_days=30,
    )
    assert cov.coverage_name == "Inpatient Care"
    assert cov.benefit_limit == Decimal("500000.00")


def test_exclusion_schema_waiting_period_validation():
    """Verify exclusion waiting period cannot be negative."""
    with pytest.raises(ValidationError):
        PolicyExclusionCreateRequest(
            title="Pre-Existing",
            description="Prior conditions",
            waiting_period_months=-6,  # Invalid
        )

    excl = PolicyExclusionCreateRequest(
        exclusion_code="EXCL-01",
        title="Joint Replacement",
        description="Two year waiting period for joint replacement",
        waiting_period_months=24,
        exclusion_type="waiting_period",
    )
    assert excl.waiting_period_months == 24


# ---------------------------------------------------------------------------
# Policy CRUD & Service Tests
# ---------------------------------------------------------------------------

def test_create_policy_success(policy_specialist: Employee):
    """Verify policy specialist can create a structured policy record with coverages and exclusions."""
    session = MagicMock()
    session.scalar.return_value = None  # No duplicate

    payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health Insurance",
        product_name="Family Health Optima",
        insurance_type="health",
        policy_version="v1.0",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        source_url="https://starhealth.in/fho-terms.pdf",
        supported_claim_types=["health"],
        coverages=[
            PolicyCoverageCreateRequest(
                coverage_name="Inpatient Hospitalization",
                coverage_category="inpatient",
                benefit_limit=Decimal("500000.00"),
                deductible=Decimal("0.00"),
                co_pay_percentage=Decimal("10.00"),
                waiting_period_days=30,
            )
        ],
        exclusions=[
            PolicyExclusionCreateRequest(
                exclusion_code="EXCL-PED",
                title="Pre-Existing Diseases",
                description="Waiting period applies.",
                waiting_period_months=48,
                exclusion_type="waiting_period",
            )
        ],
    )

    doc = create_policy_record(session, policy_specialist, payload)

    assert doc.policy_identifier == "STAR-FHO-2026"
    assert doc.insurer_name == "Star Health Insurance"
    assert doc.insurance_type == "health"
    assert doc.status == "uploaded"
    assert doc.checksum_sha256.startswith("placeholder:")
    session.commit.assert_called_once()


def test_create_policy_unauthorized(adjuster_employee: Employee):
    """Verify claims adjuster cannot create policy records."""
    session = MagicMock()
    payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Optima",
        insurance_type="health",
        effective_from=date(2026, 1, 1),
    )

    with pytest.raises(PolicyAccessDeniedError):
        create_policy_record(session, adjuster_employee, payload)


def test_create_policy_duplicate_prevention(policy_specialist: Employee):
    """Verify creating a policy with the exact same identifier, insurer, and version raises PolicyDuplicateError."""
    session = MagicMock()
    existing_doc = PolicyDocument(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Optima",
        policy_version="v1.0",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )
    session.scalars.return_value.all.return_value = [existing_doc]

    payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Optima",
        insurance_type="health",
        policy_version="v1.0",
        effective_from=date(2026, 1, 1),
    )

    with pytest.raises(PolicyDuplicateError):
        create_policy_record(session, policy_specialist, payload)


def test_list_policies_and_pagination(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify list_policies pagination, search, and summary responses."""
    session = MagicMock()
    session.scalar.return_value = 1
    session.scalars.return_value.all.return_value = [sample_policy_doc]

    items, total = list_policies(
        session,
        policy_specialist,
        query="Family Health",
        insurance_type="health",
        limit=10,
        offset=0,
    )

    assert total == 1
    assert len(items) == 1
    summary = items[0]
    assert summary.policy_identifier == "STAR-FHO-2026"
    assert summary.insurer_name == "Star Health Insurance"
    assert summary.has_document_attached is False  # placeholder checksum


def test_get_policy_detail_authorized(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify retrieving full policy detail with eager loaded terms."""
    session = MagicMock()
    session.scalar.side_effect = [sample_policy_doc, 3]  # doc, linked_claims_count

    detail = get_policy_detail(session, sample_policy_doc.id, policy_specialist)

    assert detail.id == sample_policy_doc.id
    assert detail.policy_identifier == "STAR-FHO-2026"
    assert detail.linked_claims_count == 3
    assert detail.supported_claim_types == ["health"]


def test_get_policy_detail_unauthorized(adjuster_employee: Employee, sample_policy_doc: PolicyDocument):
    """Verify adjuster without document access grant cannot view policy detail."""
    session = MagicMock()
    session.scalar.return_value = sample_policy_doc
    # Mock no grants found for adjuster
    session.scalars.return_value.all.return_value = []

    with pytest.raises(PolicyAccessDeniedError):
        get_policy_detail(session, sample_policy_doc.id, adjuster_employee)


def test_update_policy_record(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify policy specialist can update policy version, dates, and metadata."""
    session = MagicMock()
    session.get.return_value = sample_policy_doc

    payload = PolicyUpdateRequest(
        policy_identifier="STAR-HEALTH-PREMIER-2026",
        insurance_type="health",
        policy_version="v2.0",
        effective_to=date(2027, 12, 31),
        source_url="https://starhealth.in/updated-terms.pdf",
        supported_claim_types=["health"],
    )

    updated = update_policy_record(session, policy_specialist, sample_policy_doc.id, payload)

    assert updated.policy_identifier == "STAR-HEALTH-PREMIER-2026"
    assert updated.insurance_type == "health"
    assert updated.policy_version == "v2.0"
    assert updated.effective_to == date(2027, 12, 31)
    assert updated.source_url == "https://starhealth.in/updated-terms.pdf"
    session.execute.assert_called_once()
    assert session.add.call_count == 2
    session.commit.assert_called_once()


def test_add_and_remove_policy_coverage(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify adding and removing a coverage term from a policy."""
    session = MagicMock()
    session.get.return_value = sample_policy_doc

    cov_payload = PolicyCoverageCreateRequest(
        coverage_name="AYUSH Care",
        coverage_category="add_on",
        benefit_limit=Decimal("50000.00"),
        is_optional=True,
    )

    cov = add_policy_coverage(session, policy_specialist, sample_policy_doc.id, cov_payload)
    assert cov.coverage_name == "AYUSH Care"
    assert cov.is_optional is True

    # Removal
    session.scalar.return_value = cov
    remove_policy_coverage(session, policy_specialist, sample_policy_doc.id, cov.id)
    session.delete.assert_called_once_with(cov)


def test_add_and_remove_policy_exclusion(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify adding and removing an exclusion term from a policy."""
    session = MagicMock()
    session.get.return_value = sample_policy_doc

    excl_payload = PolicyExclusionCreateRequest(
        exclusion_code="EXCL-COSMETIC",
        title="Cosmetic Surgery",
        description="Aesthetic procedures not covered.",
        exclusion_type="permanent",
    )

    excl = add_policy_exclusion(session, policy_specialist, sample_policy_doc.id, excl_payload)
    assert excl.title == "Cosmetic Surgery"

    # Removal
    session.scalar.return_value = excl
    remove_policy_exclusion(session, policy_specialist, sample_policy_doc.id, excl.id)
    session.delete.assert_called_once_with(excl)


# ---------------------------------------------------------------------------
# Claim-to-Policy Linking & Compatibility Tests
# ---------------------------------------------------------------------------

def test_link_policy_to_claim_success(
    adjuster_employee: Employee,
    sample_policy_doc: PolicyDocument,
    sample_health_claim: Claim,
):
    """Verify linking a claim to a compatible policy version binds metadata and grants access."""
    session = MagicMock()
    session.get.return_value = sample_policy_doc
    session.scalar.return_value = None  # No existing grant

    with patch(
        "claimsage.services.policy_admin.get_authorized_claim",
        return_value=sample_health_claim,
    ):
        result = link_policy_to_claim(
            session,
            adjuster_employee,
            sample_policy_doc.id,
            sample_health_claim.id,
        )

        assert result.claim_id == sample_health_claim.id
        assert result.policy_identifier == "STAR-FHO-2026"
        assert result.insurer_name == "Star Health Insurance"
        assert sample_health_claim.policy_identifier == "STAR-FHO-2026"
        session.commit.assert_called_once()


def test_link_policy_to_claim_incompatible_loss_date(
    adjuster_employee: Employee,
    sample_policy_doc: PolicyDocument,
    sample_health_claim: Claim,
):
    """Verify linking fails when claim loss date is outside the policy effective window."""
    session = MagicMock()
    session.get.return_value = sample_policy_doc
    sample_health_claim.loss_date = date(2025, 12, 1)  # Before policy start (2026-01-01)

    with patch(
        "claimsage.services.policy_admin.get_authorized_claim",
        return_value=sample_health_claim,
    ):
        with pytest.raises(PolicyClaimIncompatibleError) as exc_info:
            link_policy_to_claim(
                session,
                adjuster_employee,
                sample_policy_doc.id,
                sample_health_claim.id,
            )
        assert "before policy effective date" in str(exc_info.value)


def test_link_policy_to_claim_incompatible_line_of_business(
    adjuster_employee: Employee,
    sample_policy_doc: PolicyDocument,
    sample_health_claim: Claim,
):
    """Verify linking fails when insurance line does not match claim type."""
    session = MagicMock()
    sample_policy_doc.insurance_type = "auto"  # Auto policy vs Health claim
    session.get.return_value = sample_policy_doc

    with patch(
        "claimsage.services.policy_admin.get_authorized_claim",
        return_value=sample_health_claim,
    ):
        with pytest.raises(PolicyClaimIncompatibleError) as exc_info:
            link_policy_to_claim(
                session,
                adjuster_employee,
                sample_policy_doc.id,
                sample_health_claim.id,
            )
        assert "incompatible with claim type" in str(exc_info.value)


def test_historical_version_preservation(policy_specialist: Employee):
    """Verify multiple policy versions can coexist with distinct effective dates."""
    session = MagicMock()
    session.scalar.return_value = None  # No duplicate for new version

    v1_payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Family Health Optima",
        insurance_type="health",
        policy_version="v1.0",
        effective_from=date(2025, 1, 1),
        effective_to=date(2025, 12, 31),
    )
    v2_payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Family Health Optima",
        insurance_type="health",
        policy_version="v2.0",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )

    doc1 = create_policy_record(session, policy_specialist, v1_payload)
    doc2 = create_policy_record(session, policy_specialist, v2_payload)

    assert doc1.policy_version == "v1.0"
    assert doc2.policy_version == "v2.0"
    assert doc1.effective_from != doc2.effective_from


def test_audit_event_generation(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify policy operations record audit events through centralized Phase 4 audit service."""
    session = MagicMock()
    session.scalar.return_value = None

    with patch("claimsage.services.policy_admin.record_employee_action") as mock_audit:
        create_policy_record(
            session,
            policy_specialist,
            PolicyCreateRequest(
                policy_identifier="AUDIT-TEST-001",
                insurer_name="Test Insurer",
                product_name="Test Product",
                insurance_type="health",
                effective_from=date(2026, 1, 1),
            ),
        )

        mock_audit.assert_called_once()
        _, kwargs = mock_audit.call_args
        assert kwargs["employee"] == policy_specialist
        assert kwargs["action"] == "policy_created"
        assert kwargs["event_category"] == "policy"
        assert kwargs["resource_type"] == "policy"
