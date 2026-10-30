"""Tests for bounded PDF OCR processing."""

from types import SimpleNamespace

import pymupdf
import pytest

from claimsage.rag.ocr_service import OCRProcessingError, OCRService


def make_pdf(page_count: int = 1) -> bytes:
    """Create a small in-memory PDF for OCR tests."""
    document = pymupdf.open()

    for page_number in range(page_count):
        page = document.new_page()
        page.insert_text((72, 72), f"Synthetic page {page_number + 1}")

    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def make_service(**overrides: object) -> OCRService:
    """Create an OCR service with isolated test settings."""
    settings = {
        "ocr_enabled": True,
        "tesseract_cmd": None,
        "ocr_language": "eng",
        "ocr_dpi": 100,
        "ocr_max_pages": 10,
        "ocr_timeout_seconds": 5,
    }
    settings.update(overrides)

    service = OCRService()
    service.settings = SimpleNamespace(**settings)
    return service


def fake_ocr_data() -> dict[str, list[object]]:
    """Return representative pytesseract image_to_data output."""
    return {
        "text": ["Insurance", "claim", "number", ""],
        "conf": ["95.0", "85.0", "75.0", "-1"],
        "block_num": [1, 1, 1, 1],
        "par_num": [1, 1, 1, 1],
        "line_num": [1, 1, 1, 1],
    }


def test_extract_page_returns_text_and_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service()
    monkeypatch.setattr(
        "claimsage.rag.ocr_service.pytesseract.image_to_data",
        lambda *args, **kwargs: fake_ocr_data(),
    )

    result = service.extract_page(make_pdf(), 1)

    assert result.text == "Insurance claim number"
    assert result.page_number == 1
    assert result.confidence == 85.0
    assert result.extraction_method == "ocr"


def test_extract_page_rejects_when_ocr_disabled() -> None:
    service = make_service(ocr_enabled=False)

    with pytest.raises(OCRProcessingError, match="OCR is disabled"):
        service.extract_page(make_pdf(), 1)


@pytest.mark.parametrize(
    ("pdf_bytes", "page_number"),
    [
        (b"", 1),
        (b"not a pdf", 1),
        (make_pdf(), 0),
        (make_pdf(), 2),
    ],
)
def test_extract_page_rejects_invalid_input(
    pdf_bytes: bytes,
    page_number: int,
) -> None:
    service = make_service()

    with pytest.raises(OCRProcessingError):
        service.extract_page(pdf_bytes, page_number)


def test_extract_page_rejects_oversized_pdf() -> None:
    service = make_service()

    with pytest.raises(OCRProcessingError, match="permitted size"):
        service.extract_page(b"x" * (20 * 1024 * 1024 + 1), 1)


def test_extract_page_rejects_page_count_over_limit() -> None:
    service = make_service(ocr_max_pages=1)

    with pytest.raises(OCRProcessingError, match="page limit"):
        service.extract_page(make_pdf(page_count=2), 1)


def test_extract_page_converts_tesseract_timeout_to_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service()

    def raise_timeout(*args: object, **kwargs: object) -> None:
        raise RuntimeError("internal timeout details")

    monkeypatch.setattr(
        "claimsage.rag.ocr_service.pytesseract.image_to_data",
        raise_timeout,
    )

    with pytest.raises(
        OCRProcessingError,
        match="OCR could not process the requested PDF page",
    ) as error:
        service.extract_page(make_pdf(), 1)

    assert "internal timeout details" not in str(error.value)


def test_extract_page_handles_empty_ocr_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service()
    monkeypatch.setattr(
        "claimsage.rag.ocr_service.pytesseract.image_to_data",
        lambda *args, **kwargs: {
            "text": [""],
            "conf": ["-1"],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        },
    )

    result = service.extract_page(make_pdf(), 1)

    assert result.text == ""
    assert result.confidence is None
    assert result.page_number == 1
