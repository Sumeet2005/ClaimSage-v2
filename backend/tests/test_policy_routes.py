"""Unit and integration tests for Phase 5.3: Policy Administration REST APIs."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from claimsage.api.routes.policies import (
    add_coverage,
    add_exclusion,
    create_policy,
    delete_coverage,
    delete_exclusion,
    get_policies,
    get_policy,
    link_claim,
    list_policy_claims,
    retry_policy_document_embedding,
    update_policy,
)
from claimsage.db.models import (
    Claim,
    Employee,
    EmployeeRole,
    PolicyCoverage,
    PolicyDocument,
    PolicyDocumentApplicability,
    PolicyExclusion,
)
from claimsage.schemas.policy_admin import (
    PolicyClaimLinkRequest,
    PolicyCoverageCreateRequest,
    PolicyCreateRequest,
    PolicyDetailResponse,
    PolicyExclusionCreateRequest,
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
)


@pytest.fixture
def policy_specialist() -> Employee:
    return Employee(
        id=uuid4(),
        email="specialist@claimsage.local",
        display_name="Policy Specialist Dr. Rao",
        role=EmployeeRole.POLICY_SPECIALIST,
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
        filename="star_health_optima.pdf",
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


# ---------------------------------------------------------------------------
# Policy CRUD Route Tests
# ---------------------------------------------------------------------------

def test_api_list_policies(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify GET /policies returns list of summaries."""
    session = MagicMock()
    with patch(
        "claimsage.api.routes.policies.list_policies",
        return_value=([
            PolicySummaryResponse(
                id=sample_policy_doc.id,
                policy_identifier="STAR-FHO-2026",
                insurer_name="Star Health",
                status="uploaded",
                has_document_attached=False,
            )
        ], 1),
    ):
        result = get_policies(
            query="STAR",
            insurance_type="health",
            limit=10,
            offset=0,
            employee=policy_specialist,
            session=session,
        )

        assert len(result) == 1
        assert result[0].policy_identifier == "STAR-FHO-2026"


def test_api_create_policy_success(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify POST /policies creates policy and returns detail response."""
    session = MagicMock()
    payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Family Health Optima",
        insurance_type="health",
        policy_version="v1.0",
        effective_from=date(2026, 1, 1),
    )

    with patch("claimsage.api.routes.policies.create_policy_record", return_value=sample_policy_doc):
        with patch(
            "claimsage.api.routes.policies.get_policy_detail",
            return_value=PolicyDetailResponse(
                id=sample_policy_doc.id,
                policy_identifier="STAR-FHO-2026",
                insurer_name="Star Health",
                product_name="Family Health Optima",
                status="uploaded",
            ),
        ):
            response = create_policy(payload, employee=policy_specialist, session=session)
            assert response.policy_identifier == "STAR-FHO-2026"
            assert response.id == sample_policy_doc.id


def test_api_create_policy_forbidden_for_adjuster(adjuster_employee: Employee):
    """Verify POST /policies returns 403 for unauthorized claims adjuster."""
    session = MagicMock()
    payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Optima",
        insurance_type="health",
        effective_from=date(2026, 1, 1),
    )

    with patch(
        "claimsage.api.routes.policies.create_policy_record",
        side_effect=PolicyAccessDeniedError("Only policy specialists or admins can create policies."),
    ):
        with pytest.raises(HTTPException) as exc_info:
            create_policy(payload, employee=adjuster_employee, session=session)
        assert exc_info.value.status_code == 403


def test_api_create_policy_conflict_duplicate(policy_specialist: Employee):
    """Verify POST /policies returns 409 Conflict when policy version exists or overlaps."""
    session = MagicMock()
    payload = PolicyCreateRequest(
        policy_identifier="STAR-FHO-2026",
        insurer_name="Star Health",
        product_name="Optima",
        insurance_type="health",
        effective_from=date(2026, 1, 1),
    )

    with patch(
        "claimsage.api.routes.policies.create_policy_record",
        side_effect=PolicyDuplicateError("Policy version dates overlap."),
    ):
        with pytest.raises(HTTPException) as exc_info:
            create_policy(payload, employee=policy_specialist, session=session)
        assert exc_info.value.status_code == 409


def test_api_get_policy_detail_found(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify GET /policies/{policy_id} returns detail."""
    session = MagicMock()
    with patch(
        "claimsage.api.routes.policies.get_policy_detail",
        return_value=PolicyDetailResponse(
            id=sample_policy_doc.id,
            policy_identifier="STAR-FHO-2026",
            status="uploaded",
        ),
    ):
        result = get_policy(sample_policy_doc.id, employee=policy_specialist, session=session)
        assert result.id == sample_policy_doc.id


def test_api_get_policy_detail_not_found(policy_specialist: Employee):
    """Verify GET /policies/{policy_id} returns 404 when missing."""
    session = MagicMock()
    missing_id = uuid4()
    with patch(
        "claimsage.api.routes.policies.get_policy_detail",
        side_effect=PolicyNotFoundError("Not found"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            get_policy(missing_id, employee=policy_specialist, session=session)
        assert exc_info.value.status_code == 404


def test_api_update_policy(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify PATCH /policies/{policy_id} updates metadata."""
    session = MagicMock()
    payload = PolicyUpdateRequest(policy_version="v2.0")

    with patch("claimsage.api.routes.policies.update_policy_record"):
        with patch(
            "claimsage.api.routes.policies.get_policy_detail",
            return_value=PolicyDetailResponse(
                id=sample_policy_doc.id,
                policy_identifier="STAR-FHO-2026",
                policy_version="v2.0",
                status="uploaded",
            ),
        ):
            result = update_policy(
                sample_policy_doc.id,
                payload,
                employee=policy_specialist,
                session=session,
            )
            assert result.policy_version == "v2.0"


def test_api_list_policy_claims(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify GET /policies/{policy_id}/claims returns linked claims list."""
    session = MagicMock()
    with patch(
        "claimsage.api.routes.policies.get_policy_claims",
        return_value=[{"claim_number": "CLM-001"}],
    ):
        claims = list_policy_claims(sample_policy_doc.id, employee=policy_specialist, session=session)
        assert len(claims) == 1
        assert claims[0]["claim_number"] == "CLM-001"


# ---------------------------------------------------------------------------
# Coverage & Exclusion Management Route Tests
# ---------------------------------------------------------------------------

def test_api_add_and_delete_coverage(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify POST and DELETE coverage endpoints."""
    session = MagicMock()
    cov_id = uuid4()
    cov_mock = PolicyCoverage(
        id=cov_id,
        document_id=sample_policy_doc.id,
        coverage_name="AYUSH",
        coverage_category="add_on",
        benefit_limit=Decimal("50000.00"),
        is_optional=True,
        created_at=datetime.now(UTC),
    )

    # Add coverage (201)
    with patch("claimsage.api.routes.policies.add_policy_coverage", return_value=cov_mock):
        response = add_coverage(
            sample_policy_doc.id,
            PolicyCoverageCreateRequest(coverage_name="AYUSH", is_optional=True),
            employee=policy_specialist,
            session=session,
        )
        assert response.coverage_name == "AYUSH"
        assert response.id == cov_id

    # Delete coverage (204)
    with patch("claimsage.api.routes.policies.remove_policy_coverage"):
        delete_coverage(sample_policy_doc.id, cov_id, employee=policy_specialist, session=session)


def test_api_add_and_delete_exclusion(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify POST and DELETE exclusion endpoints."""
    session = MagicMock()
    excl_id = uuid4()
    excl_mock = PolicyExclusion(
        id=excl_id,
        document_id=sample_policy_doc.id,
        exclusion_code="EXCL-PED",
        title="Pre-Existing",
        description="Waiting period",
        waiting_period_months=48,
        exclusion_type="waiting_period",
        created_at=datetime.now(UTC),
    )

    # Add exclusion (201)
    with patch("claimsage.api.routes.policies.add_policy_exclusion", return_value=excl_mock):
        response = add_exclusion(
            sample_policy_doc.id,
            PolicyExclusionCreateRequest(
                title="Pre-Existing",
                description="Waiting period",
                exclusion_type="waiting_period",
            ),
            employee=policy_specialist,
            session=session,
        )
        assert response.title == "Pre-Existing"
        assert response.id == excl_id

    # Delete exclusion (204)
    with patch("claimsage.api.routes.policies.remove_policy_exclusion"):
        delete_exclusion(sample_policy_doc.id, excl_id, employee=policy_specialist, session=session)


# ---------------------------------------------------------------------------
# Claim Linking Route Tests
# ---------------------------------------------------------------------------

def test_api_link_claim_success(policy_specialist: Employee, sample_policy_doc: PolicyDocument):
    """Verify POST /policies/{policy_id}/link-claim links claim."""
    session = MagicMock()
    claim_id = uuid4()

    from claimsage.schemas.policy_admin import PolicyClaimLinkResponse

    link_res = PolicyClaimLinkResponse(
        policy_id=sample_policy_doc.id,
        claim_id=claim_id,
        claim_number="CLM-HEALTH-001",
        policy_identifier="STAR-FHO-2026",
        linked_at=datetime.now(UTC),
    )

    with patch("claimsage.api.routes.policies.link_policy_to_claim", return_value=link_res):
        response = link_claim(
            sample_policy_doc.id,
            PolicyClaimLinkRequest(claim_id=claim_id),
            employee=policy_specialist,
            session=session,
        )
        assert response.claim_number == "CLM-HEALTH-001"
        assert response.policy_identifier == "STAR-FHO-2026"


def test_api_link_claim_incompatible_date_returns_422(
    policy_specialist: Employee,
    sample_policy_doc: PolicyDocument,
):
    """Verify POST /policies/{policy_id}/link-claim returns 422 Unprocessable when dates are incompatible."""
    session = MagicMock()
    claim_id = uuid4()

    with patch(
        "claimsage.api.routes.policies.link_policy_to_claim",
        side_effect=PolicyClaimIncompatibleError("Claim loss date occurs before policy effective date."),
    ):
        with pytest.raises(HTTPException) as exc_info:
            link_claim(
                sample_policy_doc.id,
                PolicyClaimLinkRequest(claim_id=claim_id),
                employee=policy_specialist,
                session=session,
            )
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Placeholder Document Isolation Tests
# ---------------------------------------------------------------------------

def test_placeholder_document_isolation_blocks_embedding_retry(
    policy_specialist: Employee,
    sample_policy_doc: PolicyDocument,
):
    """Verify calling retry-embedding on a placeholder policy document returns 400 Bad Request."""
    session = MagicMock()
    sample_policy_doc.checksum_sha256 = "placeholder:test_hash_001"
    session.get.return_value = sample_policy_doc

    with pytest.raises(HTTPException) as exc_info:
        retry_policy_document_embedding(
            sample_policy_doc.id,
            employee=policy_specialist,
            session=session,
        )

    assert exc_info.value.status_code == 400
    assert "without an attached document" in exc_info.value.detail
