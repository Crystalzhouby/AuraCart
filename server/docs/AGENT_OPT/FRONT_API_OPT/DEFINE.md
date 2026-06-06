# DEFINE.md — 前端补充接口需求分析

## 输入

- **SPEC**: `server/docs/AGENT_OPT/FRONT_API_OPT/SPEC.md`

## 1. 功能需求

| ID | 接口 | 方法 | 功能描述 |
|----|------|------|----------|
| F1 | `/api/history/{conversation_id}` | GET | 返回指定会话的对话历史（用户查询+助手回复，按时间排序） |
| F2 | `/api/review/{product_id}` | GET | 返回商品的 RAG 知识信息（营销描述、FAQ、用户评价） |
| F3 | `/api/all_skus/{product_id}` | GET | 返回商品的所有 SKU 变体信息 |

### F1 详细说明

- 新建 `chat_message` 表存储每轮对话记录（`role` + `content` + `created_at`）
- 每次 agent 搜索完成后，写入 user query 和 assistant reply 两条记录
- 返回格式：`{messages: [{role: "user"|"assistant", content, created_at}]}`，按 `created_at` 升序
- `conversation_id` 不存在时返回 404

### F2 详细说明

- 从结构化表读取（非 product_review 向量表）：
  - `ProductMarketing.description`（单条，每个 product 一条）
  - `ProductFaq` 所有活跃行（question + answer）
  - `UserReview` 所有活跃行（nickname + rating + content）
- 返回格式：`{rag_knowledge: {marketing_description, official_faq: [...], user_reviews: [...]}}`
- product 不存在或无数据时返回 404

### F3 详细说明

- 查询 `Sku` 表：`product_id` + `is_active=True`
- 返回格式：`{skus: [{sku_id, properties, price, stock}]}`
- product 不存在或无 SKU 时返回 404

## 2. 性能需求

- 所有接口均为简单 DB 查询，无 LLM/Embedding 调用
- 响应时间目标：< 100ms（本地 DB 单表查询）

## 3. 最终交付物

### 新建文件

| 文件 | 说明 |
|------|------|
| `app/api/frontend.py` | 三个新路由的 API 实现 |
| `app/models/chat_message.py` | ChatMessage ORM 模型 |
| `tests/test_frontend_api.py` | 三个接口的测试 |

### 修改文件

| 文件 | 说明 |
|------|------|
| `app/api/search.py` | agent 完成后写入 chat_message |
| `app/main.py` | 注册 frontend router |

### 数据库变更

| 变更 | 说明 |
|------|------|
| 新建 `chat_message` 表 | 存储每轮对话的 user/assistant 消息 |

## 4. 硬约束

- 遵循现有代码风格和 API 模式（参考 `app/api/products.py`）
- 使用 SQLAlchemy 2.0 async + asyncpg
- 路由前缀 `/api`，tag 使用 `frontend`
- 不做数据库迁移脚本（依赖 ORM `create_all`）

## 5. 隐含要求

- F1 的 chat_message 写入必须在 agent 流程成功完成后才执行
- F2 的数据读取需过滤 `is_active=True`
- F3 的 SKU 需过滤 `is_active=True`

## 6. 任务完成边界

- 三个 API 可正常响应并返回 SPEC 定义的格式
- 测试通过（离线测试，mock DB）
- `chat_message` 写入不影响现有 search 流程

## 7. 风险点

| 风险 | 影响 | 缓解 |
|------|------|------|
| chat_message 写入失败阻塞 search | search 流程中断 | 写入包裹在 try/except 中，失败仅记录日志 |
| 结构化表字段为 None | 返回空列表/空字符串 | 字段级 null 检查，默认值兜底 |
| 未建索引导致慢查询 | F2 多表联合慢 | product_id 已有索引（ORM 定义 index=True） |

---

> 无 `[NEEDS CLARIFICATION]` 项。所有需求已在 brainstorming 阶段确认。
