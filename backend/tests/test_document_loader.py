from pathlib import Path

import pytest

from claimsage.rag import document_loader
from claimsage.rag.document_loader import (
    DocumentIngestionError,
    PageText,
    chunk_pages,
    extract_pdf_pages,
)


def make_page(
    text: str,
    page_number: int = 1,
) -> PageText:
    return PageText(
        source_name="policy.pdf",
        document_sha256="a" * 64,
        page_number=page_number,
        text=text,
    )


def test_chunk_pages_preserves_page_provenance() -> None:
    pages = [make_page("A " * 100, page_number=3)]

    chunks = chunk_pages(pages, chunk_size=50, overlap=10)

    assert len(chunks) > 1
    assert all(chunk.page_number == 3 for chunk in chunks)
    assert all(chunk.source_name == "policy.pdf" for chunk in chunks)
    assert all(chunk.document_sha256 == "a" * 64 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_pages_does_not_mix_pages() -> None:
    pages = [
        make_page("First page content. " * 10, page_number=1),
        make_page("Second page content. " * 10, page_number=2),
    ]

    chunks = chunk_pages(pages, chunk_size=40, overlap=5)

    assert chunks
    assert {chunk.page_number for chunk in chunks} == {1, 2}

    for chunk in chunks:
        if chunk.page_number == 1:
            assert "Second page content" not in chunk.text
        else:
            assert "First page content" not in chunk.text


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [
        (0, 0),
        (-1, 0),
        (10, 10),
        (10, 11),
        (10, -1),
    ],
)
def test_chunk_pages_rejects_invalid_settings(
    chunk_size: int,
    overlap: int,
) -> None:
    with pytest.raises(ValueError):
        chunk_pages(
            [make_page("Some document text.")],
            chunk_size=chunk_size,
            overlap=overlap,
        )


def test_chunk_pages_returns_deterministic_ids() -> None:
    pages = [make_page("Deterministic content " * 10)]

    first_result = chunk_pages(pages, chunk_size=40, overlap=5)
    second_result = chunk_pages(pages, chunk_size=40, overlap=5)

    assert [chunk.chunk_id for chunk in first_result] == [
        chunk.chunk_id for chunk in second_result
    ]


def test_extract_pdf_pages_preserves_page_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class FakeReader:
        is_encrypted = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pages = [
                FakePage("  First page\ncontent  "),
                FakePage("Second page content"),
            ]

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)

    pages = extract_pdf_pages(pdf_path)

    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert pages[0].text == "First page content"
    assert pages[1].page_number == 2
    assert pages[1].text == "Second page content"
    assert pages[0].document_sha256 == pages[1].document_sha256


def test_extract_pdf_pages_rejects_wrong_extension(tmp_path: Path) -> None:
    file_path = tmp_path / "document.txt"
    file_path.write_text("Not a PDF", encoding="utf-8")

    with pytest.raises(DocumentIngestionError, match="Only PDF"):
        extract_pdf_pages(file_path)


def test_extract_pdf_pages_rejects_empty_pdf(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.pdf"
    file_path.write_bytes(b"")

    with pytest.raises(DocumentIngestionError, match="empty"):
        extract_pdf_pages(file_path)


def test_extract_pdf_pages_rejects_no_extractable_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakePage:
        def extract_text(self) -> str:
            return ""

    class FakeReader:
        is_encrypted = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)

    with pytest.raises(DocumentIngestionError, match="no extractable text"):
        extract_pdf_pages(pdf_path)
