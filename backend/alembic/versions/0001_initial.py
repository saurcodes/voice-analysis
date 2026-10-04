"""initial schema: users, drive_connections, analyses, jobs

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("keycloak_sub", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text()),
        sa.Column("username", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "drive_connections",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("encrypted_refresh_token", sa.LargeBinary(), nullable=False),
        sa.Column("google_email", sa.Text()),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("drive_file_id", sa.Text()),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyser_version", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("metrics_json", JSONType, nullable=False),
        sa.Column("transcript_json", JSONType),
        sa.Column("speaker_context", sa.Text()),
        sa.Column("coaching_json", JSONType),
        sa.Column("coaching_warnings", JSONType),
        sa.UniqueConstraint("user_id", "content_sha256", "config_hash", "analyser_version",
                            name="uq_analyses_user_sha_config_version"),
    )
    op.create_index("ix_analyses_user_recorded", "analyses", ["user_id", "recorded_at"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id", ondelete="SET NULL")),
        sa.Column("file_name", sa.Text()),
        sa.Column("source_sha256", sa.String(64)),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('queued','running','done','failed')", name="ck_jobs_status"),
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_index("ix_analyses_user_recorded", table_name="analyses")
    op.drop_table("analyses")
    op.drop_table("drive_connections")
    op.drop_table("users")
