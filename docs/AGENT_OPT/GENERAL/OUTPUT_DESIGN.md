# Agent 流式输出设计方案

## 1. 架构概览：单队列模型

整个 Agent 工作流的流式输出基于 **单一 `asyncio.Queue` 实例** 实现。该队列由 API 路由层创建，通过 `AgentState._sse_queue` 字段注入到 LangGraph 的共享状态中，各节点通过该队列向客户端推送 SSE（Server-Sent Events）事件。

```
┌─ API 路由层 (search.py) ─────────────────────────────────────────────┐
│                                                                       │
│  1. 创建 queue = asyncio.Queue()                                      │
│  2. 注入 initial_state["_sse_queue"] = queue                          │
│  3. 后台启动 graph.ainvoke(initial_state)                              │
│  4. EventSourceResponse 消费 _agent_event_stream(queue)                │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
         │                              │
         │ 注入                         │ 消费
         ▼                              ▼
┌─ LangGraph 节点 ──┐          ┌─ _agent_event_stream ──┐
│                   │          │                         │
│  queue.put(event) │ ──────▶  │  event = await queue.get()  │
│                   │          │  yield SSE dict         │
└───────────────────┘          └─────────────────────────┘
```

**关键设计决策**：不逐 token 流式输出。各节点的 LLM 调用结果经缓冲后，以完整的语义事件（如 `welcome`、`products`、`product_reason`、`ending`）为单位推送到队列。这是面向电商导购场景的刻意选择——客户端按事件类型渲染 UI 卡片，而非逐字打印文本。

## 2. 核心组件

### 2.1 事件通道：`_sse_queue`

**定义位置**：`server/app/agent/state.py:41`

```python
class AgentState(TypedDict):
    ...
    _sse_queue: Any   # asyncio.Queue，SSE 事件通道，不参与序列化/持久化
```

`_sse_queue` 以 `_` 前缀命名表示它是传输层关注点而非业务状态。在 `graph.py:21` 中被明确排除在日志记录之外：

```python
_SKIP_LOG_FIELDS = {"_sse_queue"}
```

### 2.2 队列的创建与注入

**位置**：`server/app/api/search.py:117-224`

```python
queue: asyncio.Queue = asyncio.Queue()       # 第 117 行

initial_state: AgentState = { ... }
initial_state["_sse_queue"] = queue           # 第 224 行

graph_task = asyncio.create_task(graph.ainvoke(initial_state))  # 第 227 行
```

### 2.3 消费者协程：`_agent_event_stream`

**位置**：`server/app/api/search.py:147-369`

这是整个流式输出的中枢。它是一个异步生成器，同时充当：

| 角色 | 说明 |
|------|------|
| **队列消费者** | 循环从 `queue` 中取出事件，转换为 SSE 格式 yield 出去 |
| **超时守卫** | 30 秒总超时 + 每次 `queue.get()` 最多等 5 秒 |
| **终态处理** | graph 完成后排空残留事件、持久化记忆、发送 `next_options` 和 `done` |
| **异常兜底** | 捕获 `CancelledError`（客户端断开）、graph 异常，统一发送 error + done |

核心循环逻辑（第 230-259 行）：

```
while True:
    remaining = overall_deadline - now
    if remaining <= 0:  → 发送 error + done，返回

    try:
        event = await asyncio.wait_for(queue.get(), timeout=min(remaining, 5.0))
    except TimeoutError:
        if graph_task.done():  → 跳出循环，进入终态处理
        else:                  → 继续等待

    if event["event"] == "done":  → 转发 done，立即返回（闲聊路径）
    常规事件: 直接转发
```

**为什么 `done` 事件直接 return**：闲聊（chitchat）分支在节点内部推送 `done`，此时 graph 尚未完成（graph 在 chitchat 之后才走 END 边）。如果不直接 return 而是等 graph 完成再发 `done`，消费者会因 graph_task 仍在运行而继续等待超时。

`finally` 块处理推荐路径（第 278-369 行）：

```
finally:
    等待 graph_task 完成（最多 10 秒）
    读取 final_state
    持久化 session_memory → DB
    持久化 chat_reply → DB（仅闲聊路径有值）
    发送 next_options（从 final_state 读取）
    发送 done（含 conversation_id）
```

**`next_options` 为何在 `finally` 中发送**：OptionGen 节点不持有 queue 引用，它将结果写入 `state["next_options"]`。由 `finally` 块统一读取并发送，避免了"队列排空时发送"和"finally 块发送"之间的竞态。

### 2.4 LLM 服务的两种调用模式

**位置**：`server/app/services/llm_service.py`

| 方法 | 返回类型 | 使用节点 |
|------|---------|---------|
| `chat()` | `str` — 阻塞等待完整响应 | Router, Extraction, ScenarioGen, Retrieval, OptionGen |
| `chat_stream()` | `AsyncGenerator[str]` — 逐 token 产出 | ChitChat |

## 3. 各节点的流式输出模式

### 3.1 Router（`nodes/router.py`）

**流式输出**：无。不持有 queue，不推送任何 SSE 事件。

输出写入 state 供下游使用：
- `intent`：三分类结果（chat/explicit/scenario）
- `rewritten_query`：改写后的查询文本
- `welcome_text`：由 LLM 生成的欢迎语（由 Retriever 节点负责发送）

### 3.2 ChitChat（`nodes/chitchat.py`）

**流式输出**：缓冲后单次推送。唯一使用 `chat_stream()` 的节点，但将 token 收集完毕后作为完整文本一次性发送。

```
流程:
  1. parts = []
  2. async for token in llm.chat_stream(...):
         parts.append(token)
  3. reply = "".join(parts)
  4. queue.put({"event": "chat_reply", "data": reply})
  5. queue.put({"event": "done", "data": {}})
     ↑ 注意：done 由节点自身发送，_agent_event_stream 收到后直接 return
```

**设计考量**：闲聊回复通常较短，逐 token 流式传输对用户体验提升有限，且会增加事件数量。单次发送简化了客户端渲染逻辑。

### 3.3 Extraction（`nodes/extraction.py`）

**流式输出**：无。纯后端处理节点，三步 LLM 调用均为非流式。输出写入 `state["requirements"]`。

### 3.4 ScenarioGen（`nodes/scenario_gen.py`）

**流式输出**：无。单次非流式 LLM 调用。输出写入 `state["scenario_description"]` 和 `state["requirements"]`。

### 3.5 Retriever（`nodes/retriever.py`）★ 流式主力

**这是整个系统中唯一大量使用 SSE 推送的业务节点**。详细分析见第 4 节。

### 3.6 OptionGen（`nodes/option_gen.py`）

**流式输出**：间接。节点本身不持有 queue 引用，将 `next_options` 写入 state。由 `_agent_event_stream` 的 `finally` 块在 graph 完成后统一发送。

```
设计考量:
  - OptionGen 是工作流的最后一个节点（END 边）
  - 若在节点内发送 next_options，可能与 finally 块中的 done 事件产生竞态
  - 交由 finally 块统一发送保证了事件顺序：next_options → done
```

## 4. Retriever 节点的多队列并行处理逻辑

Retriever 节点不创建多个 `asyncio.Queue`。所谓的"多队列"指的是其内部的 **多层并行处理架构**：品类级并行检索 + 产品级并行 LLM 调用，所有结果通过串行化顺序推送到同一个共享队列。

### 4.1 整体流水线

```
Retrieval 节点入口
│
├─ 1. 发送 welcome 事件（文本由 Router 节点预生成）
│
├─ 2. 并行品类检索（asyncio.gather + Semaphore(5)）
│     ├─ _category_task(category_A)  ─┐
│     ├─ _category_task(category_B)  ─┤ 并行执行
│     └─ _category_task(category_C)  ─┘
│     每个 _category_task 内部:
│       ├─ SQL 条件转换（价格/品牌/库存过滤）
│       ├─ 双路检索并行: semantic(top-25) + keyword(top-25)
│       ├─ 加权 RRF 融合（semantic 0.7 / keyword 0.3）→ top-25
│       └─ bge-reranker 精排 → top-5
│
├─ 3. 串行处理每个品类（按 requirements 顺序）
│     ├─ 3a. 品类介绍语（仅多品类时）: queue.put(category_intro)
│     ├─ 3b. 并行生成所有产品的推荐理由（asyncio.gather）
│     └─ 3c. 串行发送每个产品:
│           queue.put(products)       → 产品 ID 和分类信息
│           queue.put(product_reason) → 推荐理由文本
│
├─ 4. 发送 ending 事件
│
└─ 5. 更新 session_memory → 写入 state
```

### 4.2 品类并行检索（第 2 步）

**位置**：`retriever.py:405-428`

```python
semaphore = asyncio.Semaphore(settings.search.max_category_concurrency)  # 默认 5

async def _bounded_task(intent):
    async with semaphore:
        return await _category_task(intent, ...)

tasks = [_bounded_task(req) for req in requirements]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

关键设计：
- **`asyncio.Semaphore(5)`** 限制同时进行的数据库检索数量，防止连接池耗尽
- **`return_exceptions=True`** 确保一个品类失败不影响其他品类
- 每个 `_category_task` 内部还有双路检索（semantic + keyword）的并行

### 4.3 品类介绍语的条件发送（第 3a 步）

**位置**：`retriever.py:450-456`

```python
if total_valid > 1:                          # 仅多品类时发送
    intro = await _generate_category_intro(...)
    if queue and intro:
        await queue.put({"event": "category_intro", "data": intro})
```

单品类场景下不发送 `category_intro`，减少不必要的 LLM 调用。

### 4.4 产品推荐理由的并行生成 + 串行发送（第 3b-3c 步）

**位置**：`retriever.py:460-481`

这是 Retriever 节点最精巧的设计：

```python
# 并行：同时为品类内所有产品生成推荐理由
reason_tasks = [
    _generate_product_reason(p, user_query, products, llm, ...)
    for p in products
]
reasons = await asyncio.gather(*reason_tasks, return_exceptions=True)

# 串行：按顺序发送产品事件和推荐理由
for i, p in enumerate(products):
    await queue.put({"event": "products", "data": {
        "product_id": p["product_id"],
        "category": ...,
        "sub_category": ...,
    }})
    reason = reasons[i] if (i < len(reasons) and isinstance(reasons[i], str)) else ""
    if reason:
        await queue.put({"event": "product_reason", "data": reason})
```

**为什么并行生成但串行发送**：
- LLM 调用是 I/O 密集型，并行执行可将 N 次调用的总耗时压缩到接近单次调用的耗时
- 串行发送保证了同一品类内产品的展示顺序（`products` 事件先于 `product_reason` 事件，产品 A 先于产品 B）
- 客户端解析时依赖这种顺序来正确配对产品卡片和推荐理由

### 4.5 并发控制的三层结构

| 层级 | 机制 | 控制对象 | 位置 |
|------|------|---------|------|
| 品类间 | `Semaphore(5)` | 同时进行 DB 检索的品类数 | `retriever.py:406` |
| 检索内部 | `asyncio.gather` | 同品类的 semantic + keyword 双路检索 | `Retriever.retrieve()` |
| 产品间 | `asyncio.gather` | 同品类内所有产品的推荐理由 LLM 调用 | `retriever.py:464` |

## 5. SSE 事件类型规范

### 5.1 事件一览

| 事件名 | 来源 | data 类型 | 发送时机 | 必发 |
|--------|------|-----------|---------|------|
| `welcome` | Retriever | `string` | 检索开始，在并行检索之前 | 否（有 welcome_text 时才发） |
| `category_intro` | Retriever | `string` | 每个品类检索完成后，产品列表之前 | 否（仅多品类时发） |
| `products` | Retriever | `{product_id, category, sub_category}` | 每个产品推荐理由之前 | 是（每个产品一条） |
| `product_reason` | Retriever | `string` | 紧接着其 `products` 事件之后 | 否（LLM 生成失败时不发） |
| `ending` | Retriever | `string` | 所有产品发送完毕后 | 是 |
| `chat_reply` | ChitChat | `string` | 闲聊 LLM 回复完成后 | 是（闲聊路径） |
| `next_options` | `finally` 块 | `[string]` | graph 完成后，`done` 之前 | 是（推荐路径） |
| `done` | ChitChat / `finally` 块 | `{}` 或 `{conversation_id}` | 流结束标记 | 是 |
| `error` | 消费者 / DB | `{message}` 或 `{detail}` | 异常发生时 | 否 |

### 5.2 推荐路径的事件序列

```
welcome → category_intro* → (products → product_reason)* → ending → next_options → done
```

其中 `*` 表示可重复零次或多次，取决于品类和产品数量。

### 5.3 闲聊路径的事件序列

```
chat_reply → done
```

## 6. 超时与异常处理

### 6.1 超时层级

| 超时 | 值 | 位置 | 行为 |
|------|-----|------|------|
| 总请求超时 | `settings.timeout.total_request`（30s） | `search.py:124` | 到期后发送 error + done |
| 单次队列等待 | 5.0s | `search.py:240` | 超时后检查 graph 是否完成 |
| graph 关闭等待 | 10.0s | `search.py:282` | finally 块中等 graph_task 完成 |

### 6.2 异常场景处理

```
场景 1: 客户端断开连接
  → asyncio.CancelledError 被捕获
  → 取消 graph_task
  → 发送 {"event": "error", "data": {"message": "客户端连接断开"}}
  → 发送 {"event": "done", "data": "{}"}

场景 2: graph 执行异常
  → graph_task.exception() 非空
  → 发送 {"event": "error", "data": {"message": str(exc)}}
  → 发送 {"event": "done", "data": "{}"}

场景 3: conversation 不存在
  → 在 _agent_event_stream 开头校验
  → 发送 {"event": "error", "data": {"detail": "conversation not found"}}
  → 发送 {"event": "done", "data": "{}"}

场景 4: 品类检索失败
  → _category_task 返回 error 字段
  → 记录到 failed_categories，不阻塞其他品类
  → 最终反映在 ending 和 next_options 中
```

## 7. 完整数据流：从生成到客户端输出

```
                    客户端 (Browser/App)
                         │
          GET /api/search/{conv_id}?q=防晒产品
                         │
                         ▼
              FastAPI 路由 (search.py:70)
                         │
            build_graph(llm, emb, db) → 6 节点 StateGraph
            queue = asyncio.Queue()
            initial_state["_sse_queue"] = queue
            graph_task = asyncio.create_task(graph.ainvoke(...))
            EventSourceResponse(_agent_event_stream(...))
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
   LangGraph 执行              _agent_event_stream 消费者
   (后台 task)                 (SSE 生成器)
          │                             │
          │                             │
┌─ START ───────────────────┐           │
│                           │           │
│  Router 节点               │           │
│  ├─ 意图三分类             │           │
│  ├─ 查询改写               │           │
│  └─ 生成 welcome_text      │           │
│                           │           │
│  ──条件边──▶              │           │
│                           │           │
│  ┌─ chat ──▶ ChitChat     │           │
│  │            ├─ chat_stream()       │
│  │            ├─ buffer tokens       │
│  │            ├─ queue.put ──────────┼──▶ {"event":"chat_reply",...}
│  │            ├─ queue.put ──────────┼──▶ {"event":"done",...}
│  │            └─ END                 │     └─ 消费者收到 done → return
│  │                                   │
│  ├─ explicit ▶ Extraction  │           │
│  │            ├─ 品类提取   │           │
│  │            ├─ 历史拼接   │           │
│  │            └─ 意图提取   │           │
│  │                         │           │
│  └─ scenario ▶ ScenarioGen │           │
│               ├─ 品类列表   │           │
│               └─ 意图生成   │           │
│                    │       │           │
│                    ▼       │           │
│               Retrieval 节点          │
│               ├─ queue.put ───────────┼──▶ {"event":"welcome",...}
│               │                       │
│               ├─ 并行品类检索 (×N)      │
│               │  ┌ _category_task(A) ─┤
│               │  │ ├─ SQL 条件转换     │
│               │  │ ├─ 双路检索(并行)   │
│               │  │ ├─ RRF 融合        │
│               │  │ └─ reranker 精排   │
│               │  ├─ _category_task(B) │
│               │  └─ _category_task(C) │
│               │                       │
│               ├─ for 品类 in results:  │
│               │  ├─ queue.put ────────┼──▶ {"event":"category_intro",...}
│               │  ├─ 并行生成推荐理由    │
│               │  └─ for 产品 in 品类:  │
│               │     ├─ queue.put ─────┼──▶ {"event":"products",...}
│               │     └─ queue.put ─────┼──▶ {"event":"product_reason",...}
│               │                       │
│               ├─ queue.put ───────────┼──▶ {"event":"ending",...}
│               └─ 更新 memory → state   │
│                    │       │           │
│                    ▼       │           │
│               OptionGen 节点           │
│               └─ next_options → state │
│                    │       │           │
│                    ▼       │           │
│                   END      │           │
│                            │           │
└────────────────────────────┘           │
          │                             │
          ▼                             │
   graph_task 完成                       │
          │                             │
          └── final_state ──────────────┼──▶ finally 块:
                                        │     ├─ 持久化 session_memory
                                        │     ├─ 持久化 chat_reply（如有）
                                        │     ├─ 发送 next_options ──▶
                                        │     └─ 发送 done ──────────▶
                                        │
                                        ▼
                                    客户端收到完整 SSE 事件流
```

## 8. 设计原则总结

1. **单一事件通道**：整个工作流共享一个 `asyncio.Queue`，避免多队列同步复杂度
2. **语义事件而非 token 流**：以业务事件（welcome/category_intro/products/product_reason/ending）为单位推送，匹配客户端卡片式 UI 渲染
3. **并行生成 + 串行发送**：LLM 调用并行执行减少延迟，但事件推送严格按序保证客户端解析正确性
4. **关注点分离**：`next_options` 和 `done` 由基础设施层（`_agent_event_stream`）统一发送，节点只需关注业务逻辑
5. **优雅降级**：每个品类独立容错，单品类失败不影响整体；LLM 调用失败使用 fallback 而非中断流程
6. **两阶段 done 处理**：闲聊路径（节点内 done → 消费者直接 return）vs 推荐路径（finally 块中 done），适应不同的图拓扑结构
