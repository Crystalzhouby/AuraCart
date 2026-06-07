"""Add chat_message table for conversation history persistence

Revision ID: 20260606_0003
Revises: 20260603_0002
Create Date: 2026-06-06

保存每轮对话的用户查询与助手回复，按 created_at 排序即为对话时间线。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260606_0003"
down_revision: Union[str, Sequence[str], None] = "20260603_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 chat_message 表。"""
    op.create_table(
        "chat_message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False, index=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """删除 chat_message 表。"""
    op.drop_table("chat_message")
