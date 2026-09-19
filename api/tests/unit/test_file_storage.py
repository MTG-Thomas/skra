"""
Unit tests for file storage service.

Tests S3 URL generation and utility functions with mocked S3 client.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.file_storage import FileStorageService, reset_file_storage_service


@pytest.fixture(autouse=True)
def reset_service():
    """Reset file storage service singleton before each test."""
    reset_file_storage_service()
    yield
    reset_file_storage_service()


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.s3_configured = True
    settings.s3_endpoint = "http://localhost:9000"
    settings.s3_public_endpoint = None  # Use internal endpoint for tests
    settings.s3_access_key = "test-access-key"
    settings.s3_secret_key = "test-secret-key"
    settings.s3_region = "us-east-1"
    settings.s3_bucket = "test-bucket"
    settings.s3_presigned_url_expiry = 600
    settings.s3_download_url_expiry = 3600
    settings.storage_backend = "s3"
    settings.storage_configured = True
    settings.azure_blob_configured = False
    settings.azure_storage_connection_string = None
    settings.azure_storage_account_url = None
    settings.azure_storage_account_key = None
    settings.azure_blob_container = "test-container"
    settings.azure_blob_sas_expiry = 600
    settings.azure_blob_download_sas_expiry = 3600
    return settings


@pytest.fixture
def file_storage_service(mock_settings):
    """Create file storage service with mock settings."""
    return FileStorageService(settings=mock_settings)


class TestFileStorageService:
    """Tests for FileStorageService."""

    def test_compute_hash(self):
        """Test SHA-256 hash computation."""
        content = b"Hello, World!"
        hash_result = FileStorageService.compute_hash(content)

        # SHA-256 hash should be 64 hex characters
        assert len(hash_result) == 64
        assert all(c in "0123456789abcdef" for c in hash_result)

        # Same content should produce same hash
        assert FileStorageService.compute_hash(content) == hash_result

        # Different content should produce different hash
        assert FileStorageService.compute_hash(b"Different") != hash_result

    def test_guess_content_type(self):
        """Test MIME type guessing."""
        # Common file types
        assert FileStorageService.guess_content_type("document.pdf") == "application/pdf"
        assert FileStorageService.guess_content_type("image.png") == "image/png"
        assert FileStorageService.guess_content_type("image.jpg") == "image/jpeg"
        assert FileStorageService.guess_content_type("data.json") == "application/json"
        assert FileStorageService.guess_content_type("script.js") in [
            "application/javascript",
            "text/javascript",
        ]
        assert FileStorageService.guess_content_type("style.css") == "text/css"
        assert FileStorageService.guess_content_type("page.html") == "text/html"

        # Unknown type should default to octet-stream
        assert FileStorageService.guess_content_type("file.unknown") == "application/octet-stream"

    def test_generate_s3_key(self, file_storage_service):
        """Test S3 key generation."""
        org_id = uuid4()
        entity_id = uuid4()
        attachment_id = uuid4()

        s3_key = file_storage_service.generate_s3_key(
            organization_id=org_id,
            entity_type="document",
            entity_id=entity_id,
            attachment_id=attachment_id,
            filename="test-file.pdf",
        )

        # Key should contain all components
        assert str(org_id) in s3_key
        assert "document" in s3_key
        assert str(entity_id) in s3_key
        assert str(attachment_id) in s3_key
        assert "test-file.pdf" in s3_key

        # Key should follow expected format
        expected = f"{org_id}/document/{entity_id}/{attachment_id}/test-file.pdf"
        assert s3_key == expected

    @pytest.mark.asyncio
    async def test_generate_upload_url(self, file_storage_service):
        """Test presigned upload URL generation."""
        with patch("aiobotocore.session.get_session") as mock_get_session:
            # Setup mock S3 client
            mock_s3_client = AsyncMock()
            mock_s3_client.generate_presigned_url = AsyncMock(
                return_value="https://s3.example.com/upload-url"
            )

            mock_session = MagicMock()
            mock_session.create_client = MagicMock()
            mock_session.create_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_s3_client
            )
            mock_session.create_client.return_value.__aexit__ = AsyncMock()

            mock_get_session.return_value = mock_session

            # Generate upload URL
            url = await file_storage_service.generate_upload_url(
                s3_key="test/key.pdf",
                content_type="application/pdf",
            )

            assert url == "https://s3.example.com/upload-url"

            # Verify S3 client was called correctly
            mock_s3_client.generate_presigned_url.assert_called_once_with(
                "put_object",
                Params={
                    "Bucket": "test-bucket",
                    "Key": "test/key.pdf",
                    "ContentType": "application/pdf",
                },
                ExpiresIn=600,
            )

    @pytest.mark.asyncio
    async def test_generate_download_url(self, file_storage_service):
        """Test presigned download URL generation."""
        with patch("aiobotocore.session.get_session") as mock_get_session:
            # Setup mock S3 client
            mock_s3_client = AsyncMock()
            mock_s3_client.generate_presigned_url = AsyncMock(
                return_value="https://s3.example.com/download-url"
            )

            mock_session = MagicMock()
            mock_session.create_client = MagicMock()
            mock_session.create_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_s3_client
            )
            mock_session.create_client.return_value.__aexit__ = AsyncMock()

            mock_get_session.return_value = mock_session

            # Generate download URL with filename
            url = await file_storage_service.generate_download_url(
                s3_key="test/key.pdf",
                filename="document.pdf",
            )

            assert url == "https://s3.example.com/download-url"

            # Verify S3 client was called with Content-Disposition
            mock_s3_client.generate_presigned_url.assert_called_once()
            call_args = mock_s3_client.generate_presigned_url.call_args
            assert call_args[0][0] == "get_object"
            assert call_args[1]["Params"]["Bucket"] == "test-bucket"
            assert call_args[1]["Params"]["Key"] == "test/key.pdf"
            assert 'filename="document.pdf"' in call_args[1]["Params"]["ResponseContentDisposition"]
            assert call_args[1]["ExpiresIn"] == 3600

    @pytest.mark.asyncio
    async def test_generate_download_url_without_filename(self, file_storage_service):
        """Test download URL generation without filename."""
        with patch("aiobotocore.session.get_session") as mock_get_session:
            mock_s3_client = AsyncMock()
            mock_s3_client.generate_presigned_url = AsyncMock(
                return_value="https://s3.example.com/download-url"
            )

            mock_session = MagicMock()
            mock_session.create_client = MagicMock()
            mock_session.create_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_s3_client
            )
            mock_session.create_client.return_value.__aexit__ = AsyncMock()

            mock_get_session.return_value = mock_session

            # Generate download URL without filename
            url = await file_storage_service.generate_download_url(
                s3_key="test/key.pdf",
            )

            assert url == "https://s3.example.com/download-url"

            # Verify no Content-Disposition header
            call_args = mock_s3_client.generate_presigned_url.call_args
            assert "ResponseContentDisposition" not in call_args[1]["Params"]

    @pytest.mark.asyncio
    async def test_delete_file(self, file_storage_service):
        """Test file deletion."""
        with patch("aiobotocore.session.get_session") as mock_get_session:
            mock_s3_client = AsyncMock()
            mock_s3_client.delete_object = AsyncMock()

            mock_session = MagicMock()
            mock_session.create_client = MagicMock()
            mock_session.create_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_s3_client
            )
            mock_session.create_client.return_value.__aexit__ = AsyncMock()

            mock_get_session.return_value = mock_session

            result = await file_storage_service.delete_file("test/key.pdf")

            assert result is True
            mock_s3_client.delete_object.assert_called_once_with(
                Bucket="test-bucket",
                Key="test/key.pdf",
            )

    @pytest.mark.asyncio
    async def test_delete_file_failure(self, file_storage_service):
        """Test file deletion failure handling."""
        # Patch the get_client method directly to raise an exception
        with patch.object(file_storage_service, "get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.side_effect = Exception("S3 error")
            mock_get_client.return_value = mock_context

            result = await file_storage_service.delete_file("test/key.pdf")

            assert result is False

    @pytest.mark.asyncio
    async def test_file_exists(self, file_storage_service):
        """Test file existence check."""
        with patch("aiobotocore.session.get_session") as mock_get_session:
            mock_s3_client = AsyncMock()
            mock_s3_client.head_object = AsyncMock()

            mock_session = MagicMock()
            mock_session.create_client = MagicMock()
            mock_session.create_client.return_value.__aenter__ = AsyncMock(
                return_value=mock_s3_client
            )
            mock_session.create_client.return_value.__aexit__ = AsyncMock()

            mock_get_session.return_value = mock_session

            result = await file_storage_service.file_exists("test/key.pdf")

            assert result is True
            mock_s3_client.head_object.assert_called_once_with(
                Bucket="test-bucket",
                Key="test/key.pdf",
            )

    @pytest.mark.asyncio
    async def test_file_not_exists(self, file_storage_service):
        """Test file existence check for non-existent file."""
        # Patch the get_client method directly to raise an exception
        with patch.object(file_storage_service, "get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.side_effect = Exception("NoSuchKey")
            mock_get_client.return_value = mock_context

            result = await file_storage_service.file_exists("test/nonexistent.pdf")

            assert result is False

    @pytest.mark.asyncio
    async def test_presigned_urls_use_sigv4_against_public_host(self, mock_settings):
        """Presigned URLs are SigV4 signed against the public endpoint host.

        Regression test for issue #94: the default client config produced
        SigV2 URLs (Garage 403), and rewriting the host after signing
        invalidated SigV4 (Host is a signed header). Offline: presigning
        is local HMAC, no network access.
        """
        from urllib.parse import parse_qs, urlsplit

        mock_settings.s3_endpoint = "http://minio:9000"
        mock_settings.s3_public_endpoint = "http://203.0.113.10:3900"
        service = FileStorageService(settings=mock_settings)

        upload_url = await service.generate_upload_url(
            s3_key="org/image.png",
            content_type="image/png",
        )
        download_url = await service.generate_download_url(
            s3_key="org/image.png",
        )

        for url in (upload_url, download_url):
            parts = urlsplit(url)
            assert parts.netloc == "203.0.113.10:3900"
            query = parse_qs(parts.query)
            assert query.get("X-Amz-Algorithm") == ["AWS4-HMAC-SHA256"]
            assert "AWSAccessKeyId" not in query
            assert "Signature" not in query

    def test_signing_endpoint_prefers_public(self, mock_settings):
        """Signing host is the public endpoint when configured."""
        mock_settings.s3_public_endpoint = "http://public.example.invalid:3900"
        service = FileStorageService(settings=mock_settings)
        assert service._signing_endpoint() == "http://public.example.invalid:3900"

    def test_signing_endpoint_falls_back_to_internal(self, mock_settings):
        """Without a public endpoint the internal endpoint is used."""
        mock_settings.s3_public_endpoint = None
        service = FileStorageService(settings=mock_settings)
        assert service._signing_endpoint() == "http://localhost:9000"


class TestFileStorageServiceNotConfigured:
    """Tests for FileStorageService when S3 is not configured."""

    @pytest.mark.asyncio
    async def test_get_client_raises_when_not_configured(self):
        """Test that get_client raises RuntimeError when S3 is not configured."""
        mock_settings = MagicMock()
        mock_settings.s3_configured = False

        service = FileStorageService(settings=mock_settings)

        with pytest.raises(RuntimeError, match="S3 storage not configured"):
            async with service.get_client():
                pass


@pytest.fixture
def mock_azure_settings():
    """Create mock Azure Blob settings for testing."""
    settings = MagicMock()
    settings.storage_backend = "azure_blob"
    settings.storage_configured = True
    settings.s3_configured = False
    settings.azure_blob_configured = True
    settings.azure_storage_connection_string = (
        "DefaultEndpointsProtocol=https;"
        "AccountName=testaccount;"
        "AccountKey=testkey;"
        "EndpointSuffix=core.windows.net"
    )
    settings.azure_storage_account_url = None
    settings.azure_storage_account_key = None
    settings.azure_blob_container = "test-container"
    settings.azure_blob_sas_expiry = 600
    settings.azure_blob_download_sas_expiry = 3600
    return settings


@pytest.fixture
def azure_storage_service(mock_azure_settings):
    """Create Azure Blob file storage service with mock settings."""
    return FileStorageService(settings=mock_azure_settings)


class TestAzureBlobFileStorageService:
    """Tests for Azure Blob storage backend."""

    def test_azure_account_name_and_key_from_connection_string(self, azure_storage_service):
        """Test Azure account credentials are parsed from connection string."""
        account_name, account_key = azure_storage_service._get_azure_account_name_and_key()

        assert account_name == "testaccount"
        assert account_key == "testkey"

    def test_azure_account_name_and_key_from_account_url(self, mock_azure_settings):
        """Test Azure account credentials are parsed from account URL and key."""
        mock_azure_settings.azure_storage_connection_string = None
        mock_azure_settings.azure_storage_account_url = "https://docsproof.blob.core.windows.net"
        mock_azure_settings.azure_storage_account_key = "account-key"
        service = FileStorageService(settings=mock_azure_settings)

        account_name, account_key = service._get_azure_account_name_and_key()

        assert account_name == "docsproof"
        assert account_key == "account-key"

    @pytest.mark.asyncio
    async def test_generate_azure_upload_url(self, azure_storage_service):
        """Test Azure Blob upload SAS URL generation."""
        mock_blob = MagicMock()
        mock_blob.url = "https://testaccount.blob.core.windows.net/test-container/test/key.pdf"
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob

        with (
            patch.object(
                azure_storage_service, "_get_blob_service_client", return_value=mock_service
            ),
            patch("azure.storage.blob.generate_blob_sas", return_value="sig=token") as mock_sas,
        ):
            url = await azure_storage_service.generate_upload_url(
                s3_key="test/key.pdf",
                content_type="application/pdf",
            )

        assert (
            url == "https://testaccount.blob.core.windows.net/test-container/test/key.pdf?sig=token"
        )
        mock_service.get_blob_client.assert_called_once_with(
            container="test-container",
            blob="test/key.pdf",
        )
        sas_kwargs = mock_sas.call_args.kwargs
        assert sas_kwargs["account_name"] == "testaccount"
        assert sas_kwargs["container_name"] == "test-container"
        assert sas_kwargs["blob_name"] == "test/key.pdf"
        assert sas_kwargs["account_key"] == "testkey"
        assert sas_kwargs["content_type"] == "application/pdf"
        assert sas_kwargs["permission"].write is True
        assert sas_kwargs["permission"].create is True

    @pytest.mark.asyncio
    async def test_generate_azure_download_url_with_filename(self, azure_storage_service):
        """Test Azure Blob download SAS URL generation."""
        mock_blob = MagicMock()
        mock_blob.url = "https://testaccount.blob.core.windows.net/test-container/test/key.pdf"
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob

        with (
            patch.object(
                azure_storage_service, "_get_blob_service_client", return_value=mock_service
            ),
            patch("azure.storage.blob.generate_blob_sas", return_value="sig=token") as mock_sas,
        ):
            url = await azure_storage_service.generate_download_url(
                s3_key="test/key.pdf",
                filename="document.pdf",
            )

        assert (
            url == "https://testaccount.blob.core.windows.net/test-container/test/key.pdf?sig=token"
        )
        sas_kwargs = mock_sas.call_args.kwargs
        assert sas_kwargs["permission"].read is True
        assert sas_kwargs["content_disposition"] == 'attachment; filename="document.pdf"'

    @pytest.mark.asyncio
    async def test_azure_delete_file(self, azure_storage_service):
        """Test Azure Blob deletion."""
        mock_blob = MagicMock()
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob

        with patch.object(
            azure_storage_service, "_get_blob_service_client", return_value=mock_service
        ):
            result = await azure_storage_service.delete_file("test/key.pdf")

        assert result is True
        mock_blob.delete_blob.assert_called_once_with(delete_snapshots="include")

    @pytest.mark.asyncio
    async def test_azure_file_exists(self, azure_storage_service):
        """Test Azure Blob existence check."""
        mock_blob = MagicMock()
        mock_blob.exists.return_value = True
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob

        with patch.object(
            azure_storage_service, "_get_blob_service_client", return_value=mock_service
        ):
            result = await azure_storage_service.file_exists("test/key.pdf")

        assert result is True

    @pytest.mark.asyncio
    async def test_azure_upload_file(self, azure_storage_service):
        """Test Azure Blob upload."""
        mock_blob = MagicMock()
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob

        with (
            patch.object(
                azure_storage_service, "_get_blob_service_client", return_value=mock_service
            ),
            patch("azure.storage.blob.ContentSettings") as mock_content_settings,
        ):
            result = await azure_storage_service.upload_file(
                s3_key="test/key.pdf",
                content=b"file-content",
                content_type="application/pdf",
            )

        assert result is True
        mock_content_settings.assert_called_once_with(content_type="application/pdf")
        mock_blob.upload_blob.assert_called_once_with(
            b"file-content",
            overwrite=True,
            content_settings=mock_content_settings.return_value,
        )

    @pytest.mark.asyncio
    async def test_azure_ensure_container_exists_creates_missing_container(
        self,
        azure_storage_service,
    ):
        """Test Azure Blob container creation."""
        mock_container = MagicMock()
        mock_container.exists.return_value = False
        mock_service = MagicMock()
        mock_service.get_container_client.return_value = mock_container

        with patch.object(
            azure_storage_service, "_get_blob_service_client", return_value=mock_service
        ):
            result = await azure_storage_service.ensure_bucket_exists()

        assert result is True
        mock_service.get_container_client.assert_called_once_with("test-container")
        mock_container.create_container.assert_called_once()

    def test_azure_blob_configuration_required(self, mock_azure_settings):
        """Test Azure Blob operations require complete configuration."""
        mock_azure_settings.azure_blob_configured = False
        service = FileStorageService(settings=mock_azure_settings)

        with pytest.raises(RuntimeError, match="Azure Blob storage not configured"):
            service._require_azure_blob_configured()

    def test_azure_sas_generation_requires_account_key(self, mock_azure_settings):
        """Test SAS generation requires account key material."""
        mock_azure_settings.azure_storage_connection_string = None
        mock_azure_settings.azure_storage_account_url = None
        mock_azure_settings.azure_storage_account_key = None
        service = FileStorageService(settings=mock_azure_settings)

        with pytest.raises(RuntimeError, match="Azure Blob SAS generation requires"):
            service._get_azure_account_name_and_key()
