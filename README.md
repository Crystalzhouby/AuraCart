# AI-Agent-Ecom-Guide

基于 **RAG + SSE** 的多模态电商智能导购 AI Agent。  
Android 原生 App + FastAPI 后端，支持流式对话、商品卡片渲染、购物车管理。

---

## 技术选型

| 层级 | 技术 | 说明 |
|------|------|------|
| 客户端 | Android + Kotlin | 原生 App，对话页、SSE 流式渲染、商品卡片 |
| 后端 | FastAPI + Python 3.9 | RAG 编排、SSE 流式接口、商品检索 |
| 大模型 | Doubao-Seed-2.0-lite | 火山引擎 Ark API（OpenAI 兼容格式） |
| 数据 | JSONL + 图片 | 100 条真实脱敏商品数据，含 FAQ 和用户评价 |

---

## 项目结构

```text
AI-Agent-Ecom-Guide/
├── client/                     # Android 客户端（Kotlin）
│   └── app/src/main/java/com/ecomguide/
│       ├── model/              # 数据模型（ApiProduct、MessageItem、CartItem 等）
│       ├── network/            # 网络层（RetrofitClient、ChatStreamClient SSE）
│       ├── repository/         # 仓库层（CartRepository、DemoProducts）
│       └── ui/                 # UI 层（ChatFragment、ProductDetailActivity 等）
├── server/                     # FastAPI 后端
│   ├── app/
│   │   ├── api/                # HTTP/SSE 路由（chat.py、products.py）
│   │   ├── core/               # 配置（config.py 读取 .env）
│   │   ├── schemas/            # 请求/响应模型（chat、product、cart）
│   │   ├── services/           # 核心服务（RagService、ProductRepository、CartService）
│   │   └── prompts/            # 系统提示词（Prompt Engineering）
│   ├── tests/                  # 单元测试
│   └── requirements.txt        # Python 依赖
├── data/
│   ├── ecommerce_agent_dataset/ # 原始商品 JSON + 实拍图片（100 条）
│   ├── processed/               # 处理后的 products.jsonl（供 RAG 检索）
│   └── scripts/                 # 数据处理脚本
├── docs/                        # 技术文档（架构、API、RAG 设计等）
├── DEPENDENCIES.md              # 全量依赖清单（服务端 + 客户端）
├── docker-compose.yml
├── .env.example                 # 环境变量模板
└── README.md
```

---

## 快速启动

### 1. 后端服务

```bash
# 克隆项目
git clone https://github.com/Crystalzhouby/AI-Agent-Ecom-Guide.git
cd AI-Agent-Ecom-Guide

# 配置环境变量（填入 Ark API Key）
cp .env.example server/.env

# 安装依赖
cd server
python3 -m pip install -r requirements.txt

# 启动服务（端口 8000）
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. Android 客户端

1. 用 Android Studio 打开 `client/` 目录
2. 等待 Gradle 同步完成
3. 启动 Android 模拟器，点击 **Run ▶**
4. 模拟器通过 `http://10.0.2.2:8000` 访问后端（= 宿主机 localhost:8000）

> **真机调试**：将 `RetrofitClient.kt` 中的 `BASE_URL` 改为电脑局域网 IP，手机和电脑需在同一 WiFi。

### 3. 验证后端接口

```bash
# 健康检查
curl http://localhost:8000/health

# 流式对话（SSE）
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"推荐一款抗初老精华"}'

# 商品详情（含 FAQ + 用户评价）
curl http://localhost:8000/api/products/p_beauty_001
```

---

## SSE 事件协议

客户端严格按事件类型渲染，**不从模型文本中解析结构化数据**（防幻觉）：

| 事件名 | 数据格式 | 触发时机 |
|--------|---------|---------|
| `delta` | `{"text": "..."}` | AI 回复文字片段（逐字推送） |
| `product_cards` | `{"products": [...]}` | RAG 检索到匹配商品 |
| `cart_update` | `{"action": "add", ...}` | 识别到加购意图 |
| `done` | `{"session_id": "..."}` | 本次流结束 |

---

## 数据处理

```bash
# 从原始 JSON 生成 products.jsonl（RAG 检索用）
python3 data/scripts/import_products.py \
  --raw-dir data/ecommerce_agent_dataset \
  --output data/processed/products.jsonl

# 构建文本索引
python3 data/scripts/build_index.py \
  --products data/processed/products.jsonl \
  --output data/processed/text_index.json
```

若未运行数据处理脚本，后端会自动使用内置 Demo 商品保证接口可用。

---

## 依赖清单

详见 [DEPENDENCIES.md](./DEPENDENCIES.md)。

---

## 技术文档

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 整体架构设计 |
| [docs/client_design.md](docs/client_design.md) | Android 客户端设计方案 |
| [docs/api.md](docs/api.md) | 后端接口文档 |
| [docs/rag_design.md](docs/rag_design.md) | RAG 链路设计 |
| [docs/deployment.md](docs/deployment.md) | 部署说明 |
| [docs/demo_script.md](docs/demo_script.md) | 3-5 分钟演示脚本 |
