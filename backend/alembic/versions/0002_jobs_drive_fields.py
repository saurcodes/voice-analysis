"""jobs gain drive_file_id and drive_modified_time so Drive-sourced jobs can be retried

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("drive_file_id", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("drive_modified_time", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "drive_modified_time")
    op.drop_column("jobs", "drive_file_id")
