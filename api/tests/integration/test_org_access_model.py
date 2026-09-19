"""
Integration tests for the V1 organization access model (ADR-001, issue #73).

Decision under test (docs/architecture/001-organization-access.md):
- Authenticated users hold a GLOBAL role across the workspace. Organizations
  are documentation partitions, not tenant authorization boundaries.
- An organization ID in a route selects records, never permissions. The
  browser's persisted `currentOrg` is navigation context, not authorization.
- The same role has the same access in every organization; API keys inherit
  the owning user's role; disabled organizations are hidden from default
  listings and global search.

These tests use two organizations (plus a disabled one) and assert that
behavior is identical across them for each role.
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.core.auth import (
    UserPrincipal,
    get_current_active_user,
    get_current_user,
    get_execution_context,
)
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


@contextmanager
def patched_password_side_effects():
    """Patch audit + search-index side effects for password routes."""
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    with (
        patch(
            "src.routers.passwords.get_audit_service",
            return_value=audit_service,
        ),
        patch("src.routers.passwords.index_entity_for_search", new=AsyncMock()),
        patch("src.routers.passwords.remove_entity_from_search", new=AsyncMock()),
    ):
        yield


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
# ExecutionContext contract (ADR-001: org_id is None for every user)
# =============================================================================


@pytest.mark.integration
class TestExecutionContextContract:
    """The ExecutionContext implementation must match the documented contract."""

    async def test_context_is_global_for_contributor(self):
        """Contributor context carries org_id=None and global scope."""
        ctx = await get_execution_context(user=make_principal(UserRole.CONTRIBUTOR), db=MagicMock())
        assert ctx.org_id is None
        assert ctx.is_global_scope is True
        assert ctx.scope == "GLOBAL"

    async def test_context_is_global_for_reader(self):
        """Reader context carries org_id=None and global scope."""
        ctx = await get_execution_context(user=make_principal(UserRole.READER), db=MagicMock())
        assert ctx.org_id is None
        assert ctx.is_global_scope is True


# =============================================================================
# Two-organization role matrix on org routes (passwords as representative)
# =============================================================================


@pytest.mark.integration
class TestTwoOrgContributorMatrix:
    """Contributors can read and write in BOTH organizations (ADR-001)."""

    @pytest.mark.parametrize("org_fixture", ["org_a_id", "org_b_id"])
    async def test_contributor_crud_same_in_both_orgs(
        self, client: AsyncClient, org_fixture, request
    ):
        """Create/read/update/delete succeed identically in org A and org B."""
        org_id = request.getfixturevalue(org_fixture)
        password = make_password(org_id)
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=password)
        mock_repo.get_by_id_and_org = AsyncMock(return_value=password)
        mock_repo.update = AsyncMock(return_value=password)
        mock_repo.delete = AsyncMock()

        with auth_as(make_principal(UserRole.CONTRIBUTOR)):
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=mock_repo),
                patched_password_side_effects(),
            ):
                create = await client.post(
                    f"/api/organizations/{org_id}/passwords",
                    json={"name": "Admin Account", "password": "secret123"},
                )
                assert create.status_code == 201
                assert create.json()["organization_id"] == str(org_id)

                get = await client.get(f"/api/organizations/{org_id}/passwords/{password.id}")
                assert get.status_code == 200

                update = await client.put(
                    f"/api/organizations/{org_id}/passwords/{password.id}",
                    json={"name": "Renamed"},
                )
                assert update.status_code == 200

                delete = await client.delete(f"/api/organizations/{org_id}/passwords/{password.id}")
                assert delete.status_code == 204

    @pytest.mark.parametrize("org_fixture", ["org_a_id", "org_b_id"])
    async def test_contributor_lists_both_orgs(self, client: AsyncClient, org_fixture, request):
        """Listing works identically in org A and org B."""
        org_id = request.getfixturevalue(org_fixture)
        mock_repo = AsyncMock()
        mock_repo.get_paginated_by_org = AsyncMock(return_value=([make_password(org_id)], 1))

        with auth_as(make_principal(UserRole.CONTRIBUTOR)):
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=mock_repo),
                patched_password_side_effects(),
            ):
                response = await client.get(f"/api/organizations/{org_id}/passwords")
                assert response.status_code == 200
                assert response.json()["total"] == 1


@pytest.mark.integration
class TestTwoOrgReaderMatrix:
    """Readers can read in BOTH organizations but write in NEITHER (ADR-001)."""

    @pytest.mark.parametrize("org_fixture", ["org_a_id", "org_b_id"])
    async def test_reader_reads_both_orgs(self, client: AsyncClient, org_fixture, request):
        """Reader list/get succeed identically in org A and org B."""
        org_id = request.getfixturevalue(org_fixture)
        password = make_password(org_id)
        mock_repo = AsyncMock()
        mock_repo.get_paginated_by_org = AsyncMock(return_value=([password], 1))
        mock_repo.get_by_id_and_org = AsyncMock(return_value=password)

        with auth_as(make_principal(UserRole.READER)):
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=mock_repo),
                patched_password_side_effects(),
            ):
                listed = await client.get(f"/api/organizations/{org_id}/passwords")
                assert listed.status_code == 200

                fetched = await client.get(f"/api/organizations/{org_id}/passwords/{password.id}")
                assert fetched.status_code == 200

    @pytest.mark.parametrize("org_fixture", ["org_a_id", "org_b_id"])
    async def test_reader_writes_forbidden_in_both_orgs(
        self, client: AsyncClient, org_fixture, request
    ):
        """Reader create/update/delete are 403 in org A and org B."""
        org_id = request.getfixturevalue(org_fixture)
        password_id = uuid4()

        with auth_as(make_principal(UserRole.READER)):
            create = await client.post(
                f"/api/organizations/{org_id}/passwords",
                json={"name": "Nope", "password": "secret123"},
            )
            assert create.status_code == 403

            update = await client.put(
                f"/api/organizations/{org_id}/passwords/{password_id}",
                json={"name": "Nope"},
            )
            assert update.status_code == 403

            delete = await client.delete(f"/api/organizations/{org_id}/passwords/{password_id}")
            assert delete.status_code == 403


@pytest.mark.integration
class TestAdminBoundaryBothOrgs:
    """Non-admin roles are rejected from admin routes regardless of org."""

    @pytest.mark.parametrize("role", [UserRole.READER, UserRole.CONTRIBUTOR])
    async def test_non_admin_forbidden(self, client: AsyncClient, role):
        """Reader/contributor get 403 on admin-only endpoints."""
        with auth_as(make_principal(role)):
            response = await client.get("/api/admin/users")
            assert response.status_code == 403

    async def test_cannot_create_organization_as_contributor(self, client: AsyncClient):
        """Organization creation requires admin (RequireAdmin, org-independent)."""
        with auth_as(make_principal(UserRole.CONTRIBUTOR)):
            response = await client.post("/api/organizations", json={"name": "New Org"})
            assert response.status_code == 403


# =============================================================================
# Global routes: visible to every role across organizations
# =============================================================================


@pytest.mark.integration
class TestGlobalVisibility:
    """Global list routes expose records from every org to every role."""

    @pytest.mark.parametrize(
        "role", [UserRole.READER, UserRole.CONTRIBUTOR, UserRole.ADMINISTRATOR]
    )
    async def test_global_passwords_visible_to_all_roles(
        self, client: AsyncClient, role, org_a_id, org_b_id
    ):
        """Global password list returns org A + org B records for any role."""
        mock_repo = AsyncMock()
        mock_repo.get_paginated = AsyncMock(
            return_value=([make_password(org_a_id), make_password(org_b_id)], 2)
        )

        with auth_as(make_principal(role)):
            with (
                patch("src.routers.global_view.PasswordRepository", return_value=mock_repo),
                patch(
                    "src.routers.global_view._visible_org_ids",
                    new=AsyncMock(return_value=[org_a_id, org_b_id]),
                ),
            ):
                response = await client.get("/api/global/passwords")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert {item["organization_id"] for item in data["items"]} == {
            str(org_a_id),
            str(org_b_id),
        }

    @pytest.mark.parametrize("role", [UserRole.READER, UserRole.CONTRIBUTOR])
    async def test_list_all_organizations_visible_to_all_roles(
        self, client: AsyncClient, role, org_a_id, org_b_id
    ):
        """Every authenticated user can list all organizations (ADR-001)."""
        org_a = make_org(is_enabled=True)
        org_a.id = org_a_id
        org_b = make_org(is_enabled=True)
        org_b.id = org_b_id
        mock_repo = AsyncMock()
        mock_repo.get_all = AsyncMock(return_value=[org_a, org_b])

        with auth_as(make_principal(role)):
            with patch(
                "src.routers.organizations.OrganizationRepository",
                return_value=mock_repo,
            ):
                response = await client.get("/api/organizations")

        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == {
            str(org_a_id),
            str(org_b_id),
        }


# =============================================================================
# API keys inherit the owning user's role (no org scope)
# =============================================================================


@pytest.mark.integration
class TestApiKeyInheritsRole:
    """API-key requests enforce the owner's global role in every org."""

    @pytest.mark.parametrize("org_fixture", ["org_a_id", "org_b_id"])
    async def test_contributor_key_writes_both_orgs(
        self, client: AsyncClient, org_fixture, request
    ):
        """A contributor's API key creates records in org A and org B."""
        org_id = request.getfixturevalue(org_fixture)
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=make_password(org_id))
        principal = make_principal(UserRole.CONTRIBUTOR, api_key_id=uuid4())

        with auth_as(principal):
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=mock_repo),
                patched_password_side_effects(),
            ):
                response = await client.post(
                    f"/api/organizations/{org_id}/passwords",
                    json={"name": "Via Key", "password": "secret123"},
                )
                assert response.status_code == 201

    @pytest.mark.parametrize("org_fixture", ["org_a_id", "org_b_id"])
    async def test_reader_key_read_only_in_both_orgs(
        self, client: AsyncClient, org_fixture, request
    ):
        """A reader's API key reads but cannot write in org A or org B."""
        org_id = request.getfixturevalue(org_fixture)
        mock_repo = AsyncMock()
        mock_repo.get_paginated_by_org = AsyncMock(return_value=([make_password(org_id)], 1))
        principal = make_principal(UserRole.READER, api_key_id=uuid4())

        with auth_as(principal):
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=mock_repo),
                patched_password_side_effects(),
            ):
                listed = await client.get(f"/api/organizations/{org_id}/passwords")
                assert listed.status_code == 200

                created = await client.post(
                    f"/api/organizations/{org_id}/passwords",
                    json={"name": "Via Key", "password": "secret123"},
                )
                assert created.status_code == 403

    async def test_inactive_principal_rejected(self, client: AsyncClient, org_a_id):
        """A disabled user's session/key fails the active-user gate (403)."""
        inactive = make_principal(UserRole.CONTRIBUTOR, active=False)
        app.dependency_overrides[get_current_user] = lambda: inactive
        try:
            response = await client.get(f"/api/organizations/{org_a_id}/passwords")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
class TestApiKeyAuthentication:
    """_authenticate_api_key binds a key to its owner's live role/state."""

    def _mock_db(self, key_row, user_row):
        """Stage db.execute results for the key lookup then the user lookup."""
        db = AsyncMock()
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = key_row
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user_row
        db.execute = AsyncMock(side_effect=[key_result, user_result])
        db.flush = AsyncMock()
        return db

    async def test_valid_key_returns_owner_role(self):
        """A valid key yields a principal with the owner's current role."""
        from src.core.auth import _authenticate_api_key
        from src.core.security import hash_api_key
        from src.models.orm.api_key import APIKey
        from src.models.orm.user import User

        user_id = uuid4()
        key = APIKey(user_id=user_id, name="k", key_hash=hash_api_key("bifrost_docs_raw"))
        user = User(id=user_id, email="c@example.com", role=UserRole.CONTRIBUTOR, is_active=True)
        principal = await _authenticate_api_key(self._mock_db(key, user), "bifrost_docs_raw")
        assert principal is not None
        assert principal.role == UserRole.CONTRIBUTOR
        assert principal.api_key_id == key.id

    async def test_unknown_key_returns_none(self):
        """An unknown key hash authenticates nothing."""
        from src.core.auth import _authenticate_api_key

        assert await _authenticate_api_key(self._mock_db(None, None), "bifrost_docs_no") is None

    async def test_expired_key_returns_none(self):
        """An expired key authenticates nothing."""
        from datetime import timedelta

        from src.core.auth import _authenticate_api_key
        from src.core.security import hash_api_key
        from src.models.orm.api_key import APIKey

        key = APIKey(
            user_id=uuid4(),
            name="k",
            key_hash=hash_api_key("bifrost_docs_old"),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        assert await _authenticate_api_key(self._mock_db(key, None), "bifrost_docs_old") is None

    async def test_inactive_owner_returns_none(self):
        """A key whose owner is disabled authenticates nothing."""
        from src.core.auth import _authenticate_api_key
        from src.core.security import hash_api_key
        from src.models.orm.api_key import APIKey
        from src.models.orm.user import User

        user_id = uuid4()
        key = APIKey(user_id=user_id, name="k", key_hash=hash_api_key("bifrost_docs_off"))
        user = User(id=user_id, email="off@example.com", role=UserRole.CONTRIBUTOR, is_active=False)
        assert await _authenticate_api_key(self._mock_db(key, user), "bifrost_docs_off") is None


# =============================================================================
# Disabled organizations: explicit, consistent visibility rules
# =============================================================================


@pytest.mark.integration
class TestDisabledOrganizations:
    """Disabled orgs hide from default listings and global search (ADR-001)."""

    async def test_list_orgs_hides_disabled_by_default(self, client: AsyncClient, org_a_id):
        """GET /api/organizations requests enabled-only and returns them."""
        enabled = make_org(is_enabled=True)
        enabled.id = org_a_id
        mock_repo = AsyncMock()
        mock_repo.get_all = AsyncMock(return_value=[enabled])

        with auth_as(make_principal(UserRole.READER)):
            with patch(
                "src.routers.organizations.OrganizationRepository",
                return_value=mock_repo,
            ):
                response = await client.get("/api/organizations")

        assert response.status_code == 200
        mock_repo.get_all.assert_awaited_once_with(is_enabled=True)
        assert [item["id"] for item in response.json()] == [str(org_a_id)]

    async def test_list_orgs_show_disabled_includes_all(
        self, client: AsyncClient, org_a_id, org_b_id
    ):
        """show_disabled=true requests the unfiltered list."""
        enabled = make_org(is_enabled=True)
        enabled.id = org_a_id
        disabled = make_org(is_enabled=False)
        disabled.id = org_b_id
        mock_repo = AsyncMock()
        mock_repo.get_all = AsyncMock(return_value=[enabled, disabled])

        with auth_as(make_principal(UserRole.READER)):
            with patch(
                "src.routers.organizations.OrganizationRepository",
                return_value=mock_repo,
            ):
                response = await client.get("/api/organizations?show_disabled=true")

        assert response.status_code == 200
        mock_repo.get_all.assert_awaited_once_with(is_enabled=None)
        assert {item["id"] for item in response.json()} == {
            str(org_a_id),
            str(org_b_id),
        }

    async def test_search_excludes_disabled_orgs(self, client: AsyncClient):
        """Global search requests enabled-only org IDs by default."""
        enabled = make_org(is_enabled=True)
        disabled = make_org(is_enabled=False)

        async def fake_get_all(limit=100, offset=0, is_enabled=None):
            orgs = [enabled, disabled]
            if is_enabled is not None:
                orgs = [o for o in orgs if o.is_enabled == is_enabled]
            return orgs

        mock_org_repo = AsyncMock()
        mock_org_repo.get_all = AsyncMock(side_effect=fake_get_all)
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
                response = await client.get("/api/search?q=admin&mode=text")

        assert response.status_code == 200
        mock_org_repo.get_all.assert_awaited_once_with(is_enabled=True)
        (searched_org_ids,) = mock_embeddings.text_search.await_args[0][2:3]
        assert searched_org_ids == [enabled.id]

    async def test_org_route_records_unaffected_by_org_disabled_flag(
        self, client: AsyncClient, org_b_id
    ):
        """Record routes scope by org ID; the org disabled flag gates listings."""
        password = make_password(org_b_id)
        mock_repo = AsyncMock()
        mock_repo.get_by_id_and_org = AsyncMock(return_value=password)

        with auth_as(make_principal(UserRole.CONTRIBUTOR)):
            with (
                patch("src.routers.passwords.PasswordRepository", return_value=mock_repo),
                patched_password_side_effects(),
            ):
                response = await client.get(
                    f"/api/organizations/{org_b_id}/passwords/{password.id}"
                )
                assert response.status_code == 200
        mock_repo.get_by_id_and_org.assert_awaited_once_with(password.id, org_b_id)


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


@pytest.mark.integration
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
