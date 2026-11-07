"""Claim-authorized semantic retrieval for insurance evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import ClaimEvidenceChunk, ClaimEvidenceDocument
from claimsage.rag.embedding_service import (
    EMBEDDING_DIMENSIONS,
    get_embedding_service,
)
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MIN_SIMILARITY = 0.0

_REPAIR_ESTIMATE_FILENAME_KEYWORDS = (
    "repair_estimate",
    "repair-estimate",
    "repair estimate",
    "body_shop",
    "body-shop",
    "bodyshop",
    "estimate",
)
_REPAIR_ESTIMATE_TEXT_KEYWORDS = (
    "repair estimate",
    "parts schedule",
    "body shop",
    "estimate number",
    "gross repair estimate",
)


class EvidenceRetrievalError(RuntimeError):
    """Raised when claim evidence semantic retrieval fails."""


def resolve_repair_estimate_document_id(
    db: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
) -> UUID | None:
    """Auto-resolve an uploaded, processed repair estimate document for an authorized motor claim."""

    if not isinstance(employee_id, UUID) or not isinstance(claim_id, UUID):
        return None

    try:
        claim = get_authorized_claim(
            db,
            employee_id=employee_id,
            claim_id=claim_id,
        )
        claim_type = getattr(claim, "claim_type", None)
        if (
            not isinstance(claim_type, str)
            or claim_type.strip().lower() not in {"auto", "motor"}
        ):
            return None

        stmt = (
            select(ClaimEvidenceDocument)
            .where(
                ClaimEvidenceDocument.claim_id == claim_id,
                ClaimEvidenceDocument.status == "processed",
            )
            .order_by(
                ClaimEvidenceDocument.created_at.desc(),
                ClaimEvidenceDocument.id.desc(),
            )
        )
        docs = list(db.scalars(stmt).all())
        valid_docs = [
            doc
            for doc in docs
            if isinstance(getattr(doc, "id", None), UUID)
            and isinstance(getattr(doc, "filename", None), str)
        ]
        if not valid_docs:
            return None

        for keyword in _REPAIR_ESTIMATE_FILENAME_KEYWORDS:
            for doc in valid_docs:
                if keyword in doc.filename.casefold():
                    return doc.id

        chunk_stmt = (
            select(ClaimEvidenceChunk.document_id, ClaimEvidenceChunk.text)
            .join(
                ClaimEvidenceDocument,
                ClaimEvidenceDocument.id == ClaimEvidenceChunk.document_id,
            )
            .where(
                ClaimEvidenceDocument.claim_id == claim_id,
                ClaimEvidenceDocument.status == "processed",
            )
            .order_by(
                ClaimEvidenceDocument.created_at.desc(),
                ClaimEvidenceChunk.page_number.asc(),
                ClaimEvidenceChunk.chunk_index.asc(),
            )
        )
        for row in db.execute(chunk_stmt).all():
            if not isinstance(row, tuple) or len(row) != 2:
                continue
            doc_id, text = row
            if isinstance(doc_id, UUID) and isinstance(text, str):
                lower_text = text.casefold()
                if any(kw in lower_text for kw in _REPAIR_ESTIMATE_TEXT_KEYWORDS):
                    return doc_id
    except Exception:
        return None

    return None


@dataclass(frozen=True, slots=True)
class RetrievedEvidenceChunk:
    """A retrieved claim evidence chunk with source provenance."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    text: str
    similarity: float | None
    embedding_model: str | None
    extraction_method: str
    ocr_confidence: float | None


def get_document_evidence_chunks(
    db: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> list[RetrievedEvidenceChunk]:
    """Retrieve every ordered chunk from one processed, authorized document."""

    if not isinstance(employee_id, UUID):
        raise ValueError("employee_id must be a UUID.")

    if not isinstance(claim_id, UUID):
        raise ValueError("claim_id must be a UUID.")

    if not isinstance(document_id, UUID):
        raise ValueError("document_id must be a UUID.")

    try:
        get_authorized_claim(
            db,
            employee_id=employee_id,
            claim_id=claim_id,
        )

        statement = (
            select(ClaimEvidenceChunk, ClaimEvidenceDocument.filename)
            .join(
                ClaimEvidenceDocument,
                ClaimEvidenceDocument.id == ClaimEvidenceChunk.document_id,
            )
            .where(
                ClaimEvidenceDocument.id == document_id,
                ClaimEvidenceDocument.claim_id == claim_id,
                ClaimEvidenceDocument.status == "processed",
            )
            .order_by(
                ClaimEvidenceChunk.page_number.asc(),
                ClaimEvidenceChunk.chunk_index.asc(),
                ClaimEvidenceChunk.id.asc(),
            )
        )

        rows = db.execute(statement).all()

        return [
            RetrievedEvidenceChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=filename,
                page_number=chunk.page_number,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                similarity=None,
                embedding_model=chunk.embedding_model,
                extraction_method=chunk.extraction_method,
                ocr_confidence=chunk.ocr_confidence,
            )
            for chunk, filename in rows
        ]

    except ClaimAccessDeniedError:
        raise

    except Exception as exc:
        raise EvidenceRetrievalError(
            "Claim evidence document retrieval failed."
        ) from exc


def search_claim_evidence(
    db: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = MIN_SIMILARITY,
) -> list[RetrievedEvidenceChunk]:
    """Retrieve semantically relevant evidence from one authorized claim.

    Authorization is checked before embedding generation. The SQL query
    independently scopes every result to the exact claim ID, preventing
    evidence from other claims from entering the result set.
    """

    if not isinstance(employee_id, UUID):
        raise ValueError("employee_id must be a UUID.")

    if not isinstance(claim_id, UUID):
        raise ValueError("claim_id must be a UUID.")

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must not be empty.")

    if (
        not isinstance(top_k, int)
        or isinstance(top_k, bool)
        or not 1 <= top_k <= MAX_TOP_K
    ):
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}.")

    if (
        not isinstance(min_similarity, (int, float))
        or isinstance(min_similarity, bool)
        or not math.isfinite(float(min_similarity))
        or not 0.0 <= min_similarity <= 1.0
    ):
        raise ValueError("min_similarity must be between 0 and 1.")

    try:
        # Enforce employee-to-claim authorization before embedding.
        get_authorized_claim(
            db,
            employee_id=employee_id,
            claim_id=claim_id,
        )

        embedding_service = get_embedding_service()
        query_vector = embedding_service.embed_query(query.strip())

        if (
            len(query_vector) != EMBEDDING_DIMENSIONS
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in query_vector
            )
        ):
            raise EvidenceRetrievalError(
                "Query embedding has an invalid vector shape or value."
            )

        cosine_distance = ClaimEvidenceChunk.embedding.cosine_distance(
            query_vector
        ).label("cosine_distance")

        # Cosine similarity = 1 - cosine distance.
        maximum_distance = 1.0 - float(min_similarity)

        statement = (
            select(
                ClaimEvidenceChunk,
                ClaimEvidenceDocument.filename,
                cosine_distance,
            )
            .join(
                ClaimEvidenceDocument,
                ClaimEvidenceDocument.id
                == ClaimEvidenceChunk.document_id,
            )
            .where(
                # Critical tenant/data-isolation boundary.
                ClaimEvidenceDocument.claim_id == claim_id,
                ClaimEvidenceDocument.status == "processed",
                ClaimEvidenceChunk.embedding.is_not(None),
                ClaimEvidenceChunk.embedding_model
                == embedding_service.model_name,
                cosine_distance <= maximum_distance,
            )
            .order_by(
                cosine_distance.asc(),
                ClaimEvidenceChunk.id.asc(),
            )
            .limit(max(top_k * 3, 15))
        )

        rows = db.execute(statement).all()

        candidates: list[RetrievedEvidenceChunk] = []
        seen_chunk_ids: set[UUID] = set()

        for chunk, filename, distance in rows:
            if chunk.id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.id)
            similarity = max(
                0.0,
                min(1.0, 1.0 - float(distance)),
            )

            candidates.append(
                RetrievedEvidenceChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    similarity=similarity,
                    embedding_model=chunk.embedding_model,
                    extraction_method=chunk.extraction_method,
                    ocr_confidence=chunk.ocr_confidence,
                )
            )

        unique_docs = {c.document_id for c in candidates}
        if len(unique_docs) > 1 and top_k > 1:
            max_per_doc = max(1, top_k // 2)
            results: list[RetrievedEvidenceChunk] = []
            doc_counts: dict[UUID, int] = {}
            deferred: list[RetrievedEvidenceChunk] = []

            for cand in candidates:
                count = doc_counts.get(cand.document_id, 0)
                if count < max_per_doc and len(results) < top_k:
                    results.append(cand)
                    doc_counts[cand.document_id] = count + 1
                else:
                    deferred.append(cand)

            for cand in deferred:
                if len(results) >= top_k:
                    break
                results.append(cand)
            return results

        return candidates[:top_k]

    except ClaimAccessDeniedError:
        raise

    except EvidenceRetrievalError:
        raise

    except Exception as exc:
        raise EvidenceRetrievalError(
            "Claim evidence semantic retrieval failed."
        ) from exc
