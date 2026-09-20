"""
Integration tests for the dashboard_layout widget contract (Skra issue #39).

First backend slice only: typed optional ``widgets`` layout on
``PreferencesData``, stored via the existing JSONB upsert. Covers:
- PUT -> GET round trip for ``dashboard_layout``
- Legacy columns-only payloads (widgets defaults to None)
- Duplicate / invalid / oversize widget lists rejected with 422
- Per-user authorization (repository scoped to the authenticated user)
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
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def mock_user():
    """Create a mock authenticated user."""
    return UserPrincipal(
        user_id=uuid4(),
        email="dashboard@example.com",
        name="Dashboard User",
        role=UserRole.CONTRIBUTOR,
        is_active=True,
        is_verified=True,
    )


WIDGETS_PAYLOAD = {
    "columns": {"visible": [], "order": [], "widths": {}},
    "widgets": [
        {"id": "quick-stats", "visible": True},
        {"id": "recent-activity", "visible": False},
    ],
}


def _stored(payload):
    stored = MagicMock()
    stored.preferences = payload
    return stored


@pytest.mark.integration
class TestDashboardLayoutRoundTrip:
    """PUT -> GET round trip for the dashboard_layout entity type."""

    async def test_put_get_round_trip(self, client: AsyncClient, mock_user: UserPrincipal):
        """Widgets layout survives a PUT -> GET round trip unchanged."""
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with patch("src.routers.preferences.UserPreferencesRepository") as MockRepo:
                mock_repo = AsyncMock()
                captured: dict = {}

                async def _upsert(user_id, entity_type, preferences):
                    captured["user_id"] = user_id
                    captured["entity_type"] = entity_type
                    captured["preferences"] = preferences
                    return _stored(preferences)

                async def _get_by_user_and_entity(user_id, entity_type):
                    return _stored(captured["preferences"])

                mock_repo.upsert.side_effect = _upsert
                mock_repo.get_by_user_and_entity.side_effect = _get_by_user_and_entity
                MockRepo.return_value = mock_repo

                put_response = await client.put(
                    "/api/preferences/dashboard_layout",
                    json={"preferences": WIDGETS_PAYLOAD},
                )
                assert put_response.status_code == 200
                put_data = put_response.json()
                assert put_data["entity_type"] == "dashboard_layout"
                assert put_data["preferences"]["widgets"] == WIDGETS_PAYLOAD["widgets"]

                get_response = await client.get("/api/preferences/dashboard_layout")

            assert get_response.status_code == 200
            get_data = get_response.json()
            assert get_data["preferences"]["widgets"] == WIDGETS_PAYLOAD["widgets"]
            # List order is display order: preserved exactly.
            assert [w["id"] for w in get_data["preferences"]["widgets"]] == [
                "quick-stats",
                "recent-activity",
            ]
            # The upsert received the exact widgets payload for this user.
            mock_repo.upsert.assert_called_once()
            assert captured["user_id"] == mock_user.user_id
            assert captured["entity_type"] == "dashboard_layout"
            assert captured["preferences"]["widgets"] == WIDGETS_PAYLOAD["widgets"]
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    async def test_unknown_widget_ids_accepted(self, client: AsyncClient, mock_user: UserPrincipal):
        """Unknown widget IDs pass validation; the frontend registry ignores them."""
        payload = {
            "widgets": [{"id": "future-widget-not-yet-registered", "visible": True}],
        }
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with patch("src.routers.preferences.UserPreferencesRepository") as MockRepo:
                mock_repo = AsyncMock()
                mock_repo.upsert.return_value = _stored(payload)
                MockRepo.return_value = mock_repo

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as test_client:
                    response = await test_client.put(
                        "/api/preferences/dashboard_layout",
                        json={"preferences": payload},
                    )

            assert response.status_code == 200
            assert response.json()["preferences"]["widgets"] == payload["widgets"]
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.integration
class TestLegacyColumnsPreserved:
    """Legacy columns-only payloads keep working; widgets defaults to None."""

    async def test_columns_only_payload(self, client: AsyncClient, mock_user: UserPrincipal):
        """A columns-only PUT validates and echoes with widgets None."""
        payload = {"columns": {"visible": ["name"], "order": ["name"], "widths": {}}}
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with patch("src.routers.preferences.UserPreferencesRepository") as MockRepo:
                mock_repo = AsyncMock()
                mock_repo.upsert.return_value = _stored(payload)
                MockRepo.return_value = mock_repo

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as test_client:
                    response = await test_client.put(
                        "/api/preferences/passwords",
                        json={"preferences": payload},
                    )

            assert response.status_code == 200
            data = response.json()
            assert data["preferences"]["columns"]["visible"] == ["name"]
            assert data["preferences"]["widgets"] is None
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    async def test_legacy_stored_row_without_widgets_key(
        self, client: AsyncClient, mock_user: UserPrincipal
    ):
        """Stored rows predating the widgets field still deserialize."""
        legacy = {"columns": {"visible": ["name"], "order": ["name"], "widths": {}}}
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with patch("src.routers.preferences.UserPreferencesRepository") as MockRepo:
                mock_repo = AsyncMock()
                mock_repo.get_by_user_and_entity.return_value = _stored(legacy)
                MockRepo.return_value = mock_repo

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as test_client:
                    response = await test_client.get("/api/preferences/passwords")

            assert response.status_code == 200
            assert response.json()["preferences"]["widgets"] is None
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.integration
class TestWidgetsValidation:
    """Duplicate, invalid, and oversize widget lists are rejected with 422."""

    async def test_duplicate_ids_rejected(self, client: AsyncClient, mock_user: UserPrincipal):
        """Duplicate widget ids return 422."""
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as test_client:
                response = await test_client.put(
                    "/api/preferences/dashboard_layout",
                    json={
                        "preferences": {
                            "widgets": [
                                {"id": "quick-stats", "visible": True},
                                {"id": "quick-stats", "visible": False},
                            ]
                        }
                    },
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    async def test_invalid_id_rejected(self, client: AsyncClient, mock_user: UserPrincipal):
        """Widget ids outside the bounded pattern return 422."""
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as test_client:
                response = await test_client.put(
                    "/api/preferences/dashboard_layout",
                    json={"preferences": {"widgets": [{"id": "not a valid id!", "visible": True}]}},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    async def test_oversize_list_rejected(self, client: AsyncClient, mock_user: UserPrincipal):
        """More than 12 widgets return 422."""
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        oversize = [{"id": f"widget-{i}", "visible": True} for i in range(13)]
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as test_client:
                response = await test_client.put(
                    "/api/preferences/dashboard_layout",
                    json={"preferences": {"widgets": oversize}},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.integration
class TestDashboardLayoutAuthorization:
    """Preferences access is scoped to the authenticated user."""

    async def test_put_scoped_to_current_user(self, client: AsyncClient, mock_user: UserPrincipal):
        """Upsert is called with the authenticated user's id."""
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with patch("src.routers.preferences.UserPreferencesRepository") as MockRepo:
                mock_repo = AsyncMock()
                mock_repo.upsert.return_value = _stored(WIDGETS_PAYLOAD)
                MockRepo.return_value = mock_repo

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as test_client:
                    response = await test_client.put(
                        "/api/preferences/dashboard_layout",
                        json={"preferences": WIDGETS_PAYLOAD},
                    )

            assert response.status_code == 200
            mock_repo.upsert.assert_called_once()
            assert mock_repo.upsert.call_args.kwargs["user_id"] == mock_user.user_id
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    async def test_get_scoped_to_current_user(self, client: AsyncClient, mock_user: UserPrincipal):
        """Get is called with the authenticated user's id."""
        other_user = UserPrincipal(
            user_id=uuid4(),
            email="other@example.com",
            name="Other User",
            role=UserRole.CONTRIBUTOR,
            is_active=True,
            is_verified=True,
        )
        assert other_user.user_id != mock_user.user_id
        app.dependency_overrides[get_current_active_user] = lambda: other_user
        try:
            with patch("src.routers.preferences.UserPreferencesRepository") as MockRepo:
                mock_repo = AsyncMock()
                mock_repo.get_by_user_and_entity.return_value = None
                MockRepo.return_value = mock_repo

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as test_client:
                    response = await test_client.get("/api/preferences/dashboard_layout")

            assert response.status_code == 200
            mock_repo.get_by_user_and_entity.assert_called_once_with(
                user_id=other_user.user_id,
                entity_type="dashboard_layout",
            )
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
