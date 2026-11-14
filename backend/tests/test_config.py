import pytest
from pydantic import ValidationError

from claimsage.core.config import Settings


@pytest.fixture(autouse=True)
def default_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes-long"
    )


def test_ocr_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.ocr_enabled is True
    assert settings.tesseract_cmd is None
    assert settings.ocr_language == "eng"
    assert settings.ocr_dpi == 200
    assert settings.ocr_max_pages == 100
    assert settings.ocr_timeout_seconds == 30
    assert settings.pdf_max_pages == 100


def test_ocr_settings_read_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TESSERACT_CMD",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
    monkeypatch.setenv("OCR_LANGUAGE", "eng")
    monkeypatch.setenv("OCR_DPI", "250")
    monkeypatch.setenv("OCR_MAX_PAGES", "50")
    monkeypatch.setenv("OCR_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("OCR_ENABLED", "true")
    monkeypatch.setenv("PDF_MAX_PAGES", "200")

    settings = Settings(_env_file=None)

    assert settings.tesseract_cmd == (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
    assert settings.ocr_language == "eng"
    assert settings.ocr_dpi == 250
    assert settings.ocr_max_pages == 50
    assert settings.ocr_timeout_seconds == 45
    assert settings.ocr_enabled is True
    assert settings.pdf_max_pages == 200


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("OCR_DPI", "50"),
        ("OCR_DPI", "500"),
        ("OCR_MAX_PAGES", "0"),
        ("OCR_MAX_PAGES", "501"),
        ("OCR_TIMEOUT_SECONDS", "0"),
        ("OCR_TIMEOUT_SECONDS", "301"),
        ("OCR_LANGUAGE", ""),
        ("PDF_MAX_PAGES", "0"),
        ("PDF_MAX_PAGES", "501"),
    ],
)
def test_invalid_ocr_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    value: str,
) -> None:
    monkeypatch.setenv(setting, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_upload_request_limit_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.upload_max_request_bytes == 22 * 1024 * 1024


def test_upload_request_limit_reads_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_MAX_REQUEST_BYTES", "25000000")

    settings = Settings(_env_file=None)

    assert settings.upload_max_request_bytes == 25_000_000


@pytest.mark.parametrize(
    "value",
    ["0", "100", "52428801"],
)
def test_invalid_upload_request_limits_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("UPLOAD_MAX_REQUEST_BYTES", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_gemini_settings_defaults_and_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    default_settings = Settings(_env_file=None)
    assert default_settings.gemini_api_key is None
    assert default_settings.gemini_model == "gemini-3.8-flash"

    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-gemini-key-not-real")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    configured = Settings(_env_file=None)
    assert configured.gemini_api_key is not None
    assert configured.gemini_api_key.get_secret_value() == "synthetic-gemini-key-not-real"
    assert "synthetic-gemini-key-not-real" not in repr(configured)
    assert configured.gemini_model == "gemini-2.5-flash-lite"


@pytest.mark.parametrize("invalid_model", ["", "   ", "gemini model with spaces", "gemini\nflash"])
def test_invalid_gemini_model_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    invalid_model: str,
) -> None:
    monkeypatch.setenv("GEMINI_MODEL", invalid_model)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
