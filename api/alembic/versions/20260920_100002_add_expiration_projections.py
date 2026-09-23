"""Add expiration projections table (issue #136, stage 1A)

Revision ID: 20260920_100002
Revises: 20260920_100001
Create Date: 2026-09-20 12:00:00.000000

Schema-only migration: creates the normalized expiration projection
(one row per custom asset expiration-alert date field) with the
(organization, type, asset, field key) unique key and the
(expires_on, organization) indexes for bounded reads. No data backfill
here; the rerunnable backfill job (stage 1B) populates rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260920_100002"
down_revision: str | None = "20260920_100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expiration_projections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("asset_type_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("field_id", sa.String(length=255), nullable=False),
        sa.Column("field_key", sa.String(length=255), nullable=False),
        sa.Column("field_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("asset_type_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("display_label", sa.Text(), nullable=True),
        sa.Column("asset_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_asset_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_type_id"],
            ["custom_asset_types.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["custom_assets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "asset_type_id",
            "asset_id",
            "field_key",
            name="uq_expiration_projection",
        ),
        sa.UniqueConstraint(
            "asset_id",
            "field_id",
            name="uq_expiration_projection_asset_field",
        ),
    )
    op.create_index(
        "ix_expiration_projection_expires_org",
        "expiration_projections",
        ["expires_on", "organization_id"],
    )
    op.create_index(
        "ix_expiration_projection_org_expires",
        "expiration_projections",
        ["organization_id", "expires_on"],
    )
    op.create_index(
        "ix_expiration_projection_asset_id",
        "expiration_projections",
        ["asset_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_expiration_projection_asset_id", table_name="expiration_projections")
    op.drop_index("ix_expiration_projection_org_expires", table_name="expiration_projections")
    op.drop_index("ix_expiration_projection_expires_org", table_name="expiration_projections")
    op.drop_table("expiration_projections")
