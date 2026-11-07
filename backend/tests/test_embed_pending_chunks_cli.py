from contextlib import nullcontext
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "embed_pending_chunks.py"
)
SCRIPT_SPEC = spec_from_file_location("embed_pending_chunks", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
assert SCRIPT_SPEC.loader is not None
embedding_cli = module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(embedding_cli)


def test_cli_parses_document_uuid():
    document_id = uuid4()

    args = embedding_cli.parse_args(["--document-id", str(document_id)])

    assert args.document_id == document_id


def test_cli_without_document_id_keeps_global_behavior(
    monkeypatch,
    capsys,
):
    session = MagicMock()
    session.scalar.return_value = None
    embed = MagicMock(return_value=0)
    monkeypatch.setattr(
        embedding_cli,
        "SessionLocal",
        lambda: nullcontext(session),
    )
    monkeypatch.setattr(
        embedding_cli,
        "embed_pending_policy_chunks",
        embed,
    )

    embedding_cli.main([])

    embed.assert_called_once_with(
        db=session,
        batch_size=10,
        document_id=None,
    )
    output = capsys.readouterr().out
    assert "global pending queue" in output
    assert "More pending chunks may remain: no." in output


def test_cli_rejects_invalid_document_uuid():
    with pytest.raises(SystemExit) as exc_info:
        embedding_cli.parse_args(["--document-id", "not-a-uuid"])

    assert exc_info.value.code == 2


def test_cli_reports_processed_count_and_remaining_work(
    monkeypatch,
    capsys,
):
    document_id = uuid4()
    session = MagicMock()
    session.scalar.return_value = uuid4()
    embed = MagicMock(return_value=10)
    monkeypatch.setattr(
        embedding_cli,
        "SessionLocal",
        lambda: nullcontext(session),
    )
    monkeypatch.setattr(
        embedding_cli,
        "embed_pending_policy_chunks",
        embed,
    )

    embedding_cli.main(["--document-id", str(document_id)])

    embed.assert_called_once_with(
        db=session,
        batch_size=10,
        document_id=document_id,
    )
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    output = capsys.readouterr().out
    assert "Embedded 10 policy chunks" in output
    assert "More pending chunks may remain: yes." in output
