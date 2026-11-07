"""Database-free policy embedding state and retry tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from claimsage.services import policy_embedding_ingestion as ingestion
from claimsage.services.policy_embedding_ingestion import (
    PolicyEmbeddingIngestionError,
)


def test_policy_is_ready_only_after_all_batches_are_embedded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    document = SimpleNamespace(id=document_id, status="uploaded")
    session = MagicMock(spec=Session)
    session.get.return_value = document
    session.scalar.side_effect = [document, 2, None, None]
    embed = MagicMock(side_effect=[1, 1, 0])
    monkeypatch.setattr(ingestion, "embed_pending_policy_chunks", embed)

    result = ingestion.process_policy_document_embeddings(
        session,
        document_id=document_id,
    )

    assert result.status == "processed"
    assert embed.call_count == 3
    assert all(
        call.kwargs["document_id"] == document_id
        for call in embed.call_args_list
    )
    assert session.commit.call_count == 4


def test_embedding_failure_persists_failed_state_for_idempotent_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    document = SimpleNamespace(id=document_id, status="uploaded")
    session = MagicMock(spec=Session)
    session.get.return_value = document
    session.scalar.side_effect = [document, 1, None]
    monkeypatch.setattr(
        ingestion,
        "embed_pending_policy_chunks",
        MagicMock(side_effect=RuntimeError("synthetic model failure")),
    )

    with pytest.raises(
        PolicyEmbeddingIngestionError,
        match="could not be generated",
    ):
        ingestion.process_policy_document_embeddings(
            session,
            document_id=document_id,
        )

    assert document.status == "failed"
    assert session.rollback.call_count == 1
    assert session.commit.call_count == 2


def test_ready_document_retry_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = SimpleNamespace(id=uuid4(), status="processed")
    session = MagicMock(spec=Session)
    session.get.return_value = document
    session.scalar.side_effect = [document, 1, None]
    embed = MagicMock()
    monkeypatch.setattr(ingestion, "embed_pending_policy_chunks", embed)

    result = ingestion.process_policy_document_embeddings(
        session,
        document_id=document.id,
    )

    assert result is document
    embed.assert_not_called()
    session.commit.assert_not_called()


def test_stale_processing_document_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        status="processing",
        updated_at=datetime.now(UTC) - timedelta(minutes=31),
    )
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [document, 1, None, None]
    session.get.return_value = document
    embed = MagicMock(side_effect=[1, 0])
    monkeypatch.setattr(ingestion, "embed_pending_policy_chunks", embed)

    result = ingestion.process_policy_document_embeddings(
        session,
        document_id=document_id,
    )

    assert result.status == "processed"
    assert embed.call_count == 2
