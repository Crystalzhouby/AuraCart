# 后端开发规划（前端不做额外适配）

> 目标：在**不改前端 UI / 交互代码**的前提下，让后端按当前前端协议稳定提供服务；开发过程尽量只改本次范围内代码。

## 1. 约束与原则

- **前端协议优先**：以当前 Android 客户端实际调用为准。
- **最小改动**：只改 `server/app/api`、少量 `services` 与必要 schema，不改无关模块。
- **兼容保留**：已有 `/api/search`、`/api/conversation` 可保留，不强制删除。
- **分阶段可回滚**：每阶段可单独验收，失败可快速回退。

---

## 2. 当前前端实际依赖协议（基线）

### 2.1 聊天

- `POST /api/chat/stream`
  - 请求体：`message`, `session_id`, `history`
  - SSE 事件：`delta`, `product_cards`, `cart_update`, `done`
- `POST /api/chat`（可选兜底）

### 2.2 商品

- `GET /api/products/{id}`：详情页依赖完整字段（含 `skus`, `rag_knowledge`）
- `GET /api/products`：分类/搜索列表

> 说明：这与 `API.md` 中 `/api/search` + `products/chat_reply/next_options` 存在协议差异，本规划通过后端兼容层消化差异，不要求前端改协议。

---

## 3. 开发范围（In Scope）

1. 新增（或完善）`/api/chat/stream` 与 `/api/chat` 接口。
2. 将现有 Agent 工作流事件映射为前端期望 SSE 事件。
3. 完善商品接口返回字段，满足前端详情页与卡片渲染。
4. 增加针对协议的接口测试与回归清单。

## 4. 非范围（Out of Scope）

- 不改 Android UI 布局/交互。
- 不重构 LangGraph 核心节点逻辑（仅做接口层适配）。
- 不做数据库结构大改（除非缺字段且不可替代）。
- 不做与本次需求无关的代码清理。

---

## 5. 分阶段实施计划

## Phase 0：冻结基线（0.5 天）

**目标**：先固化“当前可运行状态”，避免开发中引入不可定位问题。

- 记录现有接口行为：`/api/search`, `/api/products/{id}`, `/api/products`。
- 补充最小化请求样例（curl + 预期输出片段）。
- 建立回归清单（见第 8 节）。

**改动文件**：仅 `delivery/` 文档与测试脚本，不动业务代码。

---

## Phase 1：聊天接口兼容层（1~1.5 天）

**目标**：提供前端直连协议，前端无需改动。

### 1) 新增 API 路由

- 新增 `server/app/api/chat.py`
  - `POST /api/chat/stream`
  - `POST /api/chat`
- 在 `server/app/main.py` 注册 `chat.router`。

### 2) SSE 事件映射规则

后端内部（当前）事件 → 前端事件：

- `chat_reply`（整段）→ 拆分为多条 `delta`
- `products`（ID 列表）→ 查询详情后封装为 `product_cards`
- `done` → `done`（补齐 `session_id`）
- `next_options` 可先不下发（前端当前主链路不强依赖）

### 3) 会话 ID 映射

- 外部：`session_id`
- 内部：复用 `conversation_id`
- 映射策略：
  - 若请求带 `session_id`，直接作为 `conversation_id` 使用。
  - 若为空，后端创建新 `conversation_id` 并回传到 `done.session_id`。

**仅改动**：`api/chat.py`, `main.py`，必要时 `api/search.py` 增加可复用函数（不改节点逻辑）。

---

## Phase 2：商品接口补齐（1 天）

**目标**：让前端详情页/半屏页不再依赖本地 mock 补洞。

### 1) `GET /api/products/{id}` 返回扩展

在保持兼容字段的基础上，补齐：

- `image_url` / `img`
- `description`, `stock`, `tags`
- `skus[]`
- `rag_knowledge`（`marketing_description`, `official_faq`, `user_reviews`）

### 2) `GET /api/products`

- 支持 `category`, `q`, `limit`
- 返回 `total + products`（与前端 `ProductListResponse` 对齐）

**仅改动**：`api/products.py`、必要 schema。

---

## Phase 3：稳定性与错误语义（0.5~1 天）

**目标**：提高线上可用性，不改业务链路。

- 统一错误结构：`{"message": "..."}`。
- SSE 异常必须保证收尾 `done`。
- 增加超时保护与日志埋点（请求 ID / session_id）。
- `cart_update` 先提供空实现事件（可选），避免前端分支异常。

**仅改动**：`api/chat.py`（优先），必要时少量共用工具。

---

## 6. 文件级改动清单（建议）

**新增**

- `server/app/api/chat.py`（本次核心）

**修改**

- `server/app/main.py`（注册 chat router）
- `server/app/api/products.py`（字段补齐、列表返回对齐）
- （可选）`server/app/api/search.py`（抽复用函数，避免复制逻辑）

**不改**

- `server/app/agent/nodes/*`（除非发现阻塞性 bug）
- `server/app/services/llm_service.py`（本次不触碰）
- 前端代码与 UI 文件

---

## 7. 里程碑与交付物

### M1：聊天兼容可用

- 前端可通过 `/api/chat/stream` 收到 `delta/product_cards/done`
- `session_id` 可持续多轮对话

### M2：详情页字段完整

- 前端详情页渲染不缺字段（SKU、FAQ、评价可展示）

### M3：稳定性通过

- 异常流也能正确结束
- 日志可定位到具体会话

---

## 8. 验收清单（按部就班）

## A. 聊天链路

- [ ] `POST /api/chat/stream` 首轮可返回 `done.session_id`
- [ ] 二轮带同 `session_id` 有上下文
- [ ] SSE 顺序合法：`delta* -> product_cards? -> done`
- [ ] 异常时返回 `error` 且最终 `done`

## B. 商品链路

- [ ] `GET /api/products/{id}` 返回前端所需全部字段
- [ ] `GET /api/products` 支持 `category/q/limit`
- [ ] 图片地址可在客户端正确加载

## C. 前端联调（不改前端代码）

- [ ] AI 文本正常流式显示
- [ ] 商品卡片可渲染
- [ ] 点击卡片进入全屏详情页可展示 SKU 与评价

---

## 9. 风险与对策

- **风险 1：事件语义不一致导致前端不渲染**
  - 对策：先写 SSE 适配单测，严格校验事件名与 data 结构。

- **风险 2：商品详情字段来源分散**
  - 对策：在 `products.py` 组装统一 DTO，不把拼接逻辑散落到多个 API。

- **风险 3：改动扩散**
  - 对策：坚持“API 适配层优先”，不改 agent 节点与检索核心。

---

## 10. 开发纪律（避免改动无关代码）

- 单 PR 单目标：每个阶段单独提交。
- 不顺手重构无关模块。
- 不修改已有接口的历史行为（除非明确列入本计划）。
- 每次改动后只跑本阶段相关测试，避免大面积扰动。

---

## 11. 建议执行顺序（可直接照做）

1. 建 `chat.py` + 注册路由。
2. 跑通 `POST /api/chat/stream`，先只打通 `delta + done`。
3. 接 `product_cards` 组装。
4. 补 `POST /api/chat`（非流式兜底）。
5. 补齐 `products.py` 返回字段。
6. 回归清单逐项打勾。

> 按这个顺序做，改动面最小，定位问题也最快。