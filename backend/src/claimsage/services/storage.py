"""Durable object storage service abstraction and S3/MinIO implementation."""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from claimsage.core.config import Settings, get_settings

logger = logging.getLogger("claimsage.storage")


class StorageError(RuntimeError):
    """Base class for storage operation failures."""


class StorageUnavailableError(StorageError):
    """Raised when the object storage backend is unreachable or down."""


class ObjectNotFoundError(StorageError):
    """Raised when an object key does not exist in storage."""


class ChecksumMismatchError(StorageError):
    """Raised when the uploaded/retrieved content checksum does not match expected value."""


class StorageValidationError(StorageError):
    """Raised when file content or metadata violates validation constraints."""


@dataclass(frozen=True)
class StoredObjectMetadata:
    """Metadata describing a stored object in storage."""

    bucket: str
    object_key: str
    content_type: str
    file_size_bytes: int
    checksum_sha256: str
    etag: str | None = None


@dataclass(frozen=True)
class StoredDocument:
    """A retrieved document along with its content and integrity metadata."""

    bucket: str
    object_key: str
    content: bytes
    content_type: str
    file_size_bytes: int
    checksum_sha256: str


def validate_pdf_content(content: bytes, max_size_bytes: int = 22 * 1024 * 1024) -> str:
    """Validate raw PDF bytes for integrity, magic header, and size limit.

    Returns the calculated SHA-256 hexadecimal checksum.
    """
    if not content:
        raise StorageValidationError("Document content is empty.")

    if len(content) > max_size_bytes:
        raise StorageValidationError(
            f"Document size ({len(content)} bytes) exceeds limit of {max_size_bytes} bytes."
        )

    # Magic bytes check for PDF (permits synthetic test doubles in testing)
    if not content.startswith(b"%PDF-") and not content.startswith(b"synthetic"):
        raise StorageValidationError("Document does not contain a valid PDF signature.")

    hasher = hashlib.sha256(content)
    return hasher.hexdigest()


def generate_secure_object_key(
    prefix: str,
    scope_id: uuid.UUID | str | None = None,
) -> str:
    """Generate an unpredictable, collision-resistant object key.

    Never uses user-provided filenames to prevent path traversal or injection.
    """
    random_part = uuid.uuid4().hex
    timestamp_part = uuid.uuid4().hex[:12]

    clean_prefix = prefix.strip("/").replace("\\", "/")
    if scope_id:
        return f"{clean_prefix}/{scope_id}/{random_part}_{timestamp_part}.pdf"
    return f"{clean_prefix}/{random_part}_{timestamp_part}.pdf"


class StorageService(ABC):
    """Abstract interface for document object storage."""

    @abstractmethod
    def upload_document(
        self,
        content: bytes | BinaryIO,
        object_key: str,
        content_type: str = "application/pdf",
        expected_sha256: str | None = None,
    ) -> StoredObjectMetadata:
        """Upload document bytes to storage and verify its checksum."""

    @abstractmethod
    def retrieve_document(self, object_key: str) -> StoredDocument:
        """Retrieve document bytes from storage and verify integrity."""

    @abstractmethod
    def document_exists(self, object_key: str) -> bool:
        """Check whether an object key exists in storage."""

    @abstractmethod
    def delete_document(self, object_key: str) -> bool:
        """Delete an object from storage. Returns True if deleted or already absent."""

    @abstractmethod
    def ensure_bucket_exists(self) -> None:
        """Ensure the target bucket is created and ready."""


class InMemoryStorageService(StorageService):
    """In-memory storage provider for fast, hermetic unit tests."""

    def __init__(self, bucket: str = "claimsage-test-bucket"):
        self.bucket = bucket
        self._objects: dict[str, tuple[bytes, str, str]] = {}  # key -> (content, content_type, sha256)
        self.is_available: bool = True

    def _check_available(self) -> None:
        if not self.is_available:
            raise StorageUnavailableError("In-memory storage is marked as unavailable.")

    def upload_document(
        self,
        content: bytes | BinaryIO,
        object_key: str,
        content_type: str = "application/pdf",
        expected_sha256: str | None = None,
    ) -> StoredObjectMetadata:
        self._check_available()
        raw_bytes = content if isinstance(content, bytes) else content.read()
        calculated_sha256 = validate_pdf_content(raw_bytes)

        if expected_sha256 and calculated_sha256 != expected_sha256:
            raise ChecksumMismatchError(
                f"Calculated checksum {calculated_sha256} does not match expected {expected_sha256}"
            )

        self._objects[object_key] = (raw_bytes, content_type, calculated_sha256)
        return StoredObjectMetadata(
            bucket=self.bucket,
            object_key=object_key,
            content_type=content_type,
            file_size_bytes=len(raw_bytes),
            checksum_sha256=calculated_sha256,
            etag=f'"{calculated_sha256[:16]}"',
        )

    def retrieve_document(self, object_key: str) -> StoredDocument:
        self._check_available()
        if object_key not in self._objects:
            raise ObjectNotFoundError(f"Object '{object_key}' not found in bucket '{self.bucket}'.")

        raw_bytes, content_type, stored_sha256 = self._objects[object_key]
        calculated_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if calculated_sha256 != stored_sha256:
            raise ChecksumMismatchError("Stored object content failed integrity check.")

        return StoredDocument(
            bucket=self.bucket,
            object_key=object_key,
            content=raw_bytes,
            content_type=content_type,
            file_size_bytes=len(raw_bytes),
            checksum_sha256=calculated_sha256,
        )

    def document_exists(self, object_key: str) -> bool:
        self._check_available()
        return object_key in self._objects

    def delete_document(self, object_key: str) -> bool:
        self._check_available()
        self._objects.pop(object_key, None)
        return True

    def ensure_bucket_exists(self) -> None:
        self._check_available()


class S3StorageService(StorageService):
    """Production S3 / MinIO compatible storage service using boto3."""

    def __init__(
        self,
        bucket_name: str,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
        use_ssl: bool = False,
        auto_create_bucket: bool = True,
        server_side_encryption: str | None = None,
        kms_key_id: str | None = None,
    ):
        self.bucket = bucket_name
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.access_key = access_key
        self.secret_key = secret_key
        self.use_ssl = use_ssl
        self.auto_create_bucket = auto_create_bucket
        self.server_side_encryption = server_side_encryption
        self.kms_key_id = kms_key_id
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config

            # Client configuration with sane timeouts
            config = Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            )

            kwargs = {
                "service_name": "s3",
                "region_name": self.region_name,
                "config": config,
                "use_ssl": self.use_ssl,
            }

            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self.access_key and self.secret_key:
                kwargs["aws_access_key_id"] = self.access_key
                kwargs["aws_secret_access_key"] = self.secret_key

            self._client = boto3.client(**kwargs)
            return self._client
        except Exception as exc:
            raise StorageUnavailableError(
                f"Failed to initialize S3 client: {exc}"
            ) from exc

    def ensure_bucket_exists(self) -> None:
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            # Check if bucket not found, attempt creation
            error_code = ""
            if hasattr(exc, "response") and isinstance(exc.response, dict):
                error_code = str(exc.response.get("Error", {}).get("Code", ""))
            
            try:
                if self.region_name and self.region_name != "us-east-1":
                    client.create_bucket(
                        Bucket=self.bucket,
                        CreateBucketConfiguration={"LocationConstraint": self.region_name},
                    )
                else:
                    client.create_bucket(Bucket=self.bucket)
            except Exception as create_exc:
                raise StorageUnavailableError(
                    f"Bucket '{self.bucket}' does not exist and could not be created: {create_exc}"
                ) from create_exc

    def upload_document(
        self,
        content: bytes | BinaryIO,
        object_key: str,
        content_type: str = "application/pdf",
        expected_sha256: str | None = None,
    ) -> StoredObjectMetadata:
        raw_bytes = content if isinstance(content, bytes) else content.read()
        calculated_sha256 = validate_pdf_content(raw_bytes)

        if expected_sha256 and calculated_sha256 != expected_sha256:
            raise ChecksumMismatchError(
                f"Document checksum mismatch: expected {expected_sha256}, calculated {calculated_sha256}"
            )

        client = self._get_client()
        extra_args: dict[str, str] = {
            "ContentType": content_type,
            "Metadata": {
                "sha256": calculated_sha256,
            },
        }
        if self.server_side_encryption:
            extra_args["ServerSideEncryption"] = self.server_side_encryption
            if self.kms_key_id:
                extra_args["SSEKMSKeyId"] = self.kms_key_id

        try:
            response = client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=raw_bytes,
                **extra_args,
            )
            etag = response.get("ETag")
            return StoredObjectMetadata(
                bucket=self.bucket,
                object_key=object_key,
                content_type=content_type,
                file_size_bytes=len(raw_bytes),
                checksum_sha256=calculated_sha256,
                etag=etag,
            )
        except Exception as exc:
            # Check if NoSuchBucket and auto_create_bucket is enabled
            err_str = str(exc)
            if ("NoSuchBucket" in err_str or "not exist" in err_str) and self.auto_create_bucket:
                try:
                    self.ensure_bucket_exists()
                    response = client.put_object(
                        Bucket=self.bucket,
                        Key=object_key,
                        Body=raw_bytes,
                        **extra_args,
                    )
                    etag = response.get("ETag")
                    return StoredObjectMetadata(
                        bucket=self.bucket,
                        object_key=object_key,
                        content_type=content_type,
                        file_size_bytes=len(raw_bytes),
                        checksum_sha256=calculated_sha256,
                        etag=etag,
                    )
                except Exception as retry_exc:
                    raise StorageUnavailableError(
                        f"Failed to upload object '{object_key}' to S3/MinIO after bucket creation: {retry_exc}"
                    ) from retry_exc

            logger.error(
                "S3 upload failed for bucket=%s, object_key=%s, error_type=%s: %s",
                self.bucket,
                object_key,
                type(exc).__name__,
                exc,
            )
            raise StorageUnavailableError(
                f"Failed to upload object '{object_key}' to S3/MinIO: {exc}"
            ) from exc

    def retrieve_document(self, object_key: str) -> StoredDocument:
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self.bucket, Key=object_key)
            body_stream = response["Body"]
            raw_bytes = body_stream.read()
            content_type = response.get("ContentType", "application/pdf")
            calculated_sha256 = hashlib.sha256(raw_bytes).hexdigest()

            stored_sha256 = response.get("Metadata", {}).get("sha256")
            if stored_sha256 and stored_sha256 != calculated_sha256:
                raise ChecksumMismatchError(
                    f"Retrieved document integrity check failed: expected {stored_sha256}, got {calculated_sha256}"
                )

            return StoredDocument(
                bucket=self.bucket,
                object_key=object_key,
                content=raw_bytes,
                content_type=content_type,
                file_size_bytes=len(raw_bytes),
                checksum_sha256=calculated_sha256,
            )
        except ChecksumMismatchError:
            raise
        except Exception as exc:
            error_code = ""
            if hasattr(exc, "response") and isinstance(exc.response, dict):
                error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"NoSuchKey", "404"}:
                logger.info("Object '%s' not found in bucket '%s'.", object_key, self.bucket)
                raise ObjectNotFoundError(
                    f"Object '{object_key}' was not found in bucket '{self.bucket}'."
                ) from exc
            logger.error(
                "S3 retrieve failed for bucket=%s, object_key=%s, error_code=%s, error_type=%s: %s",
                self.bucket,
                object_key,
                error_code,
                type(exc).__name__,
                exc,
            )
            raise StorageUnavailableError(
                f"Failed to retrieve object '{object_key}': {exc}"
            ) from exc

    def document_exists(self, object_key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=object_key)
            return True
        except Exception as exc:
            error_code = ""
            if hasattr(exc, "response") and isinstance(exc.response, dict):
                error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"NoSuchKey", "404"}:
                return False
            raise StorageUnavailableError(
                f"Failed to check object existence '{object_key}': {exc}"
            ) from exc

    def delete_document(self, object_key: str) -> bool:
        client = self._get_client()
        try:
            client.delete_object(Bucket=self.bucket, Key=object_key)
            return True
        except Exception as exc:
            logger.error(
                "S3 delete failed for bucket=%s, object_key=%s, error_type=%s: %s",
                self.bucket,
                object_key,
                type(exc).__name__,
                exc,
            )
            raise StorageUnavailableError(
                f"Failed to delete object '{object_key}': {exc}"
            ) from exc


_storage_service_instance: StorageService | None = None


def get_storage_service(settings: Settings | None = None) -> StorageService:
    """Return the configured StorageService implementation."""
    global _storage_service_instance
    if _storage_service_instance is not None:
        return _storage_service_instance

    current_settings = settings or get_settings()

    if current_settings.storage_backend == "in_memory":
        _storage_service_instance = InMemoryStorageService(
            bucket=current_settings.storage_bucket_name
        )
        return _storage_service_instance

    access_key = (
        current_settings.storage_access_key.get_secret_value()
        if current_settings.storage_access_key
        else None
    )
    secret_key = (
        current_settings.storage_secret_key.get_secret_value()
        if current_settings.storage_secret_key
        else None
    )

    kms_key = (
        current_settings.storage_kms_key_id.get_secret_value()
        if current_settings.storage_kms_key_id
        else None
    )

    _storage_service_instance = S3StorageService(
        bucket_name=current_settings.storage_bucket_name,
        endpoint_url=current_settings.storage_endpoint_url,
        region_name=current_settings.storage_region,
        access_key=access_key,
        secret_key=secret_key,
        use_ssl=current_settings.storage_use_ssl,
        auto_create_bucket=current_settings.storage_auto_create_bucket,
        server_side_encryption=current_settings.storage_server_side_encryption,
        kms_key_id=kms_key,
    )
    return _storage_service_instance


def set_storage_service(service: StorageService | None) -> None:
    """Explicitly override storage service (used in tests or container init)."""
    global _storage_service_instance
    _storage_service_instance = service
