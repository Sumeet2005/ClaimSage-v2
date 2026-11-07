"""Persist policy documents and extracted chunks."""

import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from claimsage.db.models import (
    PolicyChunk,
    PolicyClause,
    PolicyDocument,
    PolicyDocumentApplicability,
)
from claimsage.rag.document_loader import chunk_pages, extract_pdf_pages
from claimsage.schemas.policies import PolicyDocumentApplicability as Applicability

_CLAUSE_CATEGORIES = {
    "coverage": "coverage",
    "coverages": "coverage",
    "exclusion": "exclusion",
    "exclusions": "exclusion",
    "condition": "condition",
    "conditions": "condition",
    "deductible": "deductible",
    "deductibles": "deductible",
    "limit": "limit",
    "limits": "limit",
    "definition": "definition",
    "definitions": "definition",
    "endorsement": "endorsement",
    "endorsements": "endorsement",
    "evidence requirement": "evidence_requirement",
    "evidence requirements": "evidence_requirement",
}


class DocumentPersistenceError(Exception):
    """Raised when a policy document cannot be persisted."""


class DuplicatePolicyDocumentError(DocumentPersistenceError):
    """Raised when the same PDF has already been registered."""


def persist_policy_document(
    db: Session,
    file_path: str | Path,
    uploader_employee_id: UUID,
    filename: str | None = None,
    applicability: Applicability | None = None,
    source_url: str | None = None,
    storage_provider: str | None = None,
    storage_bucket: str | None = None,
    storage_key: str | None = None,
    storage_status: str | None = None,
) -> PolicyDocument:
    """Extract and persist a policy PDF and its text chunks.

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

    # Extract native text first and use OCR for scanned pages.
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

    if source_url is not None:
        parsed_source_url = urlsplit(source_url)
        if (
            len(source_url) > 2048
            or source_url != source_url.strip()
            or parsed_source_url.scheme != "https"
            or not parsed_source_url.hostname
            or parsed_source_url.username is not None
            or parsed_source_url.password is not None
        ):
            raise DocumentPersistenceError(
                "The policy source URL must be a valid HTTPS URL."
            )

    document = PolicyDocument(
        filename=safe_filename,
        checksum_sha256=checksum,
        mime_type="application/pdf",
        file_size_bytes=file_size,
        source_url=source_url,
        insurer_name=(
            applicability.insurer_name if applicability is not None else None
        ),
        product_name=(
            applicability.product_name if applicability is not None else None
        ),
        uploaded_by_employee_id=uploader_employee_id,
        policy_identifier=(
            applicability.policy_identifier
            if applicability is not None
            else None
        ),
        insurance_type=(
            applicability.insurance_type
            if applicability is not None
            else None
        ),
        policy_version=(
            applicability.policy_version
            if applicability is not None
            else None
        ),
        effective_from=(
            applicability.effective_from
            if applicability is not None
            else None
        ),
        effective_to=(
            applicability.effective_to
            if applicability is not None
            else None
        ),
        storage_provider=storage_provider,
        storage_bucket=storage_bucket,
        storage_key=storage_key,
        storage_status=storage_status or ("stored" if storage_key else "unavailable"),
        status="processing",
    )

    try:
        # Savepoint: a failed chunk insert also rolls back the document.
        with db.begin_nested():
            db.add(document)
            db.flush()

            if applicability is not None:
                db.add_all(
                    PolicyDocumentApplicability(
                        document_id=document.id,
                        claim_type=claim_type,
                    )
                    for claim_type in applicability.supported_claim_types
                )

            for chunk in chunks:
                policy_chunk = PolicyChunk(
                    document_id=document.id,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    extraction_method=chunk.extraction_method,
                    ocr_confidence=chunk.ocr_confidence,
                )
                db.add(policy_chunk)
                db.flush()
                clause_category, title, clause_identifier = (
                    _extract_clause_metadata(
                        chunk.text,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                    )
                )
                db.add(
                    PolicyClause(
                        document_id=document.id,
                        source_chunk_id=policy_chunk.id,
                        clause_identifier=clause_identifier,
                        clause_category=clause_category,
                        title=title,
                        clause_text=chunk.text,
                        source_page_number=chunk.page_number,
                        verification_status="pending_review",
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


def _extract_clause_metadata(
    text: str,
    *,
    page_number: int,
    chunk_index: int,
) -> tuple[str, str | None, str]:
    """Derive source-position identifiers and explicit heading labels across chunk lines."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_line = lines[0] if lines else ""
    category_pattern = re.compile(
        r"^\s*(?:(?:section|clause|article)\s+)?"
        r"(?P<number>\d+(?:\.\d+)*(?:[A-Za-z])?)"
        r"(?:[.)\s:-]+)?"
        r"(?P<title>.*)$",
        re.IGNORECASE,
    )
    section_re_1 = re.compile(
        r"^\s*(?:(?:section|clause|article)\s+|§\s*)"
        r"(?P<identifier>[A-Za-z0-9.-]+)",
        re.IGNORECASE,
    )
    section_re_2 = re.compile(
        r"^\s*(?P<identifier>\d+(?:\.\d+)*(?:[A-Za-z])?)[.)]\s+(?P<rest>\S.*)$",
        re.IGNORECASE,
    )
    heading_prefix_re = re.compile(
        r"^(?P<label>evidence requirements?|coverage|exclusions?|"
        r"conditions?|deductibles?|limits?|definitions?|endorsements?)"
        r"\b\s*[:.-]?\s*(?P<title>.*)$",
        re.IGNORECASE,
    )
    heading_keyword_re = re.compile(
        r"\b(?P<label>evidence requirements?|coverages?|exclusions?|"
        r"conditions?|deductibles?|limits?|definitions?|endorsements?)\b",
        re.IGNORECASE,
    )

    target_line = first_line
    section_match: re.Match[str] | None = None
    for candidate_line in lines:
        m = section_re_1.match(candidate_line) or section_re_2.match(candidate_line)
        if m is not None:
            target_line = candidate_line
            section_match = m
            break
        if heading_prefix_re.match(candidate_line) is not None:
            target_line = candidate_line
            break

    clause_identifier = (
        section_match.group("identifier")
        if section_match is not None
        else f"source-page-{page_number}-chunk-{chunk_index}"
    )

    heading = target_line
    numbered_heading = category_pattern.match(target_line)
    if numbered_heading is not None and numbered_heading.group("title"):
        heading = numbered_heading.group("title").strip()

    heading_prefix = heading_prefix_re.match(heading)
    if heading_prefix is not None:
        label = heading_prefix.group("label").casefold()
        category = _CLAUSE_CATEGORIES[label]
        title = heading_prefix.group("title").strip() or label.title()
        return category, title[:255], clause_identifier

    if section_match is not None and heading and len(heading) <= 120:
        keyword_match = heading_keyword_re.search(heading)
        if keyword_match is not None:
            label = keyword_match.group("label").casefold()
            category = _CLAUSE_CATEGORIES[label]
            return category, heading[:255], clause_identifier
        return "other", heading[:255], clause_identifier

    return "other", None, clause_identifier
