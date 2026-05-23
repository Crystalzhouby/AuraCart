# AI-Agent-Ecom-Guide

基于 RAG 的多模态电商智能导购 AI Agent。当前仓库先聚焦端到端最小闭环：Android 原生对话页、FastAPI 后端、商品库检索、SSE 流式回复和商品卡片。

## 技术选型

| 层级 | 技术 | 说明 |
| --- | --- | --- |
| 客户端 | Android + Kotlin | 原生 App，对话页、流式渲染、商品卡片 |
| 后端 | FastAPI + SQLite + Chroma | 会话、购物车、商品检索、RAG 编排 |
| 大模型 | Doubao-Seed-2.0-lite | 通过 Ark OpenAI-compatible API 接入 |
| 数据 | JSONL + 商品图片 URL | 50-100 条脱敏商品数据 |

## 项目结构

```text
AI-Agent-Ecom-Guide/
├── client/                 # Android 客户端
├── server/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/            # HTTP/SSE 路由
│   │   ├── core/           # 配置
│   │   ├── schemas/        # 请求、响应、商品、购物车模型
│   │   ├── services/       # RAG、商品库、购物车、模型调用
│   │   └── prompts/        # 系统提示词
│   ├── tests/
│   └── requirements.txt
├── data/                   # 商品数据集、处理脚本与处理结果
├── docs/                   # 架构、接口、RAG、部署、演示文档
├── docker-compose.yml
├── .env.example
└── README.md
```

## 优先级

1. 端到端最小闭环：Android 对话页 -> `/api/chat/stream` -> RAG 检索商品 -> 流式回复 -> 商品卡片。
2. RAG 可靠性：只推荐库内商品，价格/库存/优惠不编造。
3. 加分项做深：多轮上下文 + 反选/排除。
4. 购物车闭环：加购、删除、改数量，体现 Agent 操作结构化数据。

`admin/` 暂不做，先把客户端原生体验、后端 RAG 和流式商品卡片做稳。

## 快速开始

```bash
cp .env.example .env
cd server
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

测试流式接口：

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"推荐一款适合油皮的洗面奶"}'
```

Android 使用 Android Studio 打开 `client/`，模拟器访问后端地址为 `http://10.0.2.2:8000/`。

## 数据处理

```bash
python3 data/scripts/import_products.py --raw-dir data/ecommerce_agent_dataset --output data/processed/products.jsonl
python3 data/scripts/build_index.py --products data/processed/products.jsonl --output data/processed/text_index.json
```

更完整的数据目录约定与脚本说明见 `data/README.md`。

如果还没有正式数据，后端会使用内置 demo 商品，保证 API 能先跑通。

## 流式事件

SSE 事件拆成 `delta`、`product_cards`、`cart_update`、`done`。客户端只根据事件类型渲染，不从大模型文本里解析商品。
