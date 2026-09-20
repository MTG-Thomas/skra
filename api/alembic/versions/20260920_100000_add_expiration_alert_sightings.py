"""Add expiration alert sightings table (issue #40)

Revision ID: 20260920_100000
Revises: 20260919_100000
Create Date: 2026-09-20 10:00:00.000000

Stores one row per sent expiration alert threshold window so the daily
expiration job notifies once per window and re-alerts only on escalation
to a nearer window. Unique constraint makes recording idempotent.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260920_100000"
down_revision: str | None = "20260919_100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expiration_alert_sightings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("field_key", sa.String(length=255), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "asset_id",
            "field_key",
            "window_days",
            name="uq_expiration_alert_sighting",
        ),
    )


def downgrade() -> None:
    op.drop_table("expiration_alert_sightings")
