# 多 Agent 导购编码级方案

## 1. 细粒度模块拆分

### 1.1 Agent 层

```text
server/app/agents/
  __init__.py
  base.py
  schemas.py
  prompts.py
  query_rewrite_agent.py
  intent_recognition_agent.py
  exploration_agent.py
  need_clarify_agent.py
  scenario_plan_agent.py
  product_search_agent.py
  comparison_agent.py
  cart_action_agent.py
  recommend_agent.py
  quick_reply_agent.py
  fallback_agent.py
```

职责：

- `base.py`：统一 LLM 调用、JSON 解析、降级处理。
- `schemas.py`：所有 Agent 输入输出 Pydantic 结构。
- `prompts.py`：集中维护 Prompt。
- 具体 Agent 文件只处理自己的输入输出。

### 1.2 编排层

```text
server/app/orchestrator/
  __init__.py
  guide_orchestrator.py
  state.py
  routing.py
```

职责：

- `guide_orchestrator.py`：主流程入口。
- `state.py`：会话状态、当前阶段、Agent 上下文。
- `routing.py`：根据意图识别结果分支。

### 1.3 会话记忆层

```text
server/app/memory/
  __init__.py
  session_memory.py
  memory_store.py
```

MVP：

- `memory_store.py` 先用内存字典。
- 后续替换 PostgreSQL 或 Redis。

### 1.4 工具层

```text
server/app/tools/
  __init__.py
  retrieval_tool.py
  cart_tool.py
  product_context_tool.py
```

职责：

- `retrieval_tool.py`：包装现有 `QueryParser`、`Retriever`、`Merger`、SKU 补全。
- `cart_tool.py`：购物车加删改查。
- `product_context_tool.py`：补齐 FAQ、评价、营销描述等推荐上下文。

### 1.5 API 层

```text
server/app/api/chat.py
```

职责：

- 新增多轮对话入口。
- 支持普通 JSON 响应和 SSE 流式响应。
- 返回文本、商品、快捷回复、状态。

## 2. 目录结构

建议最终结构：

```text
server/app/
  agents/
  api/
    chat.py
    search.py
    products.py
    admin.py
  memory/
  orchestrator/
  tools/
  rag/
  services/
  schemas/
  models/
```

## 3. 核心接口

### 3.1 对话请求

```python
class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    selected_option: SelectedOption | None = None
```

实现思路：

- 如果没有 `session_id`，后端创建新会话。
- 如果有 `selected_option`，优先将 `payload` 写入会话约束。
- `message` 仍作为自然语言输入进入改写和意图识别。

### 3.2 对话响应

```python
class ChatResponse(BaseModel):
    session_id: str
    reply: str
    products: list[ProductCard] = []
    next_options: list[QuickReplyOption] = []
    status: str
```

实现思路：

- `reply` 用于对话气泡。
- `products` 用于商品卡片。
- `next_options` 用于 ABC 快捷回复。
- `status` 表示当前阶段，例如 `exploring`、`clarifying`、`complete`。

### 3.3 快捷回复选项

```python
class QuickReplyOption(BaseModel):
    key: str
    value: str
    type: Literal["chat", "explore", "clarify", "filter", "compare", "action"]
    payload: dict = Field(default_factory=dict)
```

实现思路：

- `value` 同时用于展示和点击后发送。
- `payload` 用于稳定写入会话状态。

### 3.4 会话记忆

```python
class SessionMemory(BaseModel):
    session_id: str
    conversation_stage: str
    conversation_history: list[ChatMessage]
    latent_needs: dict
    collected_constraints: dict
    last_intent: str | None
    last_products: list[dict]
    pending_question: str | None
    cart_state: dict
```

实现思路：

- 每轮开始读取。
- 每个 Agent 写入自己负责的字段。
- 每轮结束保存。

## 4. 关键数据结构

### 4.1 Agent 标准输出

```python
class AgentResult(BaseModel):
    ok: bool
    data: dict
    error: str | None = None
    raw_text: str | None = None
```

用途：

- 统一处理 LLM JSON 解析失败。
- 保留原始文本用于调试。

### 4.2 意图识别结果

```python
class IntentResult(BaseModel):
    intent: Literal[
        "clear_product_need",
        "exploratory_need",
        "scenario_solution",
        "compare_products",
        "cart_action",
        "pure_chitchat",
        "unknown",
    ]
    confidence: float
    primary_category: str | None = None
    primary_sub_category: str | None = None
    route: str
    reason: str
```

### 4.3 需求澄清结果

```python
class ClarifyResult(BaseModel):
    status: Literal["clarify", "ready"]
    missing_slots: list[str]
    collected_constraints: dict
    question: str | None = None
    candidate_next_options: list[QuickReplyOption] = []
    reason: str
```

### 4.4 检索计划

```python
class SearchPlan(BaseModel):
    keyword_queries: list[str]
    semantic_queries: list[str]
    filters: dict
    knowledge_queries: list[str]
    rerank_focus: list[str]
    negative_constraints: list[str]
```

## 5. 主功能链路时序

### 5.1 明确商品推荐

```text
Chat API
  → SessionMemory.load
  → QueryRewriteAgent
  → IntentRecognitionAgent
  → NeedClarifyAgent
  → ProductSearchAgent
  → RetrievalTool
  → ProductContextTool
  → RecommendAgent
  → QuickReplyAgent
  → SessionMemory.save
  → ChatResponse
```

### 5.2 用户只是聊天

```text
Chat API
  → SessionMemory.load
  → QueryRewriteAgent
  → IntentRecognitionAgent
  → FallbackAgent
  → QuickReplyAgent
  → SessionMemory.save
  → ChatResponse
```

### 5.3 潜在购物需求

```text
Chat API
  → SessionMemory.load
  → QueryRewriteAgent
  → IntentRecognitionAgent
  → ExplorationAgent
  → QuickReplyAgent
  → SessionMemory.save
  → ChatResponse
```

### 5.4 信息不足追问

```text
Chat API
  → SessionMemory.load
  → QueryRewriteAgent
  → IntentRecognitionAgent
  → NeedClarifyAgent(status=clarify)
  → QuickReplyAgent
  → SessionMemory.save
  → ChatResponse
```

### 5.5 购物车动作

```text
Chat API
  → SessionMemory.load
  → QueryRewriteAgent
  → IntentRecognitionAgent(intent=cart_action)
  → CartActionAgent
  → CartTool
  → QuickReplyAgent
  → SessionMemory.save
  → ChatResponse
```

## 6. 权限、隔离和边界

- Agent 只能生成结构化计划，不直接改数据库。
- 商品检索、购物车修改、订单模拟必须通过工具层执行。
- LLM 输出必须经过 Pydantic 校验。
- 推荐生成不得输出商品库外事实。
- 快捷回复不得限制用户自由输入。
- 会话记忆按 `session_id` 隔离。
- 日志中避免记录真实 API Key 和敏感配置。

## 7. 尚不确定边界

- 是否第一阶段接 LangGraph；建议先不接。
- 会话记忆是否需要服务重启后保留；MVP 可不保留。
- 购物车是否使用真实数据库表；MVP 可先会话内模拟。
- 当前 Android 客户端是否已具备快捷回复 UI；如没有，需要前端补齐。
- 是否必须支持 SSE 逐 token；如果时间紧，可先普通 JSON，再升级 SSE。
