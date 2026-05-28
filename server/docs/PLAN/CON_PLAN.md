# 系统骨架

> 基于 DEFINE.md + SPEC.md + DATA_INPUT.md 的已确认项。所有决策点已确认并整合，见末尾 §7 决策日志。

## 1. 模块拆分

| 模块 | 职责 | 边界 |
| :--- | :--- | :--- |
| **api/** | HTTP 路由 + SSE 端点 | 仅参数校验和响应编排，不含业务逻辑 |
| **services/** | 业务逻辑层 | query 拆解(LLM)、混合检索编排、embedding、LLM 调用、数据同步、数据导入 |
| **rag/** | RAG 管线 | 检索结果 → Prompt 组装 → LLM 流式生成，与 api 解耦 |
| **models/** | ORM 模型 | product / sku / product_marketing / product_faq / user_review(五源表) + product_review(向量表) 共六表 |
| **schemas/** | Pydantic Schema | API 契约 |
| **core/** | 配置、DB 连接、全局依赖 | 单例管理 |

**依赖方向：** `api → services → {models, rag}`，`rag → services.{embedding, llm}`，`core` 被所有模块依赖。

## 2. 目录结构

```
server/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI 入口，lifespan 启动 sync 定时器
│   ├── config.py                   # YAML → Pydantic Settings
│   ├── database.py                 # SQLAlchemy async engine + session
│   ├── api/
│   │   ├── __init__.py
│   │   ├── search.py               # GET /api/search/stream (SSE)
│   │   ├── products.py             # GET /api/products/{id}
│   │   └── admin.py                # POST /api/admin/{sync, import}
│   ├── models/
│   │   ├── __init__.py
│   │   ├── product.py              # Product ORM（基础信息）
│   │   ├── sku.py                  # Sku ORM（销售单品，含 stock）
│   │   ├── product_marketing.py    # ProductMarketing ORM（营销描述源表）
│   │   ├── product_faq.py          # ProductFaq ORM（FAQ 源表）
│   │   ├── user_review.py          # UserReview ORM（用户评价源表）
│   │   └── product_review.py       # ProductReview ORM（含 pgvector embedding）
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── product.py              # ProductOut, SkuOut, SearchRequest 等
│   ├── services/
│   │   ├── __init__.py
│   │   ├── query_parser.py         # LLM 查询拆解（prompt 驱动）
│   │   ├── embedding.py            # Embedding 生成（OpenAI 兼容）
│   │   ├── search.py               # 子查询路由 + 多策略检索 + 得分合并
│   │   ├── sync.py                 # 轮询五源表 → 更新 product_review
│   │   ├── llm.py                  # LLM 调用（Doubao，OpenAI 兼容）
│   │   └── import_data.py          # JSON → Chunking → Embedding → 五源表 + product_review 写入
│   └── rag/
│       ├── __init__.py
│       ├── retriever.py            # 单条子查询检索执行（向量/关键词/结构化过滤）
│       ├── merger.py               # 多子查询结果加权合并（含 source 权重）
│       ├── prompt.py               # Prompt 模板（查询拆解 + 推荐生成）
│       └── generator.py            # 检索结果 + Prompt → LLM 流式生成 → SSE
├── scripts/
│   └── import_data.py              # CLI 入口
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # fixtures: test DB, mock embedding/LLM
│   ├── test_import_data.py          # 数据导入 + chunking
│   ├── test_query_parser.py         # LLM 查询拆解（含展开逻辑 Q7）
│   ├── test_retriever.py            # 三种检索策略路由
│   ├── test_merger.py               # 多子查询合并 + negation 过滤
│   ├── test_search_api.py           # SSE 端到端
│   ├── test_sync.py                 # 数据同步逻辑
│   └── test_generator.py            # Prompt 组装 + LLM 生成
├── config.yaml                     # API keys, DB, 轮询间隔, source 权重, embedding 维度等
├── requirements.txt
└── ecommerce_agent_dataset/        # (已有) 不改动
```

## 3. 核心接口 / API

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/search/stream` | SSE 流式导购搜索。Query: `?q=推荐不含酒精的非日系防晒霜` |
| `GET` | `/api/products/{product_id}` | 单品详情（JOIN product + skus，实时价格/库存） |
| `POST` | `/api/admin/sync` | 手动触发一轮全量同步（product + sku + user_review → product_review） |
| `POST` | `/api/admin/import` | JSON 数据集全量导入（先清空六表再写入） |

**SSE 事件流格式：**

```
event: sub_queries     data: [{"text":"需要防晒霜","strategy":"semantic"}, ...]  (可选，调试用)
event: products        data: [{"product_id":"...", "title":"...", "price":199, ...}]
event: reasoning       data: "为您找到了以下商品..."   (逐 token 流式)
event: done            data: {}
```

## 4. 关键数据结构

### 4.1 product 表（关系表）

```sql
CREATE TABLE product (
    id            SERIAL PRIMARY KEY,
    product_id    VARCHAR(50) UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    brand         VARCHAR(100),
    category      VARCHAR(50),
    sub_category  VARCHAR(50),
    base_price    DECIMAL(10,2),
    image_path    VARCHAR(500),
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()       -- 外部系统更新时刷新，sync 据此检测变更
);
```

### 4.2 sku 表（关系表，外部系统可写）

```sql
CREATE TABLE sku (
    id            SERIAL PRIMARY KEY,
    sku_id        VARCHAR(50) UNIQUE NOT NULL,
    product_id    VARCHAR(50) NOT NULL REFERENCES product(product_id),
    properties    JSONB,                        -- {"容量":"30ml"} 或 {"颜色":"黑","存储":"256GB"}
    price         DECIMAL(10,2) NOT NULL,
    stock         INT DEFAULT 0,
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()       -- 外部系统更新
);
```

### 4.3 user_review 表（关系表，评论源表）

> 新增：对应 Q5 方案 A。外部系统写入此表，sync 服务轮询检测新评论后 embedding 写入 product_review。

```sql
CREATE TABLE user_review (
    id            SERIAL PRIMARY KEY,
    product_id    VARCHAR(50) NOT NULL REFERENCES product(product_id),
    nickname      VARCHAR(100),
    rating        INT CHECK (rating >= 1 AND rating <= 5),
    content       TEXT NOT NULL,
    is_active     BOOLEAN DEFAULT TRUE,         -- 外部系统可软删除
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);
```

### 4.3a product_marketing 表（关系表，营销描述源表）

> 新增（方案A）：为 marketing_description 补源表，支持增量更新，与 user_review 模式一致。

```sql
CREATE TABLE product_marketing (
    id            SERIAL PRIMARY KEY,
    product_id    VARCHAR(50) NOT NULL REFERENCES product(product_id),
    description   TEXT NOT NULL,                   -- 营销描述原文
    is_active     BOOLEAN DEFAULT TRUE,            -- 外部系统可软删除
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);
```

### 4.3b product_faq 表（关系表，FAQ 源表）

> 新增（方案A）：为 official_faq 补源表，每 FAQ 一行，支持独立增删改。

```sql
CREATE TABLE product_faq (
    id            SERIAL PRIMARY KEY,
    product_id    VARCHAR(50) NOT NULL REFERENCES product(product_id),
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    is_active     BOOLEAN DEFAULT TRUE,            -- 外部系统可软删除单条 FAQ
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);
```

### 4.4 product_review 表（向量表，pgvector）

```sql
CREATE TABLE product_review (
    id            SERIAL PRIMARY KEY,
    product_id    VARCHAR(50) NOT NULL REFERENCES product(product_id),
    source        VARCHAR(30) NOT NULL,          -- 'marketing' | 'faq' | 'user_review'
    content       TEXT NOT NULL,                 -- 嵌入前的自然语言文本
    content_tsv   tsvector,                      -- 中文分词全文检索（zhparser + jieba），由触发器自动更新
    embedding     vector({dim}),                 -- 维度由 config.yaml 配置，运行时建表/迁移
    metadata      JSONB,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);
-- 向量索引：HNSW（支持增量写入，适合同步场景），Q12 已确认
CREATE INDEX ON product_review USING hnsw (embedding vector_cosine_ops);
-- 全文检索索引：zhparser 中文分词，Q8 已确认
CREATE INDEX ON product_review USING gin (content_tsv);
-- 加速 product_id + source 联合过滤
CREATE INDEX ON product_review (product_id, source);
```

| source | 源表 | metadata | 说明 |
| :--- | :--- | :--- | :--- |
| `marketing` | `product_marketing` | `{}` | 每商品 1 条 |
| `faq` | `product_faq` | `{"question": "..."}` | 每 FAQ 1 条 |
| `user_review` | `user_review` | `{"nickname": "...", "rating": 5}` | 每条评价 1 条 |

> basic_info（title/brand/category/sub_category）不进入向量索引。这些字段均为结构化数据，由 LLM 查询展开（Q7）+ SQL 精确过滤覆盖，语义向量检索对其无增益。

### 4.5 Chunking 策略（import_data / sync 写入 product_review 时执行）

| source | content 模板 |
| :--- | :--- |
| `marketing` | `"{marketing_description}"` |
| `faq` | `"问题：{question}\n回答：{answer}"` |
| `user_review` | `"用户{nickname}评分{rating}分，评价：{content}"` |

> 每个商品产生 1 + N(faq) + M(review) 条 product_review 记录。约 100 商品 × 平均 7 条 ≈ 700 条向量。

### 4.6 检索时 source 权重

> 对应 Q3：不同来源在向量检索得分上施加权重，official_faq 可信度最高，user_review 主观性最强权重最低。

```yaml
# config.yaml
search:
  source_weights:
    faq:           1.0
    marketing:     0.9
    user_review:   0.6
```

合并公式：`final_score = cosine_similarity × source_weight`，同 product_id 取 top-K 均值后参与跨子查询合并。

### 4.7 子查询数据结构

```python
@dataclass
class SubQuery:
    text: str                    # "需要防晒霜"
    strategy: str                # "semantic" | "keyword" | "structured_filter"
    negation: bool = False       # True → 硬过滤
    field: str | None = None     # structured_filter 时指定字段
    operator: str | None = None  # "eq" | "lt" | "gt" | "contains" | "not_contains"
    value: str | float | None = None
    expanded_values: list[str] | None = None  # Q7: LLM 展开的知识值列表
    # 例："不要日系品牌" → field="brand", operator="not_in",
    #     expanded_values=["SK-II","资生堂","CPB","雪肌精","DHC","FANCL","植村秀","SUQQU",...]
```

> query_parser 的 LLM prompt 负责从原始查询中产出 `List[SubQuery]`。
> **Q7 方案A — 查询展开**：当用户查询涉及需要世界知识的属性（如"日系品牌""适合油皮"），LLM 在拆解时展开为具体值列表存入 `expanded_values`，检索时走结构化 `IN` / `NOT IN` 过滤。对 LLM 知识覆盖不到的小众品牌，由语义检索兜底（见 §5.1 检索路由）。

### 4.8 Pydantic Schema

```python
class ProductOut:
    product_id: str
    title: str
    brand: str | None
    category: str | None
    base_price: float | None
    image_url: str | None
    stock: int | None
    skus: list[SkuOut]

class SkuOut:
    sku_id: str
    properties: dict
    price: float
    stock: int
```

## 5. 主功能链路时序

### 5.1 搜索链路

**超时策略（Q10 已确认）：**
| 阶段 | 超时 | 降级策略 |
| :--- | :--- | :--- |
| 查询拆解 LLM | 3s | 失败 → 原始查询整体走 semantic 检索 |
| 向量检索（单条） | 1s | 失败 → 该子查询结果为空 |
| 关键词检索（单条） | 1s | 失败 → 该子查询结果为空 |
| 推荐生成 LLM（流式） | 15s | 失败 → SSE 仅返回 products，无 reasoning |
| 总请求 | 30s | 超时 → SSE 发送已收集结果 + done |

**检索阈值（Q9 已确认）：**
- 每个子查询取 top-K=20 条
- 合并后最终返回给 generator 的商品数上限 N=10
- 检索结果不足（< 3 个）时触发降级：放宽 price 范围为 ±30% + 忽略最低权重子查询

```
User      api/search    query_parser(LLM)     retriever              merger             generator(LLM)
 |             |              |                    |                    |                    |
 |-- SSE ----->|              |                    |                    |                    |
 |   ?q=...    |-- parse() -->|                    |                    |                    |
 |             |   prompt:    |                    |                    |                    |
 |             |   "你是意图拆解专家,将用户查询拆分为单一意图子句,         |                    |
 |             |    标注strategy(semantic/keyword/structured_filter),     |                    |
 |             |    negation, field, operator, value"                     |                    |
 |             |   Q7: 涉及世界知识的属性(如"日系品牌"),展开为具体值列表   |                    |
 |             |   expanded_values=["SK-II","资生堂","CPB",...]          |                    |
 |             |              |                    |                    |                    |
 |             |<-- List[SubQuery] (超时3s, 失败→整体semantic)          |                    |
 |             |              |                    |                    |                    |
 |             |-- SSE: sub_queries (可选, 调试用) |                    |                    |
 |             |              |                    |                    |                    |
 |             |-- for each sub_query (non-negation first, K=20):       |                    |
 |             |   retriever.route(sub_query) ----->|                    |                    |
 |             |              |                    |                    |                    |
 |             |              |   semantic: embed() + pgvector cosine (HNSW)               |
 |             |              |   keyword:  tsquery @@ content_tsv (zhparser 中文分词)      |
 |             |              |            + ILIKE on product.brand/product.category       |
 |             |              |   structured: WHERE field op value                         |
 |             |              |     (expanded_values → WHERE brand IN (...) / NOT IN (...)) |
 |             |              |   超时1s, 失败→空结果  |                    |                    |
 |             |<-- hits: [{product_id, score, source}] |                    |                    |
 |             |              |                    |                    |                    |
 |             |-- merger.merge(all_hits, negation_queries, topK=20, finalN=10) ---------->|
 |             |   step1: 应用 source_weight (config.yaml)              |                    |
 |             |   step2: 同 product_id 聚合 (top-K 均值)               |                    |
 |             |   step3: 多子查询得分加权平均合并                       |                    |
 |             |   step4: negation 硬过滤 (直接排除)                    |                    |
 |             |   step5: 结果 < 3 → 降级 (放宽条件)                    |                    |
 |             |<-- ranked_products (max 10) --------------------------|                    |
 |             |              |                    |                    |                    |
 |             |-- SSE: products                   |                    |                    |
 |             |              |                    |                    |                    |
 |             |-- generator.generate(products, query) -------------------------------->|
 |             |   prompt: "你是导购专家,基于以下商品信息回答用户,        |                    |
 |             |            不得编造价格/库存/功能"                      |                    |
 |             |   (超时15s, 失败→仅返回products无reasoning)            |                    |
 |             |<-- SSE: reasoning (逐 token) ----------------------------------------|
 |             |-- SSE: done                       |                    |                    |
```

### 5.2 数据同步链路

> **核心原则**：product + sku + product_marketing + product_faq + user_review 为真相源（五源表），product_review 为搜索副本。
> - product 的结构化字段（title/brand/category/sub_category）不进入向量索引，搜索时直接 SQL 查询，变更无需同步
> - price/stock 变更（sku 表）→ 无需更新向量，搜索时 JOIN sku 获取实时价格
> - 文本内容变更（product_marketing.description / product_faq.answer / user_review.content）→ 需 re-embedding 更新 product_review
> - is_active=FALSE → 从 product_review 删除对应行

```
sync.py (每 N 秒)                 DB                           embedding.py
 |                                 |                                |
 |-- 获取 advisory lock (防重入)    |                                |
 |                                 |                                |
 |-- 轮询 product 变更:            |                                |
 |   WHERE updated_at > last_sync  |                                |
 |   is_active=FALSE              |-- DELETE FROM product_review   |
 |                                  |   WHERE product_id = ?        |
 |                                  |   (删除该商品所有 source 行)   |                |
 |   title/brand/cat 变更           |-- 无操作 (搜索时直接 SQL        |
 |                                  |   查询 product 表获取)         |
 |                                 |                                |
 |-- 轮询 product_marketing 变更:  |                                |
 |   WHERE updated_at > last_sync  |                                |
 |   新增 (INSERT)                  |-- INSERT product_review        |
 |                                  |   source='marketing'           |
 |                                  |   (embed description) ------->|-- embed() -->|
 |   is_active=FALSE (软删除)       |-- DELETE FROM product_review   |
 |                                  |   WHERE product_id=? AND       |
 |                                  |   source='marketing'           |
 |   description 变更               |-- UPDATE product_review        |
 |                                  |   (re-embed) ---------------->|-- embed() -->|
 |                                 |                                |
 |-- 轮询 product_faq 变更:        |                                |
 |   WHERE updated_at > last_sync  |                                |
 |   新增 FAQ                       |-- INSERT product_review        |
 |                                  |   source='faq'                 |
 |                                  |   (embed q+a) --------------->|-- embed() -->|
 |   is_active=FALSE (软删除单条)   |-- DELETE FROM product_review   |
 |                                  |   WHERE id 匹配                |
 |   question/answer 变更           |-- UPDATE product_review        |
 |                                  |   (re-embed) ---------------->|-- embed() -->|
 |                                 |                                |
 |-- 轮询 sku 变更:                |                                |
 |   WHERE updated_at > last_sync  |                                |
 |   price/stock 变更              |-- 无操作 (搜索时 JOIN 获取)     |
 |   is_active=FALSE               |-- 无操作 (JOIN 时自动过滤)      |
 |   (SKU 增删不影响 product_review) |                                |
 |                                 |                                |
 |-- 轮询 user_review 变更:        |                                |
 |   WHERE updated_at > last_sync  |                                |
 |   新增评论                       |-- INSERT product_review        |
 |                                  |   (embed content) ----------->|-- embed() -->|
 |   is_active=FALSE (软删除)       |-- DELETE FROM product_review   |
 |   content 变更                   |-- UPDATE product_review        |
 |                                  |   (re-embed) ---------------->|-- embed() -->|
 |                                 |                                |
 |-- 更新 last_sync 时间戳          |                                |
 |-- 释放 advisory lock             |                                |
```

### 5.3 数据导入链路

```
CLI / POST /api/admin/import    import_data.py       embedding.py        DB
 |                                   |                    |                |
 |-- trigger ----------------------->|                    |                |
 |                                   |-- 清空 product/sku/product_marketing/product_faq/user_review/product_review  |
 |                                   |-- 遍历 JSON 文件    |                |
 |                                   |-- INSERT product/sku/product_marketing/product_faq  |
 |                                   |   (写入五张源表)   |--------------->|
 |                                   |-- 按 §4.5 构造 chunk|                |
 |                                   |   (每商品 1+N+M 条) |                |
 |                                   |-- 批量 embed() ---->|                |
 |                                   |<-- vectors ---------|                |
 |                                   |-- INSERT product_review ----------->|
 |<-- {"imported": 100}              |                    |                |
```

## 6. 权限、隔离、边界与工程策略

| 层面 | 约定 |
| :--- | :--- |
| **认证** | 不做。admin 端点仅 `127.0.0.1` 监听 |
| **外部系统边界** | 外部系统写入 `product`、`sku`、`product_marketing`、`product_faq`、`user_review` 五张源表。`product_review` 是本系统内部表，外部不可见 |
| **LLM 调用边界** | LLM 两次调用：① query_parser（查询拆解+知识展开）、② generator（推荐理由生成）。两次调用的 prompt 均硬约束"不得编造"。LLM 不直接访问 DB |
| **数据一致性** | `product + sku + user_review` 为真相源；`product_review` 为搜索副本。秒级轮询窗口内允许短暂不一致。搜索时 JOIN sku 获取实时价格/库存 |
| **反幻觉** | generator prompt 注入检索结果的全部结构化字段（价格、库存、SKU），指令"只能使用以上信息，不得编造优惠券/功能/库存" |
| **静态文件** | `StaticFiles` 挂载 `ecommerce_agent_dataset/`，返回相对路径，前端拼接 base URL（如 `/static/{image_path}`）。不做图片 embedding |
| **并发** | 搜索无状态可水平扩展；sync 单实例（DB advisory lock 防重入） |
| **降级** | embedding 不可用 → 纯关键词检索；LLM 不可用 → 仅返回检索结果无推荐理由；pgvector 不可用 → 503 |
| **超时** | 查询拆解 3s / 检索 1s / 推荐生成 15s / 总请求 30s（Q10）。超时后 SSE 发送已收集结果 |
| **日志** | structlog JSON 格式，记录：请求耗时、LLM 调用 token 数、检索命中数、超时/降级事件。生产可接入 ELK/Loki |
| **启动行为** | 不自动导入数据（Q11，防误覆盖），需手动调用 `POST /api/admin/import` 或 CLI 脚本 |

---

## 7. 已确认决策日志

| # | 问题 | 决策 | 落地点 |
| :--- | :--- | :--- | :--- |
| Q1 | 向量数据库选型 | **pgvector** | PostgreSQL 统一管理，免去额外服务运维 |
| Q2 | 流式协议 | **SSE** | 比 WebSocket 更轻量，单向推送够用 |
| Q3 | 轮询间隔 | **秒级**（`config.yaml` `sync_interval_s`） | sync.py 定时轮询 `updated_at` |
| Q4 | 商品图片处理 | **不做 embedding，仅静态文件返回** | `StaticFiles` 挂载，API 返回相对路径 |
| Q5 | 用户评价同步 | **外部写入 `user_review` 源表，本系统轮询检测** | sync.py → embed → product_review |
| Q6 | 商品上下架 | **`is_active` 字段软控制** | sync.py 检测 is_active=FALSE → 从 product_review 删除 |
| Q7 | 品牌-产地知识关系 | **方案A：LLM 查询展开为主 + 语义兜底** | `expanded_values` 字段，LLM 展开具体品牌列表走结构化过滤 |
| Q8 | 关键词检索方案 | **tsvector + zhparser 中文分词** | product_review.content_tsv 列 + GIN 索引 |
| Q9 | 检索阈值 | **K=20, N=10, <3 触发降级** | merger.py 参数化，降级放宽 price ±30% |
| Q10 | 超时策略 | **拆解3s / 检索1s / 生成15s / 总30s** | 各服务层 asyncio.timeout，失败走降级 |
| Q11 | 数据库初始化 | **方案B：手动显式导入** | 启动不自动导入，需手动调用 import 接口或 CLI |
| Q12 | 向量索引类型 | **HNSW** | 支持增量写入，适合同步场景 |
| Q13 | marketing/FAQ 源表 | **方案A：新增 product_marketing + product_faq 两张独立源表** | 与 user_review 模式一致，五源表均可增量更新 |

---

## 8. 方案主要优点

1. **统一数据存储（PostgreSQL + pgvector）**  
   关系数据和向量数据在同一数据库中，免去多数据库运维复杂度。搜索时直接 JOIN product/sku 获取实时价格和库存，天然保证数据一致性。

2. **三种检索策略互补**  
   - 语义检索（向量，仅非结构化文本）：覆盖"适合油皮的洗面奶""不油腻"等模糊主观意图  
   - 关键词检索（tsvector + zhparser + ILIKE）：覆盖评价内容关键词 + 品牌/品类的模糊匹配  
   - 结构化过滤（SQL + expanded_values）：覆盖价格范围、品牌精确值、SKU 属性等客观条件  
   检索策略由 LLM 在查询拆解阶段自动标注，无需人工规则维护。basic_info 纯结构化字段不进向量库，职责分明。

3. **LLM 查询展开（Q7 方案A）弥合知识鸿沟**  
   "不要日系品牌"这类需要世界知识的查询，由 LLM 展开为具体品牌列表走结构化过滤，精确高效；小众品牌由语义检索兜底。

4. **源表/副本分离架构**  
   五张源表（product / sku / product_marketing / product_faq / user_review）由外部系统管理，product_review 为搜索副本（仅存非结构化文本向量）。product 的结构化字段变更无需 re-embedding，价格/库存变更 JOIN 实时获取，同步开销低。

5. **完整的降级链路**  
   查询拆解失败 → 整体语义检索；embedding 不可用 → 纯关键词检索；LLM 不可用 → 仅返回检索结果。无单点故障导致服务完全不可用。

6. **流式 SSE 响应**  
   先返回检索到的商品列表，再流式返回推荐理由，用户感知延迟低。

7. **数据规模友好**  
   约 100 商品 × ~7 条 chunk ≈ 700 条向量（仅非结构化文本），HNSW 索引完全在内存中，检索延迟 < 10ms。无需分布式向量数据库。

---

## 9. 风险与缓解措施

| 风险 | 等级 | 影响 | 缓解措施 |
| :--- | :--- | :--- | :--- |
| **LLM 查询展开遗漏品牌** | 中 | "不要日系品牌"的展开列表不完整，漏掉小众品牌 | 关键词检索兜底（ILIKE + tsquery 直接在 product 表查询 brand 字段）；prompt 中要求 LLM 尽可能全面列举 |
| **中文分词效果不确定** | 中 | zhparser + jieba 对电商领域分词精度影响关键词检索召回 | 保留 ILIKE 作为补充；tsquery 使用 `to_tsquery('simple', ...)` 宽松匹配；上线后用实际查询验证 |
| **Chunking 粒度不当** | 中 | 过粗 → 召回率高但精确度低；过细 → 相反 | 基线为一商品一 chunk，后续根据检索命中率调整 FAQ/评价是否独立拆分 |
| **大模型幻觉** | 高 | 编造价格、库存、功能，影响用户信任 | generator prompt 硬注入结构化字段；指令"只能使用以上信息"；禁止提及优惠券/折扣 |
| **Embedding 领域适配** | 低 | 豆包/千问 embedding 对电商中文的语义表达能力未验证 | 两个平台都测试，选检索命中率更优者；embedding 模型切换成本低（仅需 rebuild product_review） |
| **结构化与向量数据不一致** | 中 | 商品下架后仍被搜到；价格已变但搜索结果显示旧价 | 搜索时 JOIN 实时表获取价格/库存；`is_active=FALSE` 由 sync 定期清除向量；不一致窗口 = 轮询间隔（秒级） |
| **LLM API 限流/不可用** | 高 | 查询拆解或推荐生成失败 | 查询拆解降级为整体语义检索；推荐生成降级为仅返回商品列表无推荐理由；config.yaml 配置重试 + 超时 |
| **sync 单点故障** | 低 | sync 进程挂掉期间商品信息不同步 | advisory lock 确保可快速重启；监控轮询心跳日志；数据不一致窗口有限（最近一次同步前的变更） |

---

## 10. 实现复杂度评估

### 总体评级：中等

| 维度 | 评估 | 说明 |
| :--- | :--- | :--- |
| **新概念学习** | 低 | 技术栈成熟（FastAPI + SQLAlchemy + pgvector），均为 Python 生态常用组件 |
| **模块数量** | 中 | 约 15 个核心 .py 文件，6 个逻辑模块，职责边界清晰 |
| **外部依赖** | 中 | PostgreSQL + pgvector + zhparser（需安装扩展）；豆包 LLM + Embedding API（OpenAI 兼容，已就绪） |
| **算法复杂度** | 中 | 查询拆解 prompt 设计、多策略检索路由、RRF/加权合并——均为已知模式，无自研算法 |
| **状态管理** | 低 | 无状态搜索 + sync 定时器，无分布式协调需求 |
| **边界情况** | 中 | 需处理的异常路径较多（超时、降级、空结果、LLM 格式错误），但均有明确降级策略 |

### 按模块复杂度

| 模块 | 复杂度 | 说明 |
| :--- | :--- | :--- |
| `core/` (config, db) | 低 | 标准配置加载 + SQLAlchemy 连接管理 |
| `models/` | 低 | 4 个 ORM 模型，纯声明式 |
| `api/` | 低 | 3 个路由，薄层透传 |
| `services/import_data.py` | 中 | JSON 解析 + Chunking 模板化 + 批量 embedding |
| `services/sync.py` | 中 | 轮询五源表 + 差异检测 + 增量 re-embedding（product 仅处理 is_active → DELETE，无 embedding 操作） |
| `services/query_parser.py` | 中高 | LLM prompt 设计 + 输出解析 + 展开逻辑（Q7），依赖 LLM 输出格式稳定性 |
| `services/search.py` | 中 | 子查询路由编排，逻辑清晰但分支多 |
| `rag/retriever.py` | 中 | 三策略实现（pgvector / tsvector / SQL），每种独立简洁 |
| `rag/merger.py` | 中 | source 权重 + 聚合 + 降级，纯计算逻辑 |
| `rag/generator.py` | 中 | SSE 流式输出 + prompt 注入，模式成熟 |
| `rag/prompt.py` | 中高 | 查询拆解 + 推荐生成两套 prompt 模板，需多轮调优 |

**关键路径风险**：`query_parser` 和 `prompt` 的质量高度依赖 prompt engineering 迭代，是影响最终效果的最大变量。

---

## 11. 可交付性

### 交付物清单

| 交付物 | 形式 | 验收标准 |
| :--- | :--- | :--- |
| 后端 API 服务 | FastAPI 应用（`app/`） | 三个端点可调用，SSE 流式正常 |
| 数据库模型 | SQLAlchemy + Alembic 迁移脚本 | 六张表自动创建，索引就绪 |
| 数据导入工具 | CLI 脚本 + API 端点 | 100 个商品 JSON → 六表，5 分钟内完成 |
| 数据同步服务 | lifespan 后台定时器 | 商品变更后 2 个轮询周期内体现在搜索结果中 |
| 检索能力 | 混合搜索引擎 | 模糊推荐 + 条件筛选两类场景可返回合理商品 |
| 配置文件模板 | `config.yaml` + `.env.example` | 替换 API key 即可启动 |

### 不交付项（明确排除）

- 多轮对话 / 会话管理
- 前端 UI
- 用户认证与权限
- Docker 镜像 / K8s 配置（本地运行即可）
- 性能压测报告

### 交付节奏建议

| 阶段 | 内容 | 预计人天 |
| :--- | :--- | :--- |
| **Phase 1: 骨架搭建** | config / db / models / schemas / 空 API 路由 | 1-2 天 |
| **Phase 2: 数据导入** | import_data + Chunking + 批量 embedding | 1-2 天 |
| **Phase 3: 检索核心** | query_parser + retriever + merger | 2-3 天 |
| **Phase 4: 生成与流式** | generator + SSE 端点 + prompt 调优 | 1-2 天 |
| **Phase 5: 同步与边界** | sync 定时器 + 降级 + 超时 + 错误处理 | 1-2 天 |
| **Phase 6: 测试与文档** | 单元测试 + 集成测试 + API 文档 | 1-2 天 |
| **总计** | | **7-13 人天** |

> 工期范围取决于 prompt 调优迭代轮数和测试覆盖深度。

---

## 12. 可测试性

### 测试分层

| 层级 | 范围 | 工具 | 覆盖目标 |
| :--- | :--- | :--- | :--- |
| **单元测试** | 纯逻辑模块（merger, import_data chunking, prompt 模板） | pytest | 核心逻辑覆盖率 > 80% |
| **集成测试** | retriever + 真实 PostgreSQL/pgvector | pytest + test DB | 三种检索策略正确性 |
| **API 测试** | SSE 端点端到端 | httpx + pytest-asyncio | SSE 事件流格式正确 |
| **Mock 测试** | query_parser, generator（依赖 LLM） | pytest-mock / respx | LLM 超时/格式错误降级路径 |

### 可测试性设计要点

- `query_parser` 和 `generator` 的 LLM 调用通过依赖注入，测试时替换为 mock
- `embedding` 服务同样依赖注入，测试时可用固定向量替代
- merger 为纯函数（List[hits] → List[ranked_products]），天然可单测
- retriever 每种策略独立方法，可单独验证
- SSE 端点使用 `httpx.stream()` 逐事件断言

### 关键测试场景

| 场景 | 测试方法 | 验证点 |
| :--- | :--- | :--- |
| "推荐适合油皮的洗面奶" | 集成测试 | semantic 检索召回相关商品，推荐理由提及肤质 |
| "200元以下的蓝牙耳机" | 集成测试 | structured_filter 过滤价格，keyword 匹配"蓝牙" |
| "防晒霜，不要含酒精的，不要日系" | 集成测试 | negation 硬过滤 + Q7 LLM 展开过滤日系品牌 |
| LLM 查询拆解超时 | Mock 测试 | 降级为整体 semantic 检索，不报错 |
| LLM 推荐生成返回非 JSON | Mock 测试 | SSE 仅返回 products，done 正常发送 |
| embedding API 不可用 | Mock 测试 | 降级为纯关键词检索 |
| 数据库为空 | 集成测试 | 返回空列表 + 合理提示 |
| sync 检测到商品下架 | 集成测试 | product_review 对应行被删除 |

---

## 附录 A: config.yaml 结构概要

```yaml
# ---- 数据库 ----
database:
  host: "localhost"
  port: 5432
  user: "auracart"
  password: "${DB_PASSWORD}"
  dbname: "auracart"
  vector_dim: 1024            # embedding 向量维度（豆包=1024, 千问=1536）

# ---- 大模型 (OpenAI 兼容) ----
llm:
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  api_key: "${LLM_API_KEY}"
  model: "doubao-seed-2.0-lite"
  temperature: 0.3

# ---- Embedding (OpenAI 兼容) ----
embedding:
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  api_key: "${EMBEDDING_API_KEY}"
  model: "doubao-embedding"
  batch_size: 20              # 批量 embed 时每批条数

# ---- 同步 ----
sync:
  interval_s: 2               # 轮询间隔（秒）
  enabled: true               # 是否启用自动同步

# ---- 检索 ----
search:
  source_weights:             # 向量检索得分上的 source 权重
    faq: 1.0
    marketing: 0.9
    user_review: 0.6
  top_k_per_query: 20         # 每个子查询取 top-K
  final_product_limit: 10     # 最终返回商品数上限
  min_results_threshold: 3    # 低于此数触发降级
  semantic_weight: 0.6        # 混合检索中语义得分权重
  keyword_weight: 0.4         # 混合检索中关键词得分权重

# ---- 超时 (秒) ----
timeout:
  query_parse: 3.0
  retrieval: 1.0
  generation: 15.0
  total_request: 30.0

# ---- 图片 ----
static:
  mount_path: "/static"
  local_dir: "ecommerce_agent_dataset"
```
