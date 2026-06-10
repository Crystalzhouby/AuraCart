# AuraCart Ecom Agent — 架构设计文档

---

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FastAPI 应用层                                                              │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐│
│  │ GET /api/conversation│  │ GET /api/search/{cid} │  │ GET /api/history/... ││
│  │ 创建会话              │  │ SSE 流式 Agent 搜索    │  │ 对话历史 / 商品详情    ││
│  └──────────────────────┘  └─────────┬────────────┘  └──────────────────────┘│
│                                      │                                        │
│                      ┌───────────────▼────────────────────────────┐          │
│                      │  _agent_event_stream (SSE 消费循环)         │          │
│                      │  • 校验 conversation 存在性                  │          │
│                      │  • 后台启动 graph.ainvoke(initial_state)    │          │
│                      │  • 循环消费 queue → yield SSE events        │          │
│                      │  • finally: next_options → done → 持久化     │          │
│                      └───────────────┬────────────────────────────┘          │
│                                      │                                        │
│  ┌───────────────────────────────────▼─────────────────────────────────────┐ │
│  │  LangGraph StateGraph (5 节点管线)                                        │ │
│  │  ┌────────┐   ┌───────────┐   ┌───────────┐   ┌──────────┐   ┌─────────┐│ │
│  │  │ Router │──▶│Extraction/│──▶│ Retrieval  │──▶│Option Gen│──▶│  END    ││ │
│  │  │(统一入口)│  │Scenario Gen│  │(RAG管线)   │   │(选项+结束)│  │         ││ │
│  │  └────────┘   └───────────┘   └───────────┘   └──────────┘   └─────────┘│ │
│  └────────────────────────────────────────────────────────────────────────--┘ │
│                                      │                                        │
│  ┌───────────────────────────────────▼─────────────────────────────────────┐ │
│  │  Infrastructure                                                          │ │
│  │  PostgreSQL + pgvector │ Embedding API │ LLM API │ bge-reranker │ Config │ │
│  └────────────────────────────────────────────────────────────────────────--┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| Web 框架 | FastAPI + Uvicorn | 异步 Python Web 服务 |
| 工作流引擎 | LangGraph StateGraph | 5 节点 DAG，条件边路由 |
| ORM | SQLAlchemy 2.0 async | asyncpg 驱动 |
| 向量检索 | pgvector | PostgreSQL 扩展，余弦相似度 |
| 全文检索 | PostgreSQL tsvector/tsquery | 中文分词 (zhparser) |
| 精排 | bge-reranker-v2-m3 | SiliconFlow API |
| 流式传输 | SSE (Server-Sent Events) | sse-starlette |
| 配置 | YAML + Pydantic Settings | 环境变量覆盖 |
| 日志 | structlog | 双通道 (控制台 + 文件) |

---

## 2. Agent 工作流设计

### 2.1 整体管线

```
START → Router → [条件边] → Extraction / ScenarioGen → Retrieval → OptionGen → END
                      │
                      └── chat → END (直接结束)
```

### 2.2 AgentState（节点间共享状态）

```python
class AgentState(TypedDict):
    user_query: str               # 当前用户查询原文
    conversation_id: str          # 会话 ID（UUID）
    welcome_text: str             # 欢迎语（Router 生成）
    stream: bool                  # 是否流式
    intent: str                   # chat | explicit | scenario
    requirements: list[dict]      # Extraction/ScenarioGen 输出：按品类分组的意图
    scenario_description: str | None  # 场景描述（仅 scenario 路径）
    retrieval_results: list[dict] # Retrieval 输出：商品详情列表
    chat_reply: str               # 闲聊回复 / 结束语
    next_options: list[str]       # 下一步推荐选项
    failed_categories: list[str]  # 检索失败的 sub_category
    _sse_queue: Any               # asyncio.Queue，SSE 事件传输通道
```

### 2.3 条件边路由

```python
def route_intent(state):
    intent = state["intent"]
    if intent == "chat":      return "chat"       # → END
    elif intent == "scenario": return "scenario_gen"  # → ScenarioGen
    else:                      return "extraction"    # → Extraction
```

---

## 3. 各节点详细设计

### 3.1 Router — 统一意图路由

**文件**: `app/agent/nodes/intent_route_agent.py`
**Prompt**: `app/agent/prompts/intent_router_prompt.py`

**职责**: 工作流第一个节点，单次 LLM 调用完成意图分类 + 回复生成。合并了原 Router + ChitChat + Welcome 三个节点。

**输入处理**:
1. 从 ChatHistory 表加载最近 N 轮对话历史（N = `memory_recent_rounds`，默认 10）
2. 注入 INTENT_ROUTER_SYSTEM prompt 的 `{recent_queries}` 占位符
3. 格式: `用户: {content}\n助手: {content}\n...`（时间正序）

**意图分类**:
- `chat` → 闲聊回复 + done → END
- `explicit` → 欢迎语 → Extraction
- `scenario` → 欢迎语 → ScenarioGen

**SSE 流式推送**:
```
welcome_chat_stream: start → delta × N → end
```
使用 `stream_json_field(token_stream, "welcome_chat")` 实时提取并推送 welcome_chat 字段。

**Fallback**: LLM 失败 → intent="explicit", welcome_text=""。

### 3.2 Extraction — 意图提取

**文件**: `app/agent/nodes/intent_extract_agent.py`
**Prompt**: `app/agent/prompts/intent_extract_prompt.py`

**三步流程**:

**Step 1 — 品类/品牌提取**:
- LLM 从 user_query 提取 category / sub_category / brand
- 注入品类上下文: 合法品类列表 (category_lookup) + 对话历史 + 品牌映射
- Tool 校验: `query_field_values` 验证品牌存在性; `fetch_category_context` 验证品类合法性
- 不合法品类/品牌 → null

**Step 2 — 历史拼接**:
- 按 (category, sub_category) 从 ChatHistory 表过滤查询滑动窗口历史
- 多品类独立拼接，分段展示 (## 品类 N: ...)
- 末尾追加当前查询: `当前查询: {user_query}`

**Step 3 — 分组意图提取**:
- LLM 从拼接文本按品类分组提取: text / min_price / max_price / order_num / brand
- 自然语言价格调整规则:
  - 当前查询含"更平价/贵一点"且无显式数值 → 从历史提取价格基线按比例调整
  - 当前查询有显式数值 → 直接使用

**输出格式**:
```json
[{category, sub_category, text, min_price, max_price, order_num, brand}]
```

### 3.3 Scenario Gen — 场景需求生成

**文件**: `app/agent/nodes/scene_generate_agent.py`
**Prompt**: `app/agent/prompts/scene_generate_prompt.py`

**流程**:
1. 从 category_lookup 表读取可用品类列表
2. 提取前 `max_scene_categories` 个（默认 3）品类，加载滑动窗口历史
3. LLM 端到端输出: scenario_description + requirements[]
4. 品类交叉校验: LLM 输出的 category/sub_category 与合法列表做精确匹配
5. 不匹配 → (None, None) / 匹配 → 标准化格式

**输出**: `{scenario_description: str, requirements: [intent格式]}`

### 3.4 Retrieval — 商品检索（核心 RAG 管线）

**文件**: `app/agent/nodes/product_retrieve_agent.py`
**服务**: `app/services/retriever_service.py`

#### 完整检索管线（每品类独立执行）

```
requirements → [按品类分组并行检索]
                  │
           ┌──────▼──────┐
           │ SubQuery 转换  │  intent → keyword + semantic + structured_filter
           └──────┬──────┘
                  │
           ┌──────▼──────┐
           │ SQL 条件转换  │  category/sub_category/price/stock/brand → FilterClause
           └──────┬──────┘
                  │
        ┌─────────▼─────────┐
        │  双路并行检索       │
        ├───────────────────┤
        │ 语义检索           │  pgvector cosine_distance + SQL 条件 → top-25
        │ 关键词检索         │  plainto_tsquery + ts_rank + SQL 条件 → top-25
        │ ROW_NUMBER()      │  PARTITION BY product_id → 按 product 去重
        └─────────┬─────────┘
                  │
           ┌──────▼──────┐
           │ 加权 RRF 融合 │  score(p) = 0.7/(k+rank_sem) + 0.3/(k+rank_kw) → top-25
           │ 按 product 聚合│
           └──────┬──────┘
                  │
           ┌──────▼──────┐
           │ Reranker 精排│  bge-reranker-v2-m3 → top-5; 失败 fallback 到 RRF top-5
           └──────┬──────┘
                  │
           ┌──────▼──────┐
           │ Review 截断  │  max_match_texts_per_product=5, max_chars=500
           └──────┬──────┘
                  │
           ┌──────▼──────┐
           │ SSE 逐商品发送 │  category_intro → products → product_reason → ...
           └─────────────┘
```

**并行策略**: `asyncio.Semaphore(max_category_concurrency)` 限流（默认 5），每品类独立 AsyncSession。

**检索架构关键设计**:
- **商品级** (非 SKU 级): `ROW_NUMBER() OVER (PARTITION BY product_id)` 确保每个 product 在每路检索中只出现一次
- **双路互补**: 语义检索负责语义匹配，关键词检索负责精确术语匹配
- **加权融合**: 语义 0.7 / 关键词 0.3，语义权重更高因为中文分词可能不准确
- **精排兜底**: Reranker API 超时/失败 → 用 RRF top-5 结果，不中断流程

### 3.5 Option Gen — 选项 + 结束语生成

**文件**: `app/agent/nodes/option_generate_agent.py`
**Prompt**: `app/agent/prompts/option_generate_prompt.py`

**职责**: 所有品类检索完成后执行一次。零 DB 访问。

**流程**:
1. 构建上下文: 品类摘要 + 商品数量 + 场景描述 + 对话历史 + 失败品类
2. retrieval_results 压缩: 最多 5 商品，每条 ≤300 字符
3. 单次 LLM 调用输出: ending + next_options (最多 3 条)
4. 流式路径: `stream_json_field` 提取 ending 逐 token 推送 ending_stream

---

## 4. 对话历史设计

### 4.1 数据模型

**ChatHistory 表** (`app/models/chat_history.py`):
```sql
CREATE TABLE chat_history (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL,  -- 会话 ID，有索引
    role VARCHAR(10) NOT NULL,             -- user / assistant
    content TEXT NOT NULL,                 -- 消息内容
    created_at TIMESTAMP DEFAULT now()
);
```

**Conversation 表** (`app/models/conversation.py`):
```sql
CREATE TABLE conversation (
    conversation_id VARCHAR(36) PRIMARY KEY,  -- UUID
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### 4.2 滑动窗口查询

**函数**: `get_chat_history_window(db_session, conversation_id, max_rounds, category_filter?, max_chars_per_msg?)` → `app/agent/history.py`

```sql
SELECT role, content FROM chat_history
WHERE conversation_id = :cid
ORDER BY created_at DESC
LIMIT :max_rounds * 2  -- 每轮 2 条 (user + assistant)
```

结果翻转为时间正序，格式化为: `用户: {content}\n助手: {content}\n...`

**注入点**:
- Router: 跨品类取最近 N 轮
- Extraction Step1: 跨品类取最近 N 轮
- Extraction Step2: 按 (category, sub_category) 过滤
- Scenario Gen: 按品类（前 max_scene_categories 个）过滤
- Retrieval 2b (推荐理由): 按品类过滤
- Option Gen: 跨品类取最近 N 轮

### 4.3 持久化时机

每轮 `/api/search` 完成后，在 `_agent_event_stream` 的 finally 块中:
1. 检查 `final_state.user_query` 和 `final_state.chat_reply` 均非空
2. 插入 2 条 ChatHistory: role=user + role=assistant
3. Conversation.updated_at 由 SQLAlchemy onupdate 自动维护

---

## 5. SSE 事件流设计

### 5.1 消费循环

**函数**: `_agent_event_stream(user_query, graph, queue, total_timeout, conversation_id, stream)` → `app/api/search.py`

```
1. 校验 conversation 存在性（查 Conversation 表）
2. 构建 initial_state (含 _sse_queue 注入)
3. 后台启动: graph_task = asyncio.create_task(graph.ainvoke(initial_state))
4. 循环: queue.get() → yield SSE 事件
5. 检测到 done 事件 → 直接返回 (chat 路径)
6. graph 完成 → 排空 queue 残留事件
7. finally:
   a. 持久化 ChatHistory (user + assistant)
   b. 从 final_state 读取 next_options → yield
   c. yield done (含 conversation_id)
```

### 5.2 完整事件流

**流式推荐路径 (explicit/scenario)**:
```
welcome_chat_stream (start → delta × N → end)
→ [category_intro_stream (start → delta × N → end)]  * 仅多品类
→ products (单商品) → product_reason (推荐理由)
→ ... (逐品类、逐商品重复)
→ ending_stream (start → delta × N → end)
→ next_options (消费循环 finally)
→ done (消费循环 finally)
```

**流式 chat 路径**:
```
welcome_chat_stream (start → delta × N → end)
→ done (Router 直接发送)
```

---

## 6. 配置系统

### 6.1 配置加载

YAML + Pydantic Settings 双层: `config.yaml` → `app/config.py` Settings.from_yaml()

优先级: 环境变量 > .secrets.yaml > config.yaml

### 6.2 检索参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| semantic_top_k | 25 | 语义检索返回数 |
| keyword_top_k | 25 | 关键词检索返回数 |
| rrf_semantic_weight | 0.7 | RRF 语义权重 |
| rrf_keyword_weight | 0.3 | RRF 关键词权重 |
| rrf_k | 60 | RRF 平滑参数 |
| rrf_top_k | 25 | RRF 融合后 top-k |
| rerank_top_k | 5 | 精排后最终返回数 |
| max_match_texts_per_product | 5 | 单商品最多 review 条数 |
| max_match_chars_per_product | 500 | 单商品 review 最大字符数 |
| max_category_concurrency | 5 | 品类并行最大并发数 |
| max_scene_categories | 3 | 场景生成最大品类数 |
| memory_recent_rounds | 10 | 滑动窗口轮数 |
| reasoning_max_chars | 100 | 推荐理由字数 |

### 6.3 超时配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| timeout.total_request | 300 | SSE 总超时 (秒) |
| timeout.rerank | 5.0 | Reranker API 超时 |
| timeout.generation | 60.0 | LLM 生成超时 |

---

## 7. Fallback 策略

| 节点 | 失败行为 |
|------|---------|
| Router | LLM 失败 → intent="explicit", welcome_text="" |
| Extraction Step1 | LLM 失败 → 品类/品牌为 null |
| Extraction Step3 | LLM 失败 → [{text: user_query, category: null, ...}] |
| Scenario Gen | LLM 失败 → requirements=[], scenario_description=user_query |
| Retrieval (单品类) | 异常 → 记录到 failed_categories，其他品类继续 |
| Retrieval (全部失败) | 用原始 user_query 做语义检索兜底 |
| Reranker | API 失败 → 跳过精排，直接返回 RRF top-5 |
| Option Gen | LLM 失败 → next_options=[], ending="" |

---
