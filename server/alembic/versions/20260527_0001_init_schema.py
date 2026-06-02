"""初始 Schema

Revision ID: 20260527_0001
Revises: (无 -- 初始迁移)
Create Date: 2026-05-27

这是引导 AuraCart 整个关系型 schema 的基础迁移。它将创建六张表：

* **product** -- 核心产品目录（每个独立产品对应一行）。
* **sku** -- 关联产品的变体级库存单位。
* **product_marketing** -- 每个产品的长篇幅营销描述。
* **product_faq** -- 每个产品的问答对。
* **user_review** -- 客户提交的带星级评分的评论。
* **product_review** -- 含 pgvector 嵌入的聚合评论内容，供语义/RAG
  搜索管线使用。

同时启用 ``vector`` PostgreSQL 扩展，以便 ``product_review.embedding``
列（维度 1024）能够存储稠密向量。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import TSVECTOR


# ---------------------------------------------------------------------------
# 版本标识符 -- Alembic 用于确定迁移顺序并将本版本链接到依赖链中。
# ---------------------------------------------------------------------------
revision: str = "20260527_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """应用初始 schema：启用 ``vector`` 扩展并创建全部六张核心表及其索引。"""

    # pgvector 扩展必须在创建任何 Vector 列之前存在。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ==================================================================
    # 表: product
    # 代表目录中可售卖商品的主实体。
    # ==================================================================
    op.create_table(
        "product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("sub_category", sa.String(length=50), nullable=True),
        sa.Column(
            "base_price", sa.Numeric(precision=10, scale=2), nullable=True
        ),
        sa.Column("image_path", sa.String(length=500), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id"),
    )

    # ==================================================================
    # 表: sku
    # 变体级库存记录（颜色/尺寸/配置）。
    # ==================================================================
    op.create_table(
        "sku",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.String(length=50), nullable=False),
        sa.Column("product_id", sa.String(length=50), nullable=False),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.Column(
            "price", sa.Numeric(precision=10, scale=2), nullable=False
        ),
        sa.Column(
            "stock",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku_id"),
    )
    # 加速按父产品查询。
    op.create_index(
        "ix_sku_product_id", "sku", ["product_id"], unique=False
    )

    # ==================================================================
    # 表: product_marketing
    # 用于展示和全文搜索的长篇幅产品描述。
    # ==================================================================
    op.create_table(
        "product_marketing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_marketing_product_id",
        "product_marketing",
        ["product_id"],
        unique=False,
    )

    # ==================================================================
    # 表: product_faq
    # 供 RAG 管线用于生成上下文相关回答的问答对。
    # ==================================================================
    op.create_table(
        "product_faq",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=50), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_faq_product_id",
        "product_faq",
        ["product_id"],
        unique=False,
    )

    # ==================================================================
    # 表: user_review
    # 客户提交的评分与评论文本。
    # ==================================================================
    op.create_table(
        "user_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=50), nullable=False),
        sa.Column("nickname", sa.String(length=100), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_review_product_id",
        "user_review",
        ["product_id"],
        unique=False,
    )

    # ==================================================================
    # 表: product_review
    # 聚合评论内容，包含稠密向量嵌入（dim=1024），供余弦相似度语义搜索
    # 使用。``source`` 列用于区分评论来源
    # （例如 'marketing'、'faq'、'user'）。
    # ==================================================================
    op.create_table(
        "product_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "content_tsv",
            TSVECTOR(),
            nullable=True,
            server_default=sa.text("''::tsvector"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_review_product_id",
        "product_review",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    """回退初始迁移：先删除索引，再删除对应的表。

    对象按依赖关系的逆序删除（子索引和子表先于父表），以避免外键/依赖冲突。
    """

    op.drop_index(
        "ix_product_review_product_id", table_name="product_review"
    )
    op.drop_table("product_review")

    op.drop_index("ix_user_review_product_id", table_name="user_review")
    op.drop_table("user_review")

    op.drop_index("ix_product_faq_product_id", table_name="product_faq")
    op.drop_table("product_faq")

    op.drop_index(
        "ix_product_marketing_product_id", table_name="product_marketing"
    )
    op.drop_table("product_marketing")

    op.drop_index("ix_sku_product_id", table_name="sku")
    op.drop_table("sku")

    op.drop_table("product")
