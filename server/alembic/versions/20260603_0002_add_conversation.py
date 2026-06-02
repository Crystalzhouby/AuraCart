"""Add conversation table for multi-session support

Revision ID: 20260603_0002
Revises: 6af5d4918efe
Create Date: 2026-06-03

创建 conversation 表，以 UUID 为主键，JSONB 列存储对话记忆。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260603_0002"
down_revision: Union[str, Sequence[str], None] = "6af5d4918efe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 conversation 表。"""
    op.create_table(
        "conversation",
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column(
            "memory",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
    )


def downgrade() -> None:
    """删除 conversation 表。"""
    op.drop_table("conversation")
