"""Authenticated policy document and access-management endpoints."""

import os
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import (
    AuditEvent,
    Claim,
    Employee,
    EmployeeRole,
    PolicyDocument,
    PolicyDocumentAccess,
)
from claimsage.db.session import get_db
from claimsage.rag.document_loader import (
    MAX_PDF_SIZE_BYTES,
    DocumentIngestionError,
)
from claimsage.schemas.policies import (
    PolicyDocumentAccessGrantRequest,
    PolicyDocumentAccessGrantResponse,
    PolicyDocumentUploadResponse,
)
from claimsage.services.document_persistence import (
    DocumentPersistenceError,
    DuplicatePolicyDocumentError,
    persist_policy_document,
)

router = APIRouter(prefix="/policies", tags=["Policy Documents"])

UPLOAD_CHUNK_SIZE = 1024 * 1024

ACCESS_MANAGEMENT_ROLES = {
    EmployeeRole.ADMIN,
    EmployeeRole.POLICY_SPECIALIST,
}


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

        document = persist_policy_document(
            db=session,
            file_path=temporary_path,
            uploader_employee_id=employee.id,
            filename=filename,
        )

        chunk_count = len(document.chunks)

        session.add(
            AuditEvent(
                actor_employee_id=employee.id,
                action="policy_document_uploaded",
                resource_type="policy_document",
                resource_id=str(document.id),
                details="Policy PDF uploaded and processed successfully.",
            )
        )

        session.commit()

        return PolicyDocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            chunk_count=chunk_count,
        )

    except DuplicatePolicyDocumentError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A policy document with this content already exists.",
        ) from None

    except (DocumentIngestionError, DocumentPersistenceError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None

    except HTTPException:
        session.rollback()
        raise

    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The policy document could not be processed.",
        ) from None

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

        file.file.close()


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
