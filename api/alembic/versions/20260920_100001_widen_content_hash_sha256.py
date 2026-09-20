"""Widen embedding_index.content_hash for SHA-256 (refs #134)

Revision ID: 20260920_100001
Revises: 20260920_100000
Create Date: 2026-09-20 11:00:00.000000

EmbeddingsService.compute_content_hash now produces SHA-256 (64 hex chars)
instead of MD5 (32 hex chars). Old MD5 hashes self-heal: they mismatch the
new hash on the next index run, triggering a one-time re-index.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260920_100001"
down_revision: str | None = "20260920_100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "embedding_index",
        "content_hash",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
        comment="SHA-256 hash of searchable_text to detect changes",
    )


def downgrade() -> None:
    # Backfill MD5 hashes from the stored plaintext (searchable_text is a
    # non-nullable Text column) before shrinking. Without this, PostgreSQL
    # rejects the VARCHAR(64) -> VARCHAR(32) rewrite on 64-char SHA-256 rows.
    op.execute("UPDATE embedding_index SET content_hash = md5(searchable_text)")
    op.alter_column(
        "embedding_index",
        "content_hash",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
        comment="MD5 hash of searchable_text to detect changes",
    )
