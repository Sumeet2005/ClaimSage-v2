"""PostgreSQL tests for local policy embedding persistence."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

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
    """Create only the required tables in a disposable claimsage_test schema."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.fail(
            "DATABASE_URL must explicitly target PostgreSQL claimsage_test.",
            pytrace=False,
        )

    try:
        parsed_url = make_url(database_url)
    except (TypeError, ValueError):
        pytest.fail(
            "DATABASE_URL must explicitly target PostgreSQL claimsage_test.",
            pytrace=False,
        )

    if (
        parsed_url.get_backend_name() != "postgresql"
        or parsed_url.database != "claimsage_test"
    ):
        pytest.fail(
            "Refusing database test setup outside PostgreSQL claimsage_test.",
            pytrace=False,
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    schema_name = f"claimsage_embedding_tests_{uuid4().hex}"
    connection = None
    schema_created = False

    try:
        try:
            connection = engine.connect()
            database_name = connection.scalar(text("SELECT current_database()"))
        except Exception:
            pytest.fail(
                "Could not verify the PostgreSQL test database; "
                "connection details suppressed.",
                pytrace=False,
            )

        if database_name != "claimsage_test":
            pytest.fail(
                "Refusing database test setup outside claimsage_test.",
                pytrace=False,
            )

        connection.execute(text(f"CREATE SCHEMA {schema_name}"))
        connection.execute(text(f"SET search_path TO {schema_name}, public"))
        connection.commit()
        schema_created = True

        Base.metadata.create_all(
            connection,
            tables=[
                Employee.__table__,
                PolicyDocument.__table__,
                PolicyChunk.__table__,
            ],
            checkfirst=False,
        )
        connection.commit()

        with Session(bind=connection) as session:
            yield session
    finally:
        if connection is not None:
            if schema_created:
                connection.rollback()
                connection.execute(
                    text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
                )
                connection.commit()
            connection.close()
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


def test_document_scoped_embedding_leaves_other_documents_untouched(
    db_session,
):
    target_chunks = create_policy_chunks(db_session, count=2)
    other_chunks = create_policy_chunks(db_session, count=2)
    service = FakeEmbeddingService(
        vectors=[
            [0.1] * EMBEDDING_DIMENSIONS,
            [0.2] * EMBEDDING_DIMENSIONS,
        ]
    )

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
        document_id=target_chunks[0].document_id,
    )

    assert processed == 2
    assert set(service.received_texts) == {
        chunk.text for chunk in target_chunks
    }
    assert all(chunk.embedding is not None for chunk in target_chunks)
    assert all(chunk.embedding is None for chunk in other_chunks)


def test_skips_chunks_that_already_have_embeddings(db_session):
    chunks = create_policy_chunks(db_session, count=2)

    existing_vector = [0.3] * EMBEDDING_DIMENSIONS

    chunks[0].embedding = existing_vector
    chunks[0].embedding_model = "test-local-model"

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
    assert chunks[0].embedding_model == "test-local-model"
    assert chunks[1].embedding_model == "test-local-model"


def test_document_scope_replaces_incompatible_embeddings_only(db_session):
    target_chunks = create_policy_chunks(db_session, count=2)
    other_chunks = create_policy_chunks(db_session, count=1)
    existing_vector = [0.3] * EMBEDDING_DIMENSIONS
    target_chunks[0].embedding = existing_vector
    target_chunks[0].embedding_model = "previous-model"
    service = FakeEmbeddingService(
        vectors=[
            [0.4] * EMBEDDING_DIMENSIONS,
            [0.5] * EMBEDDING_DIMENSIONS,
        ]
    )

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
        document_id=target_chunks[0].document_id,
    )

    assert processed == 2
    assert set(service.received_texts) == {
        target_chunks[0].text,
        target_chunks[1].text,
    }
    assert target_chunks[0].embedding != existing_vector
    assert target_chunks[0].embedding_model == "test-local-model"
    assert other_chunks[0].embedding is None


def test_missing_document_id_returns_zero_without_embedding(db_session):
    create_policy_chunks(db_session, count=1)
    service = FakeEmbeddingService()

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
        document_id=uuid4(),
    )

    assert processed == 0
    assert service.received_texts == []


def test_returns_zero_when_no_pending_chunks_exist(db_session):
    service = FakeEmbeddingService()

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
    )

    assert processed == 0
    assert service.received_texts == []


def test_omitted_document_id_preserves_global_behavior(db_session):
    first_document_chunks = create_policy_chunks(db_session, count=1)
    second_document_chunks = create_policy_chunks(db_session, count=1)
    service = FakeEmbeddingService(
        vectors=[
            [0.1] * EMBEDDING_DIMENSIONS,
            [0.2] * EMBEDDING_DIMENSIONS,
        ]
    )

    processed = embed_pending_policy_chunks(
        db_session,
        embedding_service=service,
    )

    assert processed == 2
    assert set(service.received_texts) == {
        first_document_chunks[0].text,
        second_document_chunks[0].text,
    }


def test_document_scope_respects_batch_limit(db_session):
    chunks = create_policy_chunks(db_session, count=3)
    service = FakeEmbeddingService(
        vectors=[[0.1] * EMBEDDING_DIMENSIONS]
    )

    processed = embed_pending_policy_chunks(
        db_session,
        batch_size=1,
        embedding_service=service,
        document_id=chunks[0].document_id,
    )

    assert processed == 1
    assert len(service.received_texts) == 1
    assert sum(chunk.embedding is None for chunk in chunks) == 2


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
