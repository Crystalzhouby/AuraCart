# AuraCart API 接口文档

> **版本**：v2.2（会话管理 + 展示流对齐） | **更新日期**：2026-06-06

## 1. 基础信息

- **Base URL**: `http://localhost:8000`
- **Content-Type**: `application/json`
- **SSE 流式端点**: `text/event-stream`

---

## 2. 健康检查

### `GET /health`

验证服务存活状态。

```bash
curl http://localhost:8000/health
```

**响应**：
```json
{"status": "ok"}
```

---

## 3. 会话管理

### `GET /api/conversation`

创建新会话，返回唯一 `conversation_id`。后续调用 `/api/search/{conversation_id}` 时使用该 ID 进行多轮对话，记忆自动持久化到 conversation 表。

```bash
curl http://localhost:8000/api/conversation
```

**响应**（200）：
```json
{"conversation_id": "550e8400-e29b-41d4-a716-446655440000"}
```

> **说明**：无副作用，每次调用生成新 UUID 并写入 conversation 表（初始 memory 为空数组）。conversation_id 为搜索接口必填路径参数，所有查询均归属一个会话。多轮对话直接使用同一 conversation_id 即可自动加载历史记忆。

---

## 4. 搜索接口（核心）

### `GET /api/search/{conversation_id}`

AI 商品导购主入口，**全部采用 Agent 工作流**（LangGraph 6 节点管线），通过 SSE 事件流实时推送结果。
conversation_id 为必填路径参数，由 `/api/conversation` 创建获取。conversation_id 在 conversation 表中不存在时返回 `error` 事件（`{"detail": "conversation not found"}`），前端应重建会话并重试。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `conversation_id` | string (path) | 是 | — | 会话 ID，由 `/api/conversation` 获取 |
| `q` | string | 是 | — | 用户查询文本 |
| `stream` | bool | 否 | `true` | 保留参数（始终走 SSE 流式，忽略此参数） |

```bash
# 单轮查询
curl -N "http://localhost:8000/api/search/550e8400-e29b-41d4-a716-446655440000?q=推荐一款适合夏天的防晒霜"

# 多轮对话（同一 conversation_id）
curl -N "http://localhost:8000/api/search/550e8400-e29b-41d4-a716-446655440000?q=要轻量的"
```

### 4.1 SSE 事件规格

Agent 工作流节点：**Router**（意图分类+查询改写）→ **Extraction / ScenarioGen**（需求提取）→ **Retrieval**（欢迎语 → 并行检索 → 品类介绍 → 逐商品推荐 → 结束语 + done）→ **OptionGen**（后续选项）。

| event | data 类型 | 发送时机 | 说明 |
|-------|----------|---------|------|
| `welcome` | `string` | Retrieval 入口 | LLM 生成的欢迎语，基于用户需求，单品类突出特点、多品类突出场景感 |
| `products` | `object` | 每个商品推荐前 | 单个商品 ID 和品类信息（非数组），后跟该商品的 `chat_reply` |
| `chat_reply` | `string` | 品类开始前 / 商品推荐后 | 多品类时为品类介绍过渡语，每个商品后为该商品的推荐理由 |
| `done` | `object` | Retrieval 末尾 | 含结束语 `text` 和 `conversation_id` |
| `next_options` | `array` | `done` 事件之后 | 2-4 条下一步推荐选项，LLM 可能返回空数组（此时不发送此事件） |
| `error` | `object` | 异常时 | 错误信息，通常后跟 `done` 事件 |

### 4.2 welcome 事件

```
data: "海边度假装备得备齐！结合你的出游场景，帮你整理了几个超实用的品类～"
```

> `welcome` 为每条查询的第一个事件，单品类时突出品类特点，多品类时突出场景感。

### 4.3 products 事件（单商品）

```json
{
  "product_id": "p_beauty_001",
  "sku_id": "s_p_beauty_001_1",
  "category": "面部护肤",
  "sub_category": "防晒霜"
}
```

> 每个 `products` 事件只包含一个商品（非数组）。其后紧跟该商品的 `chat_reply` 推荐理由。前端收到后调用 **batch API**（§5）批量获取标题/价格/图片/属性。

### 4.4 chat_reply 事件

**品类介绍过渡语**（仅多品类，在品类下第一个商品之前）：
```
data: "🧴 首先是美妆护肤（防晒必备）。海边紫外线强，高倍数且防水的防晒必不可少："
```

**单商品推荐理由**（每个 `products` 事件之后）：
```
data: "巴黎欧莱雅主打水感轻薄质地，上脸瞬间推开成膜，无厚重黏腻感，适合海边游玩用。"
```

> 多品类场景：每个品类先发一段品类介绍 `chat_reply`，再逐个发送 `products` + `chat_reply`（推荐理由）。单品类场景：直接逐商品发送 `products` + `chat_reply`，无品类介绍。

### 4.5 done 事件

```json
{
  "text": "以上就是为你搭配的海边出游三件套，有看中的款式吗？或者告诉我你的预算，帮你再进一步筛选～",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `string` | LLM 生成的结束语，总结推荐内容并引导下一步互动 |
| `conversation_id` | `string` | 当前会话 ID（由服务端在 done 事件中注入） |

### 4.6 next_options 事件

```json
["有没有更平价的防晒霜？", "这些适合敏感肌吗？", "比较一下这几款的防晒指数"]
```

> **注意**：当 LLM 返回空数组 `[]` 时，服务端不发送 `next_options` 事件。前端在收到 `done` 事件后若干秒内未收到 `next_options` 时应视为无后续选项。

### 4.7 error 事件

```json
{"message": "请求超时"}
```

**conversation not found 错误**（conversation_id 在 DB 中不存在时）：

```json
{"detail": "conversation not found"}
```

> 前端收到此错误后应调用 `GET /api/conversation` 重建会话并自动重试当前查询。

### 4.8 典型事件流示例

**单品类查询**（如"200 元以下的蓝牙耳机"）：

```
event: welcome
data: "帮你挑了几款口碑好、性价比高的蓝牙耳机～"

event: products
data: {"product_id":"p_digi_001","sku_id":"s_p_digi_001_1","category":"数码电子","sub_category":"蓝牙耳机"}

event: chat_reply
data: "漫步者 X3——¥159，音质均衡，续航 24 小时，入门首选。"

event: products
data: {"product_id":"p_digi_002","sku_id":"s_p_digi_002_1","category":"数码电子","sub_category":"蓝牙耳机"}

event: chat_reply
data: "小米 Buds 3——¥189，轻量设计佩戴舒适，支持主动降噪。"

event: done
data: {"text":"这两款都是 200 元以内的人气款，有看中的吗？","conversation_id":"550e8400-..."}

event: next_options
data: ["需要关注降噪功能吗？","想看看 100 元以内的入门款吗？","比较一下这几款"]
```

**多品类查询**（如场景化"去三亚度假需要准备什么"）：

```
event: welcome
data: "海边度假装备得备齐！结合你的出游场景，帮你整理了几个超实用的品类～"

event: chat_reply
data: "🧴 首先是美妆护肤（防晒必备）。海边紫外线强，高倍数且防水的防晒必不可少："

event: products
data: {"product_id":"p_beauty_006","sku_id":"s_p_beauty_006_1","category":"美妆护肤","sub_category":"防晒"}

event: chat_reply
data: "巴黎欧莱雅主打水感轻薄质地，上脸瞬间推开成膜，无厚重黏腻感，适合海边游玩用。"

event: products
data: {"product_id":"p_beauty_010","sku_id":"s_p_beauty_010_1","category":"美妆护肤","sub_category":"防晒"}

event: chat_reply
data: "安热沙小金瓶——SPF50+，遇水防晒力更强，去海边冲浪游泳都不怕被晒黑！"

event: chat_reply
data: "\n\n🕶️ 接下来是服饰配件（凹造型加防晒）。除了涂抹防晒，物理防晒也很重要："

event: products
data: {"product_id":"p_clothes_001","sku_id":"s_p_clothes_001_2","category":"服饰运动","sub_category":"短袖T恤"}

event: chat_reply
data: "这款白色优衣库T恤吸湿速干效果好，出了汗也不会黏在背上，适合夏天出行穿。"

event: done
data: {"text":"以上就是为你搭配的海边出游两件套，有看中的款式吗？或者告诉我你的预算～","conversation_id":"550e8400-..."}

event: next_options
data: ["需要推荐适合海边的凉鞋吗？","需要搭配晒后修复产品吗？","比较一下这两款防晒霜"]
```

### 4.9 前端集成要点

0. **会话初始化**：页面/组件加载时调用 `GET /api/conversation` 获取 `conversation_id`，持久化到本地存储。后续所有 `/api/search/{conversation_id}` 请求使用该 ID
1. **收到 `welcome` 事件**：在聊天区域显示欢迎语，作为对话开场
2. **收到 `products` 事件**：单商品对象（非数组），收集 `product_id` 和 `sku_id`，调用 batch API（§5）获取详情后渲染商品卡片
3. **收到 `chat_reply` 事件**：可能是品类介绍过渡语（多品类）或单商品推荐理由。多品类时品类介绍作为分组标题，推荐理由紧跟商品卡片
4. **收到 `done` 事件**：记录 `conversation_id`，读取 `text` 字段展示结束语，停止 loading 状态
5. **收到 `next_options` 事件**：以快捷按钮形式展示在回复末尾。若 `done` 事件后约 2 秒内未收到此事件（LLM 返回空数组时服务端不发送），视为无后续选项
6. **收到 `error` 事件**：若 `detail` 为 `"conversation not found"`，调用 `/api/conversation` 重建会话并自动重试当前查询；其他错误（如 `"请求超时"`）展示错误提示

---

## 5. 商品查询

### 5.1 `GET /api/products/{product_id}`

获取单个产品基本信息（不含 SKU 列表和图片路径）。

```bash
curl http://localhost:8000/api/products/p_beauty_001
```

**响应**（200）：
```json
{
  "product_id": "p_beauty_001",
  "title": "安热沙小金瓶防晒霜",
  "brand": "安热沙",
  "category": "面部护肤",
  "sub_category": "防晒霜",
  "base_price": 198.0
}
```

**错误**（404）：产品不存在或已下架。

### 5.2 `GET /api/products/image/{product_id}`

获取产品图片文件。

```bash
curl -o product.jpg http://localhost:8000/api/products/image/p_beauty_001
```

**响应**：图片二进制流。404 表示产品不存在、已下架或无图片文件。

### 5.3 `GET /api/sku/{sku_id}`

获取单个 SKU 的属性、价格和库存。

```bash
curl http://localhost:8000/api/sku/s_p_beauty_001_1
```

**响应**（200）：
```json
{
  "sku_id": "s_p_beauty_001_1",
  "properties": {"容量": "60ml"},
  "price": 198.0,
  "stock": 50
}
```

**错误**（404）：SKU 不存在或已停用。

---

## 6. 批量查询

> **设计意图**：`products` SSE 事件只传 ID，前端通过以下 3 个 batch API 批量获取卡片所需的全部数据，将请求数从 N×3 降为 3 次。

### 6.1 `GET /api/products/batch?ids=...`

批量获取产品基本信息（最多 20 个）。不存在的 ID 静默忽略，已下架自动过滤。

```bash
curl "http://localhost:8000/api/products/batch?ids=p_beauty_001,p_beauty_002,p_fash_010"
```

**参数**：`ids` — 逗号分隔的 product_id 列表（自动去重去空）。

**响应**（200）：
```json
[
  {"product_id":"p_beauty_001","title":"安热沙小金瓶防晒霜","brand":"安热沙","category":"面部护肤","sub_category":"防晒霜","base_price":198.0},
  {"product_id":"p_beauty_002","title":"资生堂蓝胖子防晒霜","brand":"资生堂","category":"面部护肤","sub_category":"防晒霜","base_price":239.0}
]
```

**错误**（422）：超过 `max_batch_ids`（默认 20）或 `ids` 为空。

### 6.2 `GET /api/products/image/batch?ids=...`

批量获取产品图片路径。

```bash
curl "http://localhost:8000/api/products/image/batch?ids=p_beauty_001,p_beauty_002"
```

**响应**（200）：
```json
[
  {"product_id":"p_beauty_001","image_url":"ecommerce_agent_dataset/images/p_beauty_001_live.jpg"},
  {"product_id":"p_beauty_002","image_url":"ecommerce_agent_dataset/images/p_beauty_002_live.jpg"}
]
```

### 6.3 `GET /api/sku/batch?ids=...`

批量获取 SKU 详情（最多 20 个）。

```bash
curl "http://localhost:8000/api/sku/batch?ids=s_p_beauty_001_1,s_p_beauty_001_2"
```

**响应**（200）：
```json
[
  {"sku_id":"s_p_beauty_001_1","product_id":"p_beauty_001","properties":{"容量":"60ml"},"price":198.0,"stock":50},
  {"sku_id":"s_p_beauty_001_2","product_id":"p_beauty_001","properties":{"容量":"30ml"},"price":128.0,"stock":30}
]
```

---

## 7. 管理接口

### `POST /api/admin/sync`

手动触发数据同步：扫描源表（product_marketing / product_faq / user_review）的变更，重新生成嵌入向量并写入 `product_review` 表。

```bash
curl -X POST http://localhost:8000/api/admin/sync
```

**响应**（200）：
```json
{"status":"ok","message":"Sync completed"}
```

---

## 8. 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/conversation` | 创建新会话 |
| `GET` | `/api/search/{conversation_id}?q=` | Agent 工作流 SSE 搜索（核心） |
| `GET` | `/api/products/{product_id}` | 单个产品信息 |
| `GET` | `/api/products/image/{product_id}` | 产品图片 |
| `GET` | `/api/sku/{sku_id}` | 单个 SKU 详情 |
| `GET` | `/api/products/batch?ids=` | 批量产品信息 |
| `GET` | `/api/products/image/batch?ids=` | 批量产品图片 |
| `GET` | `/api/sku/batch?ids=` | 批量 SKU 详情 |
| `POST` | `/api/admin/sync` | 触发数据同步 |

---

## 9. 注意事项

1. **仅 SSE 流式** — `/api/search` 不再支持非流式 JSON 模式（已移除传统 RAG 管线），`stream` 参数保留但忽略
2. **中文 URL 编码** — curl 中使用中文需编码，推荐使用 `server/scripts/transfer_api_request.py` 转换
3. **SSE 超时** — 默认 300s（`config.yaml` 中 `timeout.total_request` 可配），场景化查询涉多品类并行检索，建议不低于 180s
4. **数据库依赖** — 除 `/health` 外所有接口依赖 PostgreSQL，需预先运行数据导入脚本
5. **LLM/Embedding 依赖** — `/api/search` 需有效的 LLM 和 Embedding API Key，Agent 工作流强依赖 LLM 进行意图分类、查询改写、推荐理由生成等
6. **Batch API 限制** — 单次最多 20 个 ID（`config.yaml` 中 `search.max_batch_ids` 可配）
7. **端口** — 默认 8000，Docker 映射同端口
8. **会话记忆持久化** — `conversation_id` 为必填路径参数，所有查询均归属于一个会话，记忆（原始查询按品类分组）自动持久化到 `conversation` 表的 `memory` JSONB 字段
9. **多轮对话** — Router 节点利用历史记忆改写不完整查询（如"要轻量的"→"要轻量的跑鞋"），Memory 按 `(category, sub_category)` 分组存储原始查询
