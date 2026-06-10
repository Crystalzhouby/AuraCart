# 多Agent电商导购系统 — 实现方案

> **文档性质**：架构级实现方案，非代码级任务拆解。关注模块边界、数据流向、接口契约。
> 不确定的实现设计边界条件在文末第9节集中列出（当前状态：已确认，8 项已定案 + 3 项编码细化）。

**目标**：在现有 FastAPI + RAG 管线上，叠加 LangGraph 驱动的 6-Agent 工作流，实现意图路由、场景化需求拆解、并行品类检索、渐进式 SSE 流式输出、多轮对话记忆管理。

**技术栈**：Python 3.10+ / FastAPI / LangGraph / SQLAlchemy Async / SSE (sse-starlette) / PostgreSQL + pgvector

---

## 1. 整体实现架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Application                             │
│                                                                          │
│  GET /api/search?q=...&stream=true                                       │
│         │                                                                │
│         ▼                                                                │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    LangGraph StateGraph                           │   │
│  │                                                                   │   │
│  │   AgentState: conversation_history, user_query, intent,           │   │
│  │               is_scenario, requirements, products_summary,        │   │
│  │               scenario_description, chat_reply, next_options      │   │
│  │                                                                   │   │
│  │   Nodes (6) + Conditional Edges:                                  │   │
│  │                                                                   │   │
│  │   START → [Intent Router] ──chat──→ [Chit-Chat] ──→ END          │   │
│  │                  │                                                │   │
│  │         recommend│                                                │   │
│  │       ┌──────────┴──────────┐                                     │   │
│  │  is_scenario=false     is_scenario=true                           │   │
│  │       │                     │                                     │   │
│  │  [Intent Extraction]   [Scenario Gen]                             │   │
│  │       │                     │                                     │   │
│  │       └──────┬──────────────┘                                     │   │
│  │              ▼                                                    │   │
│  │         [ Memory ]  ←── append-only, 2000 token 写时截断          │   │
│  │              │                                                    │   │
│  │              ▼                                                    │   │
│  │     [Product Retrieval]  ←── LLM筛选 → 按sub_category分组         │   │
│  │       │        │              → 并行检索(max=5, 独立session)      │   │
│  │       │        │              → 渐进式SSE + products_summary      │   │
│  │   SSE流 │  State写                                               │   │
│  │       ▼        ▼                                                  │   │
│  │     END    [Option Gen]  ←── 读AgentState, 无DB                   │   │
│  │                 │                                                  │   │
│  │                 ▼                                                  │   │
│  │               END                                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  GET /api/products/batch?ids=p1,p2,...      (新)                         │
│  GET /api/products/image/batch?ids=p1,p2,...(新)                         │
│  GET /api/sku/batch?ids=sk1,sk2,...         (新)                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**架构要点**：

- **LangGraph 作为编排层**：不改变现有 RAG 管线核心逻辑，以节点函数形式包裹调用。每个 Agent 节点是一个 `async def node(state: AgentState) -> dict` 函数，返回部分 State 更新。
- **SSE 通道独立于 StateGraph**：Product Retrieval 节点通过 `asyncio.Queue`（作为 AgentState 隐藏字段 `_sse_queue`）将 SSE 事件从节点内部传递到 FastAPI 的 `EventSourceResponse` 生成器，不与 LangGraph State 耦合。
- **两条路径在 Memory 处汇合**：explicit 路径 (Extraction → Memory) 和 scenario 路径 (Scenario Gen → Memory) 都产出 `requirements.sub_queries`，Product Retrieval 统一读取。
- **独立 session 仅 Product Retrieval 使用**：并行品类任务各自 `async with async_session()`，Option Gen 无需 session。

---

## 2. 核心功能接口与需求映射

### 2.1 接口总览

| 接口 | 方法 | 功能 | 映射需求 |
|------|------|------|----------|
| `/api/search?q=&stream=true` | GET | 多Agent导购主入口（SSE流式） | FR1-FR8 |
| `/api/products/batch?ids=` | GET | 批量获取商品详情 | FR4（前端渲染） |
| `/api/products/image/batch?ids=` | GET | 批量获取商品图片 | FR4（前端渲染） |
| `/api/sku/batch?ids=` | GET | 批量获取SKU详情 | FR4（前端渲染） |
| `/server/scripts/setup_category_lookup.py` | CLI | 构建 category_lookup 表并填充数据 | FR9 |
| category_lookup 表 | DB | 提供合法 (category, sub_category) 值对 | FR3, FR4, FR9 |

### 2.2 需求覆盖详述

**FR1 (意图路由)**：由 `/api/search` 内部 Intent Router 节点实现。一次 LLM 调用同时输出 `intent` + `is_scenario`，驱动 LangGraph 条件边。

**FR2 (意图提取 + 品类标记)**：Intent Extraction 节点复用 `QueryParser` 的 LLM 解析能力，**使用扩展后的 `QUERY_PARSE_SYSTEM`**（新增 `category`/`sub_category` 输出字段 + 品类标记指引 + 需求合并逻辑）。Intent Extraction 节点与现有 `/api/search` 的 QueryParser 共用同一份提示词。不再输出 `topic_shift`。

**FR3 (场景需求生成)**：Scenario Gen 节点从 `category_lookup` 表查询可用品类列表 → 注入提示词模板 `{category_list}` → 单次 LLM 调用端到端输出带品类标签的 SubQuery 列表 + `scenario_description`。每次请求都查询 category_lookup 表，无需缓存。

**FR4 (商品检索与推荐理由)**：Product Retrieval 节点内部执行 5 步：
1. LLM 需求筛选（2000 token 窗口）
2. 按 sub_category 分组（三级回退）
3. `asyncio` 并行检索（每品类独立 `async_session()`，max_concurrency=5）
4. 渐进式 SSE（`products` + `reasoning` 事件，reasoning token 附带 `category`/`sub_category`）
5. 提取 `products_summary` 写入 AgentState（`asyncio.gather` 收集后串行聚合）

**FR5 (推荐选项)**：Option Gen 节点读 `AgentState.products_summary`，纯 LLM 调用生成 2-4 条选项，**零 DB 访问**。

**FR6 (闲聊)**：Chit-Chat 节点，简短回复 + 服务边界声明。

**FR7 (多轮记忆)**：AgentState 的 `conversation_history` 字段（`Annotated[list, add]`），每次 append 后执行 token 计数（简易 `char_count / 4` 估算） + 写时截断（2000 token），截断仅日志记录。

**FR8 (LangGraph 编排)**：StateGraph + 条件边实现完整路由逻辑。

**FR9 (Category 查找表)**：独立脚本 `setup_category_lookup.py` 创建表 + DISTINCT 填充。

---

## 3. 模块拆解

### 3.1 模块总览

```
server/app/
├── agent/                          # 新增：LangGraph Agent 层
│   ├── __init__.py
│   ├── state.py                    # AgentState 定义（含 _sse_queue 隐藏字段）
│   ├── graph.py                    # StateGraph 构建 + 条件边
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── router.py               # Intent Router 节点
│   │   ├── extraction.py           # Intent Extraction 节点（复用扩展后的 QUERY_PARSE_SYSTEM）
│   │   ├── scenario_gen.py         # Scenario Gen 节点
│   │   ├── retrieval.py            # Product Retrieval 节点（含并行逻辑、品类任务编排）
│   │   ├── option_gen.py           # Option Gen 节点
│   │   └── chitchat.py             # Chit-Chat 节点
│   ├── memory.py                   # Memory 工具（char/4 token 估算、写时截断）
│   └── prompts/                    # Agent 提示词模板（Intent Extraction 不在此——复用 rag/prompt.py）
│       ├── __init__.py
│       ├── router_prompt.py
│       ├── scenario_gen_prompt.py
│       ├── relevance_filter_prompt.py
│       ├── option_gen_prompt.py
│       └── chitchat_prompt.py
├── api/
│   ├── search.py                   # 修改：接入 LangGraph 工作流，注入 _sse_queue，消费 SSE 事件
│   └── products.py                 # 修改：新增 3 个 batch 端点
├── models/
│   └── category_lookup.py          # 新增：category_lookup ORM 模型
├── services/
│   ├── retriever.py                # 修改：SubQuery 新增 category/sub_category 字段
│   ├── query_parser.py             # 修改：_parse_response() 适配新字段；复用扩展后的 QUERY_PARSE_SYSTEM
│   └── sku_utils.py                # 新增：_get_skus() 从 search.py 迁移至此（供 Agent 节点复用）
├── rag/
│   ├── generator.py                # 无结构性修改（保持 Generator(llm) 接口不变）
│   └── prompt.py                   # 修改：扩展 QUERY_PARSE_SYSTEM（含 category/sub_category + 品类标记指引）
│                                       + 扩展 GENERATOR_SYSTEM 模板变量 {requirements_summary}
├── config.py                       # 修改：新增 max_category_concurrency, pool_size, max_overflow
└── database.py                     # 修改：create_async_engine 显式配置 pool_size/max_overflow

server/
├── config.yaml                     # 修改：新增并发控制配置
└── scripts/
    └── setup_category_lookup.py    # 新增：category_lookup 建表 + 填充脚本
```

### 3.2 模块详细说明

#### M1: `app/agent/state.py` — AgentState 定义

| 维度 | 内容 |
|------|------|
| **职责** | 定义 LangGraph 工作流共享状态的类型结构 |
| **输入** | 无（纯类型定义） |
| **输出** | `AgentState` TypedDict |
| **核心字段** | `user_query: str`, `conversation_history: Annotated[list, add]`, `intent: str`, `is_scenario: bool`, `requirements: dict`, `scenario_description: str`, `products_summary: list[dict]`, `chat_reply: str`, `next_options: list[str]`, `failed_categories: list[str]`, `_sse_queue: asyncio.Queue \| None`（隐藏字段，`repr=False`，不参与 State 序列化，用于 SSE 事件通道） |

#### M2: `app/agent/graph.py` — StateGraph 构建

| 维度 | 内容 |
|------|------|
| **职责** | 将 6 个节点函数组装为 StateGraph，定义条件边 |
| **输入** | `LLMService` 实例、`async_session` factory |
| **输出** | 编译后的 `StateGraph`（可调用 `graph.ainvoke()` 或 `graph.astream()`） |
| **关键逻辑** | `add_conditional_edges("router", route_intent, {"chat": "chitchat", "extraction": "extraction", "scenario_gen": "scenario_gen"})` |

#### M3: `app/agent/nodes/router.py` — 意图路由

| 维度 | 内容 |
|------|------|
| **职责** | 根据 user_query + conversation_history 做两级分类 |
| **输入** | `AgentState.user_query`, `AgentState.conversation_history` |
| **输出** | `{"intent": "recommend"\|"chat", "is_scenario": bool}` |
| **LLM 调用** | 1 次（非流式，解析 JSON 响应） |
| **超时** | `settings.timeout.query_parse` (3s) |
| **Fallback** | `{"intent": "recommend", "is_scenario": false}` |

#### M4: `app/agent/nodes/extraction.py` — 意图提取

| 维度 | 内容 |
|------|------|
| **职责** | 从 user_query 中提取结构化 SubQuery 列表，含品类标记 |
| **输入** | `AgentState.user_query`, `AgentState.conversation_history`（历史 sub_queries，用于需求合并） |
| **输出** | `{"requirements": {"sub_queries": [...]}}` — 每个 SubQuery 含 `category`/`sub_category` 可选字段 |
| **LLM 调用** | 1 次（复用 `LLMService.chat_stream` 收集完整响应后解析 JSON） |
| **超时** | `settings.timeout.query_parse` (3s) |
| **与现有代码关系** | 复用 `QueryParser._parse_response()` 的 JSON 解析逻辑 + **扩展后的 `QUERY_PARSE_SYSTEM`**（`app/rag/prompt.py`，已新增 category/sub_category 字段 + 品类标记指引 + 需求合并逻辑）。与现有 `/api/search` 的 QueryParser 共用同一份提示词 |
| **Fallback** | `[SubQuery(text=user_query, strategy="semantic")]` |

#### M5: `app/agent/nodes/scenario_gen.py` — 场景需求生成

| 维度 | 内容 |
|------|------|
| **职责** | 一次性端到端：场景分析 + 按品类分组输出 SubQuery |
| **输入** | `AgentState.user_query`, `AgentState.conversation_history`, `category_list: str`（每次请求从 category_lookup 表 `SELECT category, sub_category` 查询，不缓存） |
| **输出** | `{"scenario_description": str, "requirements": {"sub_queries": [...]}}` — 每条 SubQuery 带 `category`/`sub_category` |
| **LLM 调用** | 1 次（非流式，单次端到端提示词） |
| **DB 访问** | 每次请求读 `category_lookup` 表（数据量 < 200 行，查询开销可忽略） |
| **超时** | `settings.timeout.query_parse` (3s) |
| **Fallback** | 视为误判 → 回退到 Intent Extraction 做 explicit 分解 |

#### M6: `app/agent/nodes/retrieval.py` — 商品检索（最复杂节点）

| 维度 | 内容 |
|------|------|
| **职责** | LLM 筛选 → 分组 → 并行检索 → 渐进式 SSE → 提取 products_summary |
| **输入** | `AgentState.requirements.sub_queries`, `AgentState.user_query`, `AgentState._sse_queue` |
| **输出** | SSE 事件流（products + reasoning token stream + done）；写入 State: `{"products_summary": [...]}` |
| **内部步骤** | 见下方流程图 |
| **LLM 调用** | 1 次筛选 + N 次 Generator（N = 品类数，每品类 1 次） |
| **DB 访问** | N 个并行任务各自 `async with async_session()` |
| **超时** | 筛选: 3s; 单品类检索+生成: `settings.timeout.generation` (15s)；总体: `settings.timeout.total_request` (30s) |

**Product Retrieval 内部流程**：

```
输入: requirements.sub_queries (2000 token 窗口), user_query, _sse_queue
                        │
                        ▼
           ┌────────────────────────┐
           │ Step 1: LLM 需求筛选    │  ← 轻量级提示词, 2000 token 窗口
           │ 输出: relevant_indices  │  ← 非流式 JSON 响应
           └───────────┬────────────┘
                       │ 失败 → 使用全部 2000 token 历史
                       ▼
           ┌────────────────────────┐
           │ Step 2: 按 sub_category │  ← 三级回退: sub_category→category→default
           │         分组            │  ← 校验 category_lookup 有效性
           └───────────┬────────────┘
                       │
                       ▼
           ┌────────────────────────┐
           │ Step 3: 并行检索        │  ← asyncio.Semaphore(max_concurrency=5)
           │                        │  ← 每品类一个 asyncio.Task
           │  ┌──────────────────┐  │
           │  │ async with       │  │  ← 独立 AsyncSession
           │  │ async_session()  │  │  ← task 内部 try/except，始终返回结构化结果:
           │  │   as db:         │  │     {category, sub_category, products_summary, error}
           │  │                  │  │
           │  │  1. retriever    │  │  ← Retriever.retrieve(品类SubQuery组)
           │  │     .retrieve()  │  │
           │  │  2. merger.merge │  │  ← Merger RRF 融合
           │  │  3. _get_skus()  │  │  ← 查商品详情 (独立 session, 函数来自 services/sku_utils.py)
           │  │  4. generator    │  │  ← LLM 生成推荐理由 (流式), Generator(llm) 接口不变
           │  │     .generate()  │  │
           │  │  5. sse_queue    │  │  ← products 事件: [{product_id,sku_id,category,sub_category}]
           │  │     .put()       │  │  ← reasoning 事件: {token, category, sub_category}
           │  │  6. 提取 summary │  │  ← 从 _get_skus() 结果提取轻量摘要
           │  └──────────────────┘  │
           └───────────┬────────────┘
                       │ asyncio.gather(*tasks) —— 收集结构化结果列表
                       ▼
           ┌────────────────────────┐
           │ Step 4: 串行聚合 summary│  ← 遍历 results 合并 products_summary
           │         发送 done 事件  │  ← 含 failed_categories (汇总 error 字段)
           └────────────────────────┘
                        │
                        ▼
              返回 {"products_summary": [...]}
```

#### M7: `app/agent/nodes/option_gen.py` — 推荐选项生成

| 维度 | 内容 |
|------|------|
| **职责** | 基于 products_summary 生成 2-4 条下一步推荐选项 |
| **输入** | `AgentState.requirements`, `AgentState.products_summary`, `AgentState.conversation_history`, `AgentState.scenario_description` |
| **输出** | `{"next_options": ["选项1", "选项2", ...]}` |
| **LLM 调用** | 1 次（非流式 JSON 响应） |
| **DB 访问** | **无** |
| **超时** | 3s |
| **Fallback** | 跳过，回复末尾不追加选项 |

#### M8: `app/agent/nodes/chitchat.py` — 闲聊

| 维度 | 内容 |
|------|------|
| **职责** | 简短友好回复 |
| **输入** | `AgentState.user_query`, `AgentState.conversation_history` |
| **输出** | `{"chat_reply": str}` |
| **LLM 调用** | 1 次（流式或非流式均可） |
| **DB 访问** | 无 |
| **超时** | 3s |
| **Fallback** | 硬编码兜底消息 |

#### M9: `app/agent/memory.py` — Memory 工具

| 维度 | 内容 |
|------|------|
| **职责** | Token 计数、写时截断（2000 token）、截断日志记录 |
| **输入** | `conversation_history: list[dict]`（append 后的完整列表） |
| **输出** | 截断后的 `conversation_history` |
| **关键函数** | `truncate_by_tokens(history: list, max_tokens: int, logger) -> list` |
| **Token 计数** | 简易估算 `len(json.dumps(history, ensure_ascii=False)) / 4`（无需 tiktoken 依赖，±20% 偏差可接受） |
| **截断策略** | 从列表头部开始丢弃，直到剩余 token 数 ≤ 2000。记录截断前的 token 总数和丢弃的需求组数。 |

#### M10: `app/api/search.py` — API 层适配（修改）

| 维度 | 内容 |
|------|------|
| **职责** | 接收请求 → 初始化 LLMService + EmbeddingService → 构建 LangGraph → `initial_state._sse_queue = asyncio.Queue()` → `graph.ainvoke()` → SSE 事件消费 → `EventSourceResponse` |
| **变更范围** | 替换现有的 `_run_pipeline()` + `event_stream()` 为 LangGraph 调用；保留 `/api/search` 路由签名不变 |
| **关键设计** | 创建 `asyncio.Queue`，通过 `initial_state._sse_queue = queue` 注入；节点内部通过 `await state._sse_queue.put(event)` 发送事件；端点从 `await state._sse_queue.get()` 消费事件 |

#### M11: `app/api/products.py` — Batch API（新增 3 个端点）

| 端点 | 功能 | 参数 | 返回 |
|------|------|------|------|
| `GET /api/products/batch` | 批量获取商品详情 | `ids` (逗号分隔 product_id) | `[{product_id, title, brand, category, sub_category, base_price}, ...]` |
| `GET /api/products/image/batch` | 批量获取商品图片 URL | `ids` (逗号分隔 product_id) | `[{product_id, image_url}, ...]` |
| `GET /api/sku/batch` | 批量获取 SKU 详情 | `ids` (逗号分隔 sku_id) | `[{sku_id, product_id, properties, price, stock}, ...]` |

> **设计原则**：batch 端点沿用现有单条查询的 SQL 逻辑（`Product` / `Sku` 模型），
> 使用 `WHERE product_id IN (:ids)` 的批量查询模式，一次 SQL 完成。

#### M12: `app/models/category_lookup.py` — Category 查找表模型

| 维度 | 内容 |
|------|------|
| **表** | `category_lookup` (id, category, sub_category, UNIQUE(category, sub_category)) |
| **ORM 模型** | 继承 `Base`，字段: `id: int (PK)`, `category: str`, `sub_category: str` |
| **维护方式** | 非应用自动管理。通过 `server/scripts/setup_category_lookup.py` 手动执行 |

#### M13: 配置变更

| 配置项 | 文件 | 默认值 | 说明 |
|--------|------|--------|------|
| `search.max_category_concurrency` | `config.yaml` + `config.py` | 5 | 品类并行检索最大并发数 |
| `database.pool_size` | `config.yaml` + `config.py` + `database.py` | 8 | SQLAlchemy 连接池大小 |
| `database.max_overflow` | `config.yaml` + `config.py` + `database.py` | 5 | 连接池溢出上限 |

#### M14: `app/services/retriever.py` — SubQuery 扩展（修改）

| 维度 | 内容 |
|------|------|
| **变更** | 在 `SubQuery` dataclass 中新增两个可选字段 |
| **新字段** | `category: str \| None = None`, `sub_category: str \| None = None` |
| **兼容性** | 默认值 `None`，现有 `SubQuery(...)` 构造代码无需修改 |

#### M15: `app/services/sku_utils.py` — _get_skus 迁移（新增）

| 维度 | 内容 |
|------|------|
| **职责** | 根据 ranked SKU hits 查询商品详情（从 `search.py` 迁移） |
| **输入** | `db: AsyncSession`, `ranked: list` |
| **输出** | `list[dict]` — 完整 SKU 字典列表 |
| **变更原因** | 原函数定义在 `search.py`，Agent 节点 `retrieval.py` 也需要调用，迁移到共享 services 模块 |

---

## 4. 方案主要优点

### 4.1 稳定交付优先

- **最小侵入**：LangGraph 工作流作为现有 `/api/search` 的**内部重构**，不改变路由签名、不引入新依赖（`langgraph` 是唯一新增包）、不修改现有数据模型（仅新增 `category_lookup` 独立表）。
- **渐进式替换**：`/api/search?stream=false` 的非流式路径可保留现有逻辑作为应急回退；Agent 节点逐个实现、逐个接入，支持增量交付。
- **Fallback 全覆盖**：6 个 Agent 节点均有明确的失败回退策略，任何节点失败不会导致请求 500。

### 4.2 性能平衡

- **并行检索**：场景路径下 5 品类并行执行，相比串行可缩短检索延迟至原来的 ~1/5。
- **SSE 渐进式返回**：首个品类完成后立即推送给前端，用户感知延迟（TTFB）接近单品类检索耗时，而非全部品类耗时之和。
- **SSE 精简 + Batch API**：products 事件仅传 ID，前端通过 3 次 batch 请求获取详情（vs. 最多 45 次逐条请求），网络开销大幅降低。
- **Option Gen 零 DB**：通过 AgentState.products_summary 传递数据，消除一次不必要的数据库查询。

### 4.3 代码组织清晰

- **Agent 层独立**：所有 LangGraph 相关代码集中在 `app/agent/` 下，与现有 `app/services/`、`app/rag/` 平行，互不污染。
- **提示词集中管理**：Agent 专用提示词在 `app/agent/prompts/`；共用的 `QUERY_PARSE_SYSTEM` 和 `GENERATOR_SYSTEM` 保留在 `app/rag/prompt.py`，Agent 节点直接 import。
- **数据契约统一**：SubQuery 作为所有 Agent 间的唯一数据交换格式。

---

## 5. 主要风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| **SSE 流式与 LangGraph 节点模型冲突** | 高 | LangGraph 节点是 async 函数，通过 `AgentState._sse_queue` 向外推送 SSE 事件；FastAPI 端点从 Queue 消费 → `EventSourceResponse`。Queue 在 `graph.ainvoke()` 前注入 State |
| **并行任务间 State 写入竞争** | 中 | `products_summary` 由 Product Retrieval 节点**串行聚合**各并行任务的返回值（`asyncio.gather` 收集 → 遍历合并 → 写 State），各任务通过任务内 try/except 返回结构化结果。`conversation_history` 由 LangGraph 的 `Annotated[list, add]` 自动处理 |
| **LLM API 并发限流** | 中 | 5 品类并行 = 5 个 Generator LLM 调用同时进行。通过 `max_category_concurrency` 信号量控制峰值；若仍触发限流，可在调用层增加重试（指数退避） |
| **扩展 QUERY_PARSE_SYSTEM 影响现有管线** | 中 | 新增 `category`/`sub_category` 字段默认 `None`，JSON 解析器应兼容冗余字段。若现有测试因新字段失败，需调整 `_parse_response()` 的字段校验逻辑 |
| **连接池耗尽** | 低 | `pool_size=8, max_overflow=5` 已预留 buffer。极端场景（多个并发请求同时做 5 品类检索）可能触达上限，但 `max_overflow` 提供临时溢出 |
| **category_lookup 数据过期** | 低 | 手动脚本方式。operation.md 中明确执行时机 |

---

## 6. 实现复杂度

### 6.1 复杂度分级

| 模块 | 复杂度 | 理由 |
|------|--------|------|
| AgentState 定义 | 低 | TypedDict 定义，纯数据结构。含 `_sse_queue` 隐藏字段 |
| Intent Router | 低 | 单次 LLM 调用 + JSON 解析 |
| Intent Extraction | 低 | 复用 QueryParser + 扩展后的 QUERY_PARSE_SYSTEM，不新建独立提示词 |
| Scenario Gen | 低 | 单次 LLM 调用 + category_list 注入（每次查询 DB） |
| Chit-Chat | 低 | 单次 LLM 调用 |
| Option Gen | 低 | 单次 LLM 调用，无 DB |
| Memory 工具 | 低 | char/4 token 估算 + 列表截断 |
| Batch API (3 端点) | 低 | 现有查询逻辑的批量版本 |
| SubQuery 字段扩展 | 低 | dataclass 新增可选字段 |
| category_lookup 模型 + 脚本 | 低 | 一张独立表 + 一个 SQL 脚本 |
| _get_skus 迁移 (sku_utils.py) | 低 | 函数从 search.py 移动到 services 模块 |
| Graph 构建 | 中 | StateGraph + 条件边配置 |
| **Product Retrieval** | **高** | 并行编排最复杂：LLM 筛选 → SubQuery 分组 → `asyncio.Semaphore` 限流 → 独立 session 管理 → SSE 事件队列（含品类元数据包装） → Generator 流式调用 → 任务内 try/except 结构化返回 → products_summary 串行聚合 → 超时与失败隔离 |
| SSE 事件队列集成 | 中 | Queue 通过 `_sse_queue` 传递、事件格式标准化、reasoning token 附 `category`/`sub_category`、done 事件汇总 `failed_categories` |
| API 层适配 | 中 | 将现有 `_run_pipeline()` + `event_stream()` 替换为 LangGraph 调用 + Queue 注入与消费 |
| 提示词扩展 | 中 | QUERY_PARSE_SYSTEM 新增字段 + 品类标记指引 + 需求合并；GENERATOR_SYSTEM 新增 `{requirements_summary}` 变量 |

### 6.2 整体评估

- **新增代码量**：预估 ~1500-2000 行（含提示词模板 ~300 行、节点函数 ~400 行、并行编排 ~250 行、Graph 构建 ~100 行、Memory 工具 ~80 行、State 定义 ~50 行、batch API ~100 行、sku_utils.py ~30 行、配置 ~50 行、脚本 ~60 行、测试 ~500 行）
- **修改代码量**：预估 ~150-250 行（`search.py` 重构、`retriever.py` 字段扩展、`prompt.py` 提示词扩展、`query_parser.py` 适配、`database.py` 配置、`config.py` 新字段）
- **删除文件**：`app/agent/prompts/extraction_prompt.py` 不再需要（由 B3 决策取消）
- **核心难点**：Product Retrieval 的并行编排（信号量限流、独立 session、结构化错误返回、SSE 事件交错中 token 品类归属的正确性）

---

## 7. 可测试性

### 7.1 测试分层策略

```
┌─────────────────────────────────────────────┐
│ E2E Test (test_e2e.py)                      │  ← 完整 HTTP 请求 → SSE 响应
│ 覆盖: 3 条用户路径（单轮/多轮/场景化）       │
├─────────────────────────────────────────────┤
│ Integration Test (test_agent_graph.py)       │  ← LangGraph 图调用（mock LLM + DB）
│ 覆盖: 条件边路由、State 传递、节点链          │
├─────────────────────────────────────────────┤
│ Unit Test — Agent Nodes                      │
│ test_router.py / test_extraction.py /        │  ← 各节点函数（mock LLM）
│ test_scenario_gen.py / test_retrieval.py /   │
│ test_option_gen.py / test_chitchat.py        │
├─────────────────────────────────────────────┤
│ Unit Test — Utilities                        │
│ test_memory.py / test_batch_api.py /         │  ← 纯函数/工具测试
│ test_subquery.py / test_sku_utils.py         │
└─────────────────────────────────────────────┘
```

### 7.2 关键测试点

| 测试场景 | 测试方法 | 验证点 |
|----------|----------|--------|
| 各节点 Fallback | Mock LLM 抛出异常/超时 | 节点返回降级结果 |
| 并行检索失败隔离 | Mock 某品类 `retrieve()` 抛异常 | 该品类进入 `failed_categories`，其他品类正常 |
| 品类失败 vs 无结果区分 | 注入品类异常 / 正常但 0 结果 | `error` 字段正确区分两种状态 |
| Memory 写时截断 | 构造超 2000 char 的 history（~500 token） | 截断后 token 估算值 ≤ 2000，日志有记录 |
| SSE 事件格式 | 收集所有 SSE 事件 | products 事件含 `category`/`sub_category`；reasoning 事件含 `token`+`category`+`sub_category`；done 事件含 `failed_categories` |
| reasoning token 品类归属 | 并行发送 2 品类 → 收集 SSE | 每个 token 的 `category`/`sub_category` 正确，前端可据此路由 |
| 条件边路由 | 输入 3 种 user_query | chat→ChitChat, explicit→Extraction, scenario→ScenarioGen |
| batch API | 请求 15 个 product_id | 返回 15 条（已上架的），忽略不存在的 |
| SubQuery 兼容性 | 不传 `category` 参数构造 SubQuery | `category` 为 `None`，现有测试不报错 |
| QUERY_PARSE_SYSTEM 扩展后兼容 | 用旧格式 mock 响应（无 category 字段）调 `_parse_response()` | 解析成功，新字段为 `None` |
| _get_skus 迁移后一致 | 对比迁移前后同输入输出 | 结果完全一致 |

### 7.3 Mock 策略

- **LLM**：通过 `unittest.mock.AsyncMock` 模拟 `LLMService.chat()` 和 `chat_stream()`，返回预定义 JSON 响应。不引入额外的 mock 框架。
- **DB**：使用 `aiosqlite`（内存）或现有 `conftest.py` 中的测试数据库 fixture。并行 session 测试需确保连接池行为在测试数据库中一致。
- **SSE Queue**：`asyncio.Queue` 可直接在测试中读写，无需 mock。

---

## 8. 可交付性

### 8.1 交付增量建议

| 阶段 | 交付内容 | 可独立验证 | 预估工期 |
|------|----------|------------|----------|
| **Phase 0: 基础设施** | SubQuery 字段扩展 + category_lookup 模型 + 脚本 + config 变更 + database.py pool 配置 + `_get_skus` 迁移至 sku_utils.py | ✅ category_lookup 表可查，SubQuery 新字段可用 | 0.5 天 |
| **Phase 1: 单 Agent 节点** | Intent Router + Intent Extraction（复用扩展后的 QUERY_PARSE_SYSTEM）+ Chit-Chat | ✅ 三个节点可独立调用，返回正确结果 | 1 天 |
| **Phase 2: 场景路径** | Scenario Gen + category_lookup 动态注入（每次查询 DB） | ✅ 场景查询可产出带品类标签的 SubQuery | 0.5 天 |
| **Phase 3: Memory** | Memory 工具（char/4 token 估算 + 截断）+ conversation_history | ✅ 多轮对话 history 可正确 append 和截断 | 0.5 天 |
| **Phase 4: 检索核心** | Product Retrieval（LLM 筛选 + 分组 + 并行检索 + SSE（含品类元数据）+ 任务内 try/except + asyncio.gather 聚合 products_summary） | ✅ 场景路径可返回分组推荐结果 | 2 天 |
| **Phase 5: Option Gen** | Option Gen 节点 | ✅ 推荐末尾出现下一步选项 | 0.5 天 |
| **Phase 6: Graph 编排** | StateGraph 构建 + 条件边 + API 层适配（Queue 注入 + SSE 消费） | ✅ 完整工作流可端到端运行 | 1 天 |
| **Phase 7: Batch API** | 3 个 batch 端点 | ✅ 批量查询可返回正确结果 | 0.5 天 |
| **Phase 8: 测试** | 单元测试 + 集成测试（含结构化错误返回、品类元数据验证） | ✅ CI 绿灯 | 1.5 天 |

**总预估**：约 8 个工作日（1 人）。Phase 0-3 可并行开发部分节点。

### 8.2 验收标准

| 标准 | 验证方式 |
|------|----------|
| Single-turn explicit 查询返回正确推荐 | `GET /api/search?q=200元以下的蓝牙耳机` → SSE 事件含 products + reasoning（token 带 category/sub_category）+ next_options |
| Multi-turn 需求累加 | 连续 3 次请求（跑鞋 → 轻量 → 预算 500），验证 Memory 中的 sub_queries 累加 |
| Scenario 查询返回跨品类推荐 | `GET /api/search?q=去三亚度假需要准备什么` → 5 品类分组 SSE + reasoning token 带 category/sub_category，前端可按品类分区渲染 |
| 单品类失败不阻断整体 | 注入品类失败 → done 事件含 failed_categories，其他品类正常；Option Gen 不生成失败品类选项 |
| 品类失败与无结果区分 | 注入品类异常 → `error` 字段有值；品类正常但 0 结果 → `error=None, products_summary=[]` |
| Memory 截断行为 | 超 2000 token 的对话 → 早期需求被截断，日志有记录 |
| Fallback 全覆盖 | 逐个注入 Agent 失败 → 验证降级路径 |
| Batch API 正确性 | `GET /api/products/batch?ids=p1,p2` → 返回对应商品详情 |
| 现有测试不受影响 | 运行现有 `pytest` 测试套件 → 全部通过 |
| QUERY_PARSE_SYSTEM 扩展向后兼容 | `_parse_response()` 处理无 `category` 字段的旧 LLM 响应 → 新字段默认 `None` |

---

## 9. 已确认的设计边界条件

以下 8 个实现设计边界问题已在方案讨论中确认。每个问题记录最终决策和关键理由。

### B1. SSE 事件队列的传递方式 ✅

**决策**：`asyncio.Queue` 作为 AgentState 隐藏字段 `_sse_queue` 传递。

- `_sse_queue: asyncio.Queue | None = field(default=None, repr=False, compare=False)` — 不参与 LangGraph State 序列化。
- API 层：`initial_state._sse_queue = asyncio.Queue()` 注入后再 `graph.ainvoke()`。
- 节点内：`await state._sse_queue.put(event)`，端点：`await state._sse_queue.get()`。

**理由**：与现有 `/api/search` 的 `asyncio.Queue` + `EventSourceResponse` 模式完全一致，零学习成本。

### B2. Generator 的 session 参数适配方式 ✅

**决策**：保持现有接口 — `Generator(llm)` 不变。

- `_get_skus(session, ranked)` 作为独立函数（迁移至 `app/services/sku_utils.py`），品类任务调用后传入 `generator.generate(skus, ...)`。
- Generator 作为纯 LLM 调用包装器，不持有 DB 依赖。

**理由**：最小化 Generator 变更；单一职责清晰；测试只需 mock `llm`。

### B3. Intent Extraction 提示词策略 ✅

**决策**：扩展现有 `QUERY_PARSE_SYSTEM`（`app/rag/prompt.py`），而非新建独立提示词。

- 新增 `category`/`sub_category` 输出字段 + 品类标记指引 + 需求合并逻辑。
- Intent Extraction 节点与现有 `/api/search` 的 QueryParser **共用同一份提示词**。
- `_parse_response()` 需确认新字段兼容性（默认 `None`，冗余字段不报错）。
- **影响**：原计划 `app/agent/prompts/extraction_prompt.py` 取消。

**理由**：用户确认 "QueryParser 实际在做 Intent Extraction 的需求提取工作"——升级一份提示词同时改进两条路径。

### B4. Token 计数工具选择 ✅

**决策**：简易估算 `len(json.dumps(history, ensure_ascii=False)) / 4`。

- 无需新增 `tiktoken` 依赖。±20% 偏差在 2000 token 软约束下可接受。

**理由**：稳定优先，后续可升级为精确 tokenizer。

### B5. category_lookup 数据读取策略 ✅

**决策**：每次查询 DB。Scenario Gen 节点内直接 `SELECT category, sub_category FROM category_lookup`。

**理由**：表数据量小（< 200 行），查询开销可忽略；无缓存失效问题。

### B6. products_summary 的并发聚合方式 ✅

**决策**：`asyncio.gather(*tasks)` 收集后，在节点内串行遍历合并。

- 各品类任务返回结构化结果 `{category, sub_category, products_summary, error}`。
- 节点内遍历 `results` 提取 `products_summary` 合并，汇总 `failed_categories`。

**理由**：简单直接，无锁竞争，`asyncio.gather` 天然处理部分失败。

### B7. 单品类任务失败的传播方式 ✅

**决策**：任务内部 try/except，始终返回结构化结果。

```python
# 成功: {"category": "面部护肤", "sub_category": "防晒霜", "products_summary": [...], "error": None}
# 失败: {"category": "面部护肤", "sub_category": "防晒霜", "products_summary": [], "error": "..."}
```

- `asyncio.gather` 不使用 `return_exceptions`，统一按结构化结果处理。
- SSE `done` 事件中汇总 `failed_categories`（从 `error` 字段提取）。

**理由**：区分"品类失败"（有 error）和"品类无结果"（空列表），状态语义清晰。

### B8. SSE reasoning token 的品类归属 ✅

**决策**：每个 `reasoning` token 事件附带 `category` 和 `sub_category` 字段。

```json
{"event": "reasoning", "data": {"token": "这款", "category": "面部护肤", "sub_category": "防晒霜"}}
```

- 前端维护 `Map<"category|sub_category", textBuffer>`，收到 token 后追加到对应品类文本区域。
- 并行品类任务通过 `asyncio.Queue` 发送 token 时，不同品类的 token 可能在 SSE 流中交错出现。`category`/`sub_category` 作为路由键确保前端正确分发。
- 元数据包装在品类任务内部完成（紧邻 `queue.put()`），不修改 `Generator` 接口。

**待前端确认**：当前设计支持**交错流式**（品类 A/B token 交替到达）。若前端期望**顺序流式**（品类 A 全部 token → 品类 B 全部 token → ...），则品类任务需内部缓冲全部 token 后一次性 `queue.put`。

---

### 新增编码层面细化设计（B9-B11，可在实现阶段确定）

### B9. `_get_skus()` 函数的位置

当前 `_get_skus(db, ranked)` 定义在 `app/api/search.py` 中。新架构下品类任务（`app/agent/nodes/retrieval.py`）也需要调用。**决策**：迁移到 `app/services/sku_utils.py`（新增），供 `search.py` 和 `retrieval.py` 共同 import。


### B10. 扩展后 QUERY_PARSE_SYSTEM 的新增字段序列化兼容性

B3 给 `QUERY_PARSE_SYSTEM` 新增 `category`/`sub_category` 字段后，`QueryParser._parse_response()` 的 JSON 解析逻辑需验证能正确处理新增字段（冗余字段不报错，缺失时默认 `None`）。`SubQuery` dataclass 需在 Phase 0 先完成字段扩展，确保 Prompt 扩展与数据模型同步。

### B11. reasoning token 的元数据包装位置

`Generator.generate()` 逐 token yield 裸字符串。包装为 `{"token": str, "category": str, "sub_category": str}` 的逻辑放在品类任务内部（紧邻 `queue.put()`），不修改 `Generator` 接口——Generator 继续产出裸 token，外层负责附加上下文元数据。

---

> **下一步**：B1-B8 已确认，B9-B11 为编码层面细化设计。可进入 Phase 0（基础设施）实现。
