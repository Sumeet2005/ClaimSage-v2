
"""Persist local embeddings for policy chunks."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import PolicyChunk
from claimsage.rag.embedding_service import (
    EMBEDDING_DIMENSIONS,
    MAX_BATCH_SIZE,
    EmbeddingServiceError,
    LocalEmbeddingService,
    get_embedding_service,
)


class EmbeddingPersistenceError(RuntimeError):
    """Raised when policy chunk embeddings cannot be persisted."""


def embed_pending_policy_chunks(
    db: Session,
    batch_size: int = MAX_BATCH_SIZE,
    embedding_service: LocalEmbeddingService | None = None,
) -> int:
    """
    Generate and persist one bounded batch of missing policy embeddings.

    PostgreSQL row locks prevent concurrent workers from processing
    the same chunks when they use separate transactions.

    The caller owns the database transaction and must commit or
    roll back the session.

    Returns:
        Number of chunks successfully prepared and flushed.
    """
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= MAX_BATCH_SIZE
    ):
        raise ValueError(
            f"batch_size must be between 1 and {MAX_BATCH_SIZE}."
        )

    service = embedding_service or get_embedding_service()

    statement = (
        select(PolicyChunk)
        .where(PolicyChunk.embedding.is_(None))
        .order_by(PolicyChunk.created_at, PolicyChunk.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )

    chunks = list(db.scalars(statement).all())

    if not chunks:
        return 0

    texts = [chunk.text for chunk in chunks]

    try:
        vectors = service.embed_texts(texts)
    except EmbeddingServiceError:
        raise
    except Exception as exc:
        raise EmbeddingPersistenceError(
            "Could not generate policy chunk embeddings."
        ) from exc

    if len(vectors) != len(chunks):
        raise EmbeddingPersistenceError(
            "The embedding service returned an unexpected number of vectors."
        )

    for vector in vectors:
        if (
            len(vector) != EMBEDDING_DIMENSIONS
            or any(
                not isinstance(value, (int, float))
                or not float("-inf") < float(value) < float("inf")
                for value in vector
            )
        ):
            raise EmbeddingPersistenceError(
                "The embedding service returned an invalid vector."
            )

    embedded_at = datetime.now(UTC)

    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = service.model_name
        chunk.embedded_at = embedded_at

    # Flush SQL statements without committing the caller's transaction.
    db.flush()

    return len(chunks)
