"""Tests for local policy embedding persistence."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from claimsage.db.base import Base
from claimsage.db.models import Employee, PolicyChunk, PolicyDocument
from claimsage.rag.embedding_service import (
    EMBEDDING_DIMENSIONS,
    EmbeddingServiceError,
)
from claimsage.services.embedding_persistence import (
    EmbeddingPersistenceError,
    embed_pending_policy_chunks,
)


class FakeEmbeddingService:
    """Deterministic embedding service for unit tests."""

    model_name = "test-local-model"

    def __init__(self, vectors=None, error=None):
        self.vectors = vectors or []
        self.error = error
        self.received_texts = []

    def embed_texts(self, texts):
        self.received_texts.extend(texts)

        if self.error:
            raise self.error

        return self.vectors


@pytest.fixture
def db_session():
    """Create an isolated SQLite test database."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)
    engine.dispose()


def create_policy_chunks(db, count=2):
    """Create a synthetic employee, document and policy chunks."""

    employee = Employee(
        email=f"{uuid4().hex}@example.test",
        display_name="Synthetic Employee",
    )
    db.add(employee)
    db.flush()

    document = PolicyDocument(
        filename="synthetic-policy.pdf",
        checksum_sha256=uuid4().hex * 2,
        mime_type="application/pdf",
        file_size_bytes=100,
        uploaded_by_employee_id=employee.id,
        status="processed",
    )
    db.add(document)
    db.flush()

    chunks = [
        PolicyChunk(
            document_id=document.id,
            page_number=1,
            chunk_index=index,
            chunk_id=uuid4().hex,
            text=f"Synthetic policy text number {index}.",
        )
        for index in range(count)
    ]

    db.add_all(chunks)
    db.flush()

    return chunks


def test_persists_pending_embeddings(db_session):
    chunks = create_policy_chunks(db_session, count=2)

    vectors = [
        [0.1] * EMBEDDING_DIMENSIONS,
        [0.2] * EMBEDDING_DIMENSIONS,
    ]

    service = FakeEmbeddingService(vectors=vectors)

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
    )

    assert processed == 2
    assert len(service.received_texts) == 2

    expected_by_text = dict(
        zip(service.received_texts, vectors, strict=True)
    )

    for chunk in chunks:
        assert chunk.embedding == expected_by_text[chunk.text]
        assert chunk.embedding_model == "test-local-model"
        assert chunk.embedded_at is not None


def test_skips_chunks_that_already_have_embeddings(db_session):
    chunks = create_policy_chunks(db_session, count=2)

    existing_vector = [0.3] * EMBEDDING_DIMENSIONS

    chunks[0].embedding = existing_vector
    chunks[0].embedding_model = "previous-model"

    service = FakeEmbeddingService(
        vectors=[[0.4] * EMBEDDING_DIMENSIONS]
    )

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
    )

    assert processed == 1
    assert len(service.received_texts) == 1
    assert chunks[0].embedding == existing_vector
    assert chunks[0].embedding_model == "previous-model"
    assert chunks[1].embedding_model == "test-local-model"


def test_returns_zero_when_no_pending_chunks_exist(db_session):
    service = FakeEmbeddingService()

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
    )

    assert processed == 0
    assert service.received_texts == []


@pytest.mark.parametrize("batch_size", [0, 65, True])
def test_rejects_invalid_batch_size(db_session, batch_size):
    with pytest.raises(ValueError):
        embed_pending_policy_chunks(
            db_session,
            batch_size=batch_size,
            embedding_service=FakeEmbeddingService(),
        )


def test_rejects_invalid_vector_dimensions(db_session):
    chunks = create_policy_chunks(db_session, count=1)

    service = FakeEmbeddingService(
        vectors=[[0.1] * (EMBEDDING_DIMENSIONS - 1)]
    )

    with pytest.raises(
        EmbeddingPersistenceError,
        match="invalid vector",
    ):
        embed_pending_policy_chunks(
            db_session,
            embedding_service=service,
        )

    assert chunks[0].embedding is None
    assert chunks[0].embedded_at is None


def test_embedding_failure_does_not_assign_vectors(db_session):
    chunks = create_policy_chunks(db_session, count=1)

    service = FakeEmbeddingService(
        error=EmbeddingServiceError("Synthetic model failure.")
    )

    with pytest.raises(EmbeddingServiceError):
        embed_pending_policy_chunks(
            db_session,
            embedding_service=service,
        )

    assert chunks[0].embedding is None
    assert chunks[0].embedding_model is None
    assert chunks[0].embedded_at is None


def test_caller_controls_transaction(db_session):
    chunks = create_policy_chunks(db_session, count=1)

    # Commit fixture data before testing embedding rollback.
    db_session.commit()

    chunk_id = chunks[0].id

    service = FakeEmbeddingService(
        vectors=[[0.5] * EMBEDDING_DIMENSIONS]
    )

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
    )

    assert processed == 1
    assert chunks[0].embedding == [0.5] * EMBEDDING_DIMENSIONS

    # Embedding persistence must not commit automatically.
    db_session.rollback()

    saved_chunk = db_session.scalar(
        select(PolicyChunk).where(PolicyChunk.id == chunk_id)
    )

    assert saved_chunk is not None
    assert saved_chunk.embedding is None
    assert saved_chunk.embedding_model is None
    assert saved_chunk.embedded_at is None
