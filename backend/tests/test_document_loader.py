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


def test_extract_pdf_pages_uses_ocr_for_scanned_pages(
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

    class FakeOCRResult:
        text = "Scanned insurance policy content"
        confidence = 91.5

    def fake_extract_page(
        self: object,
        pdf_bytes: bytes,
        page_number: int,
    ) -> FakeOCRResult:
        assert pdf_bytes == b"%PDF-test-content"
        assert page_number == 1
        return FakeOCRResult()

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)
    monkeypatch.setattr(
        document_loader.OCRService,
        "extract_page",
        fake_extract_page,
    )

    pages = extract_pdf_pages(pdf_path)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].text == "Scanned insurance policy content"
    assert pages[0].extraction_method == "ocr"
    assert pages[0].ocr_confidence == 91.5


def test_extract_pdf_pages_rejects_invalid_pdf_signature(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "invalid.pdf"
    pdf_path.write_bytes(b"This is not a PDF document.")

    with pytest.raises(
        DocumentIngestionError,
        match="valid PDF signature",
    ):
        extract_pdf_pages(pdf_path)


def test_extract_pdf_pages_rejects_oversized_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "large.pdf"
    pdf_path.write_bytes(b"%PDF-" + b"x" * 100)

    monkeypatch.setattr(
        document_loader,
        "MAX_PDF_SIZE_BYTES",
        50,
    )

    with pytest.raises(
        DocumentIngestionError,
        match="20 MiB size limit",
    ):
        extract_pdf_pages(pdf_path)


def test_extract_pdf_pages_handles_unexpected_parser_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "malformed.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakeReader:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise KeyError("Synthetic malformed PDF error")

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)

    with pytest.raises(
        DocumentIngestionError,
        match="could not be read safely",
    ):
        extract_pdf_pages(pdf_path)


def test_extract_pdf_pages_handles_page_extraction_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "page-error.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakePage:
        def extract_text(self) -> str:
            raise RuntimeError("Synthetic extraction failure")

    class FakeReader:
        is_encrypted = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)

    with pytest.raises(
        DocumentIngestionError,
        match="could not be read safely",
    ):
        extract_pdf_pages(pdf_path)
def test_extract_pdf_pages_does_not_use_ocr_for_native_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "native.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakePage:
        def extract_text(self) -> str:
            return "Native insurance policy content"

    class FakeReader:
        is_encrypted = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pages = [FakePage()]

    def fail_if_ocr_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("OCR must not run for pages with native text.")

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)
    monkeypatch.setattr(
        document_loader.OCRService,
        "extract_page",
        fail_if_ocr_called,
    )

    pages = extract_pdf_pages(pdf_path)

    assert len(pages) == 1
    assert pages[0].text == "Native insurance policy content"
    assert pages[0].extraction_method == "native"
    assert pages[0].ocr_confidence is None


def test_extract_pdf_pages_uses_ocr_only_for_scanned_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "mixed.pdf"
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
                FakePage("Native page one"),
                FakePage(""),
                FakePage("Native page three"),
            ]

    ocr_calls: list[int] = []

    class FakeOCRResult:
        text = "OCR extracted page two"
        confidence = 88.0

    def fake_extract_page(
        self: object,
        pdf_bytes: bytes,
        page_number: int,
    ) -> FakeOCRResult:
        ocr_calls.append(page_number)
        return FakeOCRResult()

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)
    monkeypatch.setattr(
        document_loader.OCRService,
        "extract_page",
        fake_extract_page,
    )

    pages = extract_pdf_pages(pdf_path)

    assert ocr_calls == [2]
    assert len(pages) == 3
    assert [page.page_number for page in pages] == [1, 2, 3]
    assert [page.extraction_method for page in pages] == [
        "native",
        "ocr",
        "native",
    ]
    assert pages[1].text == "OCR extracted page two"
    assert pages[1].ocr_confidence == 88.0


def test_chunk_pages_preserves_extraction_provenance() -> None:
    page = PageText(
        source_name="scanned-policy.pdf",
        document_sha256="b" * 64,
        page_number=4,
        text="Scanned policy coverage information.",
        extraction_method="ocr",
        ocr_confidence=92.5,
    )

    chunks = chunk_pages([page])

    assert len(chunks) == 1
    assert chunks[0].extraction_method == "ocr"
    assert chunks[0].ocr_confidence == 92.5
    assert chunks[0].page_number == 4


def test_extract_pdf_pages_accepts_pdf_at_page_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "at-limit.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakePage:
        def extract_text(self) -> str:
            return "Native policy content"

    class FakeReader:
        is_encrypted = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pages = [FakePage(), FakePage()]

    settings = type("TestSettings", (), {"pdf_max_pages": 2})()

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)
    monkeypatch.setattr(
        document_loader,
        "get_settings",
        lambda: settings,
    )

    pages = extract_pdf_pages(pdf_path)

    assert len(pages) == 2
    assert [page.page_number for page in pages] == [1, 2]


def test_extract_pdf_pages_rejects_pdf_over_page_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "over-limit.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakePage:
        def extract_text(self) -> str:
            return "Native policy content"

    class FakeReader:
        is_encrypted = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pages = [FakePage(), FakePage(), FakePage()]

    settings = type("TestSettings", (), {"pdf_max_pages": 2})()

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)
    monkeypatch.setattr(
        document_loader,
        "get_settings",
        lambda: settings,
    )

    with pytest.raises(
        DocumentIngestionError,
        match="configured page limit",
    ):
        extract_pdf_pages(pdf_path)


def test_extract_pdf_pages_checks_page_limit_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "must-not-extract.pdf"
    pdf_path.write_bytes(b"%PDF-test-content")

    class FakePage:
        def extract_text(self) -> str:
            raise AssertionError(
                "Page extraction must not run when the PDF exceeds the limit."
            )

    class FakeReader:
        is_encrypted = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.pages = [FakePage(), FakePage(), FakePage()]

    settings = type("TestSettings", (), {"pdf_max_pages": 2})()

    monkeypatch.setattr(document_loader, "PdfReader", FakeReader)
    monkeypatch.setattr(
        document_loader,
        "get_settings",
        lambda: settings,
    )

    with pytest.raises(
        DocumentIngestionError,
        match="configured page limit",
    ):
        extract_pdf_pages(pdf_path)
