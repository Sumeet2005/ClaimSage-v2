"""Idempotent policy chunk embedding and readiness management."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from claimsage.db.models import PolicyChunk, PolicyDocument
from claimsage.rag.embedding_service import get_embedding_service
from claimsage.services.embedding_persistence import (
    EmbeddingPersistenceError,
    embed_pending_policy_chunks,
)


class PolicyEmbeddingIngestionError(RuntimeError):
    """Raised when policy embeddings could not be completed safely."""


PROCESSING_STALE_AFTER = timedelta(minutes=30)


def process_policy_document_embeddings(
    session: Session,
    *,
    document_id: UUID,
) -> PolicyDocument:
    """Embed a document's missing chunks before making it searchable."""

    document = session.scalar(
        select(PolicyDocument)
        .where(PolicyDocument.id == document_id)
        .with_for_update()
    )
    if document is None:
        raise PolicyEmbeddingIngestionError(
            "The policy document could not be found."
        )
    if document.status == "processing" and (
        document.updated_at is None
        or datetime.now(UTC) - document.updated_at < PROCESSING_STALE_AFTER
    ):
        raise PolicyEmbeddingIngestionError(
            "Policy document embedding is already in progress."
        )
    if document.status not in {
        "uploaded",
        "processed",
        "failed",
        "processing",
    }:
        raise PolicyEmbeddingIngestionError(
            "The policy document is not ready for embedding."
        )

    embedding_model = get_embedding_service().model_name
    chunk_count = session.scalar(
        select(func.count())
        .select_from(PolicyChunk)
        .where(PolicyChunk.document_id == document_id)
    )
    pending_statement = select(PolicyChunk.id).where(
        PolicyChunk.document_id == document_id,
        or_(
            PolicyChunk.embedding.is_(None),
            PolicyChunk.embedding_model.is_distinct_from(embedding_model),
        ),
    )
    pending_chunk_id = session.scalar(pending_statement.limit(1))
    if document.status == "processed" and chunk_count and pending_chunk_id is None:
        return document

    document.status = "processing"
    session.commit()

    try:
        if not chunk_count:
            raise EmbeddingPersistenceError(
                "The policy document contains no text chunks."
            )

        while embed_pending_policy_chunks(
            session,
            document_id=document_id,
        ):
            session.commit()

        pending_chunk_id = session.scalar(
            select(PolicyChunk.id)
            .where(
                PolicyChunk.document_id == document_id,
                or_(
                    PolicyChunk.embedding.is_(None),
                    PolicyChunk.embedding_model.is_distinct_from(
                        embedding_model
                    ),
                ),
            )
            .limit(1)
        )
        if pending_chunk_id is not None:
            raise EmbeddingPersistenceError(
                "Policy chunks remain without embeddings."
            )
    except Exception:
        session.rollback()
        document = session.get(PolicyDocument, document_id)
        if document is not None:
            document.status = "failed"
            session.commit()
        raise PolicyEmbeddingIngestionError(
            "Policy document embeddings could not be generated."
        ) from None

    document = session.get(PolicyDocument, document_id)
    if document is None:
        raise PolicyEmbeddingIngestionError(
            "The policy document could not be found after embedding."
        )
    document.status = "processed"
    session.commit()
    return document
