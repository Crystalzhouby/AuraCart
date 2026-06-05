# 会话管理优化 — 编码级详细方案

> **输入**: `PLAN.md` | **目标**: 足够支撑直接编码

---

## 1. `server/app/api/search.py` — 详细变更

### 1.1 路由签名（行 70-78）

**当前：**

```python
@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=1, description="搜索查询字符串"),
    stream: bool = Query(True, description="是否开启 SSE 流式回答，默认 True"),
    conversation_id: str | None = Query(None, description="会话ID，用于多轮对话记忆"),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
    llm: LLMService = Depends(get_llm_service),
):
```

**改为：**

```python
@router.get("/search/{conversation_id}")
async def search(
    request: Request,
    conversation_id: str,
    q: str = Query(..., min_length=1, description="搜索查询字符串"),
    stream: bool = Query(True, description="是否开启 SSE 流式回答，默认 True"),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
    llm: LLMService = Depends(get_llm_service),
):
```

**说明**：`conversation_id` 提升为路径参数，类型从 `str | None` 变为 `str`。FastAPI 自动校验 UUID 格式（需在路径上声明 `pattern` 或依赖 Pydantic 的 UUID 类型——此处保持 `str`，手动在 DB 校验时处理格式问题）。

### 1.2 `_agent_event_stream` 签名（行 147-153）

**当前：**

```python
async def _agent_event_stream(
    user_query: str,
    graph,
    queue: asyncio.Queue,
    total_timeout: float = 60.0,
    conversation_id: str | None = None,
):
```

**改为：**

```python
async def _agent_event_stream(
    user_query: str,
    graph,
    queue: asyncio.Queue,
    total_timeout: float = 60.0,
    conversation_id: str = "",
):
```

### 1.3 记忆加载 + 存在性校验（行 174-207）

**当前逻辑**：

```python
initial_session_memory: list[dict] = []
if conversation_id:                    # ← 条件分支
    try:
        async with async_session() as session:
            result = await session.execute(
                select(Conversation.memory).where(
                    Conversation.conversation_id == conversation_id
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                initial_session_memory = row
                # debug log: 会话记忆已加载
            else:
                stream_log.warning("会话不存在，降级为空记忆", ...)  # ← 降级
    except Exception as e:
        stream_log.warning("加载会话记忆失败，降级为空记忆", ...)    # ← 降级
```

**改为**：

```python
# 校验 conversation 存在性 + 加载记忆（conversation_id 必有效）
try:
    async with async_session() as session:
        result = await session.execute(
            select(Conversation.memory).where(
                Conversation.conversation_id == conversation_id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            yield {
                "event": "error",
                "data": json.dumps({"detail": "conversation not found"}),
            }
            yield {"event": "done", "data": "{}"}
            return
        initial_session_memory = row
        stream_log.debug(
            "会话记忆已加载",
            conversation_id=conversation_id,
            groups=len(initial_session_memory),
        )
except Exception as e:
    yield {
        "event": "error",
        "data": json.dumps({"detail": str(e)}),
    }
    yield {"event": "done", "data": "{}"}
    return
```

**变更要点**：
- 移除 `if conversation_id:` 条件分支——必定执行
- 移除临时会话降级（空记忆 + warning 日志）——不存在直接终止
- DB 异常也改为终止（原为降级——DB 挂了继续执行临时会话没有意义）

### 1.4 `initial_state` 构建（行 210-223）

**当前**：

```python
initial_state: AgentState = {
    ...
    "session_memory": initial_session_memory,
    ...
}
```

不变。`initial_session_memory` 现在是 DB 中查到的真实值，不再是可能为空的 `[]`。

### 1.5 done 事件注入 conversation_id（行 260-265）

**当前**：

```python
if event["event"] == "done":
    done_received = True
    if isinstance(data, dict):
        data["conversation_id"] = conversation_id
```

不变。`conversation_id` 现在必定为非空字符串。

### 1.6 记忆持久化（行 302-333）

**当前**：

```python
if conversation_id and final_state:    # ← 条件中的 conversation_id 冗余
```

**改为**：

```python
if final_state:
```

`conversation_id` 已保证存在，无需再判断。

### 1.7 event_stream 内调用（行 120-127）

**当前**：

```python
async for event in _agent_event_stream(
    user_query=q,
    graph=agent_graph,
    queue=queue,
    total_timeout=settings.timeout.total_request,
    conversation_id=conversation_id,
):
```

不变。`conversation_id` 来源从 query param 变为 path param，但变量名和传递方式一致。

### 1.8 异常处理中的 `db.rollback()`（行 129-135）

不变。外层的 DI `db` session 是 search 函数参数，不参与 conversation 读写。

---

## 2. `delivery/API.md` — 文档同步

### 2.1 §4 搜索接口（行 49-67）

**当前**：

```
### `GET /api/search`

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `q` | string | 是 | — | 用户查询文本 |
| `stream` | bool | 否 | `true` | 保留参数向后兼容，始终走 SSE 流式 |
| `conversation_id` | string | 否 | `null` | 会话 ID，传入后启用多轮对话记忆持久化 |
```

**改为**：

```
### `GET /api/search/{conversation_id}`

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `conversation_id` | string (path) | 是 | — | 会话 ID，由 `/api/conversation` 获取 |
| `q` | string (query) | 是 | — | 用户查询文本 |
| `stream` | bool (query) | 否 | `true` | 保留参数向后兼容，始终走 SSE 流式 |
```

curl 示例更新：

```bash
# 单轮查询
curl -N "http://localhost:8000/api/search/550e8400-e29b-41d4-a716-446655440000?q=推荐一款适合夏天的防晒霜"

# 多轮对话（同一 conversation_id）
curl -N "http://localhost:8000/api/search/550e8400-e29b-41d4-a716-446655440000?q=要轻量的"
```

### 2.2 §4.4 done 事件

`conversation_id` 字段已在当前实现中返回，文档描述不变。

### 2.3 §4.8 前端集成要点

补充会话管理步骤：

```
0. **会话初始化**：页面加载时调用 `GET /api/conversation` 获取 `conversation_id`，持久化到本地
1. **收到 `products` 事件**：...（不变）
...
5. **收到 `error` 事件**：若 `detail` 为 "conversation not found"，重新创建会话并重试
```

### 2.4 §8 接口总览

```
| `GET` | `/api/search/{conversation_id}?q=` | Agent 工作流 SSE 搜索（核心） |
```

---

## 3. 新增 error 事件语义

| detail 值 | 触发场景 | 客户端处理 |
|-----------|---------|-----------|
| `"conversation not found"` | conversation_id 在 DB 中不存在 | 调用 `/api/conversation` 重建 + 重试 |
| 其他异常消息 | DB 连接失败等 | 展示错误提示，允许用户手动重试 |

---

## 4. 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `server/app/api/search.py` | 修改 | 路由签名 + 存在性校验 + 移除降级分支（~15 行变更） |
| `delivery/API.md` | 修改 | 同步路由路径和参数表格 |
