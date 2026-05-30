# AuraCart 技术设计文档

---

## 1. 项目概述

AuraCart 是一个基于 RAG（检索增强生成）架构的智能导购系统。用户输入自然语言购物查询，系统自动完成意图拆解、多策略商品检索、结果融合排序、以及 LLM 推荐文案生成，最终通过 SSE 流式返回给客户端。

**技术栈:** Python 3.12+ / FastAPI / SQLAlchemy (async) / PostgreSQL + pgvector + zhparser / OpenAI 兼容 API (LLM + Embedding)

---

## 2. 系统架构

### 2.1 分层架构

```
┌─────────────────────────────────────────────┐
│                  API 路由层                  │
│   search.py    products.py    admin.py       │
├─────────────────────────────────────────────┤
│                RAG 管线层                     │
│   prompt.py    merger.py    generator.py     │
├─────────────────────────────────────────────┤
│                服务层                         │
│   embedding.py  llm.py  query_parser.py     │
│   retriever.py  sync.py  import_data.py     │
├─────────────────────────────────────────────┤
│                数据模型层                     │
│   Product  Sku  ProductMarketing            │
│   ProductFaq  UserReview  ProductReview     │
├─────────────────────────────────────────────┤
│                基础设施层                     │
│   config.py    database.py    logging.py    │
└─────────────────────────────────────────────┘
```

### 2.2 模块职责与依赖关系

| 模块 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| 应用入口 | `app/main.py` | FastAPI 实例创建、路由注册、lifespan 管理、静态文件挂载 | api/\*, services/sync, config |
| 配置 | `app/config.py` | YAML 配置加载、环境变量覆盖、配置单例 | pyyaml, pydantic |
| 数据库 | `app/database.py` | 异步引擎创建、会话工厂、`get_db` 依赖注入、ORM Base 类 | config |
| 日志 | `app/core/logging.py` | structlog 结构化日志配置（控制台 + 文件） | — |

**API 路由层:**

| 模块 | 文件 | 注册的路由 |
|------|------|-----------|
| 搜索 | `app/api/search.py` | `GET /api/search` (stream=true\|false) |
| 商品 | `app/api/products.py` | `GET /api/products/{id}`, `GET /api/products/image/{id}`, `GET /api/sku/{id}` |
| 管理 | `app/api/admin.py` | `POST /api/admin/sync` |

**RAG 管线层:**

| 模块 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| 提示词 | `app/rag/prompt.py` | 管理 LLM 提示词模板（查询解析 / 推荐生成） | — |
| 合并器 | `app/rag/merger.py` | RRF 倒数排序融合，合并多路检索结果 | services/retriever (SKUHit) |
| 生成器 | `app/rag/generator.py` | 构建上下文、调用 LLM 流式生成推荐文案 | services/llm, prompt |

**服务层:**

| 模块 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| 嵌入服务 | `app/services/embedding.py` | OpenAI 兼容 Embedding API 封装 | httpx (via openai) |
| LLM服务 | `app/services/llm.py` | OpenAI 兼容 Chat/Stream API 封装 | httpx (via openai) |
| 查询解析 | `app/services/query_parser.py` | 调用 LLM 将自然语言拆解为 SubQuery 列表 | llm, prompt |
| 检索器 | `app/services/retriever.py` | 多策略检索执行（语义/关键词/结构化过滤） | embedding, database |
| 同步 | `app/services/sync.py` | 增量数据同步：源表变更 → 重新嵌入 → 更新向量表 | embedding, models |
| 数据导入 | `app/services/import_data.py` | JSON 批量导入、文本分块、批量嵌入 | embedding, models |

**数据模型层（6 张表）:**

| 模型 | 表 | 用途 |
|------|-----|------|
| `Product` | `product` | 商品主数据（标题/品牌/品类/价格/图片） |
| `Sku` | `sku` | SKU 变体（属性 JSONB / 价格 / 库存） |
| `ProductMarketing` | `product_marketing` | 营销描述长文本 |
| `ProductFaq` | `product_faq` | 问答对 |
| `UserReview` | `user_review` | 用户评价 |
| `ProductReview` | `product_review` | 聚合内容 + pgvector 嵌入（检索目标表） |

六表关系:

```
product ──1:N── sku
product ──1:N── product_marketing
product ──1:N── product_faq
product ──1:N── user_review
product ──1:N── product_review  (向量检索目标)
```

`product_review` 是检索的唯一目标表。`sync.py` 负责将 marketing/faq/user_review 三表的内容嵌入后写入 product_review，`import_data.py` 在初始化时批量完成此过程。

---

## 3. 核心接口与实现思路

### 3.1 GET /api/search — 全链路 RAG 检索

**路径:** 完整 RAG 管线，支持 SSE 流式 (`stream=true`) 与 JSON 非流式 (`stream=false`) 两种返回模式。流式模式下通过 SSE 实时推送每个阶段的处理结果。

**五阶段流水线:**

```
用户查询
  │
  ▼
阶段1: QueryParser.parse(q)
  │   LLM 拆解自然语言 → List[SubQuery]
  │   SSE事件: "sub_queries"
  ▼
阶段2: Retriever.retrieve(sub_queries)
  │   并行执行 keyword 检索 + semantic 检索
  │   各返回 List[SKUHit]
  ▼
阶段3: Merger.merge(keyword, semantic) → _get_skus()
  │   RRF 融合排序 → 按 sku_id 查 DB 补全商品信息
  │   SSE事件: "products"
  ▼
阶段4: Generator.generate(skus, q)
  │   构建上下文 → LLM 流式生成推荐文案
  │   SSE事件: "reasoning" (逐token)
  ▼
阶段5: SSE事件: "done"
```

**阶段 1 — 查询解析:**

`QueryParser` 使用 `QUERY_PARSE_SYSTEM` 提示词，指导 LLM 将自然语言查询拆解为 JSON 数组。每条子查询标注策略类型：

| strategy | 用途 | 示例 |
|----------|------|------|
| `semantic` | 模糊主观评价 → 向量相似度 | "保湿效果好""充电速度快" |
| `keyword` | 具体品类/品牌 → 全文搜索 | "防晒霜""蓝牙耳机" |
| `structured_filter` | 可结构化字段 → SQL WHERE | price < 200, brand NOT IN [...] |

`structured_filter` 子查询会进一步标记 field / operator / value / expanded_values，供检索阶段转换为 SQL 硬约束。

解析结果去除 markdown 代码围栏后反序列化为 `list[SubQuery]` 数据类。

**阶段 2 — 多策略检索:**

`Retriever.retrieve()` 首先从所有 sub_queries 中提取 `structured_filter` 生成 `Filters`（硬约束集合），然后按 strategy 分为两组并行执行：

- **关键词检索** (`_keyword_search`): 对每个 keyword 子查询，优先使用 PostgreSQL `tsvector` + `plainto_tsquery` 进行中文全文搜索（先尝试 `chinese` 配置，失败则 `simple`），无结果时降级为 `ILIKE` 模糊匹配。多子查询结果按 sku_id 去重保留最高分。

- **语义检索** (`_semantic_search`): 对每个 semantic 子查询独立生成 Embedding，各计算 `1 - (embedding <=> query_vector)` 余弦相似度，综合得分为多个子查询得分的 SUM，按 sku_id GROUP BY。

两路检索的 SQL 骨架相同，均为三表 JOIN：
```sql
SELECT s.sku_id, p.product_id, <score_expression>
FROM product_review pr
JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE
JOIN sku s ON s.product_id = p.product_id AND s.is_active = TRUE
[WHERE <hard_filters>]
```

**阶段 3 — RRF 融合与数据补全:**

`Merger.merge()` 对 keyword 和 semantic 两路 `list[SKUHit]` 执行 RRF（Reciprocal Rank Fusion）：

```
RRF(sku) = Σ 1/(k + rank_i)    k=60
```

RRF 仅依赖排名位置而非原始分数，天然适合异构检索源融合。融合后按 RRF 得分降序，截取 top-N（`final_sku_limit`, 默认 10）。

`_get_skus()` 按 sku_id 列表批量查询 SKU 表并 JOIN product 表，一次 SQL 完成数据补全，返回包含 product 字段（product_id/title/brand/category/sub_category/base_price）和 SKU 字段（sku_id/properties/price/stock）的扁平列表，保持 RRF 排序顺序。

**阶段 4 — LLM 推荐生成:**

`Generator._build_context()` 将扁平 SKU 列表按 product_id 分组，渲染为带编号的文本块（商品标题 → 品牌/品类/价格概要 → 各 SKU 明细），注入 `GENERATOR_SYSTEM` 提示词模板。

LLM 约束：只能使用提供的商品信息、禁止编造价格/库存/功能、诚实告知数据不足、自然导购语气。通过 `chat_stream` 逐 token 流式输出，支持超时控制。

### 3.3 GET /api/products/{product_id}

查询 `product` 表返回 `ProductInfo` schema（product_id/title/brand/category/sub_category/base_price），不含 SKU 列表和图片路径。商品不存在或已停用时返回 404。

### 3.4 GET /api/products/image/{product_id}

查询 `product.image_path`，将相对路径解析为项目根目录下的绝对路径，通过 `FileResponse` 返回图片文件。商品不存在或文件不存在时返回 404。

### 3.5 GET /api/sku/{sku_id}

查询 `sku` 表返回 `SkuOut` schema（sku_id/properties/price/stock）。SKU 不存在或已停用时返回 404。

### 3.6 POST /api/admin/sync

创建 `SyncService` 实例并调用 `run_once()`，手动触发一次增量同步。背景：应用启动时通过 lifespan 启动 `run_loop()` 后台任务，每 2 秒轮询一次，自动检测源表变更并更新向量表。本接口用于需要立即同步的场景。

---

## 4. 核心接口调用链路时序

### 4.1 全链路检索 (GET /api/search?stream=true)

```
Client                    search.py               QueryParser           Retriever              Merger           Generator          LLM/Embedding         PostgreSQL
  │                          │                        │                     │                    │                  │                     │                   │
  │──GET /api/search─────────▶│                        │                     │                    │                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │─────parse(q)──────────▶│                     │                    │                  │                     │                   │
  │                          │                        │──chat_stream()──────│────────────────────│──────────────────│────────────────────▶│                   │
  │                          │                        │◀─token stream───────│────────────────────│──────────────────│────────────────────│                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │◀───List[SubQuery]──────│                     │                    │                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │◀──SSE: sub_queries──────│                        │                     │                    │                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │──retrieve(subs,top_k)──────────────────────▶│                    │                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │                        │                     │──embed_batch()──────────────────────────────────────────▶│                   │
  │                          │                        │                     │◀──vectors────────────────────────────────────────────────│                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │                        │                     │──SQL: semantic ──────────────────────────────────────────────────────────▶│
  │                          │                        │                     │──SQL: keyword  ──────────────────────────────────────────────────────────▶│
  │                          │                        │                     │◀──rows───────────│──────────────────────────────────────────────────────│
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │◀──{"keyword":[...], "semantic":[...]}──────│                    │                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │──merge(kw, sem)─────────────────────────────────────────────▶│                  │                     │                   │
  │                          │◀──List[SKUHit] (RRF)────────────────────────────────────────│                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │──_get_skus(skuhits)──────────────────────────────────────────────────────────────────────────────────────────────────▶│
  │                          │◀──List[dict] (SKU+product)────────────────────────────────────────────────────────────────────────────────────────────│
  │                          │                        │                     │                    │                  │                     │                   │
  │◀──SSE: products─────────│                        │                     │                    │                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │──generate(skus, q)──────────────────────────────────────────────────▶│                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │                          │                        │                     │                    │──_build_context()│                     │                   │
  │                          │                        │                     │                    │──chat_stream()───│────────────────────▶│                   │
  │                          │                        │                     │                    │◀─token stream────│◀────────────────────│                   │
  │                          │◀──async token stream──────────────────────────────────────────────│                  │                     │                   │
  │                          │                        │                     │                    │                  │                     │                   │
  │◀──SSE: reasoning (×N)──│                        │                     │                    │                  │                     │                   │
  │◀──SSE: done─────────────│                        │                     │                    │                  │                     │                   │
```

### 4.2 数据同步链路

```
lifespan (后台)            SyncService               EmbeddingService              PostgreSQL
  │                          │                           │                            │
  │──run_loop()─────────────▶│                           │                            │
  │                          │                           │                            │
  │                    ┌────▶│                           │                            │
  │                    │     │──pg_advisory_lock(12345)──────────────────────────────▶│
  │                    │     │                           │                            │
  │                    │     │──_sync_product()          │                            │
  │                    │     │  查找 is_active=F 的产品   │                            │
  │                    │     │  删除对应 product_review ──────────────────────────────▶│
  │                    │     │                           │                            │
  │                    │     │──_sync_table(ProductMarketing)                         │
  │                    │     │  查找 updated_at > last_sync 的记录                    │
  │                    │     │──embed(description)──────▶│                            │
  │                    │     │◀──vector─────────────────│                            │
  │                    │     │  DELETE + INSERT product_review ───────────────────────▶│
  │                    │     │                           │                            │
  │                    │     │──_sync_faq()              │                            │
  │                    │     │──_sync_table(UserReview)  │   (同上流程)               │
  │                    │     │                           │                            │
  │                    │     │──pg_advisory_unlock(12345)────────────────────────────▶│
  │                    │     │──COMMIT───────────────────────────────────────────────▶│
  │                    │     │                           │                            │
  │                    │     │──sleep(2s)                │                            │
  │                    └─────┤                           │                            │
  │                          │                           │                            │
```

### 4.3 数据导入链路

```
scripts/import_data.py       DataImporter            EmbeddingService              PostgreSQL
  │                             │                        │                            │
  │──clear_all()───────────────▶│──DELETE ALL ──────────────────────────────────────▶│
  │                             │                        │                            │
  │──import_json_dir(dir)──────▶│                        │                            │
  │                             │  遍历 JSON 文件         │                            │
  │                             │  解析 product/sku/     │                            │
  │                             │    marketing/faq/review │                            │
  │                             │                        │                            │
  │                             │──INSERT product/sku ───────────────────────────────▶│
  │                             │                        │                            │
  │                             │──chunk_product()       │                            │
  │                             │  将 product 数据拆为    │                            │
  │                             │  (source, text, meta)  │                            │
  │                             │  元组列表              │                            │
  │                             │                        │                            │
  │                             │──embed_batch(texts)───▶│                            │
  │                             │◀──vectors─────────────│                            │
  │                             │                        │                            │
  │                             │──批量 INSERT product_review ───────────────────────▶│
  │                             │                        │                            │
  │◀──count────────────────────│                        │                            │
```

---

## 5. 关键设计决策

### 5.1 为什么检索目标表是 product_review 而不是 product

商品搜索需要理解"用户评价中的使用感受""营销描述中的卖点""FAQ 中的功能说明"等语义内容，这些信息分布在 marketing/faq/review 三张源表中。将它们嵌入后统一存入 product_review，检索时只需查一张表，简化 SQL 并统一得分口径。

### 5.2 为什么 RRF 以 SKU 为粒度

同一 product 的不同 SKU 可能在价格、容量、颜色等属性上有显著差异，符合用户查询的 SKU 和不符合的 SKU 应区分对待。RRF 对 sku_id 去重合并，确保最终排序反映的是具体 SKU 的匹配度而非 product 整体。

### 5.3 为什么 sync 使用 PostgreSQL 咨询锁

后台 sync 和应用服务运行在同一进程内（通过 lifespan 启动 asyncio background task）。咨询锁确保多实例部署时只有一个实例执行同步，避免并发写入冲突。

### 5.4 为什么 query_parser 使用流式调用

LLM 的非流式 chat 需等待完整响应（约 18s），而流式 `chat_stream` 首 token 延迟约 10.5s，显著降低用户感知等待时间。收集全部 token 后统一解析 JSON。

### 5.5 关键词检索的降级策略

zhparser 中文分词扩展为可选依赖。关键词检索先尝试 `chinese` 配置，失败则 `simple`，再失败则降级为 SQL `ILIKE` 模糊匹配，确保在不同部署环境下均有可用结果。
