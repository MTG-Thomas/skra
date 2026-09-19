"""Add sync metadata to organizations, locations, documents, and passwords

Revision ID: 20260919_100000
Revises: 20260424_100000
Create Date: 2026-09-19 10:00:00.000000

Extends the Docs-owned sync provenance contract (issue #34) to the
remaining core synced entity types. Same nullable JSONB shape as the
configurations/custom_assets columns: absent provenance serializes as
null and never affects existing rows.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260919_100000"
down_revision: str | None = "20260424_100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("sync_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "locations",
        sa.Column("sync_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("sync_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "passwords",
        sa.Column("sync_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("passwords", "sync_metadata")
    op.drop_column("documents", "sync_metadata")
    op.drop_column("locations", "sync_metadata")
    op.drop_column("organizations", "sync_metadata")
