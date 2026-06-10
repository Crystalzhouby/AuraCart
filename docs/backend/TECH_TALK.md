# AuraCart 后端关键技术讲解稿（~10分钟）

## 开场：系统定位 (30s)

大家好。AuraCart 是一个电商导购 AI Agent 系统，核心理念是**用 RAG 技术让大模型能够基于真实的商品数据回答用户的购物需求**。

用户输入自然语言查询，系统通过一个 5 节点的 LangGraph 工作流，完成从意图理解 → 商品检索 → 推荐生成的全流程，最终通过 SSE 流式推送给前端。

接下来我重点讲解 `/api/search` 这条核心链路。

---

## 整体架构 (1min)

```
GET /api/search/{conversation_id}?q=推荐一款200元以下的防晒霜&stream=true

         ┌──────────────────────────────────────────┐
         │  _agent_event_stream (SSE 消费循环)        │
         │  1. 校验会话 2. 启动graph 3. 消费queue     │
         │  4. finally: next_options → done → 持久化  │
         └───────────────┬──────────────────────────┘
                         │ asyncio.Queue
         ┌───────────────▼──────────────────────────┐
         │  LangGraph StateGraph (5节点)              │
         │  Router → Extraction/ScenarioGen          │
         │         → Retrieval → OptionGen → END     │
         └──────────────────────────────────────────┘
```

核心技术栈：FastAPI + LangGraph + PostgreSQL/pgvector + LLM + bge-reranker。配置通过 YAML + Pydantic Settings 管理，模型 API 密钥从环境变量注入。

---

## /api/search 链路详解 (3min)

当用户发起请求 `GET /api/search/{conversation_id}?q=...&stream=true`：

**第一步 — 校验会话合法性**。从 Conversation 表查询 conversation_id 是否存在。Conversation 表只有 3 个字段：conversation_id (PK)、created_at、updated_at。它的存在只证明这个会话 ID 是合法的。如果会话不存在，直接返回 error + done。

**第二步 — 构建初始状态**。创建一个 AgentState 字典，包含 user_query、conversation_id、stream 等字段。关键的一行是 `initial_state["_sse_queue"] = queue`——我们把一个 asyncio.Queue 注入到状态中，LangGraph 的所有节点通过 `state.get("_sse_queue")` 获取这个队列，把 SSE 事件推送到队列中。

**第三步 — 后台启动 graph**。`asyncio.create_task(graph.ainvoke(initial_state))` 让 LangGraph 在后台异步执行 5 节点管线。同时主协程进入消费循环。

**第四步 — 消费循环的 while True 循环**。主协程不停地从 queue 里取事件，yield 出去给 FastAPI 的 EventSourceResponse。这里有超时保护——如果超过 total_timeout（默认 300 秒），发送 error + done 结束。检测到 done 事件立即退出循环——这是 chat 路径的快速出口。

**第五步 — finally 收尾**。不管前面如何结束，finally 块永远执行。它做三件事：
1. 等待 graph 终态，获取 final_state
2. 持久化聊天记录到 ChatHistory 表——user_query (role=user) 和 chat_reply (role=assistant) 各一条
3. 从 final_state 读 next_options 发送给前端，最后发送 done 包裹 conversation_id

关于聊天记录持久化的判断条件：**只有当 user_query 和 chat_reply 均非空时才写入**。chat_reply 的来源——chat 路径由 Router 返回，推荐路径由 Option Gen 返回。这确保了闲聊回复和推荐结束语都被正确记录。

---

## Router 节点 — 意图分类 (1min)

Router 是整个工作流的第一个节点，设计上的核心决策是**单次 LLM 调用完成意图分类 + 回复生成**，合并了原来分开的 Router + ChitChat + Welcome 三个节点。

在调用 LLM 之前，它先从 ChatHistory 表加载最近 N 轮对话历史（N = memory_recent_rounds，默认 10 轮）。查询 SQL 是：

```sql
SELECT role, content FROM chat_history
WHERE conversation_id = :cid
ORDER BY created_at DESC LIMIT 20;  -- 10轮×2条
```

结果翻转为时间正序，格式化为 `用户: xxx\n助手: xxx`，注入 INTENT_ROUTER_SYSTEM prompt 的 {recent_queries} 占位符。这个 prompt 设计了三个意图类别：chat（闲聊）、explicit（明确商品需求）、scenario（场景化需求），以及对应的回复规则。

流式路径是关键优化——我们用 `stream_json_field(token_stream, "welcome_chat")` 函数，它接收 LLM 的 token 流，逐 token 匹配 JSON 中的 welcome_chat 字段，实时推送 `welcome_chat_stream` 事件。前端可以逐字展示欢迎语，无需等待完整响应。

条件边路由的逻辑：intent=="chat" → 直接到 END（由 Router 发送 done），intent=="scenario" → Scenario Gen，intent=="explicit" → Extraction。

---

## Extraction 节点 — 三步意图提取 (1min)

Extraction 负责将自然语言转换为结构化的检索条件。三步设计：

**Step 1 — 品类/品牌提取**：LLM 从用户查询中识别 category/sub_category/brand，然后走 Tool 校验。这里有两个校验：品牌用 `query_field_values` 查 product 表验证品牌是否存在，品类用 category_lookup 表精确匹配。（category_lookup 表存储所有合法的 (category, sub_category) 取值对，通过脚本从 product 表构建。）

**Step 2 — 历史拼接**：这是多轮对话的核心。从 ChatHistory 表按品类过滤加载滑动窗口历史，与当前查询拼接成一个 context 文本。举个例子，如果用户之前说"帮我推荐跑鞋"，当前说"要轻量的"，拼接后的 context 就是"历史：帮我推荐跑鞋\n当前：要轻量的"。

**Step 3 — 分组提取意图**：LLM 从拼接文本按品类分组输出 text、min_price、max_price、order_num、brand 五个字段。这里有一个自然语言价格调整规则——如果用户说"更平价一点"且没有给具体价格，系统会从历史查询中提取价格基线按比例下调。

---

## Retrieval 节点 — RAG 管线 (3min)

这是系统最核心的节点，也是最复杂的。每个品类的检索管线分 9 步，多品类并行执行，asyncio.Semaphore 限流。

**第一步 — SubQuery 转换**：把 intent 对象转换为三个 SubQuery —— keyword（全文检索）、semantic（向量检索）、structured_filter（SQL 硬约束）。keyword 和 semantic 共享 text 字段，structured_filter 处理价格/品类/品牌等条件。

**第二步 — SQL 条件转换**：把 category/sub_category 转成 `p.category = :v0 AND p.sub_category = :v1`，价格区间转成 `s.price BETWEEN :v2 AND :v3`，库存转成 `s.stock >= :v4`，品牌转成 `p.brand IN (:v5, :v6...)`。这些 SQL 片段通过 FilterClause 对象传递给检索器。

**第三步 — 双路并行检索**：这是 RAG 的关键。语义路和关键词路同时执行，各返回 top-25。

- **语义检索**：用 pgvector 的 `cosine_distance` 算子，计算 query embedding 与 product_review.embedding 的余弦距离，配合 SQL 硬约束条件
- **关键词检索**：用 `plainto_tsquery('chinese', ...)` 做中文分词，配合 `ts_rank` 做全文排序

关键技巧是每个 product 只保留一次——`ROW_NUMBER() OVER (PARTITION BY pr.product_id ORDER BY score DESC)` 确保即使一个商品的多个 review 都匹配，也只在每路结果中出现一次。这是**商品级检索**的设计核心。

**第四步 — RRF 融合**：RRF = Reciprocal Rank Fusion，公式是：

```
score(product_id) = 0.7/(60 + rank_semantic) + 0.3/(60 + rank_keyword)
```

语义 0.7、关键词 0.3 的权重分配是有原因的：中文分词（zhparser）对电商术语的切分效果不稳定，所以更依赖语义检索。k=60 是经验参数，降低了排名靠前的商品之间的分数差距。

**第五步 — bge-reranker 精排**：调用 SiliconFlow API 的 BAAI/bge-reranker-v2-m3 模型。reranker 会对 RRF top-25 的每个商品的文本内容（标题 + matched_texts）与用户查询做精细匹配，取 top-5。API 超时/失败时 fallback 到 RRF top-5，不中断流程。

**第六步 — Review 截断**：每个商品最多保留 5 条 matched_texts，每条最多 500 字符。控制 prompt 大小。

**第七步 — 品类介绍语 + 推荐理由 + 商品 SSE**：多品类时生成品类介绍过渡语（category_intro_stream），然后逐商品发送 products（product_id + category + sub_category）和 product_reason（推荐理由）。推荐理由用 LLM 生成，每条引用商品的真实 matched_texts。

---

## Option Gen + 收尾 (30s)

Option Gen 在所有品类检索完成后执行，**零数据库访问**——数据直接从 AgentState.retrieval_results 读取并压缩（最多 5 个商品，每条 ≤300 字符），单次 LLM 调用输出 ending + next_options。

SSE 事件流顺序是：
```
welcome_chat_stream → [category_intro_stream] → products → product_reason
  → ... (逐品类) → ending_stream → next_options → done
```

next_options 和 done 不是任何节点发送的，而是消费循环的 finally 块从 final_state 读取后统一发送。这样设计确保它们只发送一次，且 done 永远是最后的事件。

---

## 对话历史机制 (30s)

HISTORY_OPT2 重构后，我们删除了 session_memory 机制，改用 ChatHistory 表 + 滑动窗口。

以前的问题：session_memory 是内存中的 JSON，按 (category, sub_category) 分组存储原始查询，写入 conversation.memory JSONB 列。问题在于 memory 和 chat_message 两处都要维护，复杂且容易分裂。

现在的方案：只保留 ChatHistory 表，每次搜索完成后插入 2 条记录（user + assistant）。各节点调用 `get_chat_history_window()` 查询最近 N 轮对话，按品类过滤。Conversation 表精简为 3 字段，只用于会话存在性校验。

---

## 配置与 Fallback 策略 (30s)

所有参数都在 config.yaml 中配置，通过 Pydantic Settings 管理。关键参数：semantic_top_k=25、keyword_top_k=25、rrf_top_k=25、rerank_top_k=5、max_category_concurrency=5、内存截断 memory_max_tokens=2000。

每个节点都有 fallback 策略：Router LLM 失败 → explicit；Extraction 失败 → 语义兜底；Retrieval 单品类失败 → 记录到 failed_categories，其他继续；Reranker 失败 → 跳过精排用 RRF top-5。

## 总结 (15s)

AuraCart 后端通过 LangGraph 工作流 + RAG 管线 + SSE 流式传输，实现了一个完整的电商导购 AI Agent。核心价值是让大模型能够基于真实的商品数据库进行检索和推荐，而不是凭空编造。谢谢。
