# AuraCart — 智能导购 RAG 系统

用户输入自然语言商品查询（如"推荐一款200元以下的防晒霜"），系统自动拆解意图、多策略检索商品、LLM 生成推荐理由。支持 SSE 流式事件推送。

---

## 1. 前置条件

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.12+ | conda 环境推荐 |
| PostgreSQL | 14+ | 需安装 pgvector 和 zhparser 扩展 |
| Embedding API Key | — | OpenAI 兼容接口（如豆包、阿里云等） |
| LLM API Key | — | OpenAI 兼容接口 |

---

## 2. 安装与启动

### 2.1 环境准备

```bash
# 激活 conda 环境
conda activate AuraCart

# 进入 server 目录（后续所有命令均在此目录下执行）
cd server

# 安装 Python 依赖
pip install -r requirements.txt
```

### 2.2 配置 API 密钥

编辑 `server/config.yaml`，或创建 `server/.secrets.yaml` 设置密钥：

```yaml
# server/.secrets.yaml
embedding:
  api_key: "your-embedding-api-key"

llm:
  api_key: "your-llm-api-key"
```

### 2.3 启动数据库

```bash
cd server/scripts

# 构建并启动 PostgreSQL（含 pgvector + zhparser）
docker compose up -d --build

# 首次启动后，进入容器激活中文分词扩展
docker exec -it pg17-vector-zhparser psql -U postgres -d ecommerce
```

在 psql 中执行：

```sql
CREATE EXTENSION zhparser;
CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l,j WITH simple;
```

### 2.4 初始化表结构

```bash
cd server
alembic upgrade head
```

### 2.5 导入商品数据

```bash
cd server

# 默认导入 data/ecommerce_agent_dataset_/data/ 下全部 JSON
python scripts/import_data.py
```

### 2.6 启动服务

```bash
cd server

python run.py                          # 默认 INFO 日志, 端口 8000
python run.py --log DEBUG              # DEBUG 级别日志
python run.py --port 8080              # 指定端口
python run.py --reload                 # 开发模式热重载
```

---

## 3. API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/conversation` | 创建新会话，返回 conversation_id |
| `GET` | `/api/search/{conversation_id}` | Agent 工作流搜索（SSE 事件流），必填 q 参数 |
| `GET` | `/api/products/{product_id}` | 商品基本信息 |
| `GET` | `/api/products/image/{product_id}` | 商品图片文件 |
| `GET` | `/api/sku/{sku_id}` | SKU 单品详情 |
| `GET` | `/api/products/batch?ids=...` | 批量获取商品基本信息 (≤20) |
| `GET` | `/api/products/image/batch?ids=...` | 批量获取商品图片路径 (≤20) |
| `GET` | `/api/sku/batch?ids=...` | 批量获取 SKU 详情 (≤20) |
| `GET` | `/api/history/{conversation_id}` | 获取会话对话历史 (ChatMessage 表) |
| `GET` | `/api/review/{product_id}` | 获取商品 RAG 知识（营销/FAQ/评价） |
| `GET` | `/api/all_skus/{product_id}` | 获取商品所有活跃 SKU |
| `POST` | `/api/admin/sync` | 手动触发数据增量同步 |

---

## 4. 核心架构

### 4.1 Agent 工作流 (LangGraph 5 节点)

```
START → Router → Extraction / ScenarioGen → Retrieval → OptionGen → END
```

| 节点 | 文件 | 职责 |
|------|------|------|
| Router | `app/agent/nodes/intent_route_agent.py` | 统一意图分类 + 回复生成（chat/explicit/scenario） |
| Extraction | `app/agent/nodes/intent_extract_agent.py` | 明确商品需求的品类与约束提取 |
| ScenarioGen | `app/agent/nodes/scene_generate_agent.py` | 场景化查询 → 品类确定 |
| Retrieval | `app/agent/nodes/product_retrieve_agent.py` | 双路检索（语义 + 关键词）→ RRF 融合 → rerank → 推荐理由 |
| OptionGen | `app/agent/nodes/option_generate_agent.py` | 结束语 + 后续推荐选项合并生成 |

### 4.2 检索策略

- **语义搜索**：pgvector 余弦相似度，理解模糊评价意图
- **关键词搜索**：zhparser 分词 + PostgreSQL tsvector/ILIKE，精确匹配品类/品牌
- **结构化过滤**：品牌、品类、价格、库存精确/范围筛选
- **RRF 多路融合**：异构得分倒数排序融合 → 统一排名

### 4.3 数据覆盖

4 品类 × 25 商品 = 100 个产品：

- 美妆护肤 (p_beauty_001 ~ 025)
- 服装 (p_clothes_001 ~ 025)
- 数码电子 (p_digital_001 ~ 025)
- 食品 (p_food_001 ~ 025)

每个产品含 SKU 变体、营销描述、FAQ、用户评价等完整数据。

---

## 5. 目录结构

```
server/
├── run.py                           # 启动入口
├── config.yaml                      # 运行时配置
├── requirements.txt                 # Python 依赖
├── app/
│   ├── main.py                      # FastAPI 入口 + lifespan
│   ├── config.py                    # YAML → Pydantic 配置加载
│   ├── database.py                  # SQLAlchemy 异步引擎
│   ├── api/
│   │   ├── search.py                # /api/search SSE 搜索路由
│   │   ├── get_product_info.py      # 商品/图片/SKU/历史/评价查询路由
│   │   ├── get_conversation.py      # /api/conversation 会话管理路由
│   │   └── admin.py                 # /api/admin 后台管理路由
│   ├── agent/
│   │   ├── state.py                 # AgentState TypedDict 定义
│   │   ├── graph.py                 # StateGraph 构建 + 条件边
│   │   ├── memory.py                # 会话记忆 (session_memory)
│   │   ├── nodes/
│   │   │   ├── intent_route_agent.py
│   │   │   ├── intent_extract_agent.py
│   │   │   ├── scene_generate_agent.py
│   │   │   ├── product_retrieve_agent.py
│   │   │   └── option_generate_agent.py
│   │   ├── prompts/
│   │   │   ├── intent_router_prompt.py
│   │   │   ├── intent_extract_prompt.py
│   │   │   ├── scene_generate_prompt.py
│   │   │   ├── category_introduct_prompt.py
│   │   │   ├── product_recommendation_prompt.py
│   │   │   └── option_generate_prompt.py
│   │   └── utils/
│   │       └── stream_json.py       # 流式 JSON 字段解析
│   ├── models/
│   │   ├── product.py               # Product
│   │   ├── sku.py                   # Sku
│   │   ├── chat_message.py          # ChatMessage
│   │   ├── conversation.py          # Conversation
│   │   ├── product_review.py        # ProductReview (pgvector)
│   │   ├── product_marketing.py     # ProductMarketing
│   │   ├── product_faq.py           # ProductFaq
│   │   └── user_review.py           # UserReview
│   ├── services/
│   │   ├── llm_service.py           # LLM 调用封装
│   │   ├── embedding_service.py     # Embedding 调用封装
│   │   ├── retriever_service.py     # 多路检索 + RRF 融合
│   │   ├── sync_service.py          # 增量数据同步
│   │   └── import_data_service.py   # 初始数据导入
│   ├── schemas/                     # Pydantic 响应模型
│   └── core/
│       └── logging.py               # structlog 配置
├── scripts/
│   ├── import_data.py               # 数据导入脚本
│   └── docker-compose.yml           # PostgreSQL 容器配置
├── docs/                            # 设计文档 (AGENT_OPT/*)
├── tests/                           # pytest (130+ 用例)
├── alembic/                         # 数据库迁移
│   └── versions/
└── log/                             # 应用日志输出目录
```

---

## 6. 快速验证

```bash
# 健康检查
curl http://localhost:8000/health

# 创建会话
curl http://localhost:8000/api/conversation

# SSE 全链路搜索
curl -N "http://localhost:8000/api/search/<conversation_id>?q=推荐一款200元以下的防晒霜"

# 商品详情
curl http://localhost:8000/api/products/p_beauty_001

# 批量查询
curl "http://localhost:8000/api/products/batch?ids=p_beauty_001,p_beauty_002"

# 运行测试套件
python -m pytest tests/ -v
```
