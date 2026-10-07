"""push notifications

Revision ID: c7a2e91d4f30
Revises: b31d0c7e5a10
Create Date: 2026-10-07 10:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7a2e91d4f30"
down_revision: Union[str, Sequence[str], None] = "b31d0c7e5a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(length=128), nullable=False),
        sa.Column("auth", sa.String(length=64), nullable=False),
        sa.Column("min_category", sa.String(length=16), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_push_subscriptions_username", "push_subscriptions", ["username"])
    op.create_table(
        "app_secrets",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_secrets")
    op.drop_index("ix_push_subscriptions_username", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
