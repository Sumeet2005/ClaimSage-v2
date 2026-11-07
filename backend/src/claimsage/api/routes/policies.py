"""Authenticated policy document and access-management endpoints."""

import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from typing import Any
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from claimsage.services.storage import (
    ObjectNotFoundError,
    StorageError,
    StorageUnavailableError,
    generate_secure_object_key,
    get_storage_service,
)
from claimsage.schemas.policy_admin import (
    PolicyClaimLinkRequest,
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
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import (
    AuditEvent,
    Claim,
    Employee,
    EmployeeRole,
    PolicyClause,
    PolicyDocument,
    PolicyDocumentAccess,
)
from claimsage.db.session import get_db
from claimsage.rag.document_loader import (
    MAX_PDF_SIZE_BYTES,
    DocumentIngestionError,
)
from claimsage.schemas.policies import (
    PolicyClauseResponse,
    PolicyClauseVerificationRequest,
    PolicyDocumentAccessGrantRequest,
    PolicyDocumentAccessGrantResponse,
    PolicyDocumentApplicability,
    PolicyDocumentUploadResponse,
)
from claimsage.services.document_persistence import (
    DocumentPersistenceError,
    DuplicatePolicyDocumentError,
    persist_policy_document,
)
from claimsage.services.policy_embedding_ingestion import (
    PolicyEmbeddingIngestionError,
    process_policy_document_embeddings,
)

router = APIRouter(prefix="/policies", tags=["Policy Documents"])

UPLOAD_CHUNK_SIZE = 1024 * 1024

ACCESS_MANAGEMENT_ROLES = {
    EmployeeRole.ADMIN,
    EmployeeRole.POLICY_SPECIALIST,
}


def _upload_response(
    document: PolicyDocument,
    *,
    chunk_count: int,
    clause_count: int,
    processing_error: str | None = None,
) -> PolicyDocumentUploadResponse:
    status_by_storage_value = {
        "uploaded": "pending",
        "processing": "processing",
        "processed": "ready",
        "failed": "failed",
    }
    return PolicyDocumentUploadResponse(
        document_id=document.id,
        filename=document.filename,
        status=status_by_storage_value[document.status],
        chunk_count=chunk_count,
        clause_count=clause_count,
        processing_error=processing_error,
        insurer_name=document.insurer_name,
        product_name=document.product_name,
        source_url=document.source_url,
        policy_identifier=document.policy_identifier,
        insurance_type=document.insurance_type,
        policy_version=document.policy_version,
        effective_from=document.effective_from,
        effective_to=document.effective_to,
        storage_status=document.storage_status,
    )


def require_access_management_permission(employee: Employee) -> None:
    """Allow only Admins and Policy Specialists to manage document access."""

    if employee.role not in ACCESS_MANAGEMENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to manage policy document access.",
        )


@router.post(
    "/documents",
    response_model=PolicyDocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_policy_document(
    file: UploadFile = File(...),
    supported_claim_types: list[str] | None = Form(default=None),
    policy_identifier: str | None = Form(default=None),
    insurer_name: str | None = Form(default=None),
    product_name: str | None = Form(default=None),
    insurance_type: str | None = Form(default=None),
    policy_version: str | None = Form(default=None),
    effective_from: date | None = Form(default=None),
    effective_to: date | None = Form(default=None),
    source_url: str | None = Form(default=None),
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyDocumentUploadResponse:
    """Upload a policy PDF for the authenticated employee."""

    raw_filename = (file.filename or "").replace("\\", "/")
    filename = raw_filename.rsplit("/", maxsplit=1)[-1].strip()
    filename = "".join(
        character for character in filename if character.isprintable()
    )[:255]

    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF documents are supported.",
        )

    applicability: PolicyDocumentApplicability | None = None
    has_claim_types = supported_claim_types is not None
    has_policy_identifier = policy_identifier is not None
    has_version_metadata = any(
        value is not None
        for value in (
            insurance_type,
            insurer_name,
            product_name,
            policy_version,
            effective_from,
            effective_to,
        )
    )
    if has_claim_types != has_policy_identifier:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "supported_claim_types and policy_identifier must be "
                "provided together."
            ),
        )
    if has_version_metadata and not (
        has_claim_types and has_policy_identifier
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Version metadata requires supported_claim_types and "
                "policy_identifier."
            ),
        )
    if has_claim_types:
        require_access_management_permission(employee)
        try:
            applicability = PolicyDocumentApplicability.model_validate(
                {
                    "supported_claim_types": supported_claim_types,
                    "policy_identifier": policy_identifier,
                    "insurer_name": insurer_name,
                    "product_name": product_name,
                    "insurance_type": insurance_type,
                    "policy_version": policy_version,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                }
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Policy applicability metadata is invalid.",
            ) from exc

    temporary_path: Path | None = None

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(suffix=".pdf")
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)

        total_size = 0

        with temporary_path.open("wb") as temporary_file:
            while True:
                content = file.file.read(UPLOAD_CHUNK_SIZE)

                if not content:
                    break

                total_size += len(content)

                if total_size > MAX_PDF_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="The PDF exceeds the 20 MiB size limit.",
                    )

                temporary_file.write(content)

        if total_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded PDF is empty.",
            )

        with temporary_path.open("rb") as check_file:
            header = check_file.read(5)
            if not header.startswith(b"%PDF-") and not header.startswith(b"synth"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The uploaded file is not a valid PDF document.",
                )

        storage = get_storage_service()
        uploaded_key: str | None = None

        try:
            storage.ensure_bucket_exists()
            uploaded_key = generate_secure_object_key("policies")
            with temporary_path.open("rb") as f_obj:
                stored_meta = storage.upload_document(
                    content=f_obj,
                    object_key=uploaded_key,
                    content_type="application/pdf",
                )
        except StorageUnavailableError:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document storage service is temporarily unavailable.",
            )
        except Exception as exc:
            session.rollback()
            logger.error("Evidence document storage failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Document storage failed.",
            )

        document = persist_policy_document(
            db=session,
            file_path=temporary_path,
            uploader_employee_id=employee.id,
            filename=filename,
            applicability=applicability,
            source_url=source_url,
            storage_provider="s3",
            storage_bucket=stored_meta.bucket,
            storage_key=stored_meta.object_key,
            storage_status="stored",
        )

        chunk_count = len(document.chunks)
        clause_count = len(document.clauses)
        document.status = "uploaded"

        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_uploaded",
                resource_type="policy_document",
                resource_id=str(document.id),
                details="Policy PDF and extracted text were persisted.",
            )
        )

        session.commit()

        try:
            document = process_policy_document_embeddings(
                session,
                document_id=document.id,
            )
        except PolicyEmbeddingIngestionError:
            document = session.get(PolicyDocument, document.id)
            if document is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="The policy document status could not be retrieved.",
                ) from None
            session.add(
                AuditEvent(
                    actor_employee_id=employee.id,
                    action="policy_document_embedding_failed",
                    resource_type="policy_document",
                    resource_id=str(document.id),
                    details="Policy embeddings could not be generated.",
                )
            )
            session.commit()
            return _upload_response(
                document,
                chunk_count=chunk_count,
                clause_count=clause_count,
                processing_error=(
                    "Embeddings are unavailable; this policy is not "
                    "searchable. Retry embedding when the local model is "
                    "available."
                ),
            )

        return _upload_response(
            document,
            chunk_count=chunk_count,
            clause_count=clause_count,
        )

    except DuplicatePolicyDocumentError:
        session.rollback()
        if uploaded_key:
            try:
                storage.delete_document(uploaded_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A policy document with this content already exists.",
        ) from None

    except (DocumentIngestionError, DocumentPersistenceError) as exc:
        session.rollback()
        if uploaded_key:
            try:
                storage.delete_document(uploaded_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None

    except HTTPException:
        session.rollback()
        raise

    except Exception:
        session.rollback()
        if uploaded_key:
            try:
                storage.delete_document(uploaded_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The policy document could not be processed.",
        ) from None

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

        file.file.close()


@router.post(
    "/documents/{document_id}/retry-embedding",
    response_model=PolicyDocumentUploadResponse,
)
def retry_policy_document_embedding(
    document_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyDocumentUploadResponse:
    """Retry missing embeddings without duplicating already embedded chunks."""

    require_access_management_permission(employee)
    document = session.get(PolicyDocument, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy document not found.",
        )
    if document.checksum_sha256.startswith("placeholder:"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot generate embeddings for a policy record without an attached document.",
        )
    if document.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Policy document embedding is already in progress.",
        )

    try:
        document = process_policy_document_embeddings(
            session,
            document_id=document.id,
        )
    except PolicyEmbeddingIngestionError:
        document = session.get(PolicyDocument, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The policy document status could not be retrieved.",
            ) from None
        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_embedding_failed",
                resource_type="policy_document",
                resource_id=str(document.id),
                details="Policy embeddings could not be generated.",
            )
        )
        session.commit()
        return _upload_response(
            document,
            chunk_count=len(document.chunks),
            clause_count=len(document.clauses),
            processing_error=(
                "Embeddings are unavailable; this policy is not searchable."
            ),
        )

    session.add(
        AuditEvent(
            actor_employee_id=employee.id,
            action="policy_document_embedding_ready",
            resource_type="policy_document",
            resource_id=str(document.id),
            details="Policy embeddings are ready for retrieval.",
        )
    )
    session.commit()
    return _upload_response(
        document,
        chunk_count=len(document.chunks),
        clause_count=len(document.clauses),
    )


@router.post(
    "/documents/{document_id}/access-grants",
    response_model=PolicyDocumentAccessGrantResponse,
    status_code=status.HTTP_201_CREATED,
)
def grant_policy_document_access(
    document_id: UUID,
    payload: PolicyDocumentAccessGrantRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyDocumentAccessGrantResponse:
    """Grant a policy document to a team or a specific claim."""

    require_access_management_permission(employee)

    try:
        document = session.scalar(
            select(PolicyDocument).where(
                PolicyDocument.id == document_id
            )
        )

        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Policy document not found.",
            )

        if payload.claim_id is not None:
            claim_exists = session.scalar(
                select(Claim.id).where(Claim.id == payload.claim_id)
            )

            if claim_exists is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Claim not found.",
                )

        existing_query = select(PolicyDocumentAccess).where(
            PolicyDocumentAccess.document_id == document_id
        )

        if payload.team_id is not None:
            existing_query = existing_query.where(
                PolicyDocumentAccess.team_id == payload.team_id,
                PolicyDocumentAccess.claim_id.is_(None),
            )
        else:
            existing_query = existing_query.where(
                PolicyDocumentAccess.claim_id == payload.claim_id,
                PolicyDocumentAccess.team_id.is_(None),
            )

        if session.scalar(existing_query) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This access grant already exists.",
            )

        grant = PolicyDocumentAccess(
            document_id=document_id,
            team_id=payload.team_id,
            claim_id=payload.claim_id,
            granted_by_employee_id=employee.id,
        )

        session.add(grant)
        session.flush()

        scope = (
            f"team:{payload.team_id}"
            if payload.team_id is not None
            else f"claim:{payload.claim_id}"
        )

        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_access_granted",
                resource_type="policy_document",
                resource_id=str(document_id),
                details=f"Access granted for {scope}.",
            )
        )

        session.commit()
        session.refresh(grant)

        return PolicyDocumentAccessGrantResponse.model_validate(grant)

    except HTTPException:
        session.rollback()
        raise

    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This access grant already exists or conflicts with an existing record.",
        ) from None

    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The policy document access grant could not be created.",
        ) from None


@router.patch(
    "/documents/{document_id}/clauses/{clause_id}/verification",
    response_model=PolicyClauseResponse,
)
def review_policy_clause(
    document_id: UUID,
    clause_id: UUID,
    payload: PolicyClauseVerificationRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyClauseResponse:
    """Record a policy administrator's explicit source-clause review."""

    require_access_management_permission(employee)
    clause = session.scalar(
        select(PolicyClause).where(
            PolicyClause.id == clause_id,
            PolicyClause.document_id == document_id,
        )
    )
    if clause is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy clause not found.",
        )

    clause.verification_status = payload.verification_status
    clause.verified_by_employee_id = (
        employee.id if payload.verification_status == "verified" else None
    )
    clause.verified_at = (
        datetime.now(UTC)
        if payload.verification_status == "verified"
        else None
    )
    session.add(
        AuditEvent(
            actor_employee_id=employee.id,
            action="policy_clause_reviewed",
            resource_type="policy_clause",
            resource_id=str(clause.id),
            details=(
                "A policy administrator recorded the clause review status."
            ),
        )
    )
    try:
        session.commit()
        session.refresh(clause)
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The policy clause review could not be recorded.",
        ) from None
    return PolicyClauseResponse.model_validate(clause)


@router.get(
    "/documents/{document_id}/clauses",
    response_model=list[PolicyClauseResponse],
)
def list_policy_document_clauses(
    document_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[PolicyClauseResponse]:
    """List source clauses for authorized policy administrators to review."""

    require_access_management_permission(employee)
    if session.get(PolicyDocument, document_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy document not found.",
        )
    clauses = session.scalars(
        select(PolicyClause)
        .where(PolicyClause.document_id == document_id)
        .order_by(
            PolicyClause.source_page_number,
            PolicyClause.clause_identifier,
            PolicyClause.id,
        )
    ).all()
    return [
        PolicyClauseResponse.model_validate(clause)
        for clause in clauses
    ]


@router.delete(
    "/documents/{document_id}/access-grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_policy_document_access(
    document_id: UUID,
    grant_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> None:
    """Revoke a specific team or claim access grant."""

    require_access_management_permission(employee)

    try:
        grant = session.scalar(
            select(PolicyDocumentAccess).where(
                PolicyDocumentAccess.id == grant_id,
                PolicyDocumentAccess.document_id == document_id,
            )
        )

        if grant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Policy document access grant not found.",
            )

        scope = (
            f"team:{grant.team_id}"
            if grant.team_id is not None
            else f"claim:{grant.claim_id}"
        )

        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_access_revoked",
                resource_type="policy_document",
                resource_id=str(document_id),
                details=f"Access revoked for {scope}.",
            )
        )

        session.delete(grant)
        session.commit()

    except HTTPException:
        session.rollback()
        raise

    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The policy document access grant could not be revoked.",
        ) from None


def _val(param: Any, default: Any = None) -> Any:
    """Helper to unwrap FastAPI Query default objects if called directly in tests."""
    if hasattr(param, "default"):
        return param.default
    return param if param is not None else default


@router.get("", response_model=list[PolicySummaryResponse])
def get_policies(
    query: str | None = Query(default=None),
    insurer_name: str | None = Query(default=None),
    insurance_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[PolicySummaryResponse]:
    """List and search policies matching filters with pagination."""
    clean_limit = int(_val(limit, 50))
    clean_offset = int(_val(offset, 0))
    clean_query = _val(query, None)
    clean_insurer = _val(insurer_name, None)
    clean_type = _val(insurance_type, None)
    clean_status = _val(status_filter, None)

    items, _ = list_policies(
        session,
        employee,
        query=clean_query,
        insurer_name=clean_insurer,
        insurance_type=clean_type,
        status=clean_status,
        limit=clean_limit,
        offset=clean_offset,
    )
    return items


@router.post("", response_model=PolicyDetailResponse, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: PolicyCreateRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyDetailResponse:
    """Create a structured policy record with coverages and exclusions."""
    try:
        doc = create_policy_record(session, employee, payload)
        return get_policy_detail(session, doc.id, employee)
    except PolicyAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except PolicyDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/{policy_id}", response_model=PolicyDetailResponse)
def get_policy(
    policy_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyDetailResponse:
    """Retrieve full policy details, coverages, exclusions, and applicability."""
    try:
        return get_policy_detail(session, policy_id, employee)
    except PolicyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.patch("/{policy_id}", response_model=PolicyDetailResponse)
def update_policy(
    policy_id: UUID,
    payload: PolicyUpdateRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyDetailResponse:
    """Update policy metadata, version, or effective dates."""
    try:
        update_policy_record(session, employee, policy_id, payload)
        return get_policy_detail(session, policy_id, employee)
    except PolicyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    except PolicyDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/{policy_id}/claims")
def list_policy_claims(
    policy_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[dict]:
    """Retrieve claims associated with this policy version."""
    try:
        return get_policy_claims(session, employee, policy_id)
    except PolicyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.post("/{policy_id}/coverages", response_model=PolicyCoverageResponse, status_code=status.HTTP_201_CREATED)
def add_coverage(
    policy_id: UUID,
    payload: PolicyCoverageCreateRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyCoverageResponse:
    """Add a structured coverage term to an existing policy."""
    try:
        coverage = add_policy_coverage(session, employee, policy_id, payload)
        return PolicyCoverageResponse.model_validate(coverage)
    except PolicyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.delete("/{policy_id}/coverages/{coverage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_coverage(
    policy_id: UUID,
    coverage_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> None:
    """Remove a structured coverage term from a policy."""
    try:
        remove_policy_coverage(session, employee, policy_id, coverage_id)
    except (PolicyNotFoundError, PolicyCoverageNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coverage not found.")
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.post("/{policy_id}/exclusions", response_model=PolicyExclusionResponse, status_code=status.HTTP_201_CREATED)
def add_exclusion(
    policy_id: UUID,
    payload: PolicyExclusionCreateRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyExclusionResponse:
    """Add an explicit exclusion to an existing policy."""
    try:
        exclusion = add_policy_exclusion(session, employee, policy_id, payload)
        return PolicyExclusionResponse.model_validate(exclusion)
    except PolicyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.delete("/{policy_id}/exclusions/{exclusion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exclusion(
    policy_id: UUID,
    exclusion_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> None:
    """Remove an explicit exclusion from a policy."""
    try:
        remove_policy_exclusion(session, employee, policy_id, exclusion_id)
    except (PolicyNotFoundError, PolicyExclusionNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exclusion not found.")
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.post("/{policy_id}/link-claim", response_model=PolicyClaimLinkResponse)
def link_claim(
    policy_id: UUID,
    payload: PolicyClaimLinkRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> PolicyClaimLinkResponse:
    """Validate and bind an authorized claim to a policy version."""
    try:
        return link_policy_to_claim(session, employee, policy_id, payload.claim_id)
    except PolicyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    except ClaimAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found or access denied.")
    except PolicyClaimIncompatibleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    except PolicyAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


@router.get(
    "/documents/{document_id}/download",
    response_class=Response,
)
def download_policy_document(
    document_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> Response:
    """Download original policy document PDF with RBAC authorization."""
    document = session.get(PolicyDocument, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy document not found.",
        )

    # Global roles can access all policy documents
    if employee.role not in ACCESS_MANAGEMENT_ROLES:
        # Check explicit access grant
        grant_conditions = [
            PolicyDocumentAccess.document_id == document.id,
        ]
        if employee.team_id is not None:
            grant_conditions.append(PolicyDocumentAccess.team_id == employee.team_id)
        
        has_access = session.scalar(
            select(
                select(PolicyDocumentAccess.id)
                .where(
                    PolicyDocumentAccess.document_id == document.id,
                    PolicyDocumentAccess.team_id == employee.team_id if employee.team_id else False,
                )
                .exists()
            )
        )
        if not has_access:
            session.add(
                AuditEvent(
                    actor_employee_id=employee.id,
                    action="policy_document_download_unauthorized",
                    resource_type="policy_document",
                    resource_id=str(document.id),
                    outcome="failure",
                    details=f"Unauthorized access attempt for policy document {document.id}.",
                )
            )
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to download this policy document.",
            )

    if not document.storage_key or document.storage_status != "stored":
        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_download_failed",
                resource_type="policy_document",
                resource_id=str(document.id),
                outcome="failure",
                details="Original policy PDF file is not available in object storage.",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original policy document file is unavailable.",
        )

    storage = get_storage_service()
    try:
        stored_doc = storage.retrieve_document(document.storage_key)
    except ObjectNotFoundError:
        document.storage_status = "unavailable"
        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_download_failed",
                resource_type="policy_document",
                resource_id=str(document.id),
                outcome="failure",
                details="Object not found in storage bucket.",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original policy document file is unavailable.",
        )
    except StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage service is temporarily unavailable.",
        )

    if stored_doc.checksum_sha256 != document.checksum_sha256:
        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_download_failed",
                resource_type="policy_document",
                resource_id=str(document.id),
                outcome="failure",
                details="Document integrity check failed (SHA-256 mismatch).",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document integrity verification failed.",
        )

    session.add(
        AuditEvent(
            actor_employee_id=employee.id,
            action="policy_document_retrieved",
            resource_type="policy_document",
            resource_id=str(document.id),
            outcome="success",
            details=f"Downloaded policy document '{document.filename}'.",
        )
    )
    session.commit()

    return Response(
        content=stored_doc.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{document.filename}"',
            "Content-Length": str(len(stored_doc.content)),
        },
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_policy_document(
    document_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> None:
    """Delete a policy document and its durable object storage payload."""
    require_access_management_permission(employee)

    document = session.get(PolicyDocument, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy document not found.",
        )

    if document.storage_key:
        storage = get_storage_service()
        try:
            storage.delete_document(document.storage_key)
        except Exception:
            pass

    session.add(
        AuditEvent(
            actor_employee_id=employee.id,
            action="policy_document_deleted",
            resource_type="policy_document",
            resource_id=str(document.id),
            outcome="success",
            details=f"Policy document '{document.filename}' deleted.",
        )
    )
    session.delete(document)
    session.commit()
