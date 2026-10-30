"""Semantic retrieval for ClaimSage policy documents."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import PolicyChunk, PolicyDocument
from claimsage.rag.embedding_service import (
    EMBEDDING_DIMENSIONS,
    get_embedding_service,
)
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.services.document_access import (
    PolicyDocumentAccessDeniedError,
    build_policy_document_access_filter,
)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MIN_SIMILARITY = 0.0


class PolicyRetrievalError(RuntimeError):
    """Raised when policy semantic retrieval fails."""


@dataclass(frozen=True, slots=True)
class RetrievedPolicyChunk:
    """A policy chunk returned by semantic similarity search."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    text: str
    similarity: float
    embedding_model: str


def search_policy_chunks(
    db: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = MIN_SIMILARITY,
) -> list[RetrievedPolicyChunk]:
    """Retrieve relevant chunks only from documents the employee may access.

    Claim authorization and document authorization are enforced before
    generating embeddings or retrieving policy text.

    Similarity filtering is applied in SQL before ordering and limiting
    results, ensuring qualifying chunks are not unnecessarily excluded.
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
        or not 0.0 <= min_similarity <= 1.0
    ):
        raise ValueError("min_similarity must be between 0 and 1.")

    try:
        # Authorization must happen before embedding generation.
        document_access_filter = build_policy_document_access_filter(
            db,
            employee_id=employee_id,
            claim_id=claim_id,
        )

        embedding_service = get_embedding_service()
        query_vector = embedding_service.embed_query(query.strip())

        if len(query_vector) != EMBEDDING_DIMENSIONS:
            raise PolicyRetrievalError(
                "Query embedding has an unexpected dimension."
            )

        cosine_distance = PolicyChunk.embedding.cosine_distance(
            query_vector
        ).label("cosine_distance")

        # Cosine similarity = 1 - cosine distance.
        # Apply the minimum similarity threshold inside SQL.
        maximum_distance = 1.0 - float(min_similarity)

        statement = (
            select(
                PolicyChunk,
                PolicyDocument.filename,
                cosine_distance,
            )
            .join(
                PolicyDocument,
                PolicyDocument.id == PolicyChunk.document_id,
            )
            .where(
                PolicyDocument.status == "processed",
                PolicyChunk.embedding.is_not(None),
                PolicyChunk.embedding_model == embedding_service.model_name,
                document_access_filter,
                cosine_distance <= maximum_distance,
            )
            .order_by(
                cosine_distance.asc(),
                PolicyChunk.id.asc(),
            )
            .limit(top_k)
        )

        rows = db.execute(statement).all()

        results: list[RetrievedPolicyChunk] = []

        for chunk, filename, distance in rows:
            similarity = max(
                0.0,
                min(1.0, 1.0 - float(distance)),
            )

            results.append(
                RetrievedPolicyChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    similarity=similarity,
                    embedding_model=chunk.embedding_model,
                )
            )

        return results

    except (
        ClaimAccessDeniedError,
        PolicyDocumentAccessDeniedError,
    ):
        raise

    except PolicyRetrievalError:
        raise

    except Exception as exc:
        raise PolicyRetrievalError(
            "Policy semantic retrieval failed."
        ) from exc
