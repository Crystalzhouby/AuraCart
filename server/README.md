# AuraCart — 智能导购 RAG 系统

用户输入自然语言商品查询（如"推荐一款200元以下的防晒霜"），系统自动拆解意图、多策略检索商品、LLM 生成推荐理由并通过 SSE 流式返回。

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

`config.yaml` 中的其他配置项（数据库地址、模型名称、超时时间等）一般无需修改。

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

更多数据库操作（停止/重启/清空）见 `server/scripts/operation.md`。

### 2.4 初始化表结构

```bash
cd server
alembic upgrade head
```

### 2.5 导入商品数据

```bash
cd server

# 默认导入 ecommerce_agent_dataset/data/ 下全部 JSON
python scripts/import_data.py

# 或指定数据目录
python scripts/import_data.py ../ecommerce_agent_dataset/data
```

### 2.6 启动服务

```bash
cd server

python run.py                          # 默认 INFO 日志, 端口 8000
python run.py --log DEBUG              # DEBUG 日志级别
python run.py --port 8080              # 指定端口
python run.py --reload                 # 开发模式热重载
```

---

## 3. 功能概览

### 3.1 API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/search?q=...&top_k=10` | JSON 向量检索（不走 LLM） |
| `GET` | `/api/search/stream?q=...` | SSE 全链路 RAG：查询解析 → 检索 → LLM 推荐 |
| `GET` | `/api/products/{product_id}` | 商品基本信息（无 SKU 列表、无图片） |
| `GET` | `/api/products/image/{product_id}` | 商品图片文件 |
| `GET` | `/api/sku/{sku_id}` | SKU 单品详情 |
| `POST` | `/api/admin/sync` | 手动触发数据增量同步 |

### 3.2 核心功能

1. **向量语义搜索** — 基于 pgvector 余弦相似度，理解"保湿效果好""充电速度快"等模糊评价意图
2. **中文关键词全文搜索** — 基于 zhparser 分词 + PostgreSQL tsvector，精确匹配品类/品牌关键词
3. **结构化过滤** — 品牌、品类、价格、库存等字段的精确/范围/排除筛选
4. **RRF 多路融合** — 将语义搜索和关键词搜索的异构得分通过倒数排序融合合并为统一排名
5. **LLM 查询意图拆解** — 将自然语言查询自动分解为多条子查询，智能分配检索策略
6. **LLM 推荐生成** — 基于检索到的商品信息，流式输出导购推荐文案
7. **增量数据同步** — 后台定时轮询，将商品/营销/FAQ/评价变更自动更新到向量库

### 3.3 数据覆盖

4 个品类 × 25 个商品 = 100 个产品：

- 美妆个护（p_beauty_001 ~ 025）
- 服装（p_clothes_001 ~ 025）
- 数码电子（p_digital_001 ~ 025）
- 食品（p_food_001 ~ 025）

每个产品含 SKU 变体、营销描述、FAQ、用户评价等完整数据。

---

## 4. 快速验证

```bash
# 健康检查
curl http://localhost:8000/health

# JSON 向量检索
curl "http://localhost:8000/api/search?q=防晒霜&top_k=5"

# SSE 全链路检索
curl -N "http://localhost:8000/api/search/stream?q=推荐一款200元以下的防晒霜"

# 商品详情
curl http://localhost:8000/api/products/PROD001

# 运行自动化验证脚本
cd server
python test_demo.py
```

### 运行测试套件

```bash
cd server
python -m pytest tests/ -v
```

---

## 5. 目录结构

```
AuraCart/
├── delivery/                    # 技术说明文档
├── ecommerce_agent_dataset/     # 100 个商品 JSON + 100 张图片
│   ├── data/                    # p_beauty_*.json, p_clothes_*.json, ...
│   └── images/                  # 对应产品图片 .jpg
├── server/                      # 主应用
│   ├── run.py                   # 启动入口
│   ├── config.yaml              # 运行时配置
│   ├── requirements.txt         # Python 依赖
│   ├── test_demo.py             # 接口冒烟测试脚本
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + lifespan
│   │   ├── config.py            # YAML → Pydantic 配置加载
│   │   ├── database.py          # SQLAlchemy 异步引擎
│   │   ├── api/                 # 路由层 (search/products/admin)
│   │   ├── models/              # 6 张 ORM 表
│   │   ├── schemas/             # Pydantic 响应结构
│   │   ├── services/            # 业务逻辑 (embedding/llm/retriever/sync)
│   │   ├── rag/                 # RAG 管线 (prompt/merger/generator)
│   │   └── core/                # 基础设施 (logging)
│   ├── scripts/                 # Docker/导入脚本
│   ├── tests/                   # 38 个 pytest 测试
│   ├── alembic/                 # 数据库迁移
│   └── docs/                    # 设计/方案文档
```
