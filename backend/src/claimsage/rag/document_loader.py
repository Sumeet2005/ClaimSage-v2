"""Secure PDF text extraction and page-aware chunking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024


class DocumentIngestionError(ValueError):
    """Raised when a document cannot be safely ingested."""


@dataclass(frozen=True, slots=True)
class PageText:
    """Extracted text and provenance for one PDF page."""

    source_name: str
    document_sha256: str
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A deterministic text chunk with its source-page provenance."""

    chunk_id: str
    source_name: str
    document_sha256: str
    page_number: int
    chunk_index: int
    text: str


def _normalize_text(text: str) -> str:
    """Normalize extracted whitespace without changing word order."""
    return re.sub(r"\s+", " ", text).strip()


def extract_pdf_pages(file_path: str | Path) -> list[PageText]:
    """Extract text from a PDF while retaining page-level provenance.

    OCR is intentionally not performed. PDFs containing only scanned images
    will be rejected when no extractable text is found.
    """
    path = Path(file_path)

    if path.suffix.lower() != ".pdf":
        raise DocumentIngestionError("Only PDF documents are supported.")

    if not path.is_file():
        raise DocumentIngestionError("The PDF file does not exist.")

    file_size = path.stat().st_size
    if file_size == 0:
        raise DocumentIngestionError("The PDF file is empty.")

    if file_size > MAX_PDF_SIZE_BYTES:
        raise DocumentIngestionError("The PDF exceeds the 20 MiB size limit.")

    try:
        file_bytes = path.read_bytes()
        document_sha256 = hashlib.sha256(file_bytes).hexdigest()
        reader = PdfReader(path, strict=True)

        if reader.is_encrypted:
            raise DocumentIngestionError("Encrypted PDF documents are not supported.")

        pages: list[PageText] = []

        for page_number, page in enumerate(reader.pages, start=1):
            extracted_text = page.extract_text() or ""
            normalized_text = _normalize_text(extracted_text)

            if normalized_text:
                pages.append(
                    PageText(
                        source_name=path.name,
                        document_sha256=document_sha256,
                        page_number=page_number,
                        text=normalized_text,
                    )
                )

    except DocumentIngestionError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise DocumentIngestionError("The PDF could not be read safely.") from exc

    if not pages:
        raise DocumentIngestionError(
            "The PDF contains no extractable text. Scanned PDFs require OCR."
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
                identity = (
                    f"{page.document_sha256}:"
                    f"{page.page_number}:"
                    f"{chunk_index}:"
                    f"{chunk_text}"
                )
                chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()

                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        source_name=page.source_name,
                        document_sha256=page.document_sha256,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        text=chunk_text,
                    )
                )
                chunk_index += 1

            if end >= len(text):
                break

            next_start = max(start + 1, end - overlap)
            start = next_start

    return chunks
