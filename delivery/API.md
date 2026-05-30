# AuraCart API 接口文档

本文档提供所有 API 接口的详细说明与测试方法。所有路径均以 `http://localhost:8000` 为基础地址。

---

## 0. 前置条件

按 [README.md](README.md) 完成数据库启动、表结构初始化、数据导入和服务启动后，方可进行以下测试。

服务默认监听 `http://127.0.0.1:8000`。

---

## 1. 健康检查

**接口:** `GET /health`

**功能:** 检查服务是否运行中。

**测试方法:**

```bash
curl http://localhost:8000/health
```

**预期响应:**

```json
{"status":"ok"}
```


## 2. SSE 全链路 RAG 检索

**接口:** `GET /api/search/stream`

**功能:** 完整 RAG 管线 — LLM 查询解析 → 多策略检索（语义+关键词）→ RRF 融合排序 → LLM 推荐生成，通过 SSE 流式返回。

**参数:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `q` | string | 是 | 自然语言查询 |

**测试方法（Bash）:**

```bash
curl -N "http://localhost:8000/api/search/stream?q=推荐一款200元以下的防晒霜"
# 通过URL中的中文需要做编码，可使用脚本server\scripts\transfer_api_request.py做转换。
```

**SSE 事件序列与预期:**

事件按以下顺序发送 ——

**(1) products — 检索合并后的候选商品（SKU 级别）**

```
event: products
data: [{"product_id":"PROD001","title":"安耐晒小金瓶防晒霜","brand":"安耐晒","category":"美妆护肤","sub_category":"防晒","base_price":198.0,"sku_id":"SKU001_60ml","properties":{"容量":"60ml"},"price":198.0,"stock":42}, ...]
```

每条结果是一个匹配的 SKU + 所属 product 基本信息。最多返回 10 条（由 `config.yaml` 中 `search.final_sku_limit` 控制）。

**(3) reasoning — LLM 推荐文案（逐 token）**

```
event: reasoning
data: 为您

event: reasoning
data: 推荐

event: reasoning
data: 以下
...
```

**(4) done — 流结束**

```
event: done
data: {}
```

**(5) error（仅在异常时出现）**

```
event: error
data: {"message":"..."}

event: done
data: {}
```

**验证要点:**
- 必须包含 `sub_queries`、`products`、`reasoning`、`done` 四个事件
- `products` 中每条数据应同时包含 product 字段（product_id/title/brand/category）和 SKU 字段（sku_id/properties/price/stock）
- `reasoning` 的推荐文案应引用实际商品名称和属性

---

## 3. 商品基本信息

**接口:** `GET /api/products/{product_id}`

**功能:** 返回商品的基本元信息，不含 SKU 列表和图片路径。

**测试方法:**

```bash
curl http://localhost:8000/api/products/PROD001
```

**预期响应:**

```json
{
  "product_id": "PROD001",
  "title": "安耐晒小金瓶防晒霜",
  "brand": "安耐晒",
  "category": "美妆护肤",
  "sub_category": "防晒",
  "base_price": 198.0
}
```

**异常测试:**

```bash
# 不存在的商品应返回 404
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/products/NONEXIST
# 预期输出: 404
```

---

## 4. 商品图片

**接口:** `GET /api/products/image/{product_id}`

**功能:** 返回商品图片文件（JPEG 等格式）。

**测试方法（Bash）:**

```bash
# 下载图片到本地文件
curl -o product_image.jpg http://localhost:8000/api/products/image/PROD001

# 仅查看 HTTP 状态码
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/products/image/PROD001
# 预期输出: 200
```

**测试方法（PowerShell）:**

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/api/products/image/PROD001" -OutFile "product_image.jpg"
```

**异常测试:**

```bash
# 不存在的商品
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/products/image/NONEXIST
# 预期输出: 404
```

---

## 5. SKU 详情

**接口:** `GET /api/sku/{sku_id}`

**功能:** 返回单个 SKU 的属性、价格和库存信息。

**测试方法:**

```bash
curl http://localhost:8000/api/sku/SKU001_60ml
```

**预期响应:**

```json
{
  "sku_id": "SKU001_60ml",
  "properties": {"容量": "60ml"},
  "price": 198.0,
  "stock": 42
}
```

**异常测试:**

```bash
# 不存在的 SKU
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/sku/NONEXIST
# 预期输出: 404
```

---

## 6. 手动数据同步

**接口:** `POST /api/admin/sync`

**功能:** 手动触发一次全量数据同步，将源表（product_marketing / product_faq / user_review）的变更同步到 product_review 向量表。

**测试方法:**

```bash
curl -X POST http://localhost:8000/api/admin/sync
```

**预期响应:**

```json
{"status":"ok","message":"Sync completed"}
```

---

## 7. 自动化验证脚本

项目提供了自动化验证脚本，一键测试以上所有接口：

```bash
cd server
python test_demo.py

# 如果服务不在默认 8000 端口
python test_demo.py --base-url http://localhost:8080
```

脚本依次执行 3 个测试用例：
1. `GET /health` — 健康检查
2. `GET /api/search/stream` — SSE 全链路检索
3. `GET /api/products/{product_id}` — 商品详情 + 404 断言

全部通过时输出 `Result: ALL PASSED`。

---

## 8. 测试注意事项

1. **中文查询需要 URL 编码** — 直接粘贴中文到 curl 可能失败，推荐使用编码后的 URL 或使用 `python test_demo.py`
2. **SSE 接口超时** — `config.yaml` 中 `timeout.total_request` 默认 60s，复杂查询可能接近此限
3. **数据库必须处于运行状态** — 所有接口（除 `/health`）依赖 PostgreSQL
4. **LLM 依赖** — `/api/search/stream` 需要 LLM API Key 有效，否则阶段 1 和阶段 4 将失败
5. **Embedding 依赖** — `/api/search/stream` 需要 Embedding API Key 有效
