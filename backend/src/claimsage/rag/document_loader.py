"""Secure PDF text extraction, OCR fallback, and page-aware chunking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from claimsage.core.config import get_settings
from claimsage.rag.ocr_service import OCRProcessingError, OCRService

MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024
PDF_HEADER_SEARCH_BYTES = 1024


class DocumentIngestionError(ValueError):
    """Raised when a document cannot be safely ingested."""


@dataclass(frozen=True, slots=True)
class PageText:
    """Extracted text and provenance for one PDF page."""

    source_name: str
    document_sha256: str
    page_number: int
    text: str
    extraction_method: str = "native"
    ocr_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A deterministic text chunk with its source-page provenance."""

    chunk_id: str
    source_name: str
    document_sha256: str
    page_number: int
    chunk_index: int
    text: str
    extraction_method: str = "native"
    ocr_confidence: float | None = None


def _normalize_text(text: str) -> str:
    """Normalize extracted whitespace without changing word order."""
    return re.sub(r"\s+", " ", text).strip()


def extract_pdf_pages(file_path: str | Path) -> list[PageText]:
    """Extract native PDF text first and use OCR for image-only pages."""

    path = Path(file_path)

    if path.suffix.lower() != ".pdf":
        raise DocumentIngestionError("Only PDF documents are supported.")

    if not path.is_file():
        raise DocumentIngestionError("The PDF file does not exist.")

    try:
        # Read at most the configured limit plus one byte.
        with path.open("rb") as pdf_file:
            file_bytes = pdf_file.read(MAX_PDF_SIZE_BYTES + 1)

        if not file_bytes:
            raise DocumentIngestionError("The PDF file is empty.")

        if len(file_bytes) > MAX_PDF_SIZE_BYTES:
            raise DocumentIngestionError(
                "The PDF exceeds the 20 MiB size limit."
            )

        header_region = file_bytes[:PDF_HEADER_SEARCH_BYTES]

        if b"%PDF-" not in header_region:
            raise DocumentIngestionError(
                "The uploaded file does not contain a valid PDF signature."
            )

        document_sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Parse the exact bytes used to calculate the checksum.
        reader = PdfReader(BytesIO(file_bytes), strict=True)

        if reader.is_encrypted:
            raise DocumentIngestionError(
                "Encrypted PDF documents are not supported."
            )

        settings = get_settings()

        if len(reader.pages) > settings.pdf_max_pages:
            raise DocumentIngestionError(
                "The PDF exceeds the configured page limit."
            )

        pages: list[PageText] = []
        ocr_service = OCRService()

        for page_number, page in enumerate(reader.pages, start=1):
            extracted_text = page.extract_text() or ""
            normalized_text = _normalize_text(extracted_text)

            extraction_method = "native"
            ocr_confidence: float | None = None

            if not normalized_text:
                try:
                    ocr_result = ocr_service.extract_page(
                        pdf_bytes=file_bytes,
                        page_number=page_number,
                    )
                except OCRProcessingError as exc:
                    raise DocumentIngestionError(
                        "OCR could not process a PDF page safely."
                    ) from exc

                normalized_text = _normalize_text(ocr_result.text)
                extraction_method = "ocr"
                ocr_confidence = ocr_result.confidence

            if normalized_text:
                pages.append(
                    PageText(
                        source_name=path.name,
                        document_sha256=document_sha256,
                        page_number=page_number,
                        text=normalized_text,
                        extraction_method=extraction_method,
                        ocr_confidence=ocr_confidence,
                    )
                )

    except DocumentIngestionError:
        raise
    except Exception as exc:
        # Keep parser and extraction implementation details private.
        raise DocumentIngestionError(
            "The PDF could not be read safely."
        ) from exc

    if not pages:
        raise DocumentIngestionError(
            "The PDF contains no extractable text, including through OCR."
        )

    return pages


def chunk_pages(
    pages: list[PageText],
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[DocumentChunk]:
    """Split page text into deterministic chunks without crossing pages.

    Chunk size and overlap are measured in characters. Overlap is retained
    between consecutive chunks from the same page only.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")

    if overlap < 0:
        raise ValueError("overlap cannot be negative.")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")

    chunks: list[DocumentChunk] = []

    for page in pages:
        text = _normalize_text(page.text)

        if not text:
            continue

        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))

            if end < len(text):
                boundary = text.rfind(" ", start, end)

                if boundary > start:
                    end = boundary

            chunk_text = text[start:end].strip()

            if chunk_text:
                # Preserve the original deterministic identity formula.
                identity = (
                    f"{page.document_sha256}:"
                    f"{page.page_number}:"
                    f"{chunk_index}:"
                    f"{chunk_text}"
                )

                chunk_id = hashlib.sha256(
                    identity.encode("utf-8")
                ).hexdigest()

                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        source_name=page.source_name,
                        document_sha256=page.document_sha256,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        extraction_method=page.extraction_method,
                        ocr_confidence=page.ocr_confidence,
                    )
                )

                chunk_index += 1

            if end >= len(text):
                break

            next_start = max(start + 1, end - overlap)
            start = next_start

    return chunks
