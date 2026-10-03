"""
Integration tests for show_disabled parameter across endpoints.

Tests that the show_disabled query parameter is correctly translated into
the is_enabled repository filter for list and search endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.auth import UserPrincipal, get_current_active_user
from src.main import app
from src.models.enums import UserRole


@pytest_asyncio.fixture
async def client():
    """Create an async HTTP client for testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_user():
    """Create a mock authenticated user principal."""
    return UserPrincipal(
        user_id=uuid4(),
        email="test@example.com",
        name="Test User",
        role=UserRole.CONTRIBUTOR,
        is_active=True,
        is_verified=True,
    )


@pytest.fixture
def authenticated(mock_user):
    """Override authentication with the mock user for the duration of a test."""
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    yield mock_user
    app.dependency_overrides.pop(get_current_active_user, None)


def _mock_repo(**stubs):
    """Build an AsyncMock repository with the given stubbed methods."""
    repo = AsyncMock()
    for name, value in stubs.items():
        setattr(repo, name, AsyncMock(return_value=value))
    return repo


@pytest.mark.integration
class TestShowDisabledConfigurations:
    """Tests for show_disabled parameter on configurations endpoint."""

    async def test_list_configurations_show_disabled_false(
        self, client: AsyncClient, authenticated
    ):
        """show_disabled=false passes is_enabled=True to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.configurations.ConfigurationRepository", return_value=repo):
            response = await client.get(
                f"/api/organizations/{org_id}/configurations?show_disabled=false"
            )

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            configuration_type_id=None,
            configuration_status_id=None,
            search=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=True,
        )

    async def test_list_configurations_show_disabled_true(self, client: AsyncClient, authenticated):
        """show_disabled=true passes is_enabled=None (show all) to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.configurations.ConfigurationRepository", return_value=repo):
            response = await client.get(
                f"/api/organizations/{org_id}/configurations?show_disabled=true"
            )

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            configuration_type_id=None,
            configuration_status_id=None,
            search=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=None,
        )

    async def test_list_configurations_default_show_disabled(
        self, client: AsyncClient, authenticated
    ):
        """Omitting show_disabled defaults to enabled-only (is_enabled=True)."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.configurations.ConfigurationRepository", return_value=repo):
            response = await client.get(f"/api/organizations/{org_id}/configurations")

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            configuration_type_id=None,
            configuration_status_id=None,
            search=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=True,
        )


@pytest.mark.integration
class TestShowDisabledLocations:
    """Tests for show_disabled parameter on locations endpoint."""

    async def test_list_locations_show_disabled_false(self, client: AsyncClient, authenticated):
        """show_disabled=false passes is_enabled=True to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.locations.LocationRepository", return_value=repo):
            response = await client.get(
                f"/api/organizations/{org_id}/locations?show_disabled=false"
            )

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            search=None,
            region=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=True,
        )

    async def test_list_locations_show_disabled_true(self, client: AsyncClient, authenticated):
        """show_disabled=true passes is_enabled=None (show all) to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.locations.LocationRepository", return_value=repo):
            response = await client.get(f"/api/organizations/{org_id}/locations?show_disabled=true")

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            search=None,
            region=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=None,
        )


@pytest.mark.integration
class TestShowDisabledCustomAssets:
    """Tests for show_disabled parameter on custom assets endpoint."""

    def _mock_asset_type(self):
        asset_type = MagicMock()
        asset_type.id = uuid4()
        asset_type.fields = [{"key": "title", "name": "Title", "type": "text"}]
        asset_type.display_field_key = "title"
        return asset_type

    async def test_list_custom_assets_show_disabled_false(self, client: AsyncClient, authenticated):
        """show_disabled=false passes is_enabled=True to the repository."""
        org_id = uuid4()
        type_id = uuid4()
        repo = _mock_repo(get_paginated_by_type_and_org=([], 0))

        with (
            patch("src.routers.custom_assets.CustomAssetRepository", return_value=repo),
            patch(
                "src.routers.custom_assets._get_asset_type",
                new=AsyncMock(return_value=self._mock_asset_type()),
            ),
        ):
            response = await client.get(
                f"/api/organizations/{org_id}/custom-asset-types/{type_id}/assets"
                "?show_disabled=false"
            )

        assert response.status_code == 200
        repo.get_paginated_by_type_and_org.assert_called_once_with(
            type_id,
            org_id,
            search=None,
            search_field_key="title",
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=True,
        )

    async def test_list_custom_assets_show_disabled_true(self, client: AsyncClient, authenticated):
        """show_disabled=true passes is_enabled=None (show all) to the repository."""
        org_id = uuid4()
        type_id = uuid4()
        repo = _mock_repo(get_paginated_by_type_and_org=([], 0))

        with (
            patch("src.routers.custom_assets.CustomAssetRepository", return_value=repo),
            patch(
                "src.routers.custom_assets._get_asset_type",
                new=AsyncMock(return_value=self._mock_asset_type()),
            ),
        ):
            response = await client.get(
                f"/api/organizations/{org_id}/custom-asset-types/{type_id}/assets"
                "?show_disabled=true"
            )

        assert response.status_code == 200
        repo.get_paginated_by_type_and_org.assert_called_once_with(
            type_id,
            org_id,
            search=None,
            search_field_key="title",
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=None,
        )


@pytest.mark.integration
class TestShowDisabledPasswords:
    """Tests for show_disabled parameter on passwords endpoint."""

    async def test_list_passwords_show_disabled_false(self, client: AsyncClient, authenticated):
        """show_disabled=false passes is_enabled=True to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.passwords.PasswordRepository", return_value=repo):
            response = await client.get(
                f"/api/organizations/{org_id}/passwords?show_disabled=false"
            )

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            search=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=True,
            has_totp=None,
        )

    async def test_list_passwords_show_disabled_true(self, client: AsyncClient, authenticated):
        """show_disabled=true passes is_enabled=None (show all) to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.passwords.PasswordRepository", return_value=repo):
            response = await client.get(f"/api/organizations/{org_id}/passwords?show_disabled=true")

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            search=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=None,
            has_totp=None,
        )


@pytest.mark.integration
class TestShowDisabledDocuments:
    """Tests for show_disabled parameter on documents endpoint."""

    async def test_list_documents_show_disabled_false(self, client: AsyncClient, authenticated):
        """show_disabled=false passes is_enabled=True to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.documents.DocumentRepository", return_value=repo):
            response = await client.get(
                f"/api/organizations/{org_id}/documents?show_disabled=false"
            )

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            path=None,
            search=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=True,
        )

    async def test_list_documents_show_disabled_true(self, client: AsyncClient, authenticated):
        """show_disabled=true passes is_enabled=None (show all) to the repository."""
        org_id = uuid4()
        repo = _mock_repo(get_paginated_by_org=([], 0))

        with patch("src.routers.documents.DocumentRepository", return_value=repo):
            response = await client.get(f"/api/organizations/{org_id}/documents?show_disabled=true")

        assert response.status_code == 200
        repo.get_paginated_by_org.assert_called_once_with(
            org_id,
            path=None,
            search=None,
            sort_by=None,
            sort_dir="asc",
            limit=100,
            offset=0,
            is_enabled=None,
        )


@pytest.mark.integration
class TestShowDisabledOrganizations:
    """Tests for show_disabled parameter on organizations endpoint."""

    async def test_list_organizations_show_disabled_false(self, client: AsyncClient, authenticated):
        """show_disabled=false passes is_enabled=True to the repository."""
        repo = _mock_repo(get_all=[])

        with patch("src.routers.organizations.OrganizationRepository", return_value=repo):
            response = await client.get("/api/organizations?show_disabled=false")

        assert response.status_code == 200
        repo.get_all.assert_called_once_with(is_enabled=True)

    async def test_list_organizations_show_disabled_true(self, client: AsyncClient, authenticated):
        """show_disabled=true passes is_enabled=None (show all) to the repository."""
        repo = _mock_repo(get_all=[])

        with patch("src.routers.organizations.OrganizationRepository", return_value=repo):
            response = await client.get("/api/organizations?show_disabled=true")

        assert response.status_code == 200
        repo.get_all.assert_called_once_with(is_enabled=None)


@pytest.mark.integration
class TestShowDisabledSearch:
    """Tests for show_disabled parameter on search endpoint."""

    async def test_search_show_disabled_false(self, client: AsyncClient, authenticated):
        """show_disabled=false lists only enabled organizations for search scope."""
        repo = _mock_repo(get_all=[])

        with patch("src.routers.search.OrganizationRepository", return_value=repo):
            response = await client.get("/api/search", params={"q": "test"})

        assert response.status_code == 200
        repo.get_all.assert_called_once_with(is_enabled=True)
        assert response.json()["results"] == []

    async def test_search_show_disabled_true(self, client: AsyncClient, authenticated):
        """show_disabled=true includes disabled organizations in search scope."""
        repo = _mock_repo(get_all=[])

        with patch("src.routers.search.OrganizationRepository", return_value=repo):
            response = await client.get(
                "/api/search", params={"q": "test", "show_disabled": "true"}
            )

        assert response.status_code == 200
        repo.get_all.assert_called_once_with(is_enabled=None)
        assert response.json()["results"] == []
