数据表修复

# ProductReview表修复

## 问题
ProductReview表中的content_tsv字段的类型出错了，其属性现阶段为str，应该定义为tsvector，如下所示：
sa.Column(
    "content_tsv",
    TSVECTOR(),
    nullable=True,
    server_default=sa.text("''::tsvector"),
),


## 优化
此外，为了提高表的检索效率，索引优化如下所示：
创建基础外键索引
    op.create_index(
        "ix_product_review_product_id",
        "product_review",
        ["product_id"],
        unique=False,
    )

为全文检索字段创建 GIN 倒排索引
    op.create_index(
        "ix_product_review_content_tsv",
        "product_review",
        ["content_tsv"],
        unique=False,
        postgresql_using="gin",
    )

为向量列创建 HNSW 索引（基于余弦相似度 cosine）
    op.create_index(
        "ix_product_review_embedding",
        "product_review",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"ops": "vector_cosine_ops"},
    )


# 核心表之间缺少外键物理约束

sku、product_marketing、product_faq、user_review 和 product_review 这五张表都包含 product_id，且逻辑上强依赖 product 表的 product_id。当前代码只建了普通索引，没有物理外键。

需要为这 5 张子表增加 sa.ForeignKeyConstraint，并配置 ondelete="CASCADE"（当主表商品删除时，自动级联清理对应的向量、FAQ 和评论）。