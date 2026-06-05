# 会话管理优化

## 1. 问题

当前 `/api/search` 通过 query parameter 传递 `conversation_id`（可选），存在以下问题：

- conversation_id 作为可选参数，不传时退化为临时会话，记忆不持久化，多轮对话体验割裂
- query parameter 传递会话标识不够 RESTful，路径参数更能体现"在某会话内搜索"的资源层级关系
- 缺少客户端多会话管理的集成指导

## 2. API 路由变更

### 2.1 创建会话（不变）

```
GET /api/conversation → {"conversation_id": "uuid"}
```

### 2.2 搜索接口

```
当前:  GET /api/search?q=...&conversation_id=...&stream=true
改为:  GET /api/search/{conversation_id}?q=...&stream=true
```

将 `conversation_id` 从 query parameter 提升为路径参数（必填）。

### 2.3 异常处理

| 场景 | HTTP 状态码 | 响应 |
|------|-----------|------|
| 路径缺少 conversation_id | 404 | FastAPI 路由匹配失败，自动返回 |
| conversation_id 在 conversation 表中不存在 | 404 | `{"detail": "conversation not found"}` |
| conversation_id 格式无效（非 UUID 格式） | 422 | FastAPI 自动校验 |

**校验逻辑**：在 `_agent_event_stream` 入口处，若路径参数 conversation_id 在 DB 中查无记录，直接 yield error 事件 + done 事件终止，不再降级为临时会话。

### 2.4 旧接口兼容

旧版 query parameter 路径不再保留。客户端必须升级到路径参数格式。

## 3. 服务端改动清单

| 文件 | 变更 |
|------|------|
| `server/app/api/search.py` | 路由签名 `/{conversation_id}` → 新增 DB 存在性校验（不存在返回 404 error SSE） → 移除 `conversation_id | None` 可选逻辑和临时会话降级代码 |
| `server/app/api/conversation.py` | 不变 |
| `server/app/models/conversation.py` | 不变 |
| `server/app/agent/memory.py` | 不变（已按 conversation_id 隔离，DB 层读写已在 search.py 中正确实现） |
| `delivery/API.md` | 更新 §4 搜索接口路径和参数；更新 §8 接口总览 |

## 4. Memory 隔离验证

当前实现已正确做到按 conversation_id 隔离：

- **存储**：`search.py:_agent_event_stream` 在 graph 完成后通过 `pg_insert(Conversation).values(conversation_id=..., memory=...).on_conflict_do_update(...)` 写入同一条 conversation 记录
- **检索**：`search.py:_agent_event_stream` 在 graph 启动前通过 `select(Conversation.memory).where(Conversation.conversation_id == ...)` 精确读取该会话的 memory
- **Memory 工具函数**（`memory.py`）：纯函数，操作的是从 DB 加载到 AgentState 的 `session_memory` 列表，天然按 conversation_id 隔离

本次改动无需修改 memory 层的任何代码。

## 5. 客户端多会话集成指南

### 5.1 整体流程

```
┌──────────┐                         ┌──────────┐
│   APP    │                         │  Server  │
└─────┬────┘                         └─────┬────┘
      │                                    │
      │  ① GET /api/conversation           │
      │───────────────────────────────────>│  新建会话，conversation 表插入空记忆行
      │  {"conversation_id":"<uuid>"}      │
      │<───────────────────────────────────│
      │                                    │
      │  ② GET /api/search/<uuid>?q=...    │
      │───────────────────────────────────>│  校验 conversation_id 存在 →
      │                                    │  加载 session_memory → 执行 Agent 工作流
      │  SSE: event: products              │
      │<───────────────────────────────────│  每个品类检索完成时发送
      │  SSE: event: chat_reply            │
      │<───────────────────────────────────│  每个品类推荐理由文本
      │  SSE: event: done                  │
      │<───────────────────────────────────│  {"next_options_count":N,"conversation_id":"<uuid>"}
      │  SSE: event: next_options          │
      │<───────────────────────────────────│  ["选项1","选项2",...]
      │                                    │
      │  ③ 同一会话后续轮次                │
      │  GET /api/search/<uuid>?q=...      │
      │───────────────────────────────────>│  自动加载同一 conversation_id 的历史记忆
      │  ...（SSE 事件流同上）              │
      │                                    │
      │  ④ 新话题 → 回到 ① 创建新会话      │
```

### 5.2 客户端实现要点

**会话生命周期：**

1. **启动/新话题** — 调用 `GET /api/conversation` 获取新 `conversation_id`
2. **每轮查询** — 使用同一个 `conversation_id` 调用 `GET /api/search/{conversation_id}?q=...`
3. **切换话题** — 调用 `GET /api/conversation` 创建新会话，旧会话记忆保留在服务端（可后续恢复）
4. **会话列表**（可选，非本期需求）— 客户端本地持久化已创建的 `conversation_id` 列表

**SSE 消费伪代码：**

```javascript
async function search(conversationId, query) {
  const url = `/api/search/${conversationId}?q=${encodeURIComponent(query)}`;
  const eventSource = new EventSource(url);

  eventSource.addEventListener('products', (e) => {
    const items = JSON.parse(e.data);
    // 收集 product_ids → 调用 batch API 获取详情 → 渲染商品卡片
    renderProductCards(items);
  });

  eventSource.addEventListener('chat_reply', (e) => {
    // 追加推荐理由文本到聊天区域
    appendChatBubble(e.data);
  });

  eventSource.addEventListener('done', (e) => {
    const { next_options_count, conversation_id } = JSON.parse(e.data);
    // 停止 loading、记录 conversation_id
    stopLoading();
  });

  eventSource.addEventListener('next_options', (e) => {
    const options = JSON.parse(e.data);
    // 渲染快捷按钮
    renderQuickButtons(options);
  });

  eventSource.addEventListener('error', (e) => {
    // 若 e.data 为 {"detail":"conversation not found"}
    // → 重新创建会话 + 重试
    handleError(e);
    eventSource.close();
  });
}
```

**错误恢复策略：**

- 收到 `"conversation not found"` → 调用 `GET /api/conversation` 重建会话，自动重试当前查询
- 网络断开 / SSE 连接中断 → 重连（同一 conversation_id，服务端记忆仍在）
- 收到通用 error 事件 → 展示错误提示给用户

**多会话切换：**

```
会话列表（客户端本地维护）:
┌─────────────────────────────────┐
│ 会话1: "买防晒霜"  (2026-06-05) │
│ 会话2: "跑步装备"  (2026-06-04) │
│ [+ 新建会话]                     │
└─────────────────────────────────┘

切换时：客户端切换当前 conversation_id，下次请求带上对应 ID 即可。
```

### 5.3 客户端需关注的 API 接口汇总

| 步骤 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 创建会话 | `GET` | `/api/conversation` | 获取新 conversation_id |
| 搜索查询 | `GET` | `/api/search/{conversation_id}?q=` | SSE 流式，必填 conversation_id |
| 批量商品 | `GET` | `/api/products/batch?ids=` | 收到 products 事件后调用 |
| 批量图片 | `GET` | `/api/products/image/batch?ids=` | 渲染商品卡片时调用 |
| 批量 SKU | `GET` | `/api/sku/batch?ids=` | 渲染商品卡片时调用 |
