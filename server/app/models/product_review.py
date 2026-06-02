"""
ProductReview ORM 模型
----------------------
定义 ``ProductReview`` 实体 —— 聚合/导入的评价记录，同时存储原始评价文本
及其向量嵌入，用于语义相似度搜索。

这是 RAG（检索增强生成）管道的核心表。在数据导入过程中，原始评价会被
切块并通过外部模型（如 OpenAI ``text-embedding-3-small``）嵌入。生成的
向量持久化到 ``embedding`` 列（pgvector 类型），原始内容存储在
``content`` 中，可选的 JSONB 元数据存储在 ``extra_data`` 中。

``content_tsv`` 列保存预计算的 tsvector 分词，用于 PostgreSQL
全文搜索，实现混合（语义 + 关键词）检索。
"""

from sqlalchemy import String, DateTime, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.config import settings


class ProductReview(Base):
    """
    含向量嵌入的评价记录，用于语义搜索。

    每行表示评价内容的一个切块/片段，已嵌入为稠密向量。``embedding`` 列
    通过 pgvector PostgreSQL 扩展支持余弦相似度查询。

    属性
    ----------
    id : int (PK)
        自增代理主键。
    product_id : str
        指向 ``product.product_id`` 的外键引用。已建索引以支持
        按产品范围的高效查询。最大长度 50。
    source : str
        来源标签，指示评价的出处（例如 "amazon"、"shopify"、"manual"）。
        最大长度 30。
    content : str
        评价文本内容（切块后的片段）。以 ``TEXT``（无界）存储。必填。
    embedding : list[float]
        由配置的嵌入模型生成的稠密向量嵌入。维度由
        ``settings.database.vector_dim`` 控制
        （默认 1536，对应 ``text-embedding-3-small``）。
        以 pgvector ``VECTOR`` 类型存储。
    extra_data : dict | None
        补充的结构化元数据，以 JSONB 持久化。该列在数据库中物理名称为
        ``metadata``（通过 ``name`` 参数指定）。可为空。
    content_tsv : TSVECTOR
        PostgreSQL 原生 tsvector 类型，预计算全文搜索分词。
        默认为 ``''::tsvector``。可为空。
    created_at : datetime
        行创建时间戳，由数据库服务器自动设置。
    updated_at : datetime
        最后更新时间戳，每次 ``UPDATE`` 时自动刷新。
    """

    __tablename__ = "product_review"

    # -- 主键 ----------------------------------------------------------------
    id: Mapped[int] = mapped_column(primary_key=True)

    # -- 外键引用 ------------------------------------------------------------
    product_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )

    # -- 评价数据 ------------------------------------------------------------
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # -- 向量嵌入 ------------------------------------------------------------
    # 维度从应用配置中读取，以便按环境调整（如使用不同的嵌入模型）。
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.database.vector_dim)
    )

    # -- 补充元数据 ----------------------------------------------------------
    # 物理存储为 "metadata" 列，以避免与 SQLAlchemy 内部的 ``metadata`` 属性冲突。
    extra_data: Mapped[dict | None] = mapped_column(JSONB, name="metadata")

    # -- 全文搜索支持 --------------------------------------------------------
    # 预计算的 tsvector 分词使 PostgreSQL 的 ``@@`` 运算符能够
    # 对评价内容执行关键词查询。
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR(), nullable=True, server_default=text("''::tsvector")
    )

    # -- 生命周期 ------------------------------------------------------------
    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
