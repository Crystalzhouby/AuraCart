# PLAN.md — 前端补充接口架构方案

## 输入

- **DEFINE.md**: `server/docs/AGENT_OPT/FRONT_API_OPT/DEFINE.md`

## 1. 整体架构

```mermaid
flowchart LR
    subgraph API Layer
        F1[GET /api/history/{cid}]
        F2[GET /api/review/{pid}]
        F3[GET /api/all_skus/{pid}]
    end

    subgraph Data Sources
        CM[(chat_message)]
        CV[(conversation)]
        PM[(product_marketing)]
        PF[(product_faq)]
        UR[(user_review)]
        SK[(sku)]
    end

    subgraph Write Side
        SEARCH[search.py agent done]
        SEARCH -->|写入 user+assistant| CM
    end

    F1 --> CM
    F2 --> PM
    F2 --> PF
    F2 --> UR
    F3 --> SK
```

三个接口均为纯读查询，F1 的写操作嵌入已有 search 流程。

## 2. 核心接口与功能覆盖

| 接口 | DEFINE 需求 | 数据源 | 查询方式 |
|------|-------------|--------|----------|
| `/api/history/{cid}` | F1 | `chat_message` | `WHERE conversation_id=$cid ORDER BY created_at` |
| `/api/review/{pid}` | F2 | `product_marketing`, `product_faq`, `user_review` | 三次独立查询，按 `product_id` + `is_active=True` |
| `/api/all_skus/{pid}` | F3 | `sku` | `WHERE product_id=$pid AND is_active=True` |

## 3. 模块设计

### M1: `app/models/chat_message.py` — ChatMessage ORM

| 项目 | 说明 |
|------|------|
| 输入 | 无（ORM 模型定义） |
| 输出 | SQLAlchemy 映射类 |
| 功能 | 定义 `chat_message` 表结构 |

字段：`id`(PK), `conversation_id`(indexed), `role`(String, "user"\|"assistant"), `content`(Text), `created_at`

### M2: `app/api/frontend.py` — 路由层

| 项目 | 说明 |
|------|------|
| 输入 | HTTP GET 请求 |
| 输出 | JSON 响应 |
| 功能 | 三个端点的请求处理、参数校验、DB 查询、响应序列化 |

### M3: `app/api/search.py` — 写入钩子（修改）

| 项目 | 说明 |
|------|------|
| 输入 | agent graph 最终状态（`user_query`, `chat_reply`, `conversation_id`） |
| 输出 | 写入 chat_message 表 |
| 功能 | 在 agent 成功完成后持久化本轮对话 |

## 4. 主要优点

- **数据源清晰**：F2 使用三张结构化表，无需解析去规范化文本
- **隔离性好**：新路由放在独立 `frontend.py`，不与现有 search/products 耦合
- **写入安全**：chat_message 写入失败不阻塞 search 主流程

## 5. 主要风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| chat_message 表尚不存在导致查询报错 | 低 | 启动时 ORM `create_all` 自动建表 |
| 历史消息量过大 | 低 | 当前使用场景下数据量小，后续可按 conversation_id 分页 |

## 6. 实现复杂度评估

- **整体**: 低
- F1: 1 个新模型 + 1 个路由 + search.py 少量修改
- F2: 1 个路由（3 次简单查询）
- F3: 1 个路由（1 次简单查询）
- 新增代码量估算：~120 行

## 7. 可测试性评估

- 三个接口均为纯 DB 查询，可用 mock DB 测试
- F1 写入测试：验证 chat_message 写入不抛异常
- F2/F3：mock 三张表的查询结果，验证返回格式

## 8. 可交付性评估

- 无需外部依赖
- 无需数据库迁移脚本
- 不改变现有 API 行为

---

> 无 `[NEEDS CLARIFICATION]` 项。
