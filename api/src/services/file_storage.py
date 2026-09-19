"""
File storage service for attachments and exports.

Handles object storage operations including:
- Presigned/SAS upload URLs
- Presigned/SAS download URLs
- File deletion
- MIME type detection

Supports S3-compatible storage and Azure Blob Storage.
"""

import hashlib
import logging
import mimetypes
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl
from uuid import UUID

from src.config import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


class FileStorageService:
    """Service for object storage operations."""

    def __init__(self, settings: Settings | None = None):
        """
        Initialize file storage service.

        Args:
            settings: Application settings with storage configuration.
                     Uses get_settings() if not provided.
        """
        self.settings = settings or get_settings()
        self.backend = getattr(self.settings, "storage_backend", "s3")

    @asynccontextmanager
    async def get_client(self, endpoint_url: str | None = None) -> "AsyncGenerator[Any, None]":
        """
        Get S3 client context manager.

        Args:
            endpoint_url: Override the endpoint this client talks to.
                Defaults to the internal ``s3_endpoint``. Presigned-URL
                flows pass the public endpoint (see ``_signing_endpoint``).

        Yields:
            Async S3 client from aiobotocore, pinned to SigV4
            (S3-compatible stores such as Garage reject SigV2).

        Raises:
            RuntimeError: If S3 storage is not configured
        """
        if not self.settings.s3_configured:
            raise RuntimeError(
                "S3 storage not configured. "
                "Set BIFROST_DOCS_S3_ACCESS_KEY and BIFROST_DOCS_S3_SECRET_KEY environment variables."
            )

        from aiobotocore.config import AioConfig
        from aiobotocore.session import get_session

        session = get_session()
        async with session.create_client(
            "s3",
            endpoint_url=endpoint_url or self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
            config=AioConfig(signature_version="s3v4"),
        ) as client:
            yield client

    def _require_azure_blob_configured(self) -> None:
        if not self.settings.azure_blob_configured:
            raise RuntimeError(
                "Azure Blob storage not configured. Set BIFROST_DOCS_AZURE_STORAGE_CONNECTION_STRING "
                "or BIFROST_DOCS_AZURE_STORAGE_ACCOUNT_URL and BIFROST_DOCS_AZURE_STORAGE_ACCOUNT_KEY."
            )

    def _get_blob_service_client(self) -> Any:
        """Create an Azure Blob service client from configured credentials."""
        self._require_azure_blob_configured()

        from azure.storage.blob import BlobServiceClient

        if self.settings.azure_storage_connection_string:
            return BlobServiceClient.from_connection_string(
                self.settings.azure_storage_connection_string
            )

        if not self.settings.azure_storage_account_url:
            raise RuntimeError("Azure Blob storage account URL is required")

        return BlobServiceClient(
            account_url=self.settings.azure_storage_account_url,
            credential=self.settings.azure_storage_account_key,
        )

    def _get_azure_account_name_and_key(self) -> tuple[str, str]:
        """Get the Azure Storage account name and key for SAS generation."""
        if self.settings.azure_storage_connection_string:
            parts = dict(parse_qsl(self.settings.azure_storage_connection_string.replace(";", "&")))
            account_name = parts.get("AccountName")
            account_key = parts.get("AccountKey")
            if account_name and account_key:
                return account_name, account_key

        if self.settings.azure_storage_account_url and self.settings.azure_storage_account_key:
            account_name = self.settings.azure_storage_account_url.removeprefix("https://").split(
                ".", 1
            )[0]
            return account_name, self.settings.azure_storage_account_key

        raise RuntimeError("Azure Blob SAS generation requires a storage account key")

    def _generate_blob_sas_url(
        self,
        blob_name: str,
        expires_in: int,
        permission: str,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> str:
        """Generate an Azure Blob SAS URL for direct browser access."""
        self._require_azure_blob_configured()

        from datetime import UTC, datetime, timedelta

        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        service = self._get_blob_service_client()
        account_name, account_key = self._get_azure_account_name_and_key()
        container_name = self.settings.azure_blob_container
        blob_client = service.get_blob_client(container=container_name, blob=blob_name)

        permissions = BlobSasPermissions(
            read="r" in permission,
            write="w" in permission,
            create="w" in permission,
        )
        kwargs: dict[str, Any] = {
            "account_name": account_name,
            "container_name": container_name,
            "blob_name": blob_name,
            "permission": permissions,
            "expiry": datetime.now(UTC) + timedelta(seconds=expires_in),
            "account_key": account_key,
        }

        if content_type:
            kwargs["content_type"] = content_type
        if filename:
            kwargs["content_disposition"] = f'attachment; filename="{filename}"'

        sas_token = generate_blob_sas(**kwargs)
        return f"{blob_client.url}?{sas_token}"

    @staticmethod
    def compute_hash(content: bytes) -> str:
        """
        Compute SHA-256 hash of content.

        Args:
            content: File content bytes

        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def guess_content_type(filename: str) -> str:
        """
        Guess content type from filename.

        Args:
            filename: File name with extension

        Returns:
            MIME type string (defaults to 'application/octet-stream' if unknown)
        """
        content_type, _ = mimetypes.guess_type(filename)
        return content_type or "application/octet-stream"

    def _signing_endpoint(self) -> str:
        """
        Endpoint presigned URLs are signed against.

        Must be the host requesters actually use (public endpoint when
        configured): SigV4 binds the Host header, so signing with the
        internal endpoint and rewriting the host afterwards invalidates
        the signature. Server-side calls keep using ``s3_endpoint``.

        Returns:
            Public endpoint URL if configured, else the S3 endpoint.
        """
        return self.settings.s3_public_endpoint or self.settings.s3_endpoint

    def generate_s3_key(
        self,
        organization_id: UUID,
        entity_type: str,
        entity_id: UUID,
        attachment_id: UUID,
        filename: str,
    ) -> str:
        """
        Generate a unique S3 key for an attachment.

        Format: {org_id}/{entity_type}/{entity_id}/{attachment_id}/{filename}

        Args:
            organization_id: Organization UUID
            entity_type: Type of entity (password, document, etc.)
            entity_id: Entity UUID
            attachment_id: Attachment UUID
            filename: Original filename

        Returns:
            S3 key path
        """
        return f"{organization_id}/{entity_type}/{entity_id}/{attachment_id}/{filename}"

    async def generate_upload_url(
        self,
        s3_key: str,
        content_type: str,
        expires_in: int | None = None,
    ) -> str:
        """
        Generate a presigned PUT URL for direct S3 upload.

        Args:
            s3_key: Target path in S3
            content_type: MIME type of the file being uploaded
            expires_in: URL expiration time in seconds (default from settings)

        Returns:
            Presigned PUT URL for direct browser upload
        """
        if self.backend == "azure_blob":
            if expires_in is None:
                expires_in = self.settings.azure_blob_sas_expiry
            return self._generate_blob_sas_url(
                s3_key,
                expires_in=expires_in,
                permission="w",
                content_type=content_type,
            )

        if expires_in is None:
            expires_in = self.settings.s3_presigned_url_expiry

        async with self.get_client(endpoint_url=self._signing_endpoint()) as s3:
            url: str = await s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.settings.s3_bucket,
                    "Key": s3_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        return url

    async def generate_download_url(
        self,
        s3_key: str,
        filename: str | None = None,
        expires_in: int | None = None,
    ) -> str:
        """
        Generate a presigned GET URL for file download.

        Args:
            s3_key: File path in S3
            filename: Original filename for Content-Disposition header
            expires_in: URL expiration time in seconds (default from settings)

        Returns:
            Presigned GET URL for download
        """
        if self.backend == "azure_blob":
            if expires_in is None:
                expires_in = self.settings.azure_blob_download_sas_expiry
            return self._generate_blob_sas_url(
                s3_key,
                expires_in=expires_in,
                permission="r",
                filename=filename,
            )

        if expires_in is None:
            expires_in = self.settings.s3_download_url_expiry

        params: dict[str, Any] = {
            "Bucket": self.settings.s3_bucket,
            "Key": s3_key,
        }

        # Add Content-Disposition header for proper filename on download
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

        async with self.get_client(endpoint_url=self._signing_endpoint()) as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
        return url

    async def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3.

        Args:
            s3_key: File path in S3

        Returns:
            True if deletion was successful
        """
        try:
            if self.backend == "azure_blob":
                service = self._get_blob_service_client()
                blob = service.get_blob_client(
                    container=self.settings.azure_blob_container,
                    blob=s3_key,
                )
                blob.delete_blob(delete_snapshots="include")
                logger.info(f"Deleted file from Azure Blob: {s3_key}")
                return True

            async with self.get_client() as s3:
                await s3.delete_object(
                    Bucket=self.settings.s3_bucket,
                    Key=s3_key,
                )
            logger.info(f"Deleted file from S3: {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file from S3: {s3_key}, error: {e}")
            return False

    async def upload_file(
        self,
        s3_key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> bool:
        """
        Upload file content directly to S3.

        Args:
            s3_key: Target path in S3
            content: File content as bytes
            content_type: MIME type of the content

        Returns:
            True if upload was successful
        """
        try:
            if self.backend == "azure_blob":
                service = self._get_blob_service_client()
                blob = service.get_blob_client(
                    container=self.settings.azure_blob_container,
                    blob=s3_key,
                )
                from azure.storage.blob import ContentSettings

                blob.upload_blob(
                    content,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type),
                )
                logger.info(f"Uploaded file to Azure Blob: {s3_key} ({len(content)} bytes)")
                return True

            async with self.get_client() as s3:
                await s3.put_object(
                    Bucket=self.settings.s3_bucket,
                    Key=s3_key,
                    Body=content,
                    ContentType=content_type,
                )
            logger.info(f"Uploaded file to S3: {s3_key} ({len(content)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Failed to upload file to S3: {s3_key}, error: {e}")
            return False

    async def file_exists(self, s3_key: str) -> bool:
        """
        Check if a file exists in S3.

        Args:
            s3_key: File path in S3

        Returns:
            True if file exists
        """
        try:
            if self.backend == "azure_blob":
                service = self._get_blob_service_client()
                blob = service.get_blob_client(
                    container=self.settings.azure_blob_container,
                    blob=s3_key,
                )
                return blob.exists()

            async with self.get_client() as s3:
                await s3.head_object(
                    Bucket=self.settings.s3_bucket,
                    Key=s3_key,
                )
            return True
        except Exception:
            return False

    async def ensure_bucket_exists(self) -> bool:
        """
        Ensure the configured bucket exists, creating it if necessary.

        Useful for development/testing with MinIO.

        Returns:
            True if bucket exists or was created successfully
        """
        try:
            if self.backend == "azure_blob":
                service = self._get_blob_service_client()
                container = service.get_container_client(self.settings.azure_blob_container)
                if not container.exists():
                    container.create_container()
                    logger.info(
                        f"Created Azure Blob container: {self.settings.azure_blob_container}"
                    )
                return True

            async with self.get_client() as s3:
                try:
                    await s3.head_bucket(Bucket=self.settings.s3_bucket)
                    return True
                except Exception:
                    # Bucket doesn't exist, create it
                    await s3.create_bucket(Bucket=self.settings.s3_bucket)
                    logger.info(f"Created S3 bucket: {self.settings.s3_bucket}")
                    return True
        except Exception as e:
            logger.error(f"Failed to ensure bucket exists: {e}")
            return False


# Module-level singleton for convenience
_file_storage_service: FileStorageService | None = None


def get_file_storage_service() -> FileStorageService:
    """
    Get the file storage service singleton.

    Returns:
        FileStorageService instance
    """
    global _file_storage_service
    if _file_storage_service is None:
        _file_storage_service = FileStorageService()
    return _file_storage_service


def reset_file_storage_service() -> None:
    """Reset the file storage service (for testing)."""
    global _file_storage_service
    _file_storage_service = None
