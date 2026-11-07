"""Business services for health insurance policy administration."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

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
from claimsage.schemas.policies import normalize_insurance_type
from claimsage.schemas.policy_admin import (
    PolicyClaimLinkResponse,
    PolicyCoverageCreateRequest,
    PolicyCoverageResponse,
    PolicyCreateRequest,
    PolicyDetailResponse,
    PolicyExclusionCreateRequest,
    PolicyExclusionResponse,
    PolicySummaryResponse,
    PolicyUpdateRequest,
)
from claimsage.services.audit import (
    AuditActorType,
    AuditEventCategory,
    AuditOutcome,
    record_employee_action,
)
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)

logger = logging.getLogger(__name__)

ADMIN_ROLES = {
    EmployeeRole.ADMIN,
}


class PolicyAdminError(Exception):
    """Base exception for policy administration errors."""


class PolicyNotFoundError(PolicyAdminError):
    """Raised when a policy document cannot be found."""


class PolicyAccessDeniedError(PolicyAdminError):
    """Raised when an employee is unauthorized to perform an action."""


class PolicyDuplicateError(PolicyAdminError):
    """Raised when an identical policy version already exists."""


class PolicyCoverageNotFoundError(PolicyAdminError):
    """Raised when a coverage term does not exist."""


class PolicyExclusionNotFoundError(PolicyAdminError):
    """Raised when an exclusion does not exist."""


class PolicyClaimIncompatibleError(PolicyAdminError):
    """Raised when a policy cannot be linked to a claim due to date or line incompatibility."""


def _has_admin_permission(employee: Employee) -> bool:
    return employee.role in ADMIN_ROLES


def _accessible_policy_ids_for_adjuster(
    session: Session,
    employee: Employee,
) -> set[UUID]:
    """Retrieve IDs of policy documents granted to employee's team or assigned claims."""
    conditions = []
    if employee.team_id:
        conditions.append(PolicyDocumentAccess.team_id == employee.team_id)

    # Claims assigned or accessible to this employee
    subq = select(Claim.id).where(
        or_(
            Claim.assigned_employee_id == employee.id,
            (Claim.team_id == employee.team_id) if employee.team_id else False,
        )
    )
    conditions.append(PolicyDocumentAccess.claim_id.in_(subq))

    grants = session.scalars(
        select(PolicyDocumentAccess.document_id).where(or_(*conditions))
    ).all()
    return set(grants)


def list_policies(
    session: Session,
    employee: Employee,
    *,
    query: str | None = None,
    insurer_name: str | None = None,
    insurance_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PolicySummaryResponse], int]:
    """List and search policy documents matching filters with pagination."""
    base_query = select(PolicyDocument)

    # Scoped access for adjusters and team leads
    if not _has_admin_permission(employee):
        accessible_ids = _accessible_policy_ids_for_adjuster(session, employee)
        if not accessible_ids:
            return [], 0
        base_query = base_query.where(PolicyDocument.id.in_(accessible_ids))

    conditions = []

    if query and query.strip():
        search_pattern = f"%{query.strip()}%"
        conditions.append(
            or_(
                PolicyDocument.policy_identifier.ilike(search_pattern),
                PolicyDocument.insurer_name.ilike(search_pattern),
                PolicyDocument.product_name.ilike(search_pattern),
                PolicyDocument.filename.ilike(search_pattern),
            )
        )

    if insurer_name and insurer_name.strip():
        conditions.append(PolicyDocument.insurer_name.ilike(f"%{insurer_name.strip()}%"))

    if insurance_type and insurance_type.strip():
        normalized = normalize_insurance_type(insurance_type)
        conditions.append(PolicyDocument.insurance_type == normalized)

    if status and status.strip():
        conditions.append(PolicyDocument.status == status.strip())

    if conditions:
        base_query = base_query.where(and_(*conditions))

    # Total count query
    count_stmt = select(func.count(PolicyDocument.id))
    if not _has_admin_permission(employee):
        accessible_ids = _accessible_policy_ids_for_adjuster(session, employee)
        count_stmt = count_stmt.where(PolicyDocument.id.in_(accessible_ids))
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))

    total_count = session.scalar(count_stmt) or 0

    documents = session.scalars(
        base_query.options(
            selectinload(PolicyDocument.chunks),
            selectinload(PolicyDocument.clauses),
            selectinload(PolicyDocument.coverages),
            selectinload(PolicyDocument.exclusions),
        )
        .order_by(desc(PolicyDocument.created_at))
        .offset(offset)
        .limit(limit)
    ).all()

    items = []
    for doc in documents:
        has_doc = not doc.checksum_sha256.startswith("placeholder:")
        items.append(
            PolicySummaryResponse(
                id=doc.id,
                policy_identifier=doc.policy_identifier or "N/A",
                insurer_name=doc.insurer_name,
                product_name=doc.product_name,
                insurance_type=doc.insurance_type,
                policy_version=doc.policy_version,
                effective_from=doc.effective_from,
                effective_to=doc.effective_to,
                status=doc.status,
                has_document_attached=has_doc,
                chunk_count=len(doc.chunks),
                clause_count=len(doc.clauses),
                coverage_count=len(doc.coverages),
                exclusion_count=len(doc.exclusions),
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
        )

    return items, total_count


def get_policy_detail(
    session: Session,
    policy_id: UUID,
    employee: Employee,
) -> PolicyDetailResponse:
    """Retrieve full policy details, coverages, exclusions, and applicability."""
    doc = session.scalar(
        select(PolicyDocument)
        .options(
            selectinload(PolicyDocument.chunks),
            selectinload(PolicyDocument.clauses),
            selectinload(PolicyDocument.coverages),
            selectinload(PolicyDocument.exclusions),
            selectinload(PolicyDocument.supported_claim_types),
        )
        .where(PolicyDocument.id == policy_id)
    )

    if doc is None:
        raise PolicyNotFoundError(f"Policy {policy_id} not found.")

    if not _has_admin_permission(employee):
        accessible_ids = _accessible_policy_ids_for_adjuster(session, employee)
        if doc.id not in accessible_ids:
            raise PolicyAccessDeniedError("Access to this policy is restricted.")

    # Linked claims count
    linked_claims_count = session.scalar(
        select(func.count(PolicyDocumentAccess.id)).where(
            PolicyDocumentAccess.document_id == policy_id,
            PolicyDocumentAccess.claim_id.is_not(None),
        )
    ) or 0

    has_doc = not doc.checksum_sha256.startswith("placeholder:")

    return PolicyDetailResponse(
        id=doc.id,
        policy_identifier=doc.policy_identifier or "N/A",
        insurer_name=doc.insurer_name,
        product_name=doc.product_name,
        insurance_type=doc.insurance_type,
        policy_version=doc.policy_version,
        effective_from=doc.effective_from,
        effective_to=doc.effective_to,
        status=doc.status,
        has_document_attached=has_doc,
        chunk_count=len(doc.chunks),
        clause_count=len(doc.clauses),
        coverage_count=len(doc.coverages),
        exclusion_count=len(doc.exclusions),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        filename=doc.filename if has_doc else None,
        file_size_bytes=doc.file_size_bytes if has_doc else 0,
        source_url=doc.source_url,
        supported_claim_types=[a.claim_type for a in doc.supported_claim_types],
        coverages=[PolicyCoverageResponse.model_validate(c) for c in doc.coverages],
        exclusions=[PolicyExclusionResponse.model_validate(e) for e in doc.exclusions],
        linked_claims_count=linked_claims_count,
    )


def create_policy_record(
    session: Session,
    employee: Employee,
    payload: PolicyCreateRequest,
) -> PolicyDocument:
    """Create a structured policy record with coverages and exclusions."""
    if not _has_admin_permission(employee):
        raise PolicyAccessDeniedError("Only policy specialists or admins can create policies.")

    # Check for identical version or overlapping effective date ranges with an existing version
    existing_versions = session.scalars(
        select(PolicyDocument).where(
            PolicyDocument.policy_identifier == payload.policy_identifier,
            PolicyDocument.insurer_name == payload.insurer_name,
            PolicyDocument.product_name == payload.product_name,
        )
    ).all()
    for v in existing_versions:
        if v.policy_version == payload.policy_version:
            raise PolicyDuplicateError(
                f"Policy {payload.policy_identifier} ({payload.policy_version}) already exists."
            )
        v_start = v.effective_from
        v_end = v.effective_to
        new_start = payload.effective_from
        new_end = payload.effective_to
        if v_start is not None and new_start is not None:
            overlap = (v_end is None or new_start <= v_end) and (new_end is None or v_start <= new_end)
            if overlap:
                raise PolicyDuplicateError(
                    f"Policy version dates ({new_start} to {new_end}) overlap with existing version {v.policy_version} ({v_start} to {v_end})."
                )

    clean_insurance_type = normalize_insurance_type(payload.insurance_type)

    doc = PolicyDocument(
        id=uuid4(),
        filename=f"policy_{payload.policy_identifier.replace('/', '_')}_{payload.policy_version}.pdf",
        checksum_sha256=f"placeholder:{uuid4().hex}",
        mime_type="application/pdf",
        file_size_bytes=1,
        source_url=payload.source_url,
        insurer_name=payload.insurer_name,
        product_name=payload.product_name,
        policy_identifier=payload.policy_identifier,
        insurance_type=clean_insurance_type,
        policy_version=payload.policy_version,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        uploaded_by_employee_id=employee.id,
        status="uploaded",
    )
    session.add(doc)
    session.flush()

    # Applicability
    for claim_type in payload.supported_claim_types:
        norm_type = normalize_insurance_type(claim_type)
        session.add(
            PolicyDocumentApplicability(
                document_id=doc.id,
                claim_type=norm_type,
            )
        )

    # Initial coverages
    for cov in payload.coverages:
        session.add(
            PolicyCoverage(
                document_id=doc.id,
                coverage_name=cov.coverage_name,
                coverage_category=cov.coverage_category,
                benefit_limit=cov.benefit_limit,
                deductible=cov.deductible,
                co_pay_percentage=cov.co_pay_percentage,
                waiting_period_days=cov.waiting_period_days,
                description=cov.description,
                is_optional=cov.is_optional,
            )
        )

    # Initial exclusions
    for excl in payload.exclusions:
        session.add(
            PolicyExclusion(
                document_id=doc.id,
                exclusion_code=excl.exclusion_code,
                title=excl.title,
                description=excl.description,
                waiting_period_months=excl.waiting_period_months,
                exclusion_type=excl.exclusion_type,
            )
        )

    record_employee_action(
        session,
        employee=employee,
        action="policy_created",
        event_category=AuditEventCategory.POLICY,
        resource_type="policy",
        resource_id=str(doc.id),
        details=f"Created policy {doc.policy_identifier} ({doc.policy_version}).",
        metadata={
            "policy_identifier": doc.policy_identifier,
            "policy_version": doc.policy_version,
            "insurer_name": doc.insurer_name,
            "product_name": doc.product_name,
            "effective_from": doc.effective_from.isoformat() if doc.effective_from else None,
            "effective_to": doc.effective_to.isoformat() if doc.effective_to else None,
            "coverages_count": len(payload.coverages),
            "exclusions_count": len(payload.exclusions),
        },
    )

    session.commit()
    session.refresh(doc)
    return doc


def update_policy_record(
    session: Session,
    employee: Employee,
    policy_id: UUID,
    payload: PolicyUpdateRequest,
) -> PolicyDocument:
    """Update policy metadata, version, or effective dates without overwriting history."""
    if not _has_admin_permission(employee):
        raise PolicyAccessDeniedError("Only policy specialists or admins can update policies.")

    doc = session.get(PolicyDocument, policy_id)
    if doc is None:
        raise PolicyNotFoundError(f"Policy {policy_id} not found.")

    updated_fields = []
    if payload.policy_identifier is not None:
        doc.policy_identifier = payload.policy_identifier
        updated_fields.append("policy_identifier")
    if payload.insurer_name is not None:
        doc.insurer_name = payload.insurer_name
        updated_fields.append("insurer_name")
    if payload.product_name is not None:
        doc.product_name = payload.product_name
        updated_fields.append("product_name")
    if payload.insurance_type is not None:
        clean_insurance_type = normalize_insurance_type(payload.insurance_type)
        doc.insurance_type = clean_insurance_type
        updated_fields.append("insurance_type")
    if payload.policy_version is not None:
        doc.policy_version = payload.policy_version
        updated_fields.append("policy_version")
    if payload.effective_from is not None:
        doc.effective_from = payload.effective_from
        updated_fields.append("effective_from")
    if payload.effective_to is not None:
        doc.effective_to = payload.effective_to
        updated_fields.append("effective_to")
    if payload.source_url is not None:
        doc.source_url = payload.source_url
        updated_fields.append("source_url")
    if payload.status is not None:
        doc.status = payload.status
        updated_fields.append("status")
    if payload.supported_claim_types is not None:
        session.execute(
            delete(PolicyDocumentApplicability).where(
                PolicyDocumentApplicability.document_id == doc.id
            )
        )
        for claim_type in payload.supported_claim_types:
            norm_type = normalize_insurance_type(claim_type)
            session.add(
                PolicyDocumentApplicability(
                    document_id=doc.id,
                    claim_type=norm_type,
                )
            )
        updated_fields.append("supported_claim_types")

    record_employee_action(
        session,
        employee=employee,
        action="policy_updated",
        event_category=AuditEventCategory.POLICY,
        resource_type="policy",
        resource_id=str(doc.id),
        details=f"Updated policy {doc.policy_identifier} fields: {', '.join(updated_fields)}.",
        metadata={
            "policy_identifier": doc.policy_identifier,
            "updated_fields": updated_fields,
        },
    )

    session.commit()
    session.refresh(doc)
    return doc


def add_policy_coverage(
    session: Session,
    employee: Employee,
    policy_id: UUID,
    payload: PolicyCoverageCreateRequest,
) -> PolicyCoverage:
    """Add a structured coverage term to an existing policy."""
    if not _has_admin_permission(employee):
        raise PolicyAccessDeniedError("Only policy specialists or admins can manage coverages.")

    doc = session.get(PolicyDocument, policy_id)
    if doc is None:
        raise PolicyNotFoundError(f"Policy {policy_id} not found.")

    coverage = PolicyCoverage(
        document_id=doc.id,
        coverage_name=payload.coverage_name,
        coverage_category=payload.coverage_category,
        benefit_limit=payload.benefit_limit,
        deductible=payload.deductible,
        co_pay_percentage=payload.co_pay_percentage,
        waiting_period_days=payload.waiting_period_days,
        description=payload.description,
        is_optional=payload.is_optional,
    )
    session.add(coverage)
    session.flush()

    record_employee_action(
        session,
        employee=employee,
        action="policy_coverage_added",
        event_category=AuditEventCategory.POLICY,
        resource_type="policy_coverage",
        resource_id=str(coverage.id),
        details=f"Added coverage '{coverage.coverage_name}' to policy {doc.policy_identifier}.",
        metadata={
            "policy_id": str(doc.id),
            "coverage_name": coverage.coverage_name,
            "coverage_category": coverage.coverage_category,
            "benefit_limit": str(coverage.benefit_limit) if coverage.benefit_limit else None,
        },
    )

    session.commit()
    session.refresh(coverage)
    return coverage


def remove_policy_coverage(
    session: Session,
    employee: Employee,
    policy_id: UUID,
    coverage_id: UUID,
) -> None:
    """Remove a structured coverage term from a policy."""
    if not _has_admin_permission(employee):
        raise PolicyAccessDeniedError("Only policy specialists or admins can manage coverages.")

    coverage = session.scalar(
        select(PolicyCoverage).where(
            PolicyCoverage.id == coverage_id,
            PolicyCoverage.document_id == policy_id,
        )
    )
    if coverage is None:
        raise PolicyCoverageNotFoundError(f"Coverage {coverage_id} not found for policy {policy_id}.")

    cov_name = coverage.coverage_name
    session.delete(coverage)

    record_employee_action(
        session,
        employee=employee,
        action="policy_coverage_removed",
        event_category=AuditEventCategory.POLICY,
        resource_type="policy_coverage",
        resource_id=str(coverage_id),
        details=f"Removed coverage '{cov_name}' from policy {policy_id}.",
        metadata={"policy_id": str(policy_id), "coverage_name": cov_name},
    )

    session.commit()


def add_policy_exclusion(
    session: Session,
    employee: Employee,
    policy_id: UUID,
    payload: PolicyExclusionCreateRequest,
) -> PolicyExclusion:
    """Add an explicit exclusion to an existing policy."""
    if not _has_admin_permission(employee):
        raise PolicyAccessDeniedError("Only policy specialists or admins can manage exclusions.")

    doc = session.get(PolicyDocument, policy_id)
    if doc is None:
        raise PolicyNotFoundError(f"Policy {policy_id} not found.")

    exclusion = PolicyExclusion(
        document_id=doc.id,
        exclusion_code=payload.exclusion_code,
        title=payload.title,
        description=payload.description,
        waiting_period_months=payload.waiting_period_months,
        exclusion_type=payload.exclusion_type,
    )
    session.add(exclusion)
    session.flush()

    record_employee_action(
        session,
        employee=employee,
        action="policy_exclusion_added",
        event_category=AuditEventCategory.POLICY,
        resource_type="policy_exclusion",
        resource_id=str(exclusion.id),
        details=f"Added exclusion '{exclusion.title}' to policy {doc.policy_identifier}.",
        metadata={
            "policy_id": str(doc.id),
            "exclusion_code": exclusion.exclusion_code,
            "title": exclusion.title,
            "exclusion_type": exclusion.exclusion_type,
        },
    )

    session.commit()
    session.refresh(exclusion)
    return exclusion


def remove_policy_exclusion(
    session: Session,
    employee: Employee,
    policy_id: UUID,
    exclusion_id: UUID,
) -> None:
    """Remove an explicit exclusion from a policy."""
    if not _has_admin_permission(employee):
        raise PolicyAccessDeniedError("Only policy specialists or admins can manage exclusions.")

    exclusion = session.scalar(
        select(PolicyExclusion).where(
            PolicyExclusion.id == exclusion_id,
            PolicyExclusion.document_id == policy_id,
        )
    )
    if exclusion is None:
        raise PolicyExclusionNotFoundError(f"Exclusion {exclusion_id} not found for policy {policy_id}.")

    title = exclusion.title
    session.delete(exclusion)

    record_employee_action(
        session,
        employee=employee,
        action="policy_exclusion_removed",
        event_category=AuditEventCategory.POLICY,
        resource_type="policy_exclusion",
        resource_id=str(exclusion_id),
        details=f"Removed exclusion '{title}' from policy {policy_id}.",
        metadata={"policy_id": str(policy_id), "title": title},
    )

    session.commit()


def link_policy_to_claim(
    session: Session,
    employee: Employee,
    policy_id: UUID,
    claim_id: UUID,
) -> PolicyClaimLinkResponse:
    """Validate and bind a claim to a policy version with effective-date and line compatibility."""
    # 1. Authorize claim access
    claim = get_authorized_claim(session, employee_id=employee.id, claim_id=claim_id)

    # 2. Retrieve policy
    doc = session.get(PolicyDocument, policy_id)
    if doc is None:
        raise PolicyNotFoundError(f"Policy {policy_id} not found.")

    # 3. Line of business compatibility check
    if doc.insurance_type and claim.claim_type:
        norm_policy_type = normalize_insurance_type(doc.insurance_type)
        norm_claim_type = normalize_insurance_type(claim.claim_type)
        if norm_policy_type != norm_claim_type:
            raise PolicyClaimIncompatibleError(
                f"Policy line of business '{doc.insurance_type}' is incompatible with claim type '{claim.claim_type}'."
            )

    # 4. Effective date compatibility check against claim loss date
    if claim.loss_date is not None:
        if doc.effective_from is not None and claim.loss_date < doc.effective_from:
            raise PolicyClaimIncompatibleError(
                f"Claim loss date ({claim.loss_date}) occurs before policy effective date ({doc.effective_from})."
            )
        if doc.effective_to is not None and claim.loss_date > doc.effective_to:
            raise PolicyClaimIncompatibleError(
                f"Claim loss date ({claim.loss_date}) occurs after policy expiration date ({doc.effective_to})."
            )

    # 5. Bind claim metadata
    claim.policy_identifier = doc.policy_identifier
    claim.insurer_name = doc.insurer_name
    claim.product_name = doc.product_name

    # 6. Ensure PolicyDocumentAccess grant exists for this claim
    existing_grant = session.scalar(
        select(PolicyDocumentAccess).where(
            PolicyDocumentAccess.document_id == doc.id,
            PolicyDocumentAccess.claim_id == claim.id,
        )
    )
    if existing_grant is None:
        grant = PolicyDocumentAccess(
            document_id=doc.id,
            claim_id=claim.id,
            granted_by_employee_id=employee.id,
        )
        session.add(grant)

    # 7. Audit log
    now = datetime.now(UTC)
    record_employee_action(
        session,
        employee=employee,
        action="policy_linked_to_claim",
        event_category=AuditEventCategory.POLICY,
        resource_type="policy",
        resource_id=str(doc.id),
        claim_id=claim.id,
        details=f"Linked claim {claim.claim_number} to policy {doc.policy_identifier}.",
        metadata={
            "claim_id": str(claim.id),
            "claim_number": claim.claim_number,
            "policy_identifier": doc.policy_identifier,
            "policy_version": doc.policy_version,
            "loss_date": claim.loss_date.isoformat() if claim.loss_date else None,
        },
    )

    session.commit()
    session.refresh(claim)

    return PolicyClaimLinkResponse(
        policy_id=doc.id,
        claim_id=claim.id,
        claim_number=claim.claim_number,
        policy_identifier=doc.policy_identifier or "N/A",
        insurer_name=doc.insurer_name,
        product_name=doc.product_name,
        linked_at=now,
    )


def get_policy_claims(
    session: Session,
    employee: Employee,
    policy_id: UUID,
) -> list[dict]:
    """Retrieve claims associated with this policy version."""
    doc = session.get(PolicyDocument, policy_id)
    if doc is None:
        raise PolicyNotFoundError(f"Policy {policy_id} not found.")

    if not _has_admin_permission(employee):
        accessible_ids = _accessible_policy_ids_for_adjuster(session, employee)
        if doc.id not in accessible_ids:
            raise PolicyAccessDeniedError("Access to this policy is restricted.")

    # Find claims linked via PolicyDocumentAccess grant or matching policy identity
    grants_subq = select(PolicyDocumentAccess.claim_id).where(
        PolicyDocumentAccess.document_id == policy_id,
        PolicyDocumentAccess.claim_id.is_not(None),
    )

    claims = session.scalars(
        select(Claim)
        .where(
            or_(
                Claim.id.in_(grants_subq),
                and_(
                    Claim.policy_identifier == doc.policy_identifier,
                    Claim.insurer_name == doc.insurer_name,
                ),
            )
        )
        .order_by(desc(Claim.created_at))
    ).all()

    return [
        {
            "id": str(c.id),
            "claim_number": c.claim_number,
            "claimant_name": c.claimant_name,
            "claim_type": c.claim_type,
            "status": c.status,
            "loss_date": c.loss_date.isoformat() if c.loss_date else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in claims
    ]
