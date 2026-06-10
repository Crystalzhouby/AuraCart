# AuraCart — 智能导购 AI Agent

基于 **LangGraph + RAG + SSE** 的多模态电商智能导购系统。
Android 原生 App (Kotlin) + FastAPI 后端，支持流式对话、商品卡片渲染、购物车管理。

---

## 技术选型

| 层级 | 技术 | 说明 |
|------|------|------|
| 客户端 | Android + Kotlin | MVVM 架构，SSE 流式渲染，RecyclerView 多类型消息 |
| 后端 | FastAPI + Python 3.12 | LangGraph 5 节点 Agent 工作流，pgvector 向量检索 |
| 数据库 | PostgreSQL 14+ | pgvector 语义搜索 + zhparser 中文分词关键词搜索 |
| 大模型 | OpenAI 兼容接口 | 豆包 Seed-2.0-lite 等，通过 config.yaml 配置 |
| 数据 | JSON + 图片 | 4 品类 × 25 商品 = 100 条，含 SKU/FAQ/评价 |

---

## 项目结构

```text
AI-Agent-Ecom-Guide/
├── client/                              # Android 客户端 (Kotlin, MVVM)
│   └── app/src/main/java/com/ecomguide/
│       ├── model/Models.kt              # 数据模型 (ApiProduct, MessageItem, SSE 事件)
│       ├── network/
│       │   ├── ChatStreamClient.kt      # OkHttp SSE 长连接
│       │   ├── RetrofitClient.kt        # REST API + 图片路径解析
│       │   └── ApiService.kt            # Retrofit 接口定义
│       ├── repository/
│       │   ├── CartRepository.kt        # 购物车状态
│       │   └── DemoProducts.kt          # Demo 商品数据
│       └── ui/
│           ├── MainActivity.kt          # 主容器 (DrawerLayout + Toolbar)
│           ├── chat/ChatFragment.kt     # 聊天页 (RecyclerView + 输入框)
│           ├── chat/ChatViewModel.kt    # 核心状态容器 (SSE → MessageItem)
│           ├── detail/                  # 商品详情 (全屏/半屏/品类落地页)
│           ├── cart/CartActivity.kt     # 购物车
│           └── sidebar/                 # 侧边栏 (历史对话/消息/订单)
├── server/                              # FastAPI 后端
│   ├── run.py                           # 启动入口
│   ├── config.yaml                      # 运行时配置 (LLM/Embedding/DB)
│   ├── app/
│   │   ├── main.py                      # FastAPI 入口 + lifespan
│   │   ├── config.py                    # YAML → Pydantic 配置加载
│   │   ├── database.py                  # SQLAlchemy 异步引擎
│   │   ├── api/                         # 路由 (search, products, conversation, admin)
│   │   ├── agent/
│   │   │   ├── state.py                 # AgentState TypedDict
│   │   │   ├── graph.py                 # LangGraph StateGraph + 条件边
│   │   │   ├── memory.py                # 会话记忆 (session_memory)
│   │   │   ├── nodes/                   # 5 节点: Router → Extraction/Scenario → Retrieval → OptionGen
│   │   │   ├── prompts/                 # LLM 系统提示词 (6 个)
│   │   │   └── utils/stream_json.py     # 流式 JSON 字段解析
│   │   ├── models/                      # SQLAlchemy ORM (8 个模型)
│   │   ├── services/                    # 核心服务 (LLM, Embedding, Retriever, Sync, Import)
│   │   ├── schemas/                     # Pydantic 响应模型
│   │   └── core/logging.py             # structlog 配置
│   ├── scripts/
│   │   ├── import_data.py               # 数据导入脚本
│   │   └── docker-compose.yml           # PostgreSQL 容器 (pgvector + zhparser)
│   ├── tests/                           # pytest (130+ 用例)
│   ├── alembic/                         # 数据库迁移
│   └── docs/                            # 设计文档 (AGENT_OPT/*)
├── data/
│   └── ecommerce_agent_dataset_/data/   # 原始商品 JSON + 实拍图片 (100 条)
├── docs/
│   ├── backend/API.md                   # 后端接口文档
│   ├── backend/SPEC.md                  # 后端技术规格
│   └── frontend/                        # Android 架构与设计方案
├── delivery/                            # 交付文档
├── DEPENDENCIES.md                      # 全量依赖清单
└── README.md
```

---

## 快速启动

### 1. 后端服务

```bash
# 克隆项目
git clone https://github.com/Crystalzhouby/AI-Agent-Ecom-Guide.git
cd AI-Agent-Ecom-Guide/server

# 创建并激活 conda 环境 (Python 3.12+)
conda create -n AuraCart python=3.12
conda activate AuraCart

# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥 (创建 server/.secrets.yaml)
# embedding:
#   api_key: "your-embedding-api-key"
# llm:
#   api_key: "your-llm-api-key"

# 启动数据库 (需 Docker)
cd scripts
docker compose up -d --build

# 初始化表结构
cd ..
alembic upgrade head

# 导入商品数据
python scripts/import_data.py

# 启动服务 (端口 8000)
python run.py
```

### 2. Android 客户端

1. 用 Android Studio 打开 `client/` 目录
2. 等待 Gradle 同步完成
3. 启动 Android 模拟器，点击 **Run ▶**
4. 模拟器通过 `http://10.0.2.2:8000` 访问后端 (= 宿主机 localhost:8000)

> **真机调试**：将 `RetrofitClient.kt` 中的 `BASE_URL` 改为电脑局域网 IP，手机和电脑需在同一 WiFi。

### 3. 验证后端接口

```bash
# 健康检查
curl http://localhost:8000/health

# 创建会话
curl http://localhost:8000/api/conversation

# SSE 全链路搜索
curl -N "http://localhost:8000/api/search/<conversation_id>?q=推荐一款200元以下的防晒霜"

# 商品详情
curl http://localhost:8000/api/products/p_beauty_001

# 运行测试套件
python -m pytest tests/ -v
```

---

## SSE 事件协议

| 事件名 | 说明 | 触发时机 |
|--------|------|---------|
| `welcome_chat_stream` | 欢迎语流式推送 | 闲聊意图，逐字推送 |
| `welcome` | 欢迎语 | 非流式闲聊回复 |
| `chat_reply` | AI 回复文本 | 品类介绍 / 商品推荐理由 |
| `products` | 商品列表 (id + category) | RAG 检索到匹配商品 |
| `category_intro` / `category_intro_stream` | 品类介绍 | 场景化搜索 |
| `ending` / `ending_stream` | 结束语 | 推荐完成 |
| `next_options` | 追问标签 | 后续推荐选项 |
| `done` | 流结束 | Agent 工作流完成 |
| `error` | 错误信息 | 异常终止 |

---

## 核心架构

### Agent 工作流 (LangGraph 5 节点)

```
START → Router → Extraction / ScenarioGen → Retrieval → OptionGen → END
```

| 节点 | 职责 |
|------|------|
| Router | 统一意图分类 + 回复生成 (chat/explicit/scenario) |
| Extraction | 明确商品需求的品类与约束提取 |
| ScenarioGen | 场景化查询 → 品类确定 |
| Retrieval | 双路检索 (语义 + 关键词) → RRF 融合 → rerank → 推荐理由 |
| OptionGen | 结束语 + 后续推荐选项合并生成 |

### 检索策略

- **语义搜索**：pgvector 余弦相似度
- **关键词搜索**：zhparser 分词 + tsvector/ILIKE
- **结构化过滤**：品牌、品类、价格、库存
- **RRF 多路融合**：异构得分倒数排序融合

---

## 技术文档

| 文档 | 内容 |
|------|------|
| [docs/backend/API.md](docs/backend/API.md) | 后端接口文档 (13 个端点) |
| [docs/backend/SPEC.md](docs/backend/SPEC.md) | 后端技术规格与架构设计 |
| [docs/frontend/architecture.md](docs/frontend/architecture.md) | Android 客户端整体架构 |
| [docs/frontend/client-design.md](docs/frontend/client-design.md) | Android 客户端设计方案 |
| [server/README.md](server/README.md) | 服务端详细启动指南 |
| [DEPENDENCIES.md](DEPENDENCIES.md) | 全量依赖清单 |

---

## 数据覆盖

4 品类 × 25 商品 = 100 个产品：

- 美妆护肤 (p_beauty_001 ~ 025)
- 服装 (p_clothes_001 ~ 025)
- 数码电子 (p_digital_001 ~ 025)
- 食品 (p_food_001 ~ 025)

每个产品含 SKU 变体、营销描述、FAQ、用户评价等完整数据。
