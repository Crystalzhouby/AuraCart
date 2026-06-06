# AuraCart API 接口文档

> **版本**：v2.0（Agent 工作流重构后） | **更新日期**：2026-06-05

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

创建新会话，返回唯一 `conversation_id`。后续调用 `/api/search/{conversation_id}` 时使用该 ID 进行多轮对话，记忆自动持久化。

```bash
curl http://localhost:8000/api/conversation
```

**响应**（200）：
```json
{"conversation_id": "550e8400-e29b-41d4-a716-446655440000"}
```

> **说明**：无副作用，每次调用生成新 UUID 并写入 conversation 表。conversation_id 为搜索接口必填参数，所有查询均归属一个会话。

---

## 4. 搜索接口（核心）

### `GET /api/search/{conversation_id}`

AI 商品导购主入口，**全部采用 Agent 工作流**（LangGraph 6 节点管线），通过 SSE 事件流实时推送结果。
conversation_id 为必填路径参数，由 `/api/conversation` 创建获取。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `conversation_id` | string (path) | 是 | — | 会话 ID，由 `/api/conversation` 获取 |
| `q` | string | 是 | — | 用户查询文本 |
| `stream` | bool | 否 | `true` | 保留参数向后兼容，始终走 SSE 流式 |

```bash
# 单轮查询
curl -N "http://localhost:8000/api/search/550e8400-e29b-41d4-a716-446655440000?q=推荐一款适合夏天的防晒霜"

# 多轮对话（同一 conversation_id）
curl -N "http://localhost:8000/api/search/550e8400-e29b-41d4-a716-446655440000?q=要轻量的"
```

### 4.1 SSE 事件规格

Agent 工作流节点：**Router**（意图分类+查询改写）→ **Extraction / ScenarioGen**（需求提取）→ **Retrieval**（多品类并行检索+推荐理由生成）→ **OptionGen**（后续选项）。

| event | data 类型 | 发送时机 | 说明 |
|-------|----------|---------|------|
| `products` | `array` | 每个品类检索完成时 | 该品类的商品 ID 列表，前端调用 batch API 获取详情 |
| `chat_reply` | `string` | 每个品类推荐理由生成后 | 该品类的推荐理由完整文本（按品类顺序发送） |
| `done` | `object` | 所有品类完成 + 选项生成后 | 检索阶段结束标记，含 `conversation_id` |
| `next_options` | `array` | `done` 事件之后 | 2-4 条下一步推荐选项，前端以快捷按钮形式展示 |
| `error` | `object` | 异常时 | 错误信息，通常后跟 `done` 事件 |

### 4.2 products 事件

```json
[
  {
    "product_id": "p_beauty_001",
    "sku_id": "s_p_beauty_001_1",
    "category": "面部护肤",
    "sub_category": "防晒霜"
  },
  {
    "product_id": "p_beauty_002",
    "sku_id": "s_p_beauty_002_1",
    "category": "面部护肤",
    "sub_category": "防晒霜"
  }
]
```

> **注意**：`products` 仅包含 ID 和品类路由信息。前端收到后应调用 **batch API**（§5）批量获取标题/价格/图片/属性。

### 4.3 chat_reply 事件

```json
"根据您的需求，为您推荐以下防晒霜：\n\n1. 安热沙小金瓶防晒霜——SPF50+ PA++++，质地清爽不粘腻，防水防汗效果出色，适合夏季户外使用。¥198。\n\n2. ..."
```

> `chat_reply` 是完整的推荐理由文本（非逐 token 流式）。多品类场景下按品类顺序依次发送，每个品类一段完整文本。

### 4.4 done 事件

```json
{
  "next_options_count": 3,
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 4.5 next_options 事件

```json
["有没有更平价的防晒霜？", "这些适合敏感肌吗？", "比较一下这几款的防晒指数"]
```

### 4.6 error 事件

```json
{"message": "请求超时"}
```

### 4.7 典型事件流示例

**单品类查询**（如"200 元以下的蓝牙耳机"）：

```
event: products
data: [{"product_id":"p_digi_001","sku_id":"s_p_digi_001_1","category":"数码电子","sub_category":"蓝牙耳机"},{"product_id":"p_digi_002","sku_id":"s_p_digi_002_1","category":"数码电子","sub_category":"蓝牙耳机"}]

event: chat_reply
data: "为您找到 2 款 200 元以内的蓝牙耳机：\n1. 漫步者 X3——¥159..."

event: done
data: {"next_options_count":3,"conversation_id":"550e8400-..."}

event: next_options
data: ["需要关注降噪功能吗？","想看看 100 元以内的入门款吗？","比较一下这几款"]
```

**多品类查询**（如场景化"去三亚度假需要准备什么"）：

```
event: products
data: [{"product_id":"p_beauty_001","sku_id":"s_p_beauty_001_1","category":"面部护肤","sub_category":"防晒霜"},...]

event: chat_reply
data: "为您推荐以下防晒霜：\n1. 安热沙小金瓶——SPF50+..."

event: products
data: [{"product_id":"p_fash_010","sku_id":"s_p_fash_010_1","category":"服饰","sub_category":"墨镜"},...]

event: chat_reply
data: "墨镜方面，推荐：\n1. 雷朋飞行员系列——偏光防紫外线..."

event: products
data: [...]     ← 沙滩裤

event: chat_reply
data: "..."     ← 沙滩裤推荐理由

... (遮阳帽、凉鞋同理，按品类顺序依次发送)

event: done
data: {"next_options_count":2,"conversation_id":"550e8400-..."}

event: next_options
data: ["需要推荐泳衣吗？","需要搭配晒后修复产品吗？"]
```

### 4.8 前端集成要点

0. **会话初始化**：页面/组件加载时调用 `GET /api/conversation` 获取 `conversation_id`，持久化到本地存储。后续所有 `/api/search/{conversation_id}` 请求使用该 ID
1. **收到 `products` 事件**：收集 `product_id` 和 `sku_id`，调用 batch API（§5）获取详情后渲染商品卡片
2. **收到 `chat_reply` 事件**：将该品类的推荐理由文本追加到聊天区域。多品类时按品类分区展示
3. **收到 `done` 事件**：记录 `conversation_id`（用于下一轮对话），停止 loading 状态
4. **收到 `next_options` 事件**：以快捷按钮形式展示在回复末尾
5. **收到 `error` 事件**：若 `detail` 为 `"conversation not found"`，调用 `/api/conversation` 重建会话并自动重试当前查询；其他错误展示错误提示

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

1. **仅 SSE 流式** — `/api/search` 不再支持非流式 JSON 模式（已移除传统 RAG 管线）
2. **中文 URL 编码** — curl 中使用中文需编码，推荐使用 `server/scripts/transfer_api_request.py` 转换
3. **SSE 超时** — 默认 60s（`config.yaml` 中 `timeout.total_request` 可配）
4. **数据库依赖** — 除 `/health` 外所有接口依赖 PostgreSQL
5. **LLM/Embedding 依赖** — `/api/search` 需有效的 LLM 和 Embedding API Key
6. **Batch API 限制** — 单次最多 20 个 ID（`config.yaml` 中 `search.max_batch_ids` 可配）
7. **端口** — 默认 8000，Docker 映射同端口
8. **会话记忆持久化** — conversation_id 为必填参数，所有查询均归属于一个会话，记忆自动持久化到 `conversation` 表
