# 问题定义 — 会话管理优化

> **输入**: `server/docs/AGENT_OPT/CONVERSATION_OPT/SPEC.md`
> **变更范围**: `server/app/api/search.py`（主要），`delivery/API.md`（文档同步）

## 1. 功能需求

- **FR1 conversation_id 改为路径参数**：将 `/api/search?q=...&conversation_id=...` 改为 `GET /api/search/{conversation_id}?q=...`。conversation_id 从可选 query parameter 提升为必填路径参数。
- **FR2 conversation 存在性校验**：收到请求后在 `_agent_event_stream` 入口查询 conversation 表，若 conversation_id 不存在，立即返回 SSE error 事件 `{"detail":"conversation not found"}` + done 事件终止，不再降级为临时会话。
- **FR3 移除临时会话降级逻辑**：删除 `search.py` 中 `conversation_id: str | None` 的 `None` 分支——包括空记忆初始化、跳过 DB 读写等兼容代码。每轮查询必须有对应的 conversation 记录。
- **FR4 客户端集成指南**：在 SPEC.md §5 中输出多会话 SSE 交互流程、SSE 消费伪代码、错误恢复策略、多会话切换方案（已完成）。

## 2. 性能需求

无新增性能需求。conversation 存在性校验为单次主键查询（~1ms），不影响端到端延迟。

## 3. 最终交付物

1. `server/app/api/search.py` — 路由签名变更 + conversation 存在性校验 + 移除可选逻辑
2. `delivery/API.md` — 同步更新 §4 搜索接口路径和参数说明
3. `server/docs/AGENT_OPT/CONVERSATION_OPT/SPEC.md` — 完整设计方案（已完成）

## 4. 硬约束

- **HC1** 不修改 `conversation` 表结构、`memory.py` 工具函数、Agent 节点代码
- **HC2** SSE 事件格式不变（products/chat_reply/done/next_options/error）
- **HC3** 旧 query parameter 路径不保留（breaking change），客户端须升级
- **HC4** FastAPI 路径参数类型校验（UUID 格式）由框架自动处理

## 5. 隐含要求

1. `/api/conversation` 接口行为不变（创建 UUID + 写入空记忆行）
2. conversation 不存在时返回的错误需可被客户端识别并触发重建会话 + 重试
3. `done` 事件中的 `conversation_id` 字段保持不变（当前已注入）
4. `_agent_event_stream` 中现有的记忆加载/持久化逻辑不变——仅将 `conversation_id` 来源从可选参数改为路径参数后传入
5. 异常处理中 DB 会话 rollback 逻辑保持不变

## 6. 任务完成边界

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **路由** | `/api/search/{conversation_id}` 路径参数 | 其他 API 路由 |
| **校验** | conversation 表主键存在性查询 | 权限校验、会话过期/归档 |
| **代码清理** | 移除 `conversation_id` None 分支和临时会话降级 | Agent 节点/Memory 层重构 |
| **文档** | API.md 路径和参数更新 | 新增独立文档 |
| **客户端** | SPEC.md 中的集成指南 | 客户端 SDK 实现 |

## 7. 可能的风险点

| 风险 | 说明 |
|------|------|
| **R1 Breaking Change** | 旧客户端使用 query parameter 传 conversation_id 将直接 404。需在发布说明中明确标注，前端同步升级。 |
| **R2 会话泄漏** | 改为强制会话后，每次 `/api/search` 调用都需先调用 `/api/conversation`。若客户端遗漏创建会话步骤，请求直接失败——影响面为 404 而非静默降级。 |

## 8. 待明确问题

> SPEC.md 已和用户确认以下选择：
> - conversation_id 传递方式：路径参数（选项 C）
> - 设计方案输出位置：SPEC.md 中直接补充

无新增 `[NEEDS CLARIFICATION]` 项。本需求边界清晰、改动范围小，可直接进入 PLAN.md。
