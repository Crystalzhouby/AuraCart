# DEFINE.md — DATABASE_OPT 需求分析

> 输入: `server/docs/AGENT_OPT/DATABASE_OPT/SPEC.md`

## 1. 功能需求

### F1: 修复 ChatMessage 表始终为空

- **现状**: `AgentState.chat_reply` 字段从未被任何 agent 节点设置，导致 `search.py:333` 持久化条件 `if user_query and chat_reply:` 永远为 False。
- **目标**: Chat 流程和推荐流程均将 assistant 回复写入 `chat_reply`，使得 ChatMessage 表正确记录每轮对话。

| 流程 | 回复来源 | 写入字段 |
|---|---|---|
| Chat | Router 的 `welcome_chat` | `chat_reply` |
| 推荐 (explicit/scenario) | Option Gen 的 `ending` | `chat_reply` |

- **涉及文件**:
  - `app/agent/nodes/intent_route_agent.py` — Chat 流/非流 return 中补充 `"chat_reply": welcome_chat`
  - `app/agent/nodes/option_generate_agent.py` — return 中补充 `"chat_reply": ending`

### F2: 测试检索感知数据库实时更新

- **目标**: 验证插入/删除商品后，`/api/search` 的检索结果能感知变化。
- **测试流程**:
  1. 基于 `data/ecommerce_agent_dataset_/data/` 格式生成 3 条新商品记录（含 SKU + marketing + FAQ + reviews）
  2. 插入前执行搜索 → 记录基线结果
  3. 插入商品到 product/sku/product_marketing/product_faq/user_review 表
  4. 插入后执行搜索 → 断言新商品出现在结果中
  5. 删除上述商品数据
  6. 删除后执行搜索 → 断言新商品不再出现
- **依赖**: 需 LLM + Embedding 服务，标记为网络依赖测试。

## 2. 性能需求

无特殊性能要求。测试用例适当设置超时。

## 3. 最终交付物

1. `intent_route_agent.py` — Chat 流程补全 `chat_reply` 返回
2. `option_generate_agent.py` — 推荐流程补全 `chat_reply` 返回
3. `tests/test_chat_message_persistence.py` (新建) — ChatMessage 写入的单元测试
4. `tests/test_data_awareness.py` (新建) — 实时数据感知集成测试
5. 测试结果记录文件

## 4. 硬约束

- 不能破坏现有 120+ 测试
- 不能引入新的外部依赖
- 沿用项目现有测试模式 (pytest + MagicMock + ASGITransport)
- F2 测试需网络，遵循 CLAUDE.md 中的网络测试约定
- ChatMessage 存储格式：`role="user"` + `role="assistant"` 成对保存

## 5. 隐含要求

- `chat_reply` 可能为空字符串（LLM 异常时），此时不应保存空消息
- 插入/删除测试需清理干净，不影响后续测试
- 新商品测试数据需可复用（SKU ID 不与现有数据冲突）

## 6. 任务完成边界

- Chat 和推荐两条流程的 ChatMessage 均正确入库
- 120+ 现有测试 0 回归
- 新增测试覆盖 F1 + F2
- F2 测试标记为需网络，无网络时 skip

## 7. 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| Option Gen 的 `ending` 在异常路径为空 | 推荐流程 ChatMessage 缺失 | 仅当 `ending` 非空时保存（保持现有 `if user_query and chat_reply` 逻辑） |
| F2 测试数据清理失败 | 污染测试数据库 | 使用 finally 块确保无论测试成败都执行删除 |
| F2 依赖外部 LLM/Embedding 不稳定 | 测试不稳定 | 标记 skip，允许无网络时跳过 |

---

## 待确认项

无。所有设计决策已获用户确认。
