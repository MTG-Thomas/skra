"""
Expiration Projection repository (issue #136, stage 1A).

Persists normalized expiration rows for flagged custom-asset date fields.
Upserts are idempotent on the (organization, type, asset, field key)
unique key so transactional refreshes and the rerunnable backfill job
converge; deletes prune rows for removed assets, cleared dates, and
retired fields.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import asc, delete, desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm.custom_asset_type import CustomAssetType
from src.models.orm.expiration_projection import ExpirationProjection
from src.models.orm.organization import Organization
from src.repositories.base import BaseRepository


class ExpirationProjectionRepository(BaseRepository[ExpirationProjection]):
    """Repository for expiration projection row operations."""

    model = ExpirationProjection

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def upsert_row(
        self,
        *,
        organization_id: UUID,
        asset_type_id: UUID,
        asset_id: UUID,
        field_id: str,
        field_key: str,
        field_name: str,
        asset_type_name: str,
        expires_on,
        display_label: str | None,
        asset_updated_at,
        is_asset_enabled: bool,
    ) -> None:
        """
        Insert or refresh one projection row for an asset field.

        Idempotent: repeating the same values is a no-op write of the
        same row, so retries and backfill reruns converge.
        """
        stmt = insert(ExpirationProjection).values(
            organization_id=organization_id,
            asset_type_id=asset_type_id,
            asset_id=asset_id,
            field_id=field_id,
            field_key=field_key,
            field_name=field_name,
            asset_type_name=asset_type_name,
            expires_on=expires_on,
            display_label=display_label,
            asset_updated_at=asset_updated_at,
            is_asset_enabled=is_asset_enabled,
        )
        # Conflict target is the stable (asset_id, field_id) key: a field
        # renamed to a new key with the same id must update the existing
        # row (including field_key), not collide with the 4-tuple key.
        # organization_id/asset_type_id are intentionally not updated:
        # assets never move orgs or types, and rewriting them could
        # collide with the (organization, type, asset, field key) key.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_expiration_projection_asset_field",
            set_={
                "field_key": stmt.excluded.field_key,
                "field_name": stmt.excluded.field_name,
                "asset_type_name": stmt.excluded.asset_type_name,
                "expires_on": stmt.excluded.expires_on,
                "display_label": stmt.excluded.display_label,
                "asset_updated_at": stmt.excluded.asset_updated_at,
                "is_asset_enabled": stmt.excluded.is_asset_enabled,
            },
        )
        await self.session.execute(stmt)

    async def list_field_ids_for_asset(self, asset_id: UUID) -> list[str]:
        """List projected field ids for one asset (for stale-row pruning)."""
        result = await self.session.execute(
            select(ExpirationProjection.field_id).where(
                ExpirationProjection.asset_id == asset_id,
            )
        )
        return list(result.scalars().all())

    async def delete_for_asset(self, asset_id: UUID) -> int:
        """Delete all projection rows for an asset. Returns rows removed."""
        result = await self.session.execute(
            delete(ExpirationProjection).where(ExpirationProjection.asset_id == asset_id)
        )
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def delete_stale_for_asset(self, asset_id: UUID, keep_field_ids: set[str]) -> int:
        """
        Delete rows whose field id is no longer projected for the asset.

        Covers cleared dates, unflagged fields, and fields removed or
        re-ided by a type edit. Returns rows removed.
        """
        stmt = delete(ExpirationProjection).where(ExpirationProjection.asset_id == asset_id)
        if keep_field_ids:
            stmt = stmt.where(ExpirationProjection.field_id.not_in(keep_field_ids))
        result = await self.session.execute(stmt)
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def delete_for_type(self, asset_type_id: UUID) -> int:
        """Delete all projection rows for an asset type. Returns rows removed."""
        result = await self.session.execute(
            delete(ExpirationProjection).where(ExpirationProjection.asset_type_id == asset_type_id)
        )
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def query_upcoming(
        self,
        organization_ids: list[UUID],
        cutoff: date,
    ) -> list[ExpirationProjection]:
        """
        All projected rows expiring at or before ``cutoff`` for visible orgs.

        Active asset types only (deactivated types are hidden from expiry
        reads, mirroring the scanner's ``get_all_active``). No lower date
        bound: already-expired rows are included, like the scanner.
        Ordered by expiration date for urgency reads; callers apply
        search/sort/pagination on the bounded in-window set.
        """
        if not organization_ids:
            return []
        stmt = (
            select(ExpirationProjection)
            .join(
                CustomAssetType,
                CustomAssetType.id == ExpirationProjection.asset_type_id,
            )
            .where(
                ExpirationProjection.organization_id.in_(organization_ids),
                ExpirationProjection.expires_on <= cutoff,
                CustomAssetType.is_active.is_(True),
            )
            .order_by(
                ExpirationProjection.expires_on,
                ExpirationProjection.asset_id,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def query_global_page(
        self,
        cutoff: date,
        *,
        search: str | None,
        sort_by: str,
        sort_dir: str,
        limit: int,
        offset: int,
        show_disabled: bool,
    ) -> tuple[list[tuple[ExpirationProjection, str]], int]:
        """Return one exact global page and its database-side total.

        Historical expired rows remain visible by product policy. Unlike the
        legacy global reader, this query never materializes that full history
        in the API process: PostgreSQL applies visibility, search, ordering,
        limit, and offset before returning at most ``limit`` rows. The
        separate count preserves the standard exact-total list contract.
        """
        filters = [
            ExpirationProjection.expires_on <= cutoff,
            CustomAssetType.is_active.is_(True),
        ]
        if not show_disabled:
            filters.append(Organization.is_enabled.is_(True))

        if search and (needle := search.strip()):
            # The former Python substring match treated SQL wildcard
            # characters literally; preserve that contract in ILIKE.
            escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    ExpirationProjection.display_label.ilike(pattern, escape="\\"),
                    ExpirationProjection.asset_type_name.ilike(pattern, escape="\\"),
                    ExpirationProjection.field_name.ilike(pattern, escape="\\"),
                    Organization.name.ilike(pattern, escape="\\"),
                )
            )

        joins = (
            (CustomAssetType, CustomAssetType.id == ExpirationProjection.asset_type_id),
            (Organization, Organization.id == ExpirationProjection.organization_id),
        )
        count_stmt = select(func.count()).select_from(ExpirationProjection)
        for target, on_clause in joins:
            count_stmt = count_stmt.join(target, on_clause)
        count_stmt = count_stmt.where(*filters)
        count_result = await self.session.execute(count_stmt)
        total = int(count_result.scalar_one())

        sort_columns = {
            "days_until": ExpirationProjection.expires_on,
            "asset_display": func.lower(func.coalesce(ExpirationProjection.display_label, "")),
            "organization_name": func.lower(Organization.name),
        }
        sort_column = sort_columns.get(sort_by, sort_columns["days_until"])
        order = desc(sort_column) if sort_dir == "desc" else asc(sort_column)
        page_stmt = select(ExpirationProjection, Organization.name)
        for target, on_clause in joins:
            page_stmt = page_stmt.join(target, on_clause)
        page_stmt = (
            page_stmt.where(*filters)
            .order_by(
                order,
                asc(ExpirationProjection.asset_id),
                asc(ExpirationProjection.id),
            )
            .limit(limit)
            .offset(offset)
        )
        page_result = await self.session.execute(page_stmt)
        return [(row[0], row[1]) for row in page_result.all()], total
