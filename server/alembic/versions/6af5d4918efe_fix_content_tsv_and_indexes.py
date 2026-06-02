"""Fix content_tsv column type and add performance indexes

Revision ID: 6af5d4918efe
Revises: 20260527_0001
Create Date: 2026-06-02 19:07:36.441767

1. ALTER content_tsv 列类型: TEXT → TSVECTOR
2. 创建 GIN 索引: ix_product_review_content_tsv（全文检索）
3. 创建 HNSW 索引: ix_product_review_embedding（向量相似度）
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision: str = '6af5d4918efe'
down_revision: Union[str, Sequence[str], None] = '20260527_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """修正 content_tsv 类型并补建性能索引。"""

    # Step 1: 修正 content_tsv 列类型
    # 先删除旧默认值（TEXT 的 '' 无法自动转换为 tsvector）
    op.execute("ALTER TABLE product_review ALTER COLUMN content_tsv DROP DEFAULT")
    # 再执行类型转换（USING 子句无损转换已有数据）
    op.execute(
        "ALTER TABLE product_review "
        "ALTER COLUMN content_tsv TYPE tsvector "
        "USING content_tsv::tsvector"
    )
    # 最后设置新的 tsvector 兼容默认值
    op.execute(
        "ALTER TABLE product_review "
        "ALTER COLUMN content_tsv SET DEFAULT ''::tsvector"
    )
    # 同步 Alembic metadata
    op.alter_column(
        "product_review",
        "content_tsv",
        type_=TSVECTOR(),
        existing_type=sa.Text(),
        nullable=True,
        server_default=sa.text("''::tsvector"),
    )

    # Step 2: 为全文检索字段创建 GIN 倒排索引
    op.create_index(
        "ix_product_review_content_tsv",
        "product_review",
        ["content_tsv"],
        unique=False,
        postgresql_using="gin",
    )

    # Step 3: 为向量列创建 HNSW 索引（余弦相似度）
    op.create_index(
        "ix_product_review_embedding",
        "product_review",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """回退：逆序删除索引并还原列类型。"""

    op.drop_index(
        "ix_product_review_embedding",
        table_name="product_review",
    )
    op.drop_index(
        "ix_product_review_content_tsv",
        table_name="product_review",
    )

    op.execute("ALTER TABLE product_review ALTER COLUMN content_tsv DROP DEFAULT")
    op.execute(
        "ALTER TABLE product_review "
        "ALTER COLUMN content_tsv TYPE text "
        "USING content_tsv::text"
    )
    op.execute(
        "ALTER TABLE product_review "
        "ALTER COLUMN content_tsv SET DEFAULT ''"
    )
    op.alter_column(
        "product_review",
        "content_tsv",
        type_=sa.Text(),
        existing_type=TSVECTOR(),
        nullable=True,
        server_default=sa.text("''"),
    )
