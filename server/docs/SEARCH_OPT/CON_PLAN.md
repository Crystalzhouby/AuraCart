# /search/stream 查询优化 — 编码骨架

## 1. 模块拆分

```
                    ┌──────────────────────────┐
                    │   api/search.py           │
                    │   event_stream() 编排     │
                    └─────┬────────┬───────────┘
                          │        │
              ┌───────────┘        └───────────┐
              ▼                                ▼
   ┌──────────────────────┐      ┌──────────────────────┐
   │ services/             │      │ rag/                  │
   │   query_parser.py    │      │   merger.py (RRF)     │
   │   retriever.py       │      │   prompt.py           │
   └──────────────────────┘      │   generator.py (不变) │
                                 └──────────────────────┘
```

| 模块 | 角色 | 变更程度 |
|------|------|----------|
| `services/retriever.py` | SubQuery 数据类 + 检索执行（hard_filters 构建 + keyword/semantic 双路 SQL） | **重写** |
| `rag/merger.py` | RRF 排名融合 | **重写** |
| `rag/prompt.py` | `QUERY_PARSE_SYSTEM` 模板 | **重写** |
| `services/query_parser.py` | 调用 LLM + 解析响应 → SubQuery[] | **小幅修改** |
| `api/search.py` | SSE 编排 + 依赖注入 | **适配** |
| `config.yaml` | search 配置组 | **调整** |
| `app/config.py` | SearchSettings / TimeoutSettings | **小幅修改** |

---

## 2. 目录结构（仅列出变更文件）

```
server/
├── app/
│   ├── api/
│   │   └── search.py          ← 适配：移除 negation_pids，新 retriever/merger 调用
│   ├── services/
│   │   ├── retriever.py        ← 重写：SubQuery(无 negation) + _extract_filters() + _keyword_search + _semantic_search
│   │   ├── query_parser.py     ← 微调：_parse_response 移除 negation 字段映射
│   │   └── embedding.py        ← 不变：EmbeddingService.embed() 接口保持不变
│   ├── rag/
│   │   ├── merger.py           ← 重写：加权均值 → RRF
│   │   ├── prompt.py           ← 重写：QUERY_PARSE_SYSTEM
│   │   └── generator.py        ← 不变
│   └── config.py               ← 微调：SearchSettings 字段调整
├── config.yaml                 ← 调整：search 组
└── tests/                      ← 适配所有涉及接口变更的用例
```

---

## 3. 核心接口 / API

### 3.1 SubQuery（[retriever.py](server/app/services/retriever.py)）

```python
@dataclass
class SubQuery:
    text: str                        # 子查询文本
    strategy: str                    # "semantic" | "keyword" | "structured_filter"
    field: str | None = None         # structured_filter 目标字段
    operator: str | None = None      # eq | lt | gt | in | not_in | contains | not_contains
    value: str | float | None = None
    expanded_values: list[str] | None = None  # 多值展开
```

与当前的区别：**移除 `negation: bool` 字段**。否定语义由 operator 本身表达（`not_in`/`not_contains`）或由 semantic 相似度自然降权。

### 3.2 QueryParser（[query_parser.py](server/app/services/query_parser.py)）

```python
class QueryParser:
    def __init__(self, llm: LLMService): ...
    async def parse(self, user_query: str) -> list[SubQuery]: ...
    def _parse_response(self, llm_output: str) -> list[SubQuery]: ...
```

接口不变。`_parse_response` 内部不再读取 `negation` 字段。

### 3.3 Retriever（[retriever.py](server/app/services/retriever.py)）— 重构

```python
class Retriever:
    def __init__(self, db: AsyncSession, emb: EmbeddingService): ...

    # ---- 公开入口 ----
    async def retrieve(
        self,
        subs: list[SubQuery],          # 所有子查询（不再是单条）
        top_k: int = 20,
    ) -> dict[str, list[dict]]:        # {"keyword": [...], "semantic": [...]}
        ...

    # ---- 内部方法 ----
    def _extract_filters(
        self, subs: list[SubQuery]
    ) -> Filters:
        """从 structured_filter 子查询中提取硬约束条件集合。"""
        ...

    async def _keyword_search(
        self,
        kw_subs: list[SubQuery],       # strategy="keyword" 的子集
        filters: Filters,
        top_k: int,
    ) -> list[SKUHit]: ...

    async def _semantic_search(
        self,
        sem_subs: list[SubQuery],      # strategy="semantic" 的子集
        filters: Filters,
        top_k: int,
    ) -> list[SKUHit]: ...

    def _build_base_query(
        self, filters: Filters, score_expr: str
    ) -> str:
        """构建三表 JOIN 骨架 SQL，注入 score_expr 和 hard_filters。"""
        ...
```

**关键变化**：
- `retrieve()` 入参从单条 `SubQuery` 变为 `list[SubQuery]`，内部自行分组
- `structured_filter` 不再有独立检索方法，转为 `Filters` 对象注入 keyword/semantic 的 SQL
- 返回值从 `list[dict]` 改为 `dict[str, list[dict]]`（按路径分组的排名列表）

### 3.4 Filters（内部数据结构）

```python
@dataclass
class Filters:
    """从 structured_filter 子查询提取的硬约束集合。"""
    conditions: list[FilterClause]     # 每个子查询对应一个 WHERE 片段
    # 无 negation 字段——否定通过 operator 值表达 (not_in/not_contains)

@dataclass
class FilterClause:
    table: str                         # "product" | "sku"
    sql: str                           # 参数化 SQL 片段，如 "p.brand NOT IN (:v0,:v1)"
    params: dict                       # 对应参数值
```

`_extract_filters()` 遍历所有 `strategy="structured_filter"` 的 SubQuery，为每条生成 `FilterClause`。否定条件和非否定条件同等处理——operator 本身携带语义。

### 3.5 SKUHit（检索结果单元）

```python
@dataclass
class SKUHit:
    sku_id: str
    product_id: str
    score: float
```

替代当前松散的 `dict(product_id=..., source=..., score=...)`。keyword 路和 semantic 路均返回 `list[SKUHit]`（按 score 降序）。

### 3.6 Merger（[merger.py](server/app/rag/merger.py)）— 重写

```python
class Merger:
    def __init__(self, rrf_k: int = 60, final_limit: int = 10): ...

    def merge(
        self,
        keyword_ranked: list[SKUHit],     # keyword 路排名结果
        semantic_ranked: list[SKUHit],    # semantic 路排名结果
    ) -> list[SKUHit]:                    # RRF 融合后 Top-K
        ...
```

**关键变化**：
- `merge()` 签名：移除 `negation_queries` 参数，移除 `all_hits: list[list[dict]]` 列表嵌套
- 入参从"多源命中列表"变为"两路已排名列表"
- 内部：纯 RRF 计算，无 source_weight、无 negation_pids 排除

### 3.7 config.yaml 变更

```yaml
search:
  rrf_k: 60                    # 新增: RRF 融合参数
  top_k_per_query: 20          # 保留: 单路检索 Top-K
  final_sku_limit: 10          # 重命名(原 final_product_limit): 最终返回 SKU 数
  # 移除: source_weights → 不再需要
  # 移除: min_results_threshold → 不再需要
```

---

## 4. 关键数据结构流转

```
阶段1 输出:  list[SubQuery]                    # QueryParser.parse()
              │
              ├─ strategy="structured_filter" → 提取为 Filters
              ├─ strategy="keyword"           → 传给 keyword_search
              └─ strategy="semantic"          → 传给 semantic_search (逐条 embed)
              │
阶段2 输出:  dict{"keyword": list[SKUHit],     # Retriever.retrieve()
                  "semantic": list[SKUHit]}
              │
阶段3 输入:  (keyword_ranked, semantic_ranked)  # Merger.merge()
阶段3 输出:  list[SKUHit]                       # RRF 融合后 Top-K
              │
              ▼
              _get_products_and_skus(db, ranked_sku_hits) → 补全数据 → SSE "products"
```

**注意**：`_get_products_and_skus` 替代当前 `_get_products`。入参从 `product_ids: list[str]` 变为 `sku_hits: list[SKUHit]`，查询 SKU 表为主表，JOIN product 补全产品信息。

---

## 5. /search/stream 实现链路（分阶段）

### 阶段 1：查询解析

```
search.py: event_stream()
  │
  ├─ parser.parse(q) ──► list[SubQuery]
  │   超时降级(不变): 整条 q 作为 semantic SubQuery 兜底
  │
  └─ 日志: 打印原始查询 + 解析后子查询详情（不变）
```

### 阶段 2：双路并行检索

```
search.py: event_stream()
  │
  ├─ retriever.retrieve(subs, top_k=settings.search.top_k_per_query)
  │    │
  │    ├─ 内部分组: structured_filter / keyword / semantic
  │    ├─ _extract_filters(structured_filter subs) → Filters
  │    │
  │    ├─ (并行) _keyword_search(kw_subs, filters, top_k)
  │    │    └─ SQL: 三表 JOIN, WHERE filters + content_tsv @@ ... , ORDER BY ts_rank
  │    │
  │    └─ (并行) _semantic_search(sem_subs, filters, top_k)
  │         └─ 逐 sem_sub embed, 构建单条 SQL: 三表 JOIN, WHERE filters,
  │            SELECT sum(1-(emb<=>:vec_i)), ORDER BY sum_score
  │
  └─ 返回: {"keyword": list[SKUHit], "semantic": list[SKUHit]}
```

**注意**：keyword 路和 semantic 路无相互依赖，使用 `asyncio.gather` 并行执行。

### 阶段 3：RRF 融合 + 数据补全

```
search.py: event_stream()
  │
  ├─ merger.merge(keyword_ranked, semantic_ranked)
  │    └─ RRF(sku) = Σ 1/(k + rank_i)    (k=60, i 遍历两路)
  │    └─ 按 RRF 降序 → Top-K list[SKUHit]
  │
  ├─ _get_products_and_skus(db, ranked_sku_hits)
  │    └─ 按 sku_id 批量查询 sku 表 + JOIN product → 补全完整信息
  │
  └─ SSE event: "products"  → JSON
```

### 阶段 4-5：生成 + 结束（不变）

---

## 6. 权限、隔离和边界

### 6.1 模块边界（不变）

```
api ──► services ──► models
  │         │
  └──► rag ─┘
```

- `rag/` 不接触 DB、不做 HTTP 调用
- `services/` 不依赖 FastAPI Request/Response
- `api/` 只做编排，不含业务逻辑

### 6.2 新增内部边界

- **`Filters` + `FilterClause`** 是 `retriever.py` 内部数据结构，不流出该模块
- **`SKUHit`** 是 `services/` 和 `rag/merger.py` 之间的共享类型，定义在 `retriever.py`（与 `SubQuery` 同文件）或独立 `schemas/` 文件 **[待定]**
- **`_build_base_query()`** 是 `Retriever` 的私有方法，封装三表 JOIN + hard_filters 拼接逻辑，不对外暴露

### 6.3 不变项

- `EmbeddingService.embed()` 接口不变
- `LLMService.chat_stream()` 接口不变
- `Generator.generate()` 接口不变
- SSE 事件名和顺序不变（`products` → `reasoning` → `done`/`error`）
- DB schema / ORM 模型不变

### 6.4 事务边界

- 每次 `retriever.retrieve()` 内部使用同一个 `db: AsyncSession`
- keyword 和 semantic 两路检索共享同一会话（`asyncio.gather` 并行），SQLAlchemy AsyncSession 需确保协程安全 **[待确认：AsyncSession 是否支持并发执行多个 SQL]**
- 若两路检索中任一路的 SQL 执行出错，需 rollback 该会话（与当前修复一致）


## 7.待确认项
1. SKUHit 定义位置：放在 retriever.py（与 SubQuery 同文件）还是独立 schemas/？目前倾向前者，保持简单
前者，放在retriever.py中吧。

2. AsyncSession 并发安全性：keyword 和 semantic 两路用 asyncio.gather 并行执行 SQL，需确认 SQLAlchemy AsyncSession 是否支持同一会话内并发。若不支持，需改为串行或各自独立会话
若支持，则在同一会话内并发，若不支持，改成各自独立会话。

3. 不需要做回滚开关，旧版本可用性不强。