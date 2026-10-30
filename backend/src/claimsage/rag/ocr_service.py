"""Bounded, page-level OCR service for PDF documents."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from threading import Lock

import pymupdf
import pytesseract
from PIL import Image
from pytesseract import Output, TesseractError

from claimsage.core.config import get_settings

MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024
MAX_OCR_PIXELS = 20_000_000

# pytesseract stores its executable path in module-level state.
# Serialize OCR calls so concurrent requests cannot change it mid-execution.
_TESSERACT_LOCK = Lock()


class OCRProcessingError(Exception):
    """Raised when a PDF page cannot be processed safely by OCR."""


@dataclass(frozen=True, slots=True)
class OCRResult:
    """Text and provenance returned by OCR for one PDF page."""

    text: str
    page_number: int
    confidence: float | None
    extraction_method: str = "ocr"


class OCRService:
    """Render and OCR individual PDF pages with resource limits."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def extract_page(
        self,
        pdf_bytes: bytes,
        page_number: int,
    ) -> OCRResult:
        """Extract text from a one-based PDF page number using OCR."""

        if not self.settings.ocr_enabled:
            raise OCRProcessingError("OCR is disabled.")

        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            raise OCRProcessingError("The PDF content is empty or invalid.")

        if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
            raise OCRProcessingError("The PDF exceeds the permitted size.")

        if page_number < 1:
            raise OCRProcessingError("The page number is invalid.")

        try:
            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
                if document.is_encrypted:
                    raise OCRProcessingError("Encrypted PDFs are not supported.")

                if document.page_count > self.settings.ocr_max_pages:
                    raise OCRProcessingError(
                        "The PDF exceeds the configured OCR page limit."
                    )

                if page_number > document.page_count:
                    raise OCRProcessingError("The requested page does not exist.")

                page = document.load_page(page_number - 1)
                scale = self.settings.ocr_dpi / 72
                matrix = pymupdf.Matrix(scale, scale)

                # Check the expected render dimensions before allocating pixels.
                width = int(page.rect.width * scale)
                height = int(page.rect.height * scale)

                if width <= 0 or height <= 0:
                    raise OCRProcessingError("The PDF page dimensions are invalid.")

                if width * height > MAX_OCR_PIXELS:
                    raise OCRProcessingError(
                        "The PDF page exceeds the permitted OCR image size."
                    )

                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image_bytes = pixmap.tobytes("png")

            with Image.open(BytesIO(image_bytes)) as image:
                image.load()

                with _TESSERACT_LOCK:
                    if self.settings.tesseract_cmd:
                        pytesseract.pytesseract.tesseract_cmd = (
                            self.settings.tesseract_cmd
                        )

                    data = pytesseract.image_to_data(
                        image,
                        lang=self.settings.ocr_language,
                        config="--psm 3",
                        output_type=Output.DICT,
                        timeout=self.settings.ocr_timeout_seconds,
                    )

            lines: dict[tuple[int, int, int], list[str]] = {}
            confidence_values: list[float] = []

            for index, raw_word in enumerate(data["text"]):
                word = raw_word.strip()

                if not word:
                    continue

                try:
                    confidence = float(data["conf"][index])
                except (TypeError, ValueError):
                    confidence = -1.0

                if confidence >= 0:
                    confidence_values.append(confidence)

                line_key = (
                    int(data["block_num"][index]),
                    int(data["par_num"][index]),
                    int(data["line_num"][index]),
                )
                lines.setdefault(line_key, []).append(word)

            extracted_text = "\n".join(
                " ".join(words) for words in lines.values()
            ).strip()

            average_confidence = (
                round(sum(confidence_values) / len(confidence_values), 2)
                if confidence_values
                else None
            )

            return OCRResult(
                text=extracted_text,
                page_number=page_number,
                confidence=average_confidence,
            )

        except OCRProcessingError:
            raise
        except (TesseractError, RuntimeError, ValueError, OSError) as exc:
            raise OCRProcessingError(
                "OCR could not process the requested PDF page."
            ) from exc
        except Exception as exc:
            # Do not expose parser, image, or system details to API callers.
            raise OCRProcessingError(
                "OCR could not process the requested PDF page."
            ) from exc
