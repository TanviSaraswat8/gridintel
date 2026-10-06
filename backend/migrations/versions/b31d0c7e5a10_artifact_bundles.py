"""artifact bundles

Revision ID: b31d0c7e5a10
Revises: 9aec7b2a312c
Create Date: 2026-10-06 21:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b31d0c7e5a10"
down_revision: Union[str, Sequence[str], None] = "9aec7b2a312c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifact_bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_artifact_bundles_created_at", "artifact_bundles", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_artifact_bundles_created_at", table_name="artifact_bundles")
    op.drop_table("artifact_bundles")
