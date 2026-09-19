"""Unit tests for archived-organization visibility (issue #93, ADR-001 unchanged).

Two-org matrix: is_enabled=False is an archive/visibility state, not an
authorization boundary. Global lists, search, and default exports hide
archived orgs; show_disabled=true (or an explicit org scope, including an
explicit export selection) includes them for any role allowed to read the
record. Roles themselves never change.

Mock-based (no database): these run in CI under tests/unit, which is the
suite Sonar measures for new-code coverage.
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
from src.models.orm.organization import Organization
from src.models.orm.password import Password


def make_principal(role=UserRole.CONTRIBUTOR, active=True, api_key_id=None):
    """Create a UserPrincipal for the given role."""
    return UserPrincipal(
        user_id=uuid4(),
        email=f"{role.value}@example.com",
        name="Test User",
        role=role,
        is_active=active,
        is_verified=True,
        api_key_id=api_key_id,
    )


def make_org(is_enabled=True):
    """Create a mock Organization record."""
    org = MagicMock(spec=Organization)
    org.id = uuid4()
    org.name = "Org"
    org.metadata_ = {}
    org.is_enabled = is_enabled
    now = datetime.now(UTC)
    org.created_at = now
    org.updated_at = now
    org.updated_by_user_id = None
    org.updated_by_user = None
    return org


def make_password(org_id):
    """Create a mock Password record belonging to org_id."""
    password = MagicMock(spec=Password)
    password.id = uuid4()
    password.organization_id = org_id
    password.name = "Admin Account"
    password.username = "admin"
    password.url = "https://example.com"
    password.notes = "notes"
    password.totp_secret_encrypted = None
    password.metadata_ = {}
    password.is_enabled = True
    now = datetime.now(UTC)
    password.created_at = now
    password.updated_at = now
    password.updated_by_user_id = None
    password.updated_by_user = None
    password.organization = MagicMock()
    password.organization.name = "Org"
    return password


@contextmanager
def auth_as(principal):
    """Override authentication with the given principal."""
    app.dependency_overrides[get_current_active_user] = lambda: principal
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest_asyncio.fixture
async def client():
    """Create an async HTTP client for testing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def org_a_id():
    """First organization ID."""
    return uuid4()


@pytest.fixture
def org_b_id():
    """Second organization ID (no membership link to the test users)."""
    return uuid4()


# =============================================================================
# Disabled-org visibility matrix (issue #93): global lists, search, exports
# =============================================================================


def _filter_sql(filters):
    """Render WHERE filters with literal binds for assertions."""
    return " ".join(
        str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters
    ).replace("-", "")


def _hex(uid):
    """UUID without dashes, matching literal-bound SQL rendering."""
    return str(uid).replace("-", "")


class TestDisabledOrgVisibilityMatrix:
    """Two-org matrix: archived orgs hide by default, show_disabled opts in.

    Rule under test (issue #93, ADR-001 unchanged): is_enabled=False is an
    archive/visibility state, not an authorization boundary. Global lists,
    search, and default exports hide archived orgs; show_disabled=true (or an
    explicit org scope, including an explicit export selection) includes them
    for any role allowed to read the record. Roles themselves never change.
    """

    async def test_global_passwords_hide_disabled_by_default(
        self, client: AsyncClient, org_a_id, org_b_id
    ):
        """Default global password list filters to the enabled org only."""
        mock_repo = AsyncMock()
        mock_repo.get_paginated = AsyncMock(return_value=([], 0))

        with auth_as(make_principal(UserRole.READER)):
            with (
                patch(
                    "src.routers.global_view.PasswordRepository",
                    return_value=mock_repo,
                ),
                patch(
                    "src.routers.global_view._visible_org_ids",
                    new=AsyncMock(return_value=[org_a_id]),
                ),
            ):
                response = await client.get("/api/global/passwords")

        assert response.status_code == 200
        filters = mock_repo.get_paginated.await_args.kwargs["filters"]
        assert len(filters) == 1
        sql = _filter_sql(filters)
        assert _hex(org_a_id) in sql
        assert _hex(org_b_id) not in sql

    async def test_global_passwords_show_disabled_includes_all(
        self, client: AsyncClient, org_a_id, org_b_id
    ):
        """show_disabled=true requests the unfiltered global password list."""
        mock_repo = AsyncMock()
        mock_repo.get_paginated = AsyncMock(return_value=([], 0))

        with auth_as(make_principal(UserRole.READER)):
            with patch(
                "src.routers.global_view.PasswordRepository",
                return_value=mock_repo,
            ):
                response = await client.get("/api/global/passwords?show_disabled=true")

        assert response.status_code == 200
        filters = mock_repo.get_paginated.await_args.kwargs["filters"]
        assert filters == []

    async def test_global_passwords_same_rule_for_reader_api_key(
        self, client: AsyncClient, org_a_id, org_b_id
    ):
        """Visibility does not depend on role or credential type (ADR-001)."""
        mock_repo = AsyncMock()
        mock_repo.get_paginated = AsyncMock(return_value=([], 0))
        principal = make_principal(UserRole.READER, api_key_id=uuid4())

        with auth_as(principal):
            with (
                patch(
                    "src.routers.global_view.PasswordRepository",
                    return_value=mock_repo,
                ),
                patch(
                    "src.routers.global_view._visible_org_ids",
                    new=AsyncMock(return_value=[org_a_id]),
                ),
            ):
                response = await client.get("/api/global/passwords")

        assert response.status_code == 200
        sql = _filter_sql(mock_repo.get_paginated.await_args.kwargs["filters"])
        assert _hex(org_a_id) in sql
        assert _hex(org_b_id) not in sql

    async def test_global_custom_assets_hide_disabled_by_default(
        self, client: AsyncClient, org_a_id, org_b_id
    ):
        """Custom-asset global query (raw select path) filters by enabled org."""
        from src.core.database import get_db

        statements = []

        async def fake_execute(stmt, *args, **kwargs):
            statements.append(stmt)
            result = MagicMock()
            result.unique.return_value = result
            result.scalars.return_value = result
            result.scalars().all = MagicMock(return_value=[])
            result.scalar = MagicMock(return_value=0)
            return result

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=fake_execute)
        mock_type = MagicMock()
        mock_type.fields = []
        mock_type.display_field_key = None
        mock_type_repo = AsyncMock()
        mock_type_repo.get_by_id = AsyncMock(return_value=mock_type)
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with auth_as(make_principal(UserRole.READER)):
                with (
                    patch(
                        "src.routers.global_view.CustomAssetTypeRepository",
                        return_value=mock_type_repo,
                    ),
                    patch(
                        "src.routers.global_view._visible_org_ids",
                        new=AsyncMock(return_value=[org_a_id]),
                    ),
                ):
                    response = await client.get(f"/api/global/custom-assets?type_id={uuid4()}")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        assert response.json()["items"] == []
        # Both the record query and the count query filter by enabled org.
        assert len(statements) == 2
        sql = " ".join(str(s.compile(compile_kwargs={"literal_binds": True})) for s in statements)
        assert _hex(org_a_id) in sql
        assert _hex(org_b_id) not in sql

    async def test_search_show_disabled_includes_archived_org(
        self, client: AsyncClient, org_a_id, org_b_id
    ):
        """show_disabled=true searches archived orgs for permitted readers."""
        enabled = make_org(is_enabled=True)
        enabled.id = org_a_id
        disabled = make_org(is_enabled=False)
        disabled.id = org_b_id
        mock_org_repo = AsyncMock()
        mock_org_repo.get_all = AsyncMock(return_value=[enabled, disabled])
        mock_embeddings = MagicMock()
        mock_embeddings.check_openai_available = AsyncMock(return_value=False)
        mock_embeddings.text_search = AsyncMock(return_value=[])

        with auth_as(make_principal(UserRole.READER)):
            with (
                patch(
                    "src.routers.search.OrganizationRepository",
                    return_value=mock_org_repo,
                ),
                patch(
                    "src.routers.search.get_embeddings_service",
                    return_value=mock_embeddings,
                ),
            ):
                response = await client.get("/api/search?q=admin&mode=text&show_disabled=true")

        assert response.status_code == 200
        (searched_org_ids,) = mock_embeddings.text_search.await_args[0][2:3]
        assert searched_org_ids == [org_a_id, org_b_id]

    async def test_search_explicit_disabled_org_stays_searchable(
        self, client: AsyncClient, org_b_id
    ):
        """An explicit org scope is a direct read: archived orgs stay searchable."""
        disabled = make_org(is_enabled=False)
        disabled.id = org_b_id
        mock_org_repo = AsyncMock()
        mock_org_repo.get_by_id = AsyncMock(return_value=disabled)
        mock_embeddings = MagicMock()
        mock_embeddings.check_openai_available = AsyncMock(return_value=False)
        mock_embeddings.text_search = AsyncMock(return_value=[])

        with auth_as(make_principal(UserRole.READER)):
            with (
                patch(
                    "src.routers.search.OrganizationRepository",
                    return_value=mock_org_repo,
                ),
                patch(
                    "src.routers.search.get_embeddings_service",
                    return_value=mock_embeddings,
                ),
            ):
                response = await client.get(f"/api/search?q=admin&mode=text&org_id={org_b_id}")

        assert response.status_code == 200
        (searched_org_ids,) = mock_embeddings.text_search.await_args[0][2:3]
        assert searched_org_ids == [org_b_id]

    async def test_export_all_orgs_selects_enabled_only(self, org_a_id, org_b_id):
        """Default (all-org) export resolution excludes archived orgs."""
        from src.services.export_service import get_all_organization_ids

        statements = []

        async def fake_execute(stmt, *args, **kwargs):
            statements.append(stmt)
            result = MagicMock()
            result.fetchall = MagicMock(return_value=[(org_a_id,)])
            return result

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=fake_execute)

        org_ids = await get_all_organization_ids(mock_db)

        assert org_ids == [org_a_id]
        assert len(statements) == 1
        assert "is_enabled" in str(statements[0])

    async def test_export_explicit_disabled_org_is_included(self, org_b_id):
        """An explicit export selection is opt-in: archived orgs export."""
        from src.services import export_service
        from src.services.export_service import process_export

        export_id = uuid4()
        mock_export = MagicMock()
        mock_export.id = export_id
        mock_export.organization_ids = [str(org_b_id)]

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=mock_export)
        mock_repo.update_status = AsyncMock()
        mock_storage = AsyncMock()
        mock_storage.upload_file = AsyncMock(return_value=True)

        with (
            patch.object(export_service, "get_db_context", return_value=mock_cm),
            patch.object(export_service, "ExportRepository", return_value=mock_repo),
            patch.object(
                export_service,
                "export_passwords_to_csv",
                new=AsyncMock(return_value="pw"),
            ),
            patch.object(
                export_service,
                "export_configurations_to_csv",
                new=AsyncMock(return_value="cfg"),
            ),
            patch.object(
                export_service,
                "export_locations_to_csv",
                new=AsyncMock(return_value="loc"),
            ),
            patch.object(
                export_service,
                "export_documents_to_csv",
                new=AsyncMock(return_value="doc"),
            ),
            patch.object(
                export_service,
                "export_custom_assets_to_csv",
                new=AsyncMock(return_value="ca"),
            ),
            patch.object(
                export_service,
                "get_file_storage_service",
                return_value=mock_storage,
            ),
            patch.object(export_service, "publish_export_progress", new=AsyncMock()),
            patch.object(export_service, "publish_export_completed", new=AsyncMock()),
        ):
            await process_export(export_id)

            csv_mock = export_service.export_passwords_to_csv
            assert csv_mock.await_args[0][1] == [org_b_id]

    async def test_export_default_selection_uses_enabled_orgs(self, org_a_id):
        """Export with organization_ids=None resolves to enabled orgs only."""
        from src.services import export_service
        from src.services.export_service import process_export

        export_id = uuid4()
        mock_export = MagicMock()
        mock_export.id = export_id
        mock_export.organization_ids = None

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=mock_export)
        mock_repo.update_status = AsyncMock()
        mock_storage = AsyncMock()
        mock_storage.upload_file = AsyncMock(return_value=True)

        with (
            patch.object(export_service, "get_db_context", return_value=mock_cm),
            patch.object(export_service, "ExportRepository", return_value=mock_repo),
            patch.object(
                export_service,
                "get_all_organization_ids",
                new=AsyncMock(return_value=[org_a_id]),
            ),
            patch.object(
                export_service,
                "export_passwords_to_csv",
                new=AsyncMock(return_value="pw"),
            ),
            patch.object(
                export_service,
                "export_configurations_to_csv",
                new=AsyncMock(return_value="cfg"),
            ),
            patch.object(
                export_service,
                "export_locations_to_csv",
                new=AsyncMock(return_value="loc"),
            ),
            patch.object(
                export_service,
                "export_documents_to_csv",
                new=AsyncMock(return_value="doc"),
            ),
            patch.object(
                export_service,
                "export_custom_assets_to_csv",
                new=AsyncMock(return_value="ca"),
            ),
            patch.object(
                export_service,
                "get_file_storage_service",
                return_value=mock_storage,
            ),
            patch.object(export_service, "publish_export_progress", new=AsyncMock()),
            patch.object(export_service, "publish_export_completed", new=AsyncMock()),
        ):
            await process_export(export_id)

            csv_mock = export_service.export_passwords_to_csv
            assert csv_mock.await_args[0][1] == [org_a_id]

    async def test_reader_cannot_create_export(self, client: AsyncClient):
        """Export creation stays admin-only regardless of archive flags."""
        with auth_as(make_principal(UserRole.READER)):
            response = await client.post("/api/exports", json={})

        assert response.status_code == 403
