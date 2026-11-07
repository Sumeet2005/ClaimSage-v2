"""Authenticated claim evidence upload endpoint."""

import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

logger = logging.getLogger(__name__)

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import AuditEvent, Claim, Employee, EmployeeRole, ClaimEvidenceDocument
from claimsage.services.storage import (
    ObjectNotFoundError,
    StorageError,
    StorageUnavailableError,
    generate_secure_object_key,
    get_storage_service,
)
from claimsage.db.session import get_db
from claimsage.rag.document_loader import MAX_PDF_SIZE_BYTES
from claimsage.rag.embedding_service import EmbeddingServiceError
from claimsage.schemas.evidence import ClaimEvidenceItemResponse, ClaimEvidenceUploadResponse
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)
from claimsage.services.customer_emails import handle_document_received
from claimsage.services.evidence_persistence import (
    DuplicateClaimEvidenceError,
    EvidencePersistenceError,
    persist_claim_evidence,
)

router = APIRouter(prefix="/claims", tags=["Claim Evidence"])

UPLOAD_CHUNK_SIZE = 1024 * 1024


@router.get(
    "/evidence",
    response_model=list[ClaimEvidenceItemResponse],
)
def list_claim_evidence_documents(
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[ClaimEvidenceItemResponse]:
    """List evidence documents across authorized claims."""
    stmt = (
        select(ClaimEvidenceDocument)
        .join(Claim, ClaimEvidenceDocument.claim_id == Claim.id)
        .options(
            selectinload(ClaimEvidenceDocument.claim),
            selectinload(ClaimEvidenceDocument.uploaded_by),
            selectinload(ClaimEvidenceDocument.chunks),
        )
    )

    if employee.role == EmployeeRole.ADMIN:
        pass
    elif employee.role == EmployeeRole.CLAIMS_ADJUSTER:
        stmt = stmt.where(Claim.assigned_employee_id == employee.id)
    elif employee.role in {EmployeeRole.TEAM_LEAD, EmployeeRole.POLICY_SPECIALIST}:
        if employee.team_id:
            stmt = stmt.where(Claim.team_id == employee.team_id)
        else:
            return []
    else:
        return []

    stmt = stmt.order_by(ClaimEvidenceDocument.created_at.desc())
    docs = session.scalars(stmt).all()

    return [
        ClaimEvidenceItemResponse(
            id=doc.id,
            claim_id=doc.claim_id,
            claim_number=doc.claim.claim_number if doc.claim else "Unknown",
            claimant_name=doc.claim.claimant_name if doc.claim else "Unknown",
            filename=doc.filename,
            file_size_bytes=doc.file_size_bytes,
            mime_type=doc.mime_type,
            storage_status=doc.storage_status or "unavailable",
            status=doc.status,
            chunk_count=len(doc.chunks),
            uploaded_at=doc.created_at,
            uploaded_by_name=doc.uploaded_by.display_name if doc.uploaded_by else None,
        )
        for doc in docs
    ]


@router.post(
    "/{claim_id}/evidence",
    response_model=ClaimEvidenceUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_claim_evidence(
    claim_id: UUID,
    file: UploadFile = File(...),
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> ClaimEvidenceUploadResponse:
    """Upload and process a PDF as evidence for an authorized claim."""

    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        ) from None

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
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
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
            uploaded_key = generate_secure_object_key("evidence", scope_id=claim.id)
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

        document = persist_claim_evidence(
            db=session,
            file_path=temporary_path,
            claim_id=claim.id,
            uploader_employee_id=employee.id,
            filename=filename,
            storage_provider="s3",
            storage_bucket=stored_meta.bucket,
            storage_key=stored_meta.object_key,
            storage_status="stored",
        )

        chunk_count = len(document.chunks)

        session.add(
            AuditEvent(
                actor_type="employee",
                actor_id=employee.display_name,
                actor_employee_id=employee.id,
                claim_id=claim.id,
                event_category="evidence",
                action="claim_evidence_uploaded",
                outcome="success",
                resource_type="claim_evidence_document",
                resource_id=str(document.id),
                details=(
                    f"Evidence PDF uploaded and processed for claim "
                    f"{claim.id}."
                ),
                event_metadata={
                    "filename": document.filename,
                    "chunk_count": chunk_count,
                },
            )
        )

        handle_document_received(session, claim_id=claim.id)

        session.commit()

        return ClaimEvidenceUploadResponse(
            document_id=document.id,
            claim_id=claim.id,
            filename=document.filename,
            status=document.status,
            chunk_count=chunk_count,
            storage_status=document.storage_status,
        )

    except DuplicateClaimEvidenceError:
        session.rollback()
        if uploaded_key:
            try:
                storage.delete_document(uploaded_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This evidence document already exists for the claim.",
        ) from None

    except EmbeddingServiceError:
        session.rollback()
        if uploaded_key:
            try:
                storage.delete_document(uploaded_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The evidence embedding service is temporarily unavailable.",
        ) from None

    except EvidencePersistenceError as exc:
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
            detail="The claim evidence document could not be processed.",
        ) from None

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

        file.file.close()



@router.get(
    "/{claim_id}/evidence/{document_id}/download",
    response_class=Response,
)
def download_claim_evidence(
    claim_id: UUID,
    document_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> Response:
    """Download original claim evidence PDF with claim authorization."""
    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        ) from None

    evidence = session.get(ClaimEvidenceDocument, document_id)
    if evidence is None or evidence.claim_id != claim.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence document not found for this claim.",
        )

    if not evidence.storage_key or evidence.storage_status != "stored":
        session.add(
            AuditEvent(
                actor_type="employee",
                actor_id=employee.display_name,
                actor_employee_id=employee.id,
                claim_id=claim.id,
                event_category="evidence",
                action="claim_evidence_download_failed",
                outcome="failure",
                resource_type="claim_evidence_document",
                resource_id=str(evidence.id),
                details="Original evidence PDF file is unavailable in object storage.",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original evidence document file is unavailable.",
        )

    storage = get_storage_service()
    try:
        stored_doc = storage.retrieve_document(evidence.storage_key)
    except ObjectNotFoundError:
        evidence.storage_status = "unavailable"
        session.add(
            AuditEvent(
                actor_type="employee",
                actor_id=employee.display_name,
                actor_employee_id=employee.id,
                claim_id=claim.id,
                event_category="evidence",
                action="claim_evidence_download_failed",
                outcome="failure",
                resource_type="claim_evidence_document",
                resource_id=str(evidence.id),
                details="Object not found in storage bucket.",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original evidence document file is unavailable.",
        )
    except StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage service is temporarily unavailable.",
        )

    if stored_doc.checksum_sha256 != evidence.checksum_sha256:
        session.add(
            AuditEvent(
                actor_type="employee",
                actor_id=employee.display_name,
                actor_employee_id=employee.id,
                claim_id=claim.id,
                event_category="evidence",
                action="claim_evidence_download_failed",
                outcome="failure",
                resource_type="claim_evidence_document",
                resource_id=str(evidence.id),
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
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=claim.id,
            event_category="evidence",
            action="claim_evidence_retrieved",
            outcome="success",
            resource_type="claim_evidence_document",
            resource_id=str(evidence.id),
            details=f"Downloaded evidence document '{evidence.filename}'.",
        )
    )
    session.commit()

    return Response(
        content=stored_doc.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{evidence.filename}"',
            "Content-Length": str(len(stored_doc.content)),
        },
    )


@router.delete(
    "/{claim_id}/evidence/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_claim_evidence(
    claim_id: UUID,
    document_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> None:
    """Delete a claim evidence document and its storage payload."""
    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        ) from None

    evidence = session.get(ClaimEvidenceDocument, document_id)
    if evidence is None or evidence.claim_id != claim.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence document not found for this claim.",
        )

    if (
        employee.role not in {EmployeeRole.ADMIN, EmployeeRole.TEAM_LEAD}
        and claim.assigned_employee_id != employee.id
    ):
        session.add(
            AuditEvent(
                actor_type="employee",
                actor_id=employee.display_name,
                actor_employee_id=employee.id,
                claim_id=claim.id,
                event_category="evidence",
                action="claim_evidence_delete_unauthorized",
                outcome="failure",
                resource_type="claim_evidence_document",
                resource_id=str(evidence.id),
                details=f"Unauthorized deletion attempt by {employee.display_name}.",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete evidence for this claim.",
        )

    if evidence.storage_key:
        storage = get_storage_service()
        try:
            storage.delete_document(evidence.storage_key)
        except Exception:
            pass

    session.add(
        AuditEvent(
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=claim.id,
            event_category="evidence",
            action="claim_evidence_deleted",
            outcome="success",
            resource_type="claim_evidence_document",
            resource_id=str(evidence.id),
            details=f"Evidence document '{evidence.filename}' deleted.",
        )
    )
    session.delete(evidence)
    session.commit()
