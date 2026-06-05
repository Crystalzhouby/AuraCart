# 会话管理优化 — 实现方案

> **文档性质**：架构级实现方案。改动范围极小，仅涉及 API 路由层。
> **输入**: `DEFINE.md`

**目标**：将 conversation_id 从可选 query parameter 改为必填路径参数，新增 DB 存在性校验，移除临时会话降级逻辑。

---

## 1. 整体实现架构

```
┌──────────────────────────────────────────────────────────────────┐
│                     FastAPI Application                           │
│                                                                   │
│  GET /api/conversation          (不变)                            │
│  GET /api/search/{conversation_id}?q=...    ← 路径变更            │
│         │                                                         │
│         ▼                                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  search() 路由函数                                           │ │
│  │  1. FastAPI 自动校验 conversation_id 为 UUID 格式 (422)      │ │
│  │  2. event_stream() 内查询 conversation 表                    │ │
│  │     - 存在 → 加载 memory → 执行 Agent 工作流                 │ │
│  │     - 不存在 → yield error("conversation not found") + done  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  LangGraph Agent 工作流 (不变)                                    │
│  Conversation 表 (不变)                                           │
└──────────────────────────────────────────────────────────────────┘
```

**变更聚焦**：仅在 `search.py` 的路由层做三处改动——路由签名、存在性校验、移除可选降级分支。LangGraph 工作流、Conversation 表、Memory 工具函数均不动。

---

## 2. 核心功能接口与需求映射

| 接口 | 方法 | 变更 | 映射需求 |
|------|------|------|----------|
| `/api/conversation` | GET | 不变 | — |
| `/api/search/{conversation_id}?q=` | GET | 路径参数 + 存在性校验 | FR1, FR2 |
| `/api/search?q=&conversation_id=` | GET | **移除** | FR3 |

---

## 3. 模块设计

### 3.1 `server/app/api/search.py` — 路由层（唯一改动模块）

**输入**：
- `conversation_id: str` — 路径参数，FastAPI 自动校验 UUID 格式
- `q: str` — query parameter（不变）
- `stream: bool` — 保留兼容（不变）

**输出**：`EventSourceResponse`（SSE 事件流，格式不变）

**改动点**：

| 位置 | 当前 | 改为 |
|------|------|------|
| 路由签名 | `@router.get("/search")` | `@router.get("/search/{conversation_id}")` |
| 函数参数 | `conversation_id: str \| None = Query(None)` | `conversation_id: str`（路径参数） |
| 记忆加载 | `if conversation_id:` 分支 → 加载 DB | 无条件加载 DB（必存在） |
| 校验逻辑 | 不存在 → warning 日志 + 空记忆降级 | 不存在 → error SSE + done 终止 |
| 记忆持久化 | `if conversation_id and final_state:` | `if final_state:`（conversation_id 必存在） |
| initial_state | `"session_memory": initial_session_memory` | 无变化（值来源不变，仅去掉 if 分支） |

**存在性校验代码位置**：`_agent_event_stream` 函数内部，紧接在 `stream_log` 初始化之后、`initial_session_memory` 加载之前。校验失败的返回路径：

```python
# 伪代码
row = await session.execute(select(Conversation).where(...))
if row is None:
    yield {"event": "error", "data": json.dumps({"detail": "conversation not found"})}
    yield {"event": "done", "data": "{}"}
    return
```

### 3.2 其他模块（不变）

| 模块 | 说明 |
|------|------|
| `server/app/api/conversation.py` | 不变 |
| `server/app/models/conversation.py` | 不变 |
| `server/app/agent/memory.py` | 不变（纯函数，按 conversation_id 隔离已在 search.py 的 DB 读写层实现） |
| `server/app/agent/graph.py` | 不变 |
| `server/app/agent/state.py` | 不变 |
| `delivery/API.md` | 更新 §4 路由路径和参数表格 |

---

## 4. 方案主要优点

1. **改动面积极小**：仅 `search.py` 一个文件需要实质修改，约 10 行变更
2. **天然资源层级**：`/api/search/{conversation_id}` 明确表达"在某个会话内搜索"的语义
3. **强制规范**：不再有临时会话的灰色地带，所有查询必须归属于一个 conversation
4. **框架兜底**：UUID 格式校验由 FastAPI 路径参数自动处理（422），无需手写
5. **回归风险低**：Memory / Agent 节点 / Conversation 表均不动

---

## 5. 主要风险

| 风险 | 缓解措施 |
|------|----------|
| **Breaking change** — 旧客户端 404 | 发布说明明确标注；SPEC.md 已提供客户端升级指南 |
| **conversation 泄漏** — 404 比静默降级更显性 | 客户端错误恢复策略（SPEC.md §5.2）覆盖了 404 → 重建会话 → 重试流程 |

---

## 6. 实现复杂度评估

| 维度 | 评估 |
|------|------|
| 代码改动量 | ~10 行（search.py） |
| 新增依赖 | 无 |
| 数据库变更 | 无 |
| API 兼容性 | Breaking（路径变更） |
| 测试工作量 | 修改现有 search 测试中 conversation_id 传入方式 + 新增 404 场景测试 |
| **总体** | **极低** |

---

## 7. 可测试性评估

- **单元测试**：可直接 mock `async_session` 的 `execute` 返回值（返回 None = 模拟不存在），验证 SSE 事件流中收到 error + done
- **集成测试**：先创建 conversation → 用 valid ID 查询 → 验证正常返回；用随机 UUID → 验证 404 error SSE
- **现有测试影响**：仅需将 `conversation_id=xxx` 从 query param 改为路径拼接

---

## 8. 可交付性评估

- **交付物**：1 个文件修改（search.py）+ 1 个文档同步（API.md）
- **发布方式**：与服务端其他变更一同发布（不可独立部署——客户端需同步升级）
- **回滚策略**：git revert；但客户端需同步回退

---

## 9. 待明确问题

无。本需求边界清晰、改动极小，所有设计决策已在 SPEC.md 阶段与用户确认。
