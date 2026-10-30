"""Persist claim evidence documents, extracted chunks, and embeddings."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from claimsage.db.models import ClaimEvidenceChunk, ClaimEvidenceDocument
from claimsage.rag.document_loader import chunk_pages, extract_pdf_pages
from claimsage.rag.embedding_service import (
    EMBEDDING_DIMENSIONS,
    MAX_BATCH_SIZE,
    EmbeddingServiceError,
    LocalEmbeddingService,
    get_embedding_service,
)


class EvidencePersistenceError(RuntimeError):
    """Raised when claim evidence cannot be persisted."""


class DuplicateClaimEvidenceError(EvidencePersistenceError):
    """Raised when identical evidence already exists for the claim."""


def persist_claim_evidence(
    db: Session,
    file_path: str | Path,
    claim_id: UUID,
    uploader_employee_id: UUID,
    filename: str | None = None,
    embedding_service: LocalEmbeddingService | None = None,
) -> ClaimEvidenceDocument:
    """Extract, embed, and persist evidence for one insurance claim.

    The caller must authorize access to the claim before calling this
    service. The caller owns the outer transaction and must commit or
    roll it back.

    A nested transaction protects document metadata and chunks from
    partial persistence.
    """

    path = Path(file_path)

    if not path.is_file():
        raise EvidencePersistenceError("The PDF file does not exist.")

    file_size = path.stat().st_size

    if file_size <= 0:
        raise EvidencePersistenceError("The PDF file is empty.")

    safe_filename = Path(filename or path.name).name.strip()

    if not safe_filename:
        raise EvidencePersistenceError("A valid filename is required.")

    if len(safe_filename) > 255:
        raise EvidencePersistenceError(
            "The filename exceeds the 255-character limit."
        )

    # Reuse the existing native extraction and OCR pipeline.
    try:
        pages = extract_pdf_pages(path)
    except Exception as exc:
        raise EvidencePersistenceError(
            "The evidence PDF could not be extracted."
        ) from exc

    if not pages:
        raise EvidencePersistenceError(
            "The evidence PDF contains no extractable pages."
        )

    chunks = chunk_pages(pages)

    if not chunks:
        raise EvidencePersistenceError(
            "No text chunks could be generated from the evidence PDF."
        )

    checksum = pages[0].document_sha256

    if any(page.document_sha256 != checksum for page in pages):
        raise EvidencePersistenceError(
            "The extracted pages contain inconsistent document checksums."
        )

    # Duplicate detection is scoped to the claim.
    existing = db.scalar(
        select(ClaimEvidenceDocument).where(
            ClaimEvidenceDocument.claim_id == claim_id,
            ClaimEvidenceDocument.checksum_sha256 == checksum,
        )
    )

    if existing is not None:
        raise DuplicateClaimEvidenceError(
            "This evidence document already exists for the claim."
        )

    service = embedding_service or get_embedding_service()

    # Generate embeddings before inserting document metadata.
    # Batching respects the embedding service's maximum batch size.
    vectors: list[list[float]] = []

    try:
        for start in range(0, len(chunks), MAX_BATCH_SIZE):
            batch = chunks[start : start + MAX_BATCH_SIZE]
            batch_vectors = service.embed_texts(
                [chunk.text for chunk in batch]
            )

            if len(batch_vectors) != len(batch):
                raise EvidencePersistenceError(
                    "The embedding service returned an unexpected "
                    "number of vectors."
                )

            for vector in batch_vectors:
                if (
                    len(vector) != EMBEDDING_DIMENSIONS
                    or any(
                        not isinstance(value, (int, float))
                        or not float("-inf") < float(value) < float("inf")
                        for value in vector
                    )
                ):
                    raise EvidencePersistenceError(
                        "The embedding service returned an invalid vector."
                    )

            vectors.extend(batch_vectors)

    except EmbeddingServiceError:
        raise
    except EvidencePersistenceError:
        raise
    except Exception as exc:
        raise EvidencePersistenceError(
            "Could not generate evidence embeddings."
        ) from exc

    if len(vectors) != len(chunks):
        raise EvidencePersistenceError(
            "The number of generated embeddings does not match "
            "the number of evidence chunks."
        )

    document = ClaimEvidenceDocument(
        claim_id=claim_id,
        filename=safe_filename,
        checksum_sha256=checksum,
        mime_type="application/pdf",
        file_size_bytes=file_size,
        uploaded_by_employee_id=uploader_employee_id,
        status="processing",
    )

    embedded_at = datetime.now(UTC)

    try:
        # Savepoint prevents partial document and chunk persistence.
        with db.begin_nested():
            db.add(document)
            db.flush()

            for chunk, vector in zip(chunks, vectors, strict=True):
                db.add(
                    ClaimEvidenceChunk(
                        document_id=document.id,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        chunk_id=chunk.chunk_id,
                        text=chunk.text,
                        extraction_method=chunk.extraction_method,
                        ocr_confidence=chunk.ocr_confidence,
                        embedding=vector,
                        embedding_model=service.model_name,
                        embedded_at=embedded_at,
                    )
                )

            db.flush()

            document.status = "processed"
            db.flush()

    except IntegrityError:
        # Protect against concurrent duplicate uploads.
        existing = db.scalar(
            select(ClaimEvidenceDocument).where(
                ClaimEvidenceDocument.claim_id == claim_id,
                ClaimEvidenceDocument.checksum_sha256 == checksum,
            )
        )

        if existing is not None:
            raise DuplicateClaimEvidenceError(
                "This evidence document already exists for the claim."
            ) from None

        raise

    return document
