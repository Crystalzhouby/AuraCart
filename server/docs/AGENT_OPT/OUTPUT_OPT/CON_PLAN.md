# CON_PLAN.md — 流式输出优化编码级详细方案

> 输入：`server/docs/AGENT_OPT/OUTPUT_OPT/PLAN.md`
> 当前代码基准：MERGE_OPT 已部分实现（见下文"代码现状"）

## 代码现状

MERGE_OPT 已完成以下变更（OUTPUT_OPT 在此外基础上工作）：

| 文件 | 已变更内容 |
|------|-----------|
| `state.py` | `rewritten_query` 已移除 |
| `router.py` | 查询改写已移除，欢迎语基于 user_query + 历史生成 |
| `retriever.py` | `_generate_ending()` 已移除，流水线到 Memory 更新为止 |
| `option_gen.py` | 已合并 ending + next_options，使用 `ENDING_OPTION_SYSTEM` prompt，通过 queue 发送 ending 事件 |
| `search.py` | `rewritten_query` 已从 initial_state 移除 |

OUTPUT_OPT 需在此基础上新增流式/非流式分支控制。

## 1. 期望目录结构

```
server/
├── app/
│   ├── agent/
│   │   ├── state.py              # 修改: 新增 stream 字段
│   │   ├── graph.py              # 修改: Router 传入 _sse_queue
│   │   ├── nodes/
│   │   │   ├── router.py         # 修改: stream=true 时流式生成 welcome 并推送
│   │   │   ├── chitchat.py       # 修改: stream=true 时逐 token 推送
│   │   │   ├── retriever.py      # 修改: category_intro 流式分支
│   │   │   ├── option_gen.py     # 修改: stream=true 时流式生成 ending + stream_json_field
│   │   │   ├── extraction.py     # 不变
│   │   │   └── scenario_gen.py   # 不变
│   │   └── utils/
│   │       └── stream_json.py    # 新增: 流式 JSON 字段提取器
│   └── api/
│       └── search.py             # 修改: 注入 stream 到 initial_state
```

## 2. 模块详细设计

### 2.1 AgentState（`state.py`）

**实现思路**：新增 `stream: bool` 字段，供所有节点读取判断输出模式。

```python
# AgentState TypedDict 新增
stream: bool

# 字段列表新增（在 _sse_queue 之前）
stream: bool
```

`welcome_text` 保留（非流式模式 Router → Retriever 的中转仍需要）。

### 2.2 流式 JSON 字段提取器（新增 `utils/stream_json.py`）

这是本次最核心的新增模块。

**实现思路**：四态状态机，从 LLM token 流中实时提取指定 JSON 字段的字符串值。

**功能实现链路**：

```
chat_stream() token 流
    │
    ▼
stream_json_field(async_token_gen, "ending")
    │
    ├─ 逐字符累积到 buffer
    ├─ 状态机检测 JSON 结构
    │
    ├─ IN_ENDING 态：每个字符产出 {"type":"delta","text":<char>}
    │   产出存入 stream_events 列表（调用方负责推送到 queue）
    │
    └─ 流结束后：完整 JSON 解析 → 返回 (stream_events, parsed_dict)
```

**状态机定义**：

```
SEEK_KEY → IN_VALUE → COLLECT → DONE
```

| 状态 | 条件 | 动作 |
|------|------|------|
| `SEEK_KEY` | 在 buffer 中搜索 `"ending"` 后跟 `:` 和 `"` | 找到 → 进入 IN_VALUE，截断 buffer 到 `"` 之后 |
| `IN_VALUE` | 逐字符扫描 ending 字段的字符串值 | `\` → 跳过下一字符（转义处理）；`"` → 进入 COLLECT；其他 → 产出 delta |
| `COLLECT` | 继续累积，跟踪 `{` `}` 深度 | 深度归零 → JSON 完整 → 解析 dict → DONE |
| `DONE` | 终止态 | 返回结果 |

**难点**：ENDING_OPTION_SYSTEM 的输出格式为 `{"ending": "...", "next_options": [...]}`。ending 字段是第一键，值结束后还有 `, "next_options": [...]}`。COLLECT 态需要正确跟踪括号深度，确保 JSON 完整。

**风险点**：
- LLM 可能不在 ending 字段值中用 `\"` 转义引号（直接用中文引号 "" 等）→ 状态机可能提前误判值结束 → 缓解：错误时回退到完整 JSON 解析
- LLM 可能在 ending 之前输出额外文本（如 "好的，以下是我的回复："）→ 缓解：SEEK_KEY 态搜索第一个 `"ending"` 出现位置，之前的文本静默跳过

**函数签名**：

```python
async def stream_json_field(
    token_stream,      # AsyncGenerator[str] — chat_stream() 的返回值
    field_name: str,   # 要提取流式值的 JSON 字段名
) -> tuple[list[dict], dict]:
    """
    返回:
        stream_events: [{"type":"delta","text":"夏"}, {"type":"delta","text":"天"}, ...]
        parsed_dict: 完整 JSON 解析结果，如 {"ending":"...", "next_options":[...]}
                     解析失败返回 {}
    """
```

### 2.3 Router 节点（`nodes/router.py`）

**实现思路**：新增 `_sse_queue` 参数。当 `stream=true` 时，welcome 改用 `chat_stream()` 生成并逐 token 推送 `welcome_stream` 事件；`stream=false` 时保持现有行为（写 welcome_text 到 state）。

**函数签名变更**：

```python
# 旧: async def router_node(state: dict, llm: LLMService) -> dict:
# 新:
async def router_node(state: dict, llm: LLMService, _sse_queue=None) -> dict:
```

**核心分支逻辑**（`_generate_welcome` 替换为 `_generate_welcome_stream`）：

```
stream = state.get("stream", True)
queue = _sse_queue or state.get("_sse_queue")

if stream and queue:
    # 流式路径: chat_stream() → 逐 token 推送 welcome_stream
    await queue.put({"event": "welcome_stream", "data": {"type": "start"}})
    async for token in llm.chat_stream(messages, ...):
        await queue.put({"event": "welcome_stream", "data": {"type": "delta", "text": token}})
    await queue.put({"event": "welcome_stream", "data": {"type": "end"}})
    welcome_text = ""  # 流式模式不写 state
else:
    # 非流式路径: 保持现有行为
    welcome_text = await llm.chat(messages, ...)  # 现有 _generate_welcome 逻辑

return {"intent": intent, "welcome_text": welcome_text}
```

### 2.4 Retriever 节点（`nodes/retriever.py`）

**实现思路**：category_intro 增加流式分支；welcome 部分，非流式保持现有逻辑，流式模式不再发送（Router 已直接推送）。

**welcome 部分变更**（当前第 343-346 行）：

```
# 旧:
welcome_text = state.get("welcome_text", "")
if queue and welcome_text:
    await queue.put({"event": "welcome", "data": welcome_text})

# 新:
stream = state.get("stream", True)
if not stream:  # 仅非流式模式从 state 读取并发送
    welcome_text = state.get("welcome_text", "")
    if queue and welcome_text:
        await queue.put({"event": "welcome", "data": welcome_text})
```

**category_intro 部分变更**（当前第 393-399 行）：

```
# 旧:
if total_valid > 1:
    intro = await _generate_category_intro(...)
    if queue and intro:
        await queue.put({"event": "category_intro", "data": intro})

# 新:
if total_valid > 1:
    if stream and queue:
        await queue.put({"event": "category_intro_stream", "data": {"type": "start"}})
        async for token in llm.chat_stream(messages, temperature=0.3):
            await queue.put({"event": "category_intro_stream", "data": {"type": "delta", "text": token}})
        await queue.put({"event": "category_intro_stream", "data": {"type": "end"}})
    else:
        intro = await _generate_category_intro(...)  # 现有非流式逻辑
        if queue and intro:
            await queue.put({"event": "category_intro", "data": intro})
```

### 2.5 OptionGen 节点（`nodes/option_gen.py`）

这是变更最复杂的节点。需要将当前的 `llm.chat()` 替换为流式分支。

**当前逻辑**（第 92-169 行）：

```
raw_response = await llm.chat(messages, ...)
# JSON 解析
data = json.loads(raw_response[start:end])
ending = data.get("ending", "")
options = data.get("next_options", [])
# 推送 ending 事件
if queue and ending:
    await queue.put({"event": "ending", "data": ending})
```

**新逻辑**（流式分支）：

```
stream = state.get("stream", True)

if stream and queue:
    # 流式路径: chat_stream() + stream_json_field()
    token_stream = llm.chat_stream(messages, temperature=0.3)
    stream_events, parsed = await stream_json_field(token_stream, "ending")

    # 逐条推送 ending_stream 事件
    await queue.put({"event": "ending_stream", "data": {"type": "start"}})
    for ev in stream_events:
        await queue.put({"event": "ending_stream", "data": ev})
    await queue.put({"event": "ending_stream", "data": {"type": "end"}})

    # 从完整 JSON 提取 next_options
    if parsed:
        options = parsed.get("next_options", [])
    else:
        # fallback: 流式提取失败，尝试从累积 buffer 中正则提取
        options = []
else:
    # 非流式路径: 保持现有逻辑
    raw_response = await llm.chat(messages, temperature=0.3)
    # ... 现有 JSON 解析逻辑 ...
    data = json.loads(raw_response[start:end])
    ending = data.get("ending", "")
    options = data.get("next_options", [])
    if queue and ending:
        await queue.put({"event": "ending", "data": ending})

# 截断与返回（两种路径共用）
if len(options) > 3:
    options = options[:3]
return {"next_options": options}
```

### 2.6 ChitChat 节点（`nodes/chitchat.py`）

**实现思路**：`stream=true` 时改为逐 token 推送 `chat_reply_stream`，不再缓冲拼装后一次性发送。

**当前逻辑**（第 40-53 行）：

```
parts = []
async for token in llm.chat_stream(messages, ...):
    parts.append(token)
reply = "".join(parts)
if queue:
    await queue.put({"event": "chat_reply", "data": reply})
    await queue.put({"event": "done", "data": {}})
```

**新逻辑**：

```
stream = state.get("stream", True)

if stream and queue:
    # 流式: 逐 token 推送
    await queue.put({"event": "chat_reply_stream", "data": {"type": "start"}})
    reply_parts = []
    try:
        async for token in llm.chat_stream(messages, temperature=0.3):
            reply_parts.append(token)
            await queue.put({"event": "chat_reply_stream", "data": {"type": "delta", "text": token}})
    except Exception:
        pass
    await queue.put({"event": "chat_reply_stream", "data": {"type": "end"}})
    reply = "".join(reply_parts)
    if not reply or not reply.strip():
        reply = FALLBACK_REPLY
    await queue.put({"event": "done", "data": {}})
else:
    # 非流式: 保持现有行为
    parts = []
    try:
        async for token in llm.chat_stream(messages, temperature=0.3):
            parts.append(token)
    except Exception:
        pass
    reply = "".join(parts)
    if not reply or not reply.strip():
        reply = FALLBACK_REPLY
    if queue:
        await queue.put({"event": "chat_reply", "data": reply})
        await queue.put({"event": "done", "data": {}})
```

### 2.7 Graph 构建层（`graph.py`）

**变更点**：`_router` 包装函数传入 `_sse_queue`。

```
# 旧:
async def _router(state: AgentState) -> dict:
    result = await router_node(state, llm=llm)

# 新:
async def _router(state: AgentState) -> dict:
    result = await router_node(state, llm=llm, _sse_queue=state.get("_sse_queue"))
```

### 2.8 API 路由层（`search.py`）

**变更点**：将 `stream` 参数注入 initial_state（`search()` 函数已有 `stream` 参数，但未传入 state）。

```python
# initial_state 新增一行（第 211 行附近）:
initial_state: AgentState = {
    "user_query": user_query,
    "welcome_text": "",
    "stream": stream,             # ← 新增
    "session_memory": initial_session_memory,
    ...
}
```

注意：`search()` 函数内部的 `stream` 变量需要在构建 `initial_state` 的作用域内可访问。当前 `stream` 是 `search()` 的参数，`_agent_event_stream()` 是独立函数，需要将 `stream` 传入 `_agent_event_stream()` 或直接在 `event_stream()` 闭包中构建 `initial_state`。

实际上，当前代码中 `initial_state` 是在 `_agent_event_stream()` 函数内构建的（第 211 行），而 `stream` 参数在 `search()` → `event_stream()` 闭包中。需要将 `stream` 传入 `_agent_event_stream()`。

```python
# search() 中调用:
async for event in _agent_event_stream(
    user_query=q,
    graph=agent_graph,
    queue=queue,
    total_timeout=settings.timeout.total_request,
    conversation_id=conversation_id,
    stream=stream,               # ← 新增参数
):
```

```python
# _agent_event_stream() 函数签名新增:
async def _agent_event_stream(
    user_query: str,
    graph,
    queue: asyncio.Queue,
    total_timeout: float = 60.0,
    conversation_id: str = "",
    stream: bool = True,         # ← 新增参数
):
```

## 3. 完整事件序列

### 推荐路径 `stream=true`

```
welcome_stream {"type":"start"}
welcome_stream {"type":"delta","text":"夏"}
welcome_stream {"type":"delta","text":"天"}
...
welcome_stream {"type":"end"}
(category_intro_stream ...)*    # 仅多品类
products {"product_id":..., ...}
product_reason "..."
...
ending_stream {"type":"start"}
ending_stream {"type":"delta","text":"..."}
...
ending_stream {"type":"end"}
next_options ["...", "..."]
done {"conversation_id":"..."}
```

### 推荐路径 `stream=false`

```
welcome "..."
(category_intro "...")*         # 仅多品类
products {"product_id":..., ...}
product_reason "..."
...
ending "..."
next_options ["...", "..."]
done {"conversation_id":"..."}
```

### 闲聊路径 `stream=true`

```
chat_reply_stream {"type":"start"}
chat_reply_stream {"type":"delta","text":"..."}
...
chat_reply_stream {"type":"end"}
done {}
```

### 闲聊路径 `stream=false`

```
chat_reply "..."
done {}
```

## 4. 关键数据实体

### SSE 事件格式

**业务事件（不变）**：
```
{"event": "products",   "data": {"product_id": str, "category": str, "sub_category": str}}
{"event": "product_reason", "data": "<推荐理由文本>"}
{"event": "next_options",   "data": ["选项1", "选项2"]}
{"event": "done",       "data": {} | {"conversation_id": str}}
{"event": "error",      "data": {"message": str} | {"detail": str}}
```

**文本事件 — 非流式（`stream=false`）**：
```
{"event": "welcome",        "data": "<完整文本>"}
{"event": "category_intro", "data": "<完整文本>"}
{"event": "ending",         "data": "<完整文本>"}
{"event": "chat_reply",     "data": "<完整文本>"}
```

**文本事件 — 流式（`stream=true`）**：
```
{"event": "welcome_stream",        "data": {"type": "start"}}
{"event": "welcome_stream",        "data": {"type": "delta", "text": "<token>"}}
{"event": "welcome_stream",        "data": {"type": "end"}}
                                    ↑ category_intro_stream / ending_stream / chat_reply_stream 同理
```

### AgentState 最终结构

```python
class AgentState(TypedDict):
    user_query: str
    welcome_text: str              # 保留（非流式模式用）
    stream: bool                   # 新增
    session_memory: list[dict]
    intent: str
    requirements: list[dict]
    scenario_description: str | None
    retrieval_results: list[dict]
    chat_reply: str
    next_options: list[str]
    failed_categories: list[str]
    _sse_queue: Any
```

## 5. 风险点与缓解

| 风险 | 缓解 |
|------|------|
| `stream_json_field` 状态机在 ending 值含转义字符时误判结束 | SEEK_KEY 用精确 `"ending"` 匹配；IN_VALUE 中正确处理 `\"` 和 `\\` 转义 |
| LLM 输出 JSON 字段顺序不一致（next_options 在 ending 之前） | COLLECT 态跟踪完整 JSON，不依赖字段顺序。仅 ending 的流式提取依赖 ending 是第一或靠前的字符串字段 |
| LLM 在 JSON 外输出额外文本 | SEEK_KEY 跳过 JSON 之前的文本；COLLECT 用 `{` `}` 深度跟踪确定 JSON 结束 |
| 流式推送大幅增加 `queue.put()` 调用次数 | 每个 token 一次 put，对于 ~60 字的 ending 约 60-120 次 put。asyncio.Queue 是无锁队列，开销极低 |

## 6. 待优化项

1. `stream_json_field` 当前仅支持提取**第一个字符串字段**的值作为流式内容。如果未来需要同时流式提取多个字段，需要扩展为多字段状态机。
2. 当前流式结束后仍需完整 JSON 解析才能获取 `next_options`，这意味着客户端在 `ending_stream(end)` 后还需等待一次 JSON parse（耗时可忽略，非网络 I/O）。
3. 如果 LLM 输出极长（如 ending 超过 500 字），`stream_json_field` 的内存占用会相应增长（buffer 缓存完整 JSON）。可设置最大 buffer 上限，超过则放弃流式、回退到批量解析。
