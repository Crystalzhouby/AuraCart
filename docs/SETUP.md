# AuraCart — 项目安装与启动指南

## 1. 环境要求

| 依赖 | 版本要求 | 用途 |
|------|---------|------|
| Python | 3.12+ | 服务运行环境 |
| PostgreSQL | 17+ | 主数据库 + pgvector 向量存储 |
| Docker（可选） | 24+ | 容器化一键部署 |

**PostgreSQL 扩展要求：**
- `pgvector` — 向量相似度搜索
- `zhparser` — 中文全文分词（关键词检索）

---

## 2. 快速开始（Docker Compose）

```bash
# 1. 从项目根目录启动全部服务
docker compose up -d --build

# 2. 进入 PostgreSQL 激活中文分词（仅首次）
docker exec -it pg17-vector-zhparser psql -U postgres -d ecommerce
```

在 psql 中执行：
```sql
CREATE EXTENSION zhparser;
CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l,j WITH simple;
\q
```

```bash
# 3. 初始化表结构
docker exec -it auracart-server python -m alembic upgrade head

# 4. 导入商品数据
docker exec -it auracart-server python scripts/import_data.py

# 5. 验证服务
curl http://localhost:8000/health
```

**单独启动数据库**（沿用原 README 流程）：
```bash
cd server/scripts && docker compose up -d --build
```

---

## 3. 手动安装

### 3.1 安装 Python 依赖

```bash
cd server
pip install -r requirements.txt
```

### 3.2 配置

项目配置通过 `server/config.yaml` 管理，敏感信息写入 `server/.secrets.yaml`：

**config.yaml** — 数据库、模型端点、检索参数：
```yaml
database:
  host: "localhost"
  port: 5432
  user: "postgres"
  password: "123456"
  dbname: "ecommerce"
  vector_dim: 1024

embedding:
  base_url: "https://your-embedding-api.com/v1"
  model: "text-embedding-v4"

llm:
  base_url: "https://your-llm-api.com/v1"
  model: "your-model-id"
  temperature: 0.3
```

**.secrets.yaml** — API 密钥（不纳入版本控制）：
```yaml
embedding:
  api_key: "your-embedding-api-key"

llm:
  api_key: "your-llm-api-key"
```

**Docker 部署时**，可通过环境变量 `DB_HOST` / `DB_PORT` 覆盖数据库连接地址（参见根目录 `.env.example`）。

### 3.3 数据库初始化

```bash
cd server

# 运行数据库迁移
alembic upgrade head

# 导入商品数据
python scripts/import_data.py

# 初始化品类查找表
python scripts/setup_category_lookup.py
```

### 3.4 启动服务

```bash
cd server

# 开发模式
python run.py

# 或直接使用 uvicorn
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 4. 现有 API 一览

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/search?q=...&stream=true` | **核心接口**：SSE 流式 AI 商品推荐（Agent 工作流） |
| `GET` | `/api/search?q=...&stream=false` | JSON 非流式 AI 商品推荐（传统 RAG 管线） |
| `GET` | `/api/products/{product_id}` | 查询单个产品基本信息 |
| `GET` | `/api/products/image/{product_id}` | 获取产品图片 |
| `GET` | `/api/sku/{sku_id}` | 查询单个 SKU 详情 |
| `GET` | `/api/products/batch?ids=p1,p2,...` | 批量查询产品（最多 20 个） |
| `GET` | `/api/products/image/batch?ids=p1,p2,...` | 批量获取产品图片路径 |
| `GET` | `/api/sku/batch?ids=s1,s2,...` | 批量查询 SKU 详情（最多 20 个） |
| `POST` | `/api/admin/sync` | 触发数据同步（重建向量嵌入） |

---

## 5. 核心功能

1. **智能商品搜索** — 自然语言查询经 LLM 拆解为多策略子查询，并行检索 + RRF 融合排序
2. **流式推荐** — SSE 事件流实时推送检索进度、品类推荐理由和最终选项
3. **场景化推荐** — 支持"去海边旅游需要什么"类场景描述，自动拆分为多品类组合检索
4. **对话记忆** — 多轮对话上下文保持，支持 token 截断控制
5. **混合检索** — 语义向量搜索（pgvector） + 中文全文搜索（zhparser） + 结构化过滤
6. **增量数据同步** — 后台自动同步源表变更到向量索引（PostgreSQL 咨询锁防并发）
7. **批量查询** — 支持最多 20 个 ID 的批量产品/SKU 查询
