"""
Integration tests for locations endpoints.

Tests the complete CRUD lifecycle for locations including:
- Organization membership verification
- Organization isolation (can't access other org's locations)
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.auth import UserPrincipal, get_current_active_user
from src.main import app
from src.models.enums import UserRole


@contextmanager
def _patched_side_effects():
    """Patch audit + search-index side effects so tests run without live infra."""
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    with (
        patch(
            "src.routers.locations.get_audit_service",
            return_value=audit_service,
        ),
        patch("src.routers.locations.index_entity_for_search", new=AsyncMock()),
        patch("src.routers.locations.remove_entity_from_search", new=AsyncMock()),
    ):
        yield


def create_mock_user(user_id=None, role=None):
    """Create a mock UserPrincipal."""
    return UserPrincipal(
        user_id=user_id or uuid4(),
        email="test@example.com",
        name="Test User",
        role=role or UserRole.CONTRIBUTOR,
        is_active=True,
        is_verified=True,
    )


@pytest_asyncio.fixture
async def client():
    """Create an async HTTP client for testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def authenticated_client():
    """Create an authenticated async HTTP client for testing."""
    mock_user = create_mock_user()

    # Override the auth dependency
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, mock_user

    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
def mock_location():
    """Create a mock location entity."""
    location = MagicMock()
    location.id = uuid4()
    location.organization_id = uuid4()
    location.name = "Test Location"
    location.notes = "Some notes"
    location.metadata_ = {}
    location.sync_metadata = None
    location.is_enabled = True
    location.created_at = datetime.now(UTC)
    location.updated_at = datetime.now(UTC)
    location.address_1 = None
    location.address_2 = None
    location.city = None
    location.region = None
    location.postal_code = None
    location.country = None
    location.phone = None
    location.updated_by_user_id = None
    location.updated_by_user = None
    return location


@pytest.mark.integration
class TestLocationsEndpointAuth:
    """Tests for locations endpoint authentication."""

    async def test_unauthenticated_list_locations(self, client: AsyncClient):
        """Test that listing locations requires authentication."""
        org_id = uuid4()
        response = await client.get(f"/api/organizations/{org_id}/locations")
        assert response.status_code == 401

    async def test_unauthenticated_create_location(self, client: AsyncClient):
        """Test that creating locations requires authentication."""
        org_id = uuid4()
        response = await client.post(
            f"/api/organizations/{org_id}/locations", json={"name": "Test Location"}
        )
        assert response.status_code == 401

    async def test_unauthenticated_get_location(self, client: AsyncClient):
        """Test that getting a location requires authentication."""
        org_id = uuid4()
        location_id = uuid4()
        response = await client.get(f"/api/organizations/{org_id}/locations/{location_id}")
        assert response.status_code == 401

    async def test_unauthenticated_update_location(self, client: AsyncClient):
        """Test that updating a location requires authentication."""
        org_id = uuid4()
        location_id = uuid4()
        response = await client.put(
            f"/api/organizations/{org_id}/locations/{location_id}", json={"name": "Updated Name"}
        )
        assert response.status_code == 401

    async def test_unauthenticated_delete_location(self, client: AsyncClient):
        """Test that deleting a location requires authentication."""
        org_id = uuid4()
        location_id = uuid4()
        response = await client.delete(f"/api/organizations/{org_id}/locations/{location_id}")
        assert response.status_code == 401


@pytest.mark.integration
class TestLocationsOrganizationAccess:
    """Tests for organization access (ADR-001: orgs are partitions, not auth boundaries)."""

    async def test_list_locations_cross_org(self, authenticated_client, mock_location):
        """Test that users can list locations from any organization."""
        client, mock_user = authenticated_client
        org_id = uuid4()  # Different org than the user's

        mock_location_repo = AsyncMock()
        mock_location_repo.get_paginated_by_org = AsyncMock(return_value=([mock_location], 1))

        with patch("src.routers.locations.LocationRepository", return_value=mock_location_repo):
            response = await client.get(f"/api/organizations/{org_id}/locations")

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_create_location_cross_org(self, authenticated_client, mock_location):
        """Test that users can create locations in any organization."""
        client, mock_user = authenticated_client
        org_id = uuid4()  # Different org than the user's

        mock_location_repo = AsyncMock()
        mock_location_repo.create = AsyncMock(return_value=mock_location)

        with (
            patch(
                "src.routers.locations.LocationRepository",
                return_value=mock_location_repo,
            ),
            _patched_side_effects(),
        ):
            response = await client.post(
                f"/api/organizations/{org_id}/locations", json={"name": "Test Location"}
            )

        assert response.status_code == 201
        assert response.json()["name"] == "Test Location"


@pytest.mark.integration
class TestLocationsCRUD:
    """Tests for locations CRUD operations with mocked dependencies."""

    async def test_list_locations_success(self, authenticated_client, mock_location):
        """Test successful listing of locations."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id

        mock_location_repo = AsyncMock()
        mock_location_repo.get_paginated_by_org = AsyncMock(return_value=([mock_location], 1))

        with patch("src.routers.locations.LocationRepository", return_value=mock_location_repo):
            response = await client.get(f"/api/organizations/{org_id}/locations")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Test Location"
        assert data["items"][0]["notes"] == "Some notes"

    async def test_create_location_success(self, authenticated_client, mock_location):
        """Test successful creation of a location."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id

        mock_location_repo = AsyncMock()
        mock_location_repo.create = AsyncMock(return_value=mock_location)

        with (
            patch(
                "src.routers.locations.LocationRepository",
                return_value=mock_location_repo,
            ),
            _patched_side_effects(),
        ):
            response = await client.post(
                f"/api/organizations/{org_id}/locations",
                json={"name": "Test Location", "notes": "Some notes"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Location"
        assert data["notes"] == "Some notes"

    async def test_get_location_success(self, authenticated_client, mock_location):
        """Test successful retrieval of a location."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id
        location_id = mock_location.id

        mock_location_repo = AsyncMock()
        mock_location_repo.get_by_id_and_organization = AsyncMock(return_value=mock_location)

        with (
            patch(
                "src.routers.locations.LocationRepository",
                return_value=mock_location_repo,
            ),
            _patched_side_effects(),
        ):
            response = await client.get(f"/api/organizations/{org_id}/locations/{location_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Location"

    async def test_get_location_not_found(self, authenticated_client, mock_location):
        """Test 404 when location doesn't exist."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id
        location_id = uuid4()

        mock_location_repo = AsyncMock()
        mock_location_repo.get_by_id_and_organization = AsyncMock(return_value=None)

        from unittest.mock import patch

        with patch("src.routers.locations.LocationRepository", return_value=mock_location_repo):
            response = await client.get(f"/api/organizations/{org_id}/locations/{location_id}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Location not found"

    async def test_update_location_success(self, authenticated_client, mock_location):
        """Test successful update of a location."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id
        location_id = mock_location.id

        # Create a mock location that returns the updated values
        updated_location = MagicMock()
        updated_location.id = location_id
        updated_location.organization_id = org_id
        updated_location.name = "Updated Location"
        updated_location.notes = "Updated notes"
        updated_location.metadata_ = {}
        updated_location.sync_metadata = None
        updated_location.is_enabled = True
        updated_location.created_at = mock_location.created_at
        updated_location.updated_at = mock_location.updated_at
        updated_location.address_1 = None
        updated_location.address_2 = None
        updated_location.city = None
        updated_location.region = None
        updated_location.postal_code = None
        updated_location.country = None
        updated_location.phone = None
        updated_location.updated_by_user_id = None
        updated_location.updated_by_user = None

        mock_location_repo = AsyncMock()
        mock_location_repo.get_by_id_and_organization = AsyncMock(return_value=mock_location)
        mock_location_repo.update = AsyncMock(return_value=updated_location)

        with (
            patch(
                "src.routers.locations.LocationRepository",
                return_value=mock_location_repo,
            ),
            _patched_side_effects(),
        ):
            response = await client.put(
                f"/api/organizations/{org_id}/locations/{location_id}",
                json={"name": "Updated Location", "notes": "Updated notes"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Location"
        assert data["notes"] == "Updated notes"

    async def test_update_location_not_found(self, authenticated_client, mock_location):
        """Test 404 when updating non-existent location."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id
        location_id = uuid4()

        mock_location_repo = AsyncMock()
        mock_location_repo.get_by_id_and_organization = AsyncMock(return_value=None)

        from unittest.mock import patch

        with patch("src.routers.locations.LocationRepository", return_value=mock_location_repo):
            response = await client.put(
                f"/api/organizations/{org_id}/locations/{location_id}",
                json={"name": "Updated Location"},
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Location not found"

    async def test_delete_location_success(self, authenticated_client, mock_location):
        """Test successful deletion of a location."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id
        location_id = mock_location.id

        mock_location_repo = AsyncMock()
        mock_location_repo.get_by_id_and_organization = AsyncMock(return_value=mock_location)
        mock_location_repo.delete = AsyncMock()

        with (
            patch(
                "src.routers.locations.LocationRepository",
                return_value=mock_location_repo,
            ),
            _patched_side_effects(),
        ):
            response = await client.delete(f"/api/organizations/{org_id}/locations/{location_id}")

        assert response.status_code == 204

    async def test_delete_location_not_found(self, authenticated_client, mock_location):
        """Test 404 when deleting non-existent location."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id
        location_id = uuid4()

        mock_location_repo = AsyncMock()
        mock_location_repo.get_by_id_and_organization = AsyncMock(return_value=None)

        from unittest.mock import patch

        with patch("src.routers.locations.LocationRepository", return_value=mock_location_repo):
            response = await client.delete(f"/api/organizations/{org_id}/locations/{location_id}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Location not found"


@pytest.mark.integration
class TestLocationValidation:
    """Tests for location input validation."""

    async def test_create_location_empty_name(self, authenticated_client, mock_location):
        """Test that creating a location with empty name fails."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id

        response = await client.post(f"/api/organizations/{org_id}/locations", json={"name": ""})

        assert response.status_code == 422

    async def test_create_location_missing_name(self, authenticated_client, mock_location):
        """Test that creating a location without name fails."""
        client, mock_user = authenticated_client
        org_id = mock_location.organization_id

        response = await client.post(f"/api/organizations/{org_id}/locations", json={})

        assert response.status_code == 422
