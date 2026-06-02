# ProductReview 表修复 & 索引优化 — 需求分析

> **输入：** [SPEC.md](SPEC.md)

## 1. 功能需求

| 编号 | 需求 | 来源 |
|------|------|------|
| FR1 | `content_tsv` 列类型从 `Text`/`TEXT` 修正为 `TSVECTOR` | SPEC L3-L10 |
| FR2 | `product_review` 表新增 `product_id` 外键 BTREE 索引 | SPEC L15-L21 |
| FR3 | `product_review` 表新增 `content_tsv` 全文检索 GIN 倒排索引 | SPEC L23-L29 |
| FR4 | `product_review` 表新增 `embedding` 向量 HNSW 索引（余弦相似度） | SPEC L32-L39 |

## 2. 性能需求

- GIN 索引加速 `content_tsv @@ plainto_tsquery(...)` 全文检索查询（当前 [retriever.py](server/app/services/retriever.py#L377) 已使用此查询）
- HNSW 索引加速 `embedding <=>` 向量余弦相似度查询（当前 [retriever.py](server/app/services/retriever.py#L294) 已使用此查询）
- `product_id` BTREE 索引加速按产品过滤的 JOIN 查询

## 3. 最终交付物

| 交付物 | 说明 |
|--------|------|
| 修正后的 `product_review.py` 模型 | `content_tsv` 类型改为 `TSVECTOR()` |
| 修正后的 `20260527_0001_init_schema.py` | 初始迁移中 `content_tsv` 类型修正 |
| 新建增量迁移 `YYYYMMDD_0002_*.py` | ALTER 列类型 + 创建 3 个索引 |
| 更新的 PLAN.md | 本阶段确认后的方案文档 |

## 4. 硬约束

- **不修改业务逻辑**：`retriever.py` 的 FTS/Semantic 查询和 `import_data.py` 的触发器写入逻辑不变
- **已有数据库兼容**：已有数据的 `content_tsv` 列需通过 `USING content_tsv::tsvector` 无损转换
- **全新部署兼容**：初始迁移需同步修正，确保 `alembic upgrade head` 在空库上直接创建正确类型

## 5. 隐含要求

- `ix_product_review_product_id` 在初始迁移中已存在（[0001_init_schema.py:272-277](server/alembic/versions/20260527_0001_init_schema.py#L272-L277)），SPEC 中再次列出是为了完整性确认——若已存在则不重复创建
- `content_tsv` 的 `server_default` 需从 `''` 改为 `''::tsvector`，与 TSVECTOR 类型匹配
- 降级迁移（downgrade）需支持完整回退

## 6. 任务完成边界

- ✅ `content_tsv` 列类型在模型和迁移中均为 `TSVECTOR`
- ✅ GIN 索引 `ix_product_review_content_tsv` 存在
- ✅ HNSW 索引 `ix_product_review_embedding` 存在
- ✅ `ix_product_review_product_id` 存在（初始迁移已有，确认即可）
- ✅ `alembic upgrade head` / `alembic downgrade -1` 均无错误
- ✅ 现有测试套件零回归

## 7. 风险点

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| `ALTER COLUMN ... TYPE tsvector USING content_tsv::tsvector` 在含 NULL 值的大表上可能较慢 | 低 | 当前为开发阶段，数据量小；触发器保证了 content_tsv 始终非 NULL |
| HNSW 索引需要 pgvector 扩展支持 | 低 | 初始迁移已 `CREATE EXTENSION IF NOT EXISTS vector` |
| 初始迁移修改可能与已有部署冲突 | 低 | 初始迁移修改仅影响全新部署；已有数据库走增量迁移 |

---

## [NEEDS CLARIFICATION]

无。SPEC 中需求明确，代码库现状已探查清楚，无不确定项。
