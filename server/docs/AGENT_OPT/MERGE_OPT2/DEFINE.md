# MERGE_OPT2 — 需求分析

> 输入: `server/docs/AGENT_OPT/MERGE_OPT2/SPEC.md`
> 输出: `server/docs/AGENT_OPT/MERGE_OPT2/DEFINE.md`

## 1. 功能需求

### F1: 合并 ROUTER_SYSTEM + CHITCHAT_SYSTEM + WELCOME_SYSTEM 为统一提示词

**目标:** 将 Router 节点当前的两类 LLM 调用（ROUTER_SYSTEM 意图分类 + WELCOME_SYSTEM 欢迎语 / CHITCHAT_SYSTEM 闲聊）合并为 **一次** LLM 调用，使用统一提示词。

**涉及文件:**

| 文件 | 操作 |
|---|---|
| `app/agent/prompts/unified_router_prompt.py` | **新建** — 包含 `UNIFIED_ROUTER_SYSTEM` |
| `app/agent/prompts/router_prompt.py` | **删除** — ROUTER_SYSTEM 迁移到统一提示词 |
| `app/agent/prompts/chitchat_prompt.py` | **删除** — CHITCHAT_SYSTEM 迁移到统一提示词 |
| `app/agent/prompts/show_prompt.py` | 删除 `WELCOME_SYSTEM`（lines 1-24） |

**统一提示词设计要点:**

- 保留 ROUTER_SYSTEM 的分类能力（chat/explicit/scenario 三分类 + 示例）
- 保留 CHITCHAT_SYSTEM 的闲聊风格（自然亲切、50 字内、引导购物）
- 保留 WELCOME_SYSTEM 的欢迎语能力（单品类突出特点、多品类突出场景感）
- 新增关联逻辑：chat 时引导购物，explicit/scenario 时生成商品相关欢迎语
- 输出格式: `{"welcome_chat": "<内容>", "intent": "chat|explicit|scenario"}`

**LLM 输出格式:**

```json
{
    "welcome_chat": "回复内容（闲聊或欢迎语）",
    "intent": "chat|explicit|scenario"
}
```

### F2: 重写 router_node 为统一入口 + 合并 chitchat 功能

**目标:** `router_node` 单次 LLM 调用完成意图分类 + 回复生成，同时承担原 `chitchat_node` 的 SSE 发送职责。

**当前状态（post-MERGE_OPT）:**

```
router_node:  ROUTER_SYSTEM(LLM#1) → intent
              └─ explicit/scenario: WELCOME_SYSTEM(LLM#2) → welcome_text → state
chitchat_node: CHITCHAT_SYSTEM(LLM) → chat_reply → SSE → done
```

**目标状态:**

```
router_node:  UNIFIED_ROUTER_SYSTEM(LLM#1) → {welcome_chat, intent}
              ├─ chat:             SSE chat_reply → done → END
              └─ explicit/scenario: SSE welcome → extraction/scenario_gen
```

**router_node 新逻辑:**

```
1. 从 state 读取 user_query, session_memory, _sse_queue, stream
2. 构建 recent_queries 文本
3. 调用 UNIFIED_ROUTER_SYSTEM（单次 LLM）
4. 流式路径:
   a. 通过 stream_json_field(token_stream, "welcome_chat", ...) 逐 token 推送 SSE
   b. 解析完整 JSON 获得 intent
   c. chat → queue.put("done") → 返回 {intent, welcome_text=""}
   d. explicit/scenario → 返回 {intent, welcome_text=welcome_chat}
5. 非流式路径:
   a. 同步 LLM 调用获得完整响应
   b. chat → queue.put("chat_reply") + queue.put("done")
   c. explicit/scenario → queue.put("welcome")
   d. 返回 {intent, welcome_text}
```

**删除函数:** `_generate_welcome()` — 逻辑已合并到统一提示词，不再需要独立函数。

### F3: 删除 chitchat_node

**目标:** `chitchat_node` 的功能已合并到 `router_node`，不再需要独立节点。

| 文件 | 操作 |
|---|---|
| `app/agent/nodes/chitchat.py` | **删除** |
| `app/agent/prompts/chitchat_prompt.py` | **删除** |

### F4: 更新 graph.py

**目标:** 移除 chitchat 节点注册 + 更新条件边路由。

**改动:**

- 删除 `from app.agent.nodes.chitchat import chitchat_node`
- 删除 `_chitchat` wrapper 函数
- 删除 `graph.add_node("chitchat", _chitchat)`
- 删除 `graph.add_edge("chitchat", END)`
- 条件边改为: `{"chitchat": END, "extraction": "extraction", "scenario_gen": "scenario_gen"}`

### F5: 更新 retrieval_node

**目标:** 欢迎语 SSE 事件改由 router_node 统一发送，retrieval_node 不再发送 welcome 事件。

**改动:**

- 删除 `retrieval_node` 中发送 welcome 事件的代码块（当前 lines 343-346）:
  ```python
  # 1. 欢迎语
  welcome_text = state.get("welcome_text", "")
  if queue and welcome_text:
      await queue.put({"event": "welcome", "data": welcome_text})
  ```

> 注意: `welcome_text` 字段保留在 AgentState 中，router_node 仍写入（用于日志/调试），但不再由 retrieval_node 发送 SSE。

---

## 2. LLM 调用节省

| 路径 | 优化前（post-MERGE_OPT） | 优化后 | 节省 |
|---|---|---|---|
| Chat 路径 | 2 次（ROUTER_SYSTEM + CHITCHAT_SYSTEM） | 1 次 | **-1** |
| Explicit 路径 | 2 次（ROUTER_SYSTEM + WELCOME_SYSTEM） | 1 次 | **-1** |
| Scenario 路径 | 2 次（ROUTER_SYSTEM + WELCOME_SYSTEM） | 1 次 | **-1** |

结合 MERGE_OPT（-2 次 downstream），完整推荐路径总计: **-3 次 LLM 调用**（相对原始版本）。

---

## 3. SSE 事件流（变更后）

### Chat 路径

```
welcome_chat_stream (start → delta × N → end) → done
```

或非流式:

```
chat_reply → done
```

### 推荐路径

```
welcome_stream (start → delta × N → end) → category_intro → products → product_reason → ending → next_options → done
```

或非流式:

```
welcome → category_intro → products → product_reason → ending → next_options → done
```

> `welcome` / `welcome_stream` 由 `router_node` 发送（替代原 `retrieval_node` 发送）。

---

## 4. 最终交付物

1. `app/agent/prompts/unified_router_prompt.py` — **新建** — 统一提示词
2. `app/agent/nodes/router.py` — 重写 router_node（单次 LLM + SSE 发送）
3. `app/agent/graph.py` — 移除 chitchat 节点，更新条件边
4. `app/agent/nodes/retriever.py` — 删除 welcome SSE 发送
5. `app/agent/prompts/router_prompt.py` — **删除**
6. `app/agent/nodes/chitchat.py` — **删除**
7. `app/agent/prompts/chitchat_prompt.py` — **删除**
8. `app/agent/prompts/show_prompt.py` — 删除 WELCOME_SYSTEM
9. `tests/` — 更新测试引用

---

## 5. 硬约束

- 不能破坏现有 SSE 事件流顺序
- Chat 路径 `done` 事件由 router_node 发送（替代 chitchat_node）
- 推荐路径 `done` 事件仍由 `_agent_event_stream` finally 块发送
- 所有离线测试必须继续通过

## 6. 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| 合并 prompt 导致意图分类准确率下降 | 错误路由到 extraction/scenario_gen 或漏掉 chat | 保留完整的分类示例和规则；测试验证三分类准确率 |
| 流式 welcome_chat + intent 解析在低质量 LLM 上可能失败 | welcome_chat 为空或 intent 解析错误 | 非流式 fallback；intent fallback 为 explicit |
| 删除 chitchat_node 后 chat 路径 SSE 事件名称变更 | 前端可能依赖特定事件名 | 保持 chat_reply/chat_reply_stream 事件名向后兼容 |
| WELCOME_SYSTEM 提示词规则在合并后丢失 | 欢迎语质量下降 | 在统一提示词中保留核心规则 |

## 7. 开放问题

无 `[NEEDS CLARIFICATION]` 项。
