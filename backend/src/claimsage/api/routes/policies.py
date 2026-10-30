
"""Authenticated policy document upload endpoint."""

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import AuditEvent, Employee
from claimsage.db.session import get_db
from claimsage.rag.document_loader import (
    MAX_PDF_SIZE_BYTES,
    DocumentIngestionError,
)
from claimsage.schemas.policies import PolicyDocumentUploadResponse
from claimsage.services.document_persistence import (
    DocumentPersistenceError,
    DuplicatePolicyDocumentError,
    persist_policy_document,
)

router = APIRouter(prefix="/policies", tags=["Policy Documents"])

UPLOAD_CHUNK_SIZE = 1024 * 1024


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
