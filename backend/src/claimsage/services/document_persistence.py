
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from claimsage.db.models import PolicyChunk, PolicyDocument
from claimsage.rag.document_loader import chunk_pages, extract_pdf_pages


class DocumentPersistenceError(Exception):
    """Raised when a policy document cannot be persisted."""


class DuplicatePolicyDocumentError(DocumentPersistenceError):
    """Raised when the same PDF has already been registered."""


def persist_policy_document(
    db: Session,
    file_path: str | Path,
    uploader_employee_id: UUID,
    filename: str | None = None,
) -> PolicyDocument:
    """
    Extract and persist a policy PDF and its text chunks.

    The caller owns the outer database transaction and is responsible
    for committing or rolling it back.

    A nested transaction protects document metadata and chunks from
    partial persistence if an insert fails.
    """
    path = Path(file_path)

    if not path.is_file():
        raise DocumentPersistenceError("The PDF file does not exist.")

    file_size = path.stat().st_size

    if file_size <= 0:
        raise DocumentPersistenceError("The PDF file is empty.")

    # Reuse the existing secure PDF extraction and chunking pipeline.
    pages = extract_pdf_pages(path)

    if not pages:
        raise DocumentPersistenceError(
            "The PDF does not contain extractable pages."
        )

    chunks = chunk_pages(pages)

    if not chunks:
        raise DocumentPersistenceError(
            "No text chunks could be generated from the PDF."
        )

    checksum = pages[0].document_sha256

    # All pages must belong to the same source document.
    if any(page.document_sha256 != checksum for page in pages):
        raise DocumentPersistenceError(
            "The extracted pages contain inconsistent document checksums."
        )

    # Check for an existing document before attempting insertion.
    existing = db.scalar(
        select(PolicyDocument).where(
            PolicyDocument.checksum_sha256 == checksum
        )
    )

    if existing is not None:
        raise DuplicatePolicyDocumentError(
            "A policy document with this content already exists."
        )

    safe_filename = Path(filename or path.name).name.strip()

    if not safe_filename:
        raise DocumentPersistenceError("A valid filename is required.")

    document = PolicyDocument(
        filename=safe_filename,
        checksum_sha256=checksum,
        mime_type="application/pdf",
        file_size_bytes=file_size,
        uploaded_by_employee_id=uploader_employee_id,
        status="processing",
    )

    try:
        # Savepoint: a failed chunk insert also rolls back the document.
        with db.begin_nested():
            db.add(document)
            db.flush()

            for chunk in chunks:
                db.add(
                    PolicyChunk(
                        document_id=document.id,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        chunk_id=chunk.chunk_id,
                        text=chunk.text,
                    )
                )

            db.flush()

            document.status = "processed"
            db.flush()

    except IntegrityError:
        # The unique checksum constraint also protects against concurrent
        # uploads of identical documents.
        existing = db.scalar(
            select(PolicyDocument).where(
                PolicyDocument.checksum_sha256 == checksum
            )
        )

        if existing is not None:
            raise DuplicatePolicyDocumentError(
                "A policy document with this content already exists."
            ) from None

        # Do not misclassify unrelated database integrity failures.
        raise

    return document
