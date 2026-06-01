# AuraCart API 接口文档

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

## 3. 搜索接口（核心）

### `GET /api/search`

基于 RAG 的 AI 商品推荐。支持两套后端：**Agent 工作流**（stream=true，默认）和**传统 RAG 管线**（stream=false）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `q` | string | 是 | — | 用户查询文本 |
| `stream` | bool | 否 | `true` | SSE 流式 / JSON 非流式 |

#### 3.1 流式模式（Agent 工作流，默认）

Agent 工作流包含 6 个节点：Router → Extraction/ScenarioGen/ChitChat → Retrieval → OptionGen。结果通过 SSE 事件流实时推送到客户端。

```bash
curl -N "http://localhost:8000/api/search?q=推荐一款适合夏天的防晒霜&stream=true"
```

**SSE 事件规格**：

| event | data | 说明 |
|-------|------|------|
| `products` | `[{product_id, sku_id, category, sub_category}, ...]` | 每个品类检索完成时推送该品类的商品列表 |
| `reasoning` | `{token, category, sub_category}` | 按品类顺序串行发送推荐理由（品类聚合完整文本） |
| `chat_reply` | `string` | 闲聊路径回复（intent=chat 时） |
| `done` | `{total_categories, failed_categories}` | 检索阶段结束 |
| `next_options` | `["选项1", "选项2", ...]` | 全部完成后生成 2-4 条后续提问建议 |
| `error` | `{message}` | 异常事件 |

**典型事件流示例**：
```
event: products
data: [{"product_id":"P001","sku_id":"SKU-001","category":"面部护肤","sub_category":"防晒霜"},{"product_id":"P002","sku_id":"SKU-002","category":"面部护肤","sub_category":"防晒霜"}]

event: reasoning
data: {"token":"根据您的需求，推荐以下防晒霜：\n1. 安热沙小金瓶——SPF50+,质地清爽...\n2. ...","category":"面部护肤","sub_category":"防晒霜"}

event: done
data: {"total_categories":2,"failed_categories":[]}

event: next_options
data: ["有没有更平价的防晒霜？","这些适合敏感肌吗？","比较一下这几款的防晒指数"]
```

#### 3.2 非流式模式（传统 RAG 管线）

```bash
curl "http://localhost:8000/api/search?q=推荐一款蓝牙耳机&stream=false"
```

**响应**（`SearchResponse`）：
```json
{
  "query": "推荐一款蓝牙耳机",
  "sub_queries": [
    {"text":"蓝牙耳机","strategy":"keyword","field":null,"operator":null,"value":null,"expanded_values":null,"category":"数码电子","sub_category":"蓝牙耳机"},
    {"text":"音质清晰连接稳定","strategy":"semantic","field":null,"operator":null,"value":null,"expanded_values":null,"category":null,"sub_category":null},
    {"text":"","strategy":"structured_filter","field":"price","operator":"lt","value":500,"expanded_values":null,"category":null,"sub_category":null}
  ],
  "products": [
    {
      "product_id": "P001",
      "title": "小米Air 3 Pro",
      "brand": "小米",
      "category": "数码电子",
      "sub_category": "蓝牙耳机",
      "base_price": 399.0,
      "sku_id": "SKU-001",
      "properties": {"颜色":"白色"},
      "price": 399.0,
      "stock": 120,
      "matched_texts": [
        {"content":"音质不错，降噪效果好","source":"user_review","metadata":{}}
      ]
    }
  ],
  "reasoning": "为您推荐以下蓝牙耳机：\n1. 小米Air 3 Pro——399元..."
}
```

---

## 4. 商品查询

### 4.1 `GET /api/products/{product_id}`

获取单个产品基本信息（不含 SKU 列表和图片路径）。

```bash
curl http://localhost:8000/api/products/P001
```

**响应**（200）：
```json
{
  "product_id": "P001",
  "title": "安热沙小金瓶防晒霜",
  "brand": "安热沙",
  "category": "面部护肤",
  "sub_category": "防晒霜",
  "base_price": 198.0
}
```

**错误**（404）：产品不存在或已下架。

### 4.2 `GET /api/products/image/{product_id}`

获取产品图片文件。

```bash
curl -o product.jpg http://localhost:8000/api/products/image/P001
```

**响应**：图片二进制流。404 表示产品不存在、已下架或无图片文件。

### 4.3 `GET /api/sku/{sku_id}`

获取 SKU 属性、价格和库存。

```bash
curl http://localhost:8000/api/sku/SKU-001
```

**响应**（200）：
```json
{
  "sku_id": "SKU-001",
  "properties": {"规格":"60ml"},
  "price": 198.0,
  "stock": 50
}
```

---

## 5. 批量查询

### 5.1 `GET /api/products/batch?ids=...`

批量获取产品信息（最多 20 个）。不存在的 ID 静默忽略，已下架自动过滤。

```bash
curl "http://localhost:8000/api/products/batch?ids=P001,P002,P003"
```

**参数**：`ids` — 逗号分隔的 product_id 列表（自动去重去空）。

**响应**（200）：
```json
[
  {"product_id":"P001","title":"...","brand":"...","category":"...","sub_category":"...","base_price":198.0},
  {"product_id":"P002","title":"...","brand":"...","category":"...","sub_category":"...","base_price":null}
]
```

**错误**（422）：超过 `max_batch_ids`（默认 20）或 `ids` 为空。

### 5.2 `GET /api/products/image/batch?ids=...`

批量获取产品图片路径。

```bash
curl "http://localhost:8000/api/products/image/batch?ids=P001,P002"
```

**响应**：
```json
[
  {"product_id":"P001","image_url":"images/product_001.jpg"},
  {"product_id":"P002","image_url":"images/product_002.jpg"}
]
```

### 5.3 `GET /api/sku/batch?ids=...`

批量获取 SKU 详情（最多 20 个）。

```bash
curl "http://localhost:8000/api/sku/batch?ids=SKU-001,SKU-002"
```

**响应**（200）：
```json
[
  {"sku_id":"SKU-001","product_id":"P001","properties":{"规格":"60ml"},"price":198.0,"stock":50},
  {"sku_id":"SKU-002","product_id":"P001","properties":{"规格":"30ml"},"price":128.0,"stock":30}
]
```

---

## 6. 管理接口

### `POST /api/admin/sync`

手动触发数据同步：扫描源表（product_marketing / product_faq / user_review）的变更，重新生成嵌入向量并写入 `product_review` 表。使用 PostgreSQL 咨询锁防并发。

```bash
curl -X POST http://localhost:8000/api/admin/sync
```

**响应**：
```json
{"status":"ok","message":"Sync completed"}
```

---

## 7. 测试脚本

### 7.1 自动化验证脚本

```bash
# 在 server/ 目录下运行
cd server
python test_demo.py

# 指定非默认端口
python test_demo.py --base-url http://localhost:8080
```

脚本依次验证：
1. `GET /health` — 服务存活
2. `GET /api/search?stream=true` — 完整 SSE 流式检索
3. `GET /api/products/{id}` — 商品详情 + 404 断言

全部通过输出 `Result: ALL PASSED`。

### 7.2 手动 curl 测试脚本

将以下内容保存为 `test_api.sh` 并在项目根目录执行：

```bash
#!/bin/bash
BASE="http://localhost:8000"

echo "=== 1. Health Check ==="
curl -s $BASE/health | python -m json.tool

echo -e "\n=== 2. 搜索（非流式）==="
curl -s "$BASE/api/search?q=%E8%93%9D%E7%89%99%E8%80%B3%E6%9C%BA&stream=false" | python -m json.tool | head -30

echo -e "\n=== 3. 搜索（流式，前 5 秒输出）==="
timeout 5 curl -s -N "$BASE/api/search?q=%E9%98%B2%E6%99%92%E9%9C%9C&stream=true" 2>/dev/null | head -20

echo -e "\n=== 4. 产品查询 ==="
curl -s $BASE/api/products/P001 | python -m json.tool

echo -e "\n=== 5. 不存在的产品（应返回 404）==="
curl -s -o /dev/null -w "HTTP %{http_code}" $BASE/api/products/NONEXIST
echo ""

echo -e "\n=== 6. 批量查询 ==="
curl -s "$BASE/api/products/batch?ids=P001,P002" | python -m json.tool

echo -e "\n=== 7. 管理同步 ==="
curl -s -X POST $BASE/api/admin/sync | python -m json.tool
```

**执行**：
```bash
chmod +x test_api.sh && ./test_api.sh
```

> **注意**：curl 中中文需 URL 编码。可使用 `server/scripts/transfer_api_request.py` 自动转换。

### 7.3 单元测试

```bash
cd server

# 运行全部非网络依赖测试
python -m pytest tests/ -v --tb=short \
  --ignore=tests/test_e2e.py \
  --ignore=tests/test_llm.py \
  --ignore=tests/test_embedding.py \
  --ignore=tests/test_import_data.py \
  --ignore=tests/test_sync.py \
  --ignore=tests/test_search.py \
  --ignore=tests/test_retriever.py \
  --ignore=tests/test_generator.py \
  --ignore=tests/test_products.py \
  --ignore=tests/test_category_lookup.py \
  --ignore=tests/test_query_parser.py \
  --ignore=tests/test_sku_utils.py \
  --ignore=tests/test_merger.py

# 按模块运行
python -m pytest tests/test_router.py tests/test_graph.py -v         # Router + Graph
python -m pytest tests/test_extraction.py tests/test_scenario_gen.py -v  # Extraction + ScenarioGen
python -m pytest tests/test_retrieval_node.py tests/test_option_gen.py -v  # Retrieval + OptionGen
python -m pytest tests/test_chitchat.py -v                           # ChitChat
python -m pytest tests/test_search_agent.py -v                       # Agent SSE 集成
python -m pytest tests/test_batch_api.py -v                          # Batch API
python -m pytest tests/test_memory.py tests/test_agent_state.py -v   # Memory + State
```

### 7.4 curl URL 编码辅助

```bash
cd server
# 交互模式：输入 curl 命令，输出编码后的命令
python scripts/transfer_api_request.py

# 测试模式
python scripts/transfer_api_request.py --test
```

---

## 8. 注意事项

1. **中文 URL 编码** — curl 中使用中文需编码，推荐使用 `transfer_api_request.py` 或 `test_demo.py` 自动处理
2. **SSE 超时** — `config.yaml` 中 `timeout.total_request` 默认 60s
3. **数据库依赖** — 除 `/health` 外所有接口依赖 PostgreSQL
4. **LLM/Embedding 依赖** — `/api/search` 需有效的 LLM 和 Embedding API Key
5. **端口** — 默认 8000，Docker 映射同端口
