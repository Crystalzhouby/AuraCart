"""Rename chat_message → chat_history and drop conversation.memory

Revision ID: 20260610_0004
Revises: 20260606_0003
Create Date: 2026-06-10

1. 重命名 chat_message 表为 chat_history（结构不变）
2. 删除 conversation 表的 memory JSONB 列
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260610_0004"
down_revision: Union[str, Sequence[str], None] = "20260606_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """重命名表 + 删除列。"""
    op.rename_table("chat_message", "chat_history")
    op.drop_column("conversation", "memory")


def downgrade() -> None:
    """回退：恢复 chat_message 表名 + 恢复 memory 列。"""
    op.rename_table("chat_history", "chat_message")
    op.add_column(
        "conversation",
        sa.Column(
            "memory",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
