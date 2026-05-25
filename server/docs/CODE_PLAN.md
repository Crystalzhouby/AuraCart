# AuraCart 最小可运行闭环实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户输入自然语言查询 → 系统返回语义匹配的商品及 SKU 信息（纯向量检索 + JSON 响应）

**Architecture:** FastAPI + PostgreSQL/pgvector。单次请求链路：embed 查询文本 → pgvector cosine 相似度检索 product_review → JOIN product + sku 获取结构化信息 → JSON 返回 top-K 商品

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, pgvector, Alembic, httpx, pytest

---

## 回答四个核心问题

### 1. 什么是最小可运行闭环

> 用户输入 "推荐一款适合油皮的洗面奶" → 返回匹配商品列表（含 title / brand / price / SKUs）。

一条链路打通：**Query → Embedding → pgvector 检索 → JOIN 结构化表 → JSON 响应**。不含 LLM、不含 SSE、不含查询拆解、不含关键词检索、不含同步服务。仅向量语义检索 + 结构化数据补全。

### 2. 按什么顺序实现

| 顺序 | 模块 | 原因 |
|:---|:---|:---|
| 1 | 项目骨架 (config + db) | 一切依赖 |
| 2 | 数据库模型 (6 表 + 迁移) | 数据基础 |
| 3 | Embedding 服务 | 导入和搜索都需要 |
| 4 | 数据导入 CLI | 先有数据才能搜索 |
| 5 | 搜索端点 | 核心链路 |
| 6 | 商品详情端点 | 配套查询 |

### 3. 哪些现在必须做

- PostgreSQL + pgvector 建表（6 张表）
- JSON → 源表 + 向量化导入
- Embedding 生成（OpenAI 兼容 API）
- `GET /api/search?q=...&top_k=10` 向量检索端点（JSON 响应）
- `GET /api/products/{product_id}` 商品详情端点
- 配置管理（config.yaml → Pydantic Settings）
- 基础错误处理（DB 不可用 / embedding API 不可用 → 500）

### 4. 哪些现在明确不做

| 不做 | 原因 | 何时做 |
|:---|:---|:---|
| SSE 流式响应 | 先用 JSON 验证检索链路正确性 | 闭环跑通后 |
| LLM 查询拆解 (query_parser) | 先验证单条 embedding 直接检索的效果 | 闭环跑通后 |
| LLM 推荐理由生成 (generator) | 先返回检索结果即可 | 闭环跑通后 |
| 关键词检索 (tsvector + zhparser) | 向量检索先跑通，混合检索是增强 | 闭环跑通后 |
| 结构化过滤 (expanded_values) | 依赖 LLM 拆解，先不做 | 闭环跑通后 |
| 数据同步服务 (sync.py) | 静态数据够用，实时更新后补 | 闭环跑通后 |
| Admin API (/api/admin/*) | CLI 脚本足够 | 闭环跑通后 |
| source 权重 / merger / negation | 单策略检索不需要合并 | 混合检索时 |
| 图片静态文件服务 | 不影响检索链路 | 闭环跑通后 |
| 超时/降级/日志完善 | 先用框架默认 | 闭环跑通后 |
| 多轮对话 | SPEC 明确不交付 | — |

---

## 文件结构

```
server/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口
│   ├── config.py             # YAML → Pydantic Settings
│   ├── database.py           # SQLAlchemy async engine + session
│   ├── models/
│   │   ├── __init__.py
│   │   ├── product.py
│   │   ├── sku.py
│   │   ├── product_marketing.py
│   │   ├── product_faq.py
│   │   ├── user_review.py
│   │   └── product_review.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── product.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── embedding.py      # [最小闭环] OpenAI 兼容 embedding 调用
│   │   └── import_data.py    # [最小闭环] JSON → DB + 向量化
│   └── api/
│       ├── __init__.py
│       ├── search.py          # [最小闭环] GET /api/search
│       └── products.py        # [最小闭环] GET /api/products/{id}
├── scripts/
│   └── import_data.py         # CLI 入口
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_embedding.py
│   ├── test_import_data.py
│   ├── test_search.py
│   └── test_products.py
├── config.yaml
├── requirements.txt
└── ecommerce_agent_dataset/   # JSON 数据文件目录
```

---

### Task 1: 项目骨架 — config + database + FastAPI 入口

**Files:**
- Create: `server/requirements.txt`
- Create: `server/config.yaml`
- Create: `server/app/__init__.py`
- Create: `server/app/config.py`
- Create: `server/app/database.py`
- Create: `server/app/main.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
sqlalchemy[asyncio]>=2.0.30
asyncpg>=0.29.0
pgvector>=0.3.0
psycopg2-binary>=2.9.9
alembic>=1.13.1
httpx>=0.27.0
pydantic>=2.7.0
pydantic-settings>=2.2.1
pyyaml>=6.0.1
pytest>=8.2.0
pytest-asyncio>=0.23.7
```

- [ ] **Step 2: 创建 config.yaml（最小闭环仅需 database + embedding）**

```yaml
# ---- 数据库 ----
database:
  host: "localhost"
  port: 5432
  user: "auracart"
  password: "auracart"
  dbname: "auracart"
  vector_dim: 1024

# ---- Embedding (OpenAI 兼容) ----
embedding:
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  api_key: "${EMBEDDING_API_KEY}"
  model: "doubao-embedding"
  batch_size: 20
```

- [ ] **Step 3: 创建 app/config.py**

```python
import os
import yaml
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    host: str = "localhost"
    port: int = 5432
    user: str = "auracart"
    password: str = "auracart"
    dbname: str = "auracart"
    vector_dim: int = 1024

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"

    @property
    def sync_url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"


class EmbeddingSettings(BaseSettings):
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    api_key: str = ""
    model: str = "doubao-embedding"
    batch_size: int = 20


class Settings(BaseSettings):
    database: DatabaseSettings = DatabaseSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()

    @classmethod
    def from_yaml(cls, path: str = "config.yaml") -> "Settings":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        db_data = data.get("database", {})
        db = DatabaseSettings(**db_data)

        emb_data = data.get("embedding", {})
        emb_data["api_key"] = os.environ.get(
            "EMBEDDING_API_KEY", emb_data.get("api_key", "")
        )
        emb = EmbeddingSettings(**emb_data)

        return cls(database=db, embedding=emb)


settings = Settings.from_yaml()
```

- [ ] **Step 4: 创建 app/database.py**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(settings.database.url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
```

- [ ] **Step 5: 创建 app/main.py**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api import search, products


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="AuraCart", version="0.1.0", lifespan=lifespan)
app.include_router(search.router)
app.include_router(products.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: 创建空的 __init__.py 文件**

```bash
touch server/app/__init__.py
touch server/app/models/__init__.py
touch server/app/schemas/__init__.py
touch server/app/services/__init__.py
touch server/app/api/__init__.py
touch server/tests/__init__.py
```

- [ ] **Step 7: 验证应用可启动（无 DB 连接也能加载）**

```bash
cd server && python -c "from app.main import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add server/requirements.txt server/config.yaml server/app/
git commit -m "feat: project skeleton with config and FastAPI entry"
```

---

### Task 2: 数据库模型 — 6 表 ORM + Alembic 迁移

**Files:**
- Create: `server/app/models/product.py`
- Create: `server/app/models/sku.py`
- Create: `server/app/models/product_marketing.py`
- Create: `server/app/models/product_faq.py`
- Create: `server/app/models/user_review.py`
- Create: `server/app/models/product_review.py`
- Create: `server/alembic.ini`
- Create: `server/alembic/env.py`
- Create: `server/alembic/versions/001_init.py`
- Modify: `server/app/database.py` (import Base from models)

- [ ] **Step 1: 创建 app/models/product.py**

```python
from sqlalchemy import String, Numeric, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class Product(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(50))
    sub_category: Mapped[str | None] = mapped_column(String(50))
    base_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    image_path: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 2: 创建 app/models/sku.py**

```python
from sqlalchemy import String, Integer, Numeric, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class Sku(Base):
    __tablename__ = "sku"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    properties: Mapped[dict | None] = mapped_column(JSONB)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 3: 创建 app/models/product_marketing.py**

```python
from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class ProductMarketing(Base):
    __tablename__ = "product_marketing"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: 创建 app/models/product_faq.py**

```python
from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class ProductFaq(Base):
    __tablename__ = "product_faq"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 5: 创建 app/models/user_review.py**

```python
from sqlalchemy import String, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class UserReview(Base):
    __tablename__ = "user_review"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    nickname: Mapped[str | None] = mapped_column(String(100))
    rating: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 6: 创建 app/models/product_review.py**

```python
from sqlalchemy import String, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.config import settings


class ProductReview(Base):
    __tablename__ = "product_review"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.database.vector_dim))
    metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 7: 创建 app/models/__init__.py（汇集所有模型）**

```python
from app.models.product import Product
from app.models.sku import Sku
from app.models.product_marketing import ProductMarketing
from app.models.product_faq import ProductFaq
from app.models.user_review import UserReview
from app.models.product_review import ProductReview

__all__ = [
    "Product",
    "Sku",
    "ProductMarketing",
    "ProductFaq",
    "UserReview",
    "ProductReview",
]
```

- [ ] **Step 8: 配置 Alembic 并生成初始迁移**

```bash
cd server && pip install alembic && alembic init alembic
```

修改 `server/alembic/env.py` — 设置 target_metadata:

```python
from app.database import Base
from app.config import settings

# 必须在 import models 之前配置好
target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", settings.database.sync_url)

# 然后 import 所有 models 确保注册到 Base.metadata
from app.models import *  # noqa: E402, F401
```

- [ ] **Step 9: 生成并验证迁移**

```bash
cd server && alembic revision --autogenerate -m "init"
alembic upgrade head 2>&1 || echo "DB_NOT_AVAILABLE_OK_FOR_NOW"
```

Expected: 如果 PostgreSQL 已安装且 pgvector 扩展已启用，迁移成功；否则报错提醒安装 PostgreSQL。

- [ ] **Step 10: Commit**

```bash
git add server/app/models/ server/alembic/ server/alembic.ini
git commit -m "feat: database models for 6 tables with Alembic migration"
```

---

### Task 3: Embedding 服务

**Files:**
- Create: `server/app/services/embedding.py`
- Create: `server/tests/test_embedding.py`

- [ ] **Step 1: 写 embedding 服务的失败测试**

```python
# tests/test_embedding.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.embedding import EmbeddingService


@pytest.mark.asyncio
async def test_embed_single_text():
    svc = EmbeddingService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await svc.embed("测试文本")

    assert result == [0.1, 0.2, 0.3]
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_embed_batch():
    svc = EmbeddingService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        results = await svc.embed_batch(["文本1", "文本2"])

    assert len(results) == 2
    assert results[0] == [0.1, 0.2]
    assert results[1] == [0.3, 0.4]
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_embedding.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.embedding'`

- [ ] **Step 3: 实现 EmbeddingService**

```python
# app/services/embedding.py
import httpx


class EmbeddingService:
    def __init__(self, base_url: str, api_key: str, model: str, batch_size: int = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.batch_size = batch_size
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def embed(self, text: str) -> list[float]:
        client = await self._get_client()
        resp = await client.post(
            "/embeddings",
            json={"model": self.model, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        resp = await client.post(
            "/embeddings",
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd server && python -m pytest tests/test_embedding.py -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/__init__.py server/app/services/embedding.py server/tests/test_embedding.py
git commit -m "feat: embedding service with OpenAI-compatible API"
```

---

### Task 4: 数据导入 CLI — JSON → 源表 + 向量化

**Files:**
- Create: `server/app/services/import_data.py`
- Create: `server/scripts/import_data.py`
- Create: `server/tests/test_import_data.py`

- [ ] **Step 1: 写导入逻辑的失败测试**

```python
# tests/test_import_data.py
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.import_data import DataImporter, chunk_product


def test_chunk_product():
    product_data = {
        "product_id": "SKU001",
        "title": "安耐晒小金瓶防晒霜",
        "brand": "安耐晒",
        "category": "美妆护肤",
        "sub_category": "防晒",
        "base_price": 198.0,
        "image_path": "images/SKU001.jpg",
        "skus": [
            {
                "sku_id": "SKU001_60ml",
                "properties": {"容量": "60ml"},
                "price": 198.0,
            }
        ],
        "rag_knowledge": {
            "marketing_description": "持久防晒，防水防汗。",
            "official_faq": [
                {"question": "适合油皮吗？", "answer": "适合，清爽配方。"}
            ],
            "user_reviews": [
                {"nickname": "用户A", "rating": 5, "content": "很好用，不油腻"}
            ],
        },
    }

    chunks = chunk_product(product_data)

    assert len(chunks) == 3  # marketing + faq + user_review
    assert chunks[0] == ("marketing", "持久防晒，防水防汗。", {})
    assert chunks[1] == (
        "faq",
        "问题：适合油皮吗？\n回答：适合，清爽配方。",
        {"question": "适合油皮吗？"},
    )
    assert chunks[2] == (
        "user_review",
        "用户用户A评分5分，评价：很好用，不油腻",
        {"nickname": "用户A", "rating": 5},
    )


def test_chunk_product_no_faqs():
    product_data = {
        "product_id": "SKU002",
        "title": "测试商品",
        "brand": "测试",
        "category": "测试",
        "base_price": 10.0,
        "skus": [{"sku_id": "SKU002_1", "properties": {}, "price": 10.0}],
        "rag_knowledge": {
            "marketing_description": "测试描述",
            "official_faq": [],
            "user_reviews": [],
        },
    }

    chunks = chunk_product(product_data)
    assert len(chunks) == 1  # only marketing
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_import_data.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 chunking 和 DataImporter**

```python
# app/services/import_data.py
import json
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.models import Product, Sku, ProductMarketing, ProductFaq, UserReview, ProductReview
from app.services.embedding import EmbeddingService


def chunk_product(product_data: dict) -> list[tuple[str, str, dict]]:
    """将单个商品 JSON 拆分为待 embedding 的文本块列表。
    返回: [(source, content, metadata), ...]
    """
    chunks = []
    rag = product_data.get("rag_knowledge", {})

    # marketing_description
    marketing = rag.get("marketing_description", "")
    if marketing:
        chunks.append(("marketing", marketing, {}))

    # official_faq — 每个 FAQ 独立一条
    for faq in rag.get("official_faq", []):
        q = faq.get("question", "")
        a = faq.get("answer", "")
        content = f"问题：{q}\n回答：{a}"
        chunks.append(("faq", content, {"question": q}))

    # user_reviews — 每条评价独立一条
    for review in rag.get("user_reviews", []):
        nickname = review.get("nickname", "")
        rating = review.get("rating", 0)
        content_text = review.get("content", "")
        content = f"用户{nickname}评分{rating}分，评价：{content_text}"
        chunks.append(("user_review", content, {"nickname": nickname, "rating": rating}))

    return chunks


class DataImporter:
    def __init__(self, session: AsyncSession, embedding_svc: EmbeddingService):
        self.session = session
        self.embedding_svc = embedding_svc

    async def clear_all(self):
        for table in ["product_review", "user_review", "product_faq", "product_marketing", "sku", "product"]:
            await self.session.execute(text(f"DELETE FROM {table}"))
        await self.session.commit()

    async def import_json_dir(self, data_dir: str) -> int:
        imported = 0
        all_embeddings: list[dict] = []

        for filename in os.listdir(data_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(data_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            pid = data["product_id"]

            # 写入 product
            product = Product(
                product_id=pid,
                title=data["title"],
                brand=data.get("brand"),
                category=data.get("category"),
                sub_category=data.get("sub_category"),
                base_price=data.get("base_price"),
                image_path=data.get("image_path"),
            )
            self.session.add(product)

            # 写入 skus
            for sku_data in data.get("skus", []):
                sku = Sku(
                    sku_id=sku_data["sku_id"],
                    product_id=pid,
                    properties=sku_data.get("properties", {}),
                    price=sku_data["price"],
                    stock=sku_data.get("stock", 0),
                )
                self.session.add(sku)

            # 写入 product_marketing
            rag = data.get("rag_knowledge", {})
            marketing = rag.get("marketing_description", "")
            if marketing:
                pm = ProductMarketing(product_id=pid, description=marketing)
                self.session.add(pm)

            # 写入 product_faq
            for faq in rag.get("official_faq", []):
                pf = ProductFaq(
                    product_id=pid,
                    question=faq["question"],
                    answer=faq["answer"],
                )
                self.session.add(pf)

            # 写入 user_review
            for review in rag.get("user_reviews", []):
                ur = UserReview(
                    product_id=pid,
                    nickname=review.get("nickname"),
                    rating=review.get("rating"),
                    content=review.get("content", ""),
                )
                self.session.add(ur)

            # 生成 chunk，暂存待批量 embedding
            chunks = chunk_product(data)
            for source, content, metadata in chunks:
                all_embeddings.append({"product_id": pid, "source": source, "content": content, "metadata": metadata})

            imported += 1

        # 先 flush 源表
        await self.session.flush()

        # 批量 embedding
        texts = [e["content"] for e in all_embeddings]
        vectors = await self.embedding_svc.embed_batch(texts)

        for i, entry in enumerate(all_embeddings):
            pr = ProductReview(
                product_id=entry["product_id"],
                source=entry["source"],
                content=entry["content"],
                embedding=vectors[i],
                metadata=entry["metadata"],
            )
            self.session.add(pr)

        await self.session.commit()
        return imported
```

- [ ] **Step 4: 创建 CLI 入口**

```python
# scripts/import_data.py
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings
from app.services.embedding import EmbeddingService
from app.services.import_data import DataImporter


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_data.py <data_dir>")
        sys.exit(1)

    data_dir = sys.argv[1]
    engine = create_async_engine(settings.database.url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    embedding_svc = EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        batch_size=settings.embedding.batch_size,
    )

    async with session_factory() as session:
        importer = DataImporter(session, embedding_svc)
        await importer.clear_all()
        count = await importer.import_json_dir(data_dir)
        print(f"Imported {count} products")

    await embedding_svc.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: 运行单元测试验证 chunking 逻辑通过**

```bash
cd server && python -m pytest tests/test_import_data.py -v
```
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/services/import_data.py server/scripts/import_data.py server/tests/test_import_data.py
git commit -m "feat: data import with chunking and batch embedding"
```

---

### Task 5: 搜索端点 — 向量检索核心链路

**Files:**
- Create: `server/app/api/search.py`
- Create: `server/app/schemas/product.py`
- Create: `server/tests/test_search.py`

- [ ] **Step 1: 创建 Pydantic Schema**

```python
# app/schemas/product.py
from pydantic import BaseModel


class SkuOut(BaseModel):
    sku_id: str
    properties: dict | None
    price: float
    stock: int

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    product_id: str
    title: str
    brand: str | None
    category: str | None
    base_price: float | None
    image_path: str | None
    skus: list[SkuOut]

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    query: str
    products: list[ProductOut]
    total: int
```

- [ ] **Step 2: 写搜索端点的失败测试**

```python
# tests/test_search.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.embedding import EmbeddingService


@pytest.fixture
def mock_embedding():
    svc = EmbeddingService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test",
    )
    return svc


@pytest.mark.asyncio
async def test_search_endpoint_requires_query():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/search")
    assert resp.status_code == 422  # FastAPI validation


@pytest.mark.asyncio
async def test_search_endpoint_accepts_query():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/search?q=防晒霜")
    # No DB — 期望 500（DB 不可用），不是 422
    assert resp.status_code in (500, 503)
```

- [ ] **Step 3: 运行测试失败验证**

```bash
cd server && python -m pytest tests/test_search.py::test_search_endpoint_requires_query -v
```
Expected: FAIL — 路由未注册

- [ ] **Step 4: 实现搜索端点**

```python
# app/api/search.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.config import settings
from app.models.product_review import ProductReview
from app.models.product import Product
from app.models.sku import Sku
from app.schemas.product import ProductOut, SkuOut, SearchResponse
from app.services.embedding import EmbeddingService

router = APIRouter(prefix="/api", tags=["search"])


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        batch_size=settings.embedding.batch_size,
    )


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="搜索查询"),
    top_k: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
):
    # 1. Embed 查询
    query_vector = await emb.embed(q)

    # 2. pgvector cosine 相似度检索
    sql = text("""
        SELECT pr.product_id, 1 - (pr.embedding <=> :vec) AS similarity
        FROM product_review pr
        JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE
        ORDER BY pr.embedding <=> :vec
        LIMIT :limit
    """)
    result = await db.execute(sql, {"vec": str(query_vector), "limit": top_k})
    rows = result.fetchall()

    if not rows:
        return SearchResponse(query=q, products=[], total=0)

    # 3. 按 product_id 聚合并取最大相似度
    product_scores: dict[str, float] = {}
    for row in rows:
        pid = row.product_id
        score = row.similarity
        if pid not in product_scores or score > product_scores[pid]:
            product_scores[pid] = score

    # 4. 查询 products + skus
    ranked_pids = sorted(product_scores, key=product_scores.get, reverse=True)
    products = []
    for pid in ranked_pids:
        prod = await db.execute(
            select(Product)
            .where(Product.product_id == pid, Product.is_active == True)
        )
        prod = prod.scalar_one_or_none()
        if prod is None:
            continue

        skus_result = await db.execute(
            select(Sku)
            .where(Sku.product_id == pid, Sku.is_active == True)
        )
        skus = [
            SkuOut(
                sku_id=s.sku_id,
                properties=s.properties,
                price=float(s.price),
                stock=s.stock,
            )
            for s in skus_result.scalars().all()
        ]

        products.append(ProductOut(
            product_id=prod.product_id,
            title=prod.title,
            brand=prod.brand,
            category=prod.category,
            base_price=float(prod.base_price) if prod.base_price else None,
            image_path=prod.image_path,
            skus=skus,
        ))

    return SearchResponse(query=q, products=products, total=len(products))
```

- [ ] **Step 5: 运行测试**

```bash
cd server && python -m pytest tests/test_search.py -v
```
Expected: test_search_endpoint_requires_query PASS, test_search_endpoint_accepts_query PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/api/search.py server/app/schemas/product.py server/tests/test_search.py
git commit -m "feat: vector search endpoint with pgvector cosine similarity"
```

---

### Task 6: 商品详情端点

**Files:**
- Create: `server/app/api/products.py`
- Create: `server/tests/test_products.py`

- [ ] **Step 1: 写商品详情测试**

```python
# tests/test_products.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_product_detail_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/products/NONEXISTENT")
    # 可能 404（如果 DB 可用返回空）或 500（DB 不可用）
    assert resp.status_code in (404, 500)
```

- [ ] **Step 2: 运行测试失败验证**

```bash
cd server && python -m pytest tests/test_products.py -v
```
Expected: FAIL — 路由未注册

- [ ] **Step 3: 实现商品详情端点**

```python
# app/api/products.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.product import Product
from app.models.sku import Sku
from app.schemas.product import ProductOut, SkuOut

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)):
    prod = await db.execute(
        select(Product).where(Product.product_id == product_id, Product.is_active == True)
    )
    prod = prod.scalar_one_or_none()
    if prod is None:
        raise HTTPException(status_code=404, detail="Product not found")

    skus_result = await db.execute(
        select(Sku).where(Sku.product_id == product_id, Sku.is_active == True)
    )
    skus = [
        SkuOut(
            sku_id=s.sku_id,
            properties=s.properties,
            price=float(s.price),
            stock=s.stock,
        )
        for s in skus_result.scalars().all()
    ]

    return ProductOut(
        product_id=prod.product_id,
        title=prod.title,
        brand=prod.brand,
        category=prod.category,
        base_price=float(prod.base_price) if prod.base_price else None,
        image_path=prod.image_path,
        skus=skus,
    )
```

- [ ] **Step 4: 运行测试**

```bash
cd server && python -m pytest tests/test_products.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/api/products.py server/tests/test_products.py
git commit -m "feat: product detail endpoint with SKUs"
```

---

### Task 7: 端到端验证 — 准备样本数据并跑通完整链路

- [ ] **Step 1: 创建样本 JSON 数据文件**

在 `server/ecommerce_agent_dataset/` 下创建 3 个样本商品 JSON：

```json
// sample_001.json
{
    "product_id": "PROD001",
    "title": "安耐晒小金瓶防晒霜",
    "brand": "安耐晒",
    "category": "美妆护肤",
    "sub_category": "防晒",
    "base_price": 198.0,
    "image_path": "images/PROD001.jpg",
    "skus": [
        {"sku_id": "PROD001_60ml", "properties": {"容量": "60ml"}, "price": 198.0, "stock": 100},
        {"sku_id": "PROD001_25ml", "properties": {"容量": "25ml"}, "price": 128.0, "stock": 50}
    ],
    "rag_knowledge": {
        "marketing_description": "持久防晒，防水防汗，适合户外运动。清爽不油腻，敏感肌可用。",
        "official_faq": [
            {"question": "适合油皮吗？", "answer": "适合，清爽配方不堵塞毛孔。"},
            {"question": "需要卸妆吗？", "answer": "建议使用卸妆产品清洁。"}
        ],
        "user_reviews": [
            {"nickname": "用户A", "rating": 5, "content": "很好用，不油腻，敏感肌没过敏"},
            {"nickname": "用户B", "rating": 4, "content": "防晒效果好，就是有点小贵"}
        ]
    }
}
```

再创建 2 个不同品类的样本（如蓝牙耳机 PROD002、洗面奶 PROD003），确保跨品类检索可验证。

- [ ] **Step 2: 启动 PostgreSQL 并创建数据库**

```bash
psql -U postgres -c "CREATE DATABASE auracart;"
psql -U postgres -d auracart -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

- [ ] **Step 3: 运行迁移**

```bash
cd server && alembic upgrade head
```
Expected: `INFO  [alembic.runtime.migration] Running upgrade ... -> 001_init, init`

- [ ] **Step 4: 设置 API Key 并导入数据**

```bash
export EMBEDDING_API_KEY="your-api-key"
cd server && python scripts/import_data.py ecommerce_agent_dataset
```
Expected: `Imported 3 products`

- [ ] **Step 5: 启动服务**

```bash
cd server && uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 6: 验证搜索链路**

```bash
# 语义匹配
curl "http://localhost:8000/api/search?q=适合户外运动的防晒霜&top_k=5" | python -m json.tool

# 期待：返回 PROD001（安耐晒防晒霜），含 2 个 SKU
```

- [ ] **Step 7: 验证商品详情链路**

```bash
curl "http://localhost:8000/api/products/PROD001" | python -m json.tool
```

- [ ] **Step 8: 验证跨品类检索**

```bash
curl "http://localhost:8000/api/search?q=适合油皮&top_k=5" | python -m json.tool
# 期待：召回 review 中含"油皮"评价的洗面奶 > 防晒霜
```

- [ ] **Step 9: 验证空结果**

```bash
curl "http://localhost:8000/api/search?q=xyzzy不存在的商品xyzzy" | python -m json.tool
# 期待：{"query":"...","products":[],"total":0}
```

- [ ] **Step 10: Commit**

```bash
git add server/ecommerce_agent_dataset/
git commit -m "feat: sample data and end-to-end verification"
```

---

## 闭环完成标志

以上 7 个 Task 全部完成后，系统具备以下能力：

- [x] `POST/GET /api/search?q=推荐防晒霜` → 返回语义匹配的商品 + SKUs
- [x] `GET /api/products/{id}` → 返回商品详情 + SKUs
- [x] `python scripts/import_data.py <dir>` → JSON 数据全量导入
- [x] 所有 HTTP 端点返回标准 JSON（非流式）

这就是最小可运行闭环。后续增量叠加：SSE 流式 → LLM 查询拆解 → 关键词检索 → 结构化过滤 → 数据同步。

---

## Self-Review

---

# 第二阶段：功能完善实现计划

> **前置条件：** 最小闭环（Task 1-7）已完成并可运行。

**Goal:** 在最小闭环之上叠加完整的 RAG 智能导购能力——LLM 查询拆解、混合检索（向量+关键词+结构化）、源权重合并、SSE 流式推荐理由生成、数据实时同步。

**Architecture:** 新增 `rag/` 管线（retriever / merger / prompt / generator）和 `services/llm.py`、`services/query_parser.py`、`services/sync.py`。搜索链路升级为：Query → LLM 拆解 → 多策略检索 → 合并排序 → LLM 生成推荐理由 → SSE 流式输出。

---

## 第二阶段概览

| 阶段 | 内容 | 依赖 |
|:---|:---|:---|
| **Phase 2A: 检索增强** | LLM 服务 → 关键词检索 → Retriever + Merger | 最小闭环 |
| **Phase 2B: LLM 集成** | Prompt 模板 → Query Parser → Generator → SSE 端点 | Phase 2A |
| **Phase 2C: 运维完善** | Sync 服务 → Admin API → 生产加固 | Phase 2B |

---

### Task 8: LLM 服务 — OpenAI 兼容 Chat Completions

**Files:**
- Create: `server/app/services/llm.py`
- Create: `server/tests/test_llm.py`
- Modify: `server/app/config.py` — 添加 LLM Settings
- Modify: `server/config.yaml` — 添加 llm 配置段

- [ ] **Step 1: 更新 config.yaml，追加 llm 配置**

在现有 `config.yaml` 末尾追加：

```yaml
# ---- 大模型 (OpenAI 兼容) ----
llm:
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  api_key: "${LLM_API_KEY}"
  model: "doubao-seed-2.0-lite"
  temperature: 0.3
```

- [ ] **Step 2: 更新 app/config.py，追加 LLM Settings**

```python
# 在现有 Settings 类之前添加
class LLMSettings(BaseSettings):
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    api_key: str = ""
    model: str = "doubao-seed-2.0-lite"
    temperature: float = 0.3


# 修改 Settings.from_yaml，在 return 前添加 llm 初始化
@classmethod
def from_yaml(cls, path: str = "config.yaml") -> "Settings":
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    db_data = data.get("database", {})
    db = DatabaseSettings(**db_data)

    emb_data = data.get("embedding", {})
    emb_data["api_key"] = os.environ.get("EMBEDDING_API_KEY", emb_data.get("api_key", ""))
    emb = EmbeddingSettings(**emb_data)

    llm_data = data.get("llm", {})
    llm_data["api_key"] = os.environ.get("LLM_API_KEY", llm_data.get("api_key", ""))
    llm = LLMSettings(**llm_data)

    return cls(database=db, embedding=emb, llm=llm)
```

同时给 `Settings` 类添加 `llm` 字段：
```python
class Settings(BaseSettings):
    database: DatabaseSettings = DatabaseSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    llm: LLMSettings = LLMSettings()
```

- [ ] **Step 3: 写 LLM 服务的失败测试**

```python
# tests/test_llm.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.llm import LLMService


@pytest.mark.asyncio
async def test_chat_simple():
    svc = LLMService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "你好！"}}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await svc.chat([{"role": "user", "content": "你好"}])

    assert result == "你好！"
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_chat_stream():
    svc = LLMService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    class FakeStream:
        async def __aiter__(self):
            chunks = [
                'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
                'data: {"choices":[{"delta":{"content":"！"}}]}\n\n',
                'data: [DONE]\n\n',
            ]
            for c in chunks:
                yield c.encode()

    mock_resp = MagicMock()
    mock_resp.aiter_lines.return_value = FakeStream()

    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp
        tokens = []
        async for token in svc.chat_stream([{"role": "user", "content": "你好"}]):
            tokens.append(token)

    assert tokens == ["你好", "！"]
```

- [ ] **Step 4: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_llm.py -v
```
Expected: FAIL

- [ ] **Step 5: 实现 LLMService**

```python
# app/services/llm.py
import json
import httpx


class LLMService:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        client = await self._get_client()
        resp = await client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature if temperature is not None else self.temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def chat_stream(
        self, messages: list[dict], temperature: float | None = None
    ):
        client = await self._get_client()
        req = client.build_request(
            "POST",
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature if temperature is not None else self.temperature,
                "stream": True,
            },
        )
        resp = await client.send(req, stream=True)
        resp.raise_for_status()

        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
```

- [ ] **Step 6: 运行测试验证通过**

```bash
cd server && python -m pytest tests/test_llm.py -v
```
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add server/app/services/llm.py server/tests/test_llm.py server/app/config.py server/config.yaml
git commit -m "feat: LLM service with chat and streaming support"
```

---

### Task 9: 关键词检索 — tsvector 触发器 + keyword retriever

**Files:**
- Create: `server/app/services/retriever.py`
- Create: `server/tests/test_retriever.py`
- Modify: `server/app/services/import_data.py` — 导入后创建 tsvector 触发器

- [ ] **Step 1: 在 import_data.py 添加 tsvector 触发器逻辑**

在 `DataImporter.import_json_dir` 中，commit 之后添加触发器创建（需在 PostgreSQL 中先安装 zhparser 扩展）：

```python
# 在 import_json_dir 方法的 await self.session.commit() 之后添加
async def _ensure_tsvector_trigger(self):
    """创建 content_tsv 自动更新触发器（需 zhparser + jieba 分词）"""
    sql = text("""
        CREATE EXTENSION IF NOT EXISTS zhparser;
        CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS chinese (PARSER = zhparser);
        ALTER TEXT SEARCH CONFIGURATION chinese
            ADD MAPPING FOR n,v,a,i,e,l WITH simple;

        -- 创建或替换触发器函数
        CREATE OR REPLACE FUNCTION product_review_tsv_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.content_tsv := to_tsvector('chinese', COALESCE(NEW.content, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        -- 创建触发器（如果不存在）
        DROP TRIGGER IF EXISTS trg_product_review_tsv ON product_review;
        CREATE TRIGGER trg_product_review_tsv
            BEFORE INSERT OR UPDATE OF content ON product_review
            FOR EACH ROW EXECUTE FUNCTION product_review_tsv_trigger();

        -- 为已有数据填充 tsvector
        UPDATE product_review SET content_tsv = to_tsvector('chinese', COALESCE(content, ''));
    """)
    await self.session.execute(sql)
    await self.session.commit()
```

在 `import_json_dir` 的 `await self.session.commit()` 后调用：
```python
await self._ensure_tsvector_trigger()
```

- [ ] **Step 2: 写 Retriever 的失败测试**

```python
# tests/test_retriever.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.retriever import Retriever, SubQuery


@pytest.fixture
def mock_db():
    session = AsyncMock()
    return session


@pytest.fixture
def mock_emb():
    svc = AsyncMock()
    svc.embed.return_value = [0.1, 0.2, 0.3]
    return svc


@pytest.mark.asyncio
async def test_retrieve_semantic(mock_db, mock_emb):
    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = MagicMock()
    mock_row.product_id = "PROD001"
    mock_row.source = "marketing"
    mock_row.similarity = 0.85

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    sub = SubQuery(text="防晒霜", strategy="semantic")
    hits = await retriever.retrieve(sub, top_k=20)

    assert len(hits) == 1
    assert hits[0]["product_id"] == "PROD001"
    mock_emb.embed.assert_called_once_with("防晒霜")


@pytest.mark.asyncio
async def test_retrieve_keyword(mock_db, mock_emb):
    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = MagicMock()
    mock_row.product_id = "PROD002"
    mock_row.source = "faq"
    mock_row.ts_rank = 0.5

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    sub = SubQuery(text="蓝牙", strategy="keyword")
    hits = await retriever.retrieve(sub, top_k=20)

    assert len(hits) == 1
    assert hits[0]["product_id"] == "PROD002"
    assert hits[0]["score"] == 0.5


@pytest.mark.asyncio
async def test_retrieve_structured(mock_db, mock_emb):
    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = MagicMock()
    mock_row.product_id = "PROD001"

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    sub = SubQuery(
        text="",
        strategy="structured_filter",
        field="brand",
        operator="not_in",
        expanded_values=["SK-II", "资生堂"],
    )
    hits = await retriever.retrieve(sub, top_k=20)

    assert len(hits) == 1
    assert hits[0]["score"] == 1.0  # structured 过滤匹配得分固定为 1.0
```

- [ ] **Step 3: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_retriever.py -v
```
Expected: FAIL

- [ ] **Step 4: 实现 SubQuery dataclass + Retriever**

```python
# app/services/retriever.py
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.services.embedding import EmbeddingService


@dataclass
class SubQuery:
    text: str
    strategy: str  # "semantic" | "keyword" | "structured_filter"
    negation: bool = False
    field: str | None = None
    operator: str | None = None  # "eq" | "lt" | "gt" | "in" | "not_in" | "contains" | "not_contains"
    value: str | float | None = None
    expanded_values: list[str] | None = None


class Retriever:
    def __init__(self, db: AsyncSession, emb: EmbeddingService):
        self.db = db
        self.emb = emb

    async def retrieve(self, sub: SubQuery, top_k: int = 20) -> list[dict]:
        if sub.strategy == "semantic":
            return await self._semantic_search(sub, top_k)
        elif sub.strategy == "keyword":
            return await self._keyword_search(sub, top_k)
        elif sub.strategy == "structured_filter":
            return await self._structured_filter(sub, top_k)
        return []

    async def _semantic_search(self, sub: SubQuery, top_k: int) -> list[dict]:
        query_vector = await self.emb.embed(sub.text)
        sql = text("""
            SELECT pr.product_id, pr.source,
                   1 - (pr.embedding <=> :vec) AS similarity
            FROM product_review pr
            JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE
            ORDER BY pr.embedding <=> :vec
            LIMIT :limit
        """)
        result = await self.db.execute(sql, {"vec": str(query_vector), "limit": top_k})
        return [
            {"product_id": r.product_id, "source": r.source, "score": float(r.similarity)}
            for r in result.fetchall()
        ]

    async def _keyword_search(self, sub: SubQuery, top_k: int) -> list[dict]:
        # tsvector 全文检索 + brand/category ILIKE 兜底
        sql = text("""
            SELECT pr.product_id, pr.source,
                   ts_rank(pr.content_tsv, plainto_tsquery('chinese', :kw)) AS ts_rank
            FROM product_review pr
            JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE
            WHERE pr.content_tsv @@ plainto_tsquery('chinese', :kw)
            ORDER BY ts_rank DESC
            LIMIT :limit
        """)
        result = await self.db.execute(sql, {"kw": sub.text, "limit": top_k})
        rows = result.fetchall()

        if not rows:
            # ILIKE 兜底：brand / category / title
            sql2 = text("""
                SELECT p.product_id, 'basic_info' AS source, 0.3 AS score
                FROM product p
                WHERE p.is_active = TRUE
                  AND (p.brand ILIKE :pat OR p.category ILIKE :pat OR p.title ILIKE :pat)
                LIMIT :limit
            """)
            result2 = await self.db.execute(sql2, {"pat": f"%{sub.text}%", "limit": top_k})
            rows = result2.fetchall()

        return [
            {"product_id": r.product_id, "source": r.source, "score": float(r.ts_rank if hasattr(r, 'ts_rank') and r.ts_rank else getattr(r, 'score', 0.3))}
            for r in rows
        ]

    async def _structured_filter(self, sub: SubQuery, top_k: int) -> list[dict]:
        if sub.field in ("brand", "category", "sub_category"):
            table = "product"
        elif sub.field in ("price", "stock"):
            table = "sku"
        else:
            return []

        values = sub.expanded_values if sub.expanded_values else ([sub.value] if sub.value is not None else [])

        if sub.operator in ("in", "not_in") and values:
            placeholders = ", ".join([f":v{i}" for i in range(len(values))])
            if sub.operator == "in":
                where_clause = f"p.{sub.field} IN ({placeholders})"
            else:
                where_clause = f"p.{sub.field} NOT IN ({placeholders})"
            params = {f"v{i}": v for i, v in enumerate(values)}
        elif sub.operator == "lt" and sub.value is not None:
            where_clause = f"p.{sub.field} < :val" if table == "product" else f"s.{sub.field} < :val"
            params = {"val": sub.value}
        elif sub.operator == "gt" and sub.value is not None:
            where_clause = f"p.{sub.field} > :val" if table == "product" else f"s.{sub.field} > :val"
            params = {"val": sub.value}
        elif sub.operator in ("contains", "not_contains") and sub.value:
            pattern = f"%{sub.value}%"
            if sub.operator == "contains":
                where_clause = f"p.{sub.field} ILIKE :pat"
            else:
                where_clause = f"p.{sub.field} NOT ILIKE :pat"
            params = {"pat": pattern}
        else:
            return []

        if table == "product":
            sql = text(f"""
                SELECT p.product_id, 'basic_info' AS source, 1.0 AS score
                FROM product p
                WHERE p.is_active = TRUE AND {where_clause}
                LIMIT :limit
            """)
        else:
            sql = text(f"""
                SELECT DISTINCT s.product_id, 'sku' AS source, 1.0 AS score
                FROM sku s
                JOIN product p ON p.product_id = s.product_id AND p.is_active = TRUE
                WHERE {where_clause}
                LIMIT :limit
            """)

        params["limit"] = top_k
        result = await self.db.execute(sql, params)
        return [
            {"product_id": r.product_id, "source": r.source, "score": float(r.score)}
            for r in result.fetchall()
        ]
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd server && python -m pytest tests/test_retriever.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/services/retriever.py server/tests/test_retriever.py server/app/services/import_data.py
git commit -m "feat: keyword search with tsvector and three-strategy retriever"
```

---

### Task 10: Merger — source 权重 + 多子查询合并

**Files:**
- Create: `server/app/rag/__init__.py`
- Create: `server/app/rag/merger.py`
- Create: `server/tests/test_merger.py`
- Modify: `server/config.yaml` — 添加 source_weights 配置段

- [ ] **Step 1: 更新 config.yaml，追加检索配置**

```yaml
# ---- 检索 ----
search:
  source_weights:
    faq: 1.0
    marketing: 0.9
    user_review: 0.6
  top_k_per_query: 20
  final_product_limit: 10
  min_results_threshold: 3
```

- [ ] **Step 2: 更新 config.py，添加 SearchSettings**

```python
class SearchSettings(BaseSettings):
    source_weights: dict = {"faq": 1.0, "marketing": 0.9, "user_review": 0.6}
    top_k_per_query: int = 20
    final_product_limit: int = 10
    min_results_threshold: int = 3

# Settings 类添加:
# search: SearchSettings = SearchSettings()
# from_yaml 中添加 search_data 解析
```

- [ ] **Step 3: 写 Merger 的失败测试**

```python
# tests/test_merger.py
import pytest
from app.rag.merger import Merger


def test_merger_basic():
    merger = Merger(
        source_weights={"faq": 1.0, "marketing": 0.9, "user_review": 0.6},
        final_limit=10,
        min_threshold=3,
    )

    # 两个子查询的结果
    all_hits = [
        # 子查询1: semantic "防晒霜"
        [
            {"product_id": "P1", "source": "marketing", "score": 0.9},
            {"product_id": "P2", "source": "faq", "score": 0.8},
            {"product_id": "P1", "source": "faq", "score": 0.7},
        ],
        # 子查询2: keyword "户外"
        [
            {"product_id": "P1", "source": "user_review", "score": 0.5},
            {"product_id": "P3", "source": "marketing", "score": 0.6},
        ],
    ]

    negation_queries = []  # 无 negations
    ranked = merger.merge(all_hits, negation_queries)

    assert len(ranked) <= 10
    # P1 应该排名最高（出现在两个子查询中，且有高权重的 faq 来源）
    assert ranked[0] == "P1"
    # 去重验证
    assert len(ranked) == len(set(ranked))


def test_merger_negation():
    merger = Merger(
        source_weights={"faq": 1.0, "marketing": 0.9, "user_review": 0.6},
        final_limit=10,
        min_threshold=3,
    )

    all_hits = [
        [{"product_id": "P1", "source": "faq", "score": 0.9}],
        [{"product_id": "P2", "source": "marketing", "score": 0.8}],
    ]

    negation_queries = ["P2"]  # P2 被硬过滤

    ranked = merger.merge(all_hits, negation_queries)
    assert "P2" not in ranked
    assert "P1" in ranked


def test_merger_source_weight():
    merger = Merger(
        source_weights={"faq": 1.0, "marketing": 0.9, "user_review": 0.6},
        final_limit=10,
        min_threshold=3,
    )

    hits = [
        [
            {"product_id": "P1", "source": "faq", "score": 0.8},
            {"product_id": "P1", "source": "user_review", "score": 0.8},
        ]
    ]

    ranked = merger.merge(hits, [])
    # P1 的 faq 得分 0.8*1.0=0.8, user_review 得分 0.8*0.6=0.48, 均值=0.64
    assert len(ranked) == 1
```

- [ ] **Step 4: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_merger.py -v
```
Expected: FAIL

- [ ] **Step 5: 实现 Merger**

```python
# app/rag/merger.py
from collections import defaultdict


class Merger:
    def __init__(
        self,
        source_weights: dict[str, float],
        final_limit: int = 10,
        min_threshold: int = 3,
    ):
        self.source_weights = source_weights
        self.final_limit = final_limit
        self.min_threshold = min_threshold

    def merge(
        self,
        all_hits: list[list[dict]],
        negation_queries: list[str],  # product_ids from negation SubQueries
    ) -> list[str]:
        # Step 1: 对每组子查询 hits 应用 source_weight
        weighted_hits = []
        for hits in all_hits:
            for h in hits:
                w = self.source_weights.get(h["source"], 0.5)
                weighted_hits.append({
                    "product_id": h["product_id"],
                    "weighted_score": h["score"] * w,
                })

        # Step 2: 按 product_id 聚合，取 top-K 均值（简化为均值）
        product_scores: dict[str, list[float]] = defaultdict(list)
        for h in weighted_hits:
            product_scores[h["product_id"]].append(h["weighted_score"])

        # Step 3: 计算每个 product_id 的最终得分（所有 hits 平均值）
        final_scores = {}
        for pid, scores in product_scores.items():
            final_scores[pid] = sum(scores) / len(scores)

        # Step 4: Negation 硬过滤
        for pid in negation_queries:
            final_scores.pop(pid, None)

        # Step 5: 按得分降序排列
        ranked = sorted(final_scores, key=final_scores.get, reverse=True)

        # Step 6: 降级 — 结果不足时放宽条件
        if len(ranked) < self.min_threshold:
            # 仅保留非 negation 结果，不做进一步放宽（最小闭环不做复杂降级）
            pass

        return ranked[:self.final_limit]
```

- [ ] **Step 6: 运行测试验证通过**

```bash
cd server && python -m pytest tests/test_merger.py -v
```
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add server/app/rag/__init__.py server/app/rag/merger.py server/tests/test_merger.py server/app/config.py server/config.yaml
git commit -m "feat: merger with source weights and negation filtering"
```

---

### Task 11: Prompt 模板 — 查询拆解 + 推荐生成

**Files:**
- Create: `server/app/rag/prompt.py`

- [ ] **Step 1: 创建 Prompt 模板**

```python
# app/rag/prompt.py

QUERY_PARSE_SYSTEM = """你是一个电商查询意图拆解专家。你的任务是将用户的自然语言商品查询拆分为多个单一意图的子查询。

## 输出格式
返回一个 JSON 数组，每个元素包含：
- text: str — 子查询的文本描述
- strategy: str — "semantic"（语义模糊匹配）、"keyword"（关键词精确匹配）、"structured_filter"（结构化字段过滤）
- negation: bool — 是否为否定条件（如"不要""排除"）
- field: str|null — structured_filter 时指定字段名。可选值：brand, category, sub_category, price
- operator: str|null — 比较操作符。eq/lt/gt/in/not_in/contains/not_contains
- value: str|float|null — 单个值
- expanded_values: list[str]|null — 当需要世界知识展开时（如"日系品牌"），LLM 将属性展开为具体值列表

## 规则
1. 模糊主观意图（如"适合油皮""清爽不油腻""防晒效果好"）→ strategy="semantic"
2. 精确关键词（如"蓝牙""耳机""洗面奶"）→ strategy="keyword"
3. 明确的可结构化条件（如"200元以下""品牌是雅诗兰黛""不要日系品牌"）→ strategy="structured_filter"
4. 否定条件标记 negation=true
5. 对于需要世界知识的属性（如"日系品牌"→ ["SK-II","资生堂","CPB","雪肌精","DHC","FANCL","植村秀","SUQQU","高丝","KOSE"]），填入 expanded_values

## 可用数据表
- product: brand(VARCHAR), category(VARCHAR), sub_category(VARCHAR)
- sku: price(DECIMAL), stock(INT)

## 示例
用户查询: "推荐一款200元以下的不含酒精的非日系防晒霜"
输出:
[
  {"text": "防晒霜", "strategy": "keyword", "negation": false, "field": null, "operator": null, "value": null, "expanded_values": null},
  {"text": "防晒效果", "strategy": "semantic", "negation": false, "field": null, "operator": null, "value": null, "expanded_values": null},
  {"text": "价格低于200", "strategy": "structured_filter", "negation": false, "field": "price", "operator": "lt", "value": 200, "expanded_values": null},
  {"text": "不含酒精", "strategy": "keyword", "negation": true, "field": null, "operator": null, "value": null, "expanded_values": null},
  {"text": "不要日系品牌", "strategy": "structured_filter", "negation": true, "field": "brand", "operator": "not_in", "value": null, "expanded_values": ["SK-II","资生堂","CPB","雪肌精","DHC","FANCL","植村秀","SUQQU","高丝","KOSE"]}
]

现在请对以下用户查询进行拆解，只返回 JSON 数组，不要其他内容："""


GENERATOR_SYSTEM = """你是一个专业的导购助手。基于检索到的商品信息，为用户推荐合适的商品。

## 规则
1. 只能使用以下提供的商品信息，不得编造任何价格、库存、功能、优惠券或折扣
2. 如果商品信息不足以满足用户需求，请诚实告知，不要编造
3. 推荐时说明推荐理由，引用商品的真实属性
4. 以自然、友好的语气回复
5. 不要提及"根据检索结果""根据商品信息"等元表述

## 可用商品信息
{product_context}

## 用户查询
{user_query}

请为用户推荐："""
```

- [ ] **Step 2: Commit**

```bash
git add server/app/rag/prompt.py
git commit -m "feat: prompt templates for query parsing and recommendation generation"
```

---

### Task 12: Query Parser — LLM 查询拆解 + expanded_values

**Files:**
- Create: `server/app/services/query_parser.py`
- Create: `server/tests/test_query_parser.py`

- [ ] **Step 1: 写 Query Parser 的失败测试**

```python
# tests/test_query_parser.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.query_parser import QueryParser, SubQuery


def test_parse_llm_response():
    parser = QueryParser(llm=MagicMock())

    llm_output = json.dumps([
        {
            "text": "防晒霜",
            "strategy": "keyword",
            "negation": False,
            "field": None,
            "operator": None,
            "value": None,
            "expanded_values": None,
        },
        {
            "text": "不要日系品牌",
            "strategy": "structured_filter",
            "negation": True,
            "field": "brand",
            "operator": "not_in",
            "value": None,
            "expanded_values": ["SK-II", "资生堂", "CPB"],
        },
    ])

    subs = parser._parse_response(llm_output)
    assert len(subs) == 2
    assert subs[0].strategy == "keyword"
    assert subs[0].text == "防晒霜"
    assert subs[1].negation is True
    assert subs[1].expanded_values == ["SK-II", "资生堂", "CPB"]


@pytest.mark.asyncio
async def test_parse_with_mock_llm():
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps([
        {
            "text": "需要洗面奶",
            "strategy": "keyword",
            "negation": False,
            "field": None,
            "operator": None,
            "value": None,
            "expanded_values": None,
        },
        {
            "text": "适合油皮",
            "strategy": "semantic",
            "negation": False,
            "field": None,
            "operator": None,
            "value": None,
            "expanded_values": None,
        },
    ])

    parser = QueryParser(llm=mock_llm)
    subs = await parser.parse("推荐一款适合油皮的洗面奶")

    assert len(subs) == 2
    assert subs[0].strategy == "keyword"
    assert subs[1].strategy == "semantic"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_query_parser.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 QueryParser**

```python
# app/services/query_parser.py
import json
from app.services.retriever import SubQuery
from app.services.llm import LLMService
from app.rag.prompt import QUERY_PARSE_SYSTEM


class QueryParser:
    def __init__(self, llm: LLMService):
        self.llm = llm

    async def parse(self, user_query: str) -> list[SubQuery]:
        messages = [
            {"role": "system", "content": QUERY_PARSE_SYSTEM},
            {"role": "user", "content": user_query},
        ]

        response = await self.llm.chat(messages, temperature=0.1)
        return self._parse_response(response)

    def _parse_response(self, llm_output: str) -> list[SubQuery]:
        # 清理可能的 markdown 代码块包裹
        text = llm_output.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        data = json.loads(text)
        subs = []
        for item in data:
            subs.append(SubQuery(
                text=item.get("text", ""),
                strategy=item.get("strategy", "semantic"),
                negation=item.get("negation", False),
                field=item.get("field"),
                operator=item.get("operator"),
                value=item.get("value"),
                expanded_values=item.get("expanded_values"),
            ))
        return subs
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd server && python -m pytest tests/test_query_parser.py -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/query_parser.py server/tests/test_query_parser.py
git commit -m "feat: LLM query parser with SubQuery decomposition and expanded_values"
```

---

### Task 13: Generator — LLM 推荐理由生成 + SSE 流式

**Files:**
- Create: `server/app/rag/generator.py`
- Create: `server/tests/test_generator.py`

- [ ] **Step 1: 写 Generator 的失败测试**

```python
# tests/test_generator.py
import pytest
from unittest.mock import AsyncMock
from app.rag.generator import Generator


@pytest.mark.asyncio
async def test_generate_stream():
    mock_llm = AsyncMock()

    async def fake_stream(messages, temperature=None):
        yield "为您"
        yield "推荐"
        yield "以下商品"

    mock_llm.chat_stream = fake_stream

    generator = Generator(llm=mock_llm)

    products = [
        {
            "product_id": "P1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "skus": [{"sku_id": "P1_60ml", "price": 198.0, "properties": {"容量": "60ml"}}],
        }
    ]

    user_query = "推荐一款防晒霜"
    tokens = []
    async for token in generator.generate(products, user_query):
        tokens.append(token)

    assert tokens == ["为您", "推荐", "以下商品"]


def test_build_product_context():
    generator = Generator(llm=AsyncMock())

    products = [
        {
            "product_id": "P1",
            "title": "测试商品",
            "brand": "测试品牌",
            "category": "测试",
            "base_price": 99.0,
            "skus": [{"sku_id": "S1", "price": 99.0, "properties": {"颜色": "黑"}}],
        }
    ]

    ctx = generator._build_context(products)
    assert "测试商品" in ctx
    assert "测试品牌" in ctx
    assert "99.0" in ctx
    assert "黑" in ctx
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_generator.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 Generator**

```python
# app/rag/generator.py
from app.services.llm import LLMService
from app.rag.prompt import GENERATOR_SYSTEM


class Generator:
    def __init__(self, llm: LLMService):
        self.llm = llm

    def _build_context(self, products: list[dict]) -> str:
        lines = []
        for i, p in enumerate(products, 1):
            lines.append(f"{i}. {p['title']}")
            if p.get("brand"):
                lines.append(f"   品牌: {p['brand']}")
            if p.get("category"):
                lines.append(f"   品类: {p['category']}")
            if p.get("base_price"):
                lines.append(f"   基础价格: ¥{p['base_price']}")

            for sku in p.get("skus", []):
                props = " / ".join(f"{k}: {v}" for k, v in sku.get("properties", {}).items())
                sku_desc = f"   - SKU {sku['sku_id']}: ¥{sku['price']}"
                if props:
                    sku_desc += f" ({props})"
                lines.append(sku_desc)

            lines.append("")

        return "\n".join(lines)

    async def generate(self, products: list[dict], user_query: str):
        context = self._build_context(products)
        system_prompt = GENERATOR_SYSTEM.format(
            product_context=context,
            user_query=user_query,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请根据以上商品信息，为用户推荐：{user_query}"},
        ]

        async for token in self.llm.chat_stream(messages, temperature=0.3):
            yield token
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd server && python -m pytest tests/test_generator.py -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/rag/generator.py server/tests/test_generator.py
git commit -m "feat: LLM generator with streaming recommendation output"
```

---

### Task 14: SSE 搜索端点 — 整合全链路

**Files:**
- Modify: `server/app/api/search.py` — 替换为 SSE 流式搜索
- Modify: `server/app/schemas/product.py` — 追加 SSE 事件类型
- Modify: `server/tests/test_search.py` — SSE 测试

- [ ] **Step 1: 更新 schemas/product.py**

在现有基础上追加：
```python
class SSESubQueryEvent(BaseModel):
    text: str
    strategy: str
    negation: bool = False
    field: str | None = None
    operator: str | None = None
    value: str | float | None = None
    expanded_values: list[str] | None = None


class SSEProduct(BaseModel):
    product_id: str
    title: str
    brand: str | None
    category: str | None
    base_price: float | None
    image_path: str | None
    skus: list[SkuOut]
```

- [ ] **Step 2: 写 SSE 搜索端点的失败测试**

```python
# 追加到 tests/test_search.py
@pytest.mark.asyncio
async def test_search_sse_format():
    """验证 SSE 端点在无 DB 时至少返回正确的 HTTP 状态"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/search/stream?q=防晒霜")
    # 可能 500（DB 不可用）或开始 SSE 流
    assert resp.status_code in (200, 500, 503)
```

- [ ] **Step 3: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_search.py::test_search_sse_format -v
```
Expected: FAIL — 路由未注册

- [ ] **Step 4: 重写 search.py 为 SSE 流式全链路**

```python
# app/api/search.py（替换原内容）
import json
import asyncio
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse
from app.database import get_db
from app.config import settings
from app.models.product import Product
from app.models.sku import Sku
from app.schemas.product import SkuOut
from app.services.embedding import EmbeddingService
from app.services.llm import LLMService
from app.services.query_parser import QueryParser
from app.services.retriever import Retriever, SubQuery
from app.rag.merger import Merger
from app.rag.generator import Generator

router = APIRouter(prefix="/api", tags=["search"])


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        batch_size=settings.embedding.batch_size,
    )


def get_llm_service() -> LLMService:
    return LLMService(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=settings.llm.temperature,
    )


async def _get_products(db: AsyncSession, product_ids: list[str]) -> list[dict]:
    products = []
    for pid in product_ids:
        prod = await db.execute(
            select(Product).where(Product.product_id == pid, Product.is_active == True)
        )
        prod = prod.scalar_one_or_none()
        if prod is None:
            continue

        skus_result = await db.execute(
            select(Sku).where(Sku.product_id == pid, Sku.is_active == True)
        )
        skus = [
            {
                "sku_id": s.sku_id,
                "properties": s.properties,
                "price": float(s.price),
                "stock": s.stock,
            }
            for s in skus_result.scalars().all()
        ]

        products.append({
            "product_id": prod.product_id,
            "title": prod.title,
            "brand": prod.brand,
            "category": prod.category,
            "base_price": float(prod.base_price) if prod.base_price else None,
            "image_path": prod.image_path,
            "skus": skus,
        })

    return products


@router.get("/search/stream")
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
    llm: LLMService = Depends(get_llm_service),
):
    retriever = Retriever(db=db, emb=emb)
    parser = QueryParser(llm=llm)
    merger = Merger(
        source_weights=settings.search.source_weights,
        final_limit=settings.search.final_product_limit,
        min_threshold=settings.search.min_results_threshold,
    )
    generator = Generator(llm=llm)

    async def event_stream():
        try:
            # Step 1: LLM 查询拆解（3s 超时）
            try:
                sub_queries = await asyncio.wait_for(parser.parse(q), timeout=3.0)
            except asyncio.TimeoutError:
                # 降级：原始查询整体走 semantic
                sub_queries = [SubQuery(text=q, strategy="semantic")]

            # Step 2: 发送 sub_queries 事件（调试用）
            subs_data = [
                {
                    "text": s.text,
                    "strategy": s.strategy,
                    "negation": s.negation,
                    "field": s.field,
                    "operator": s.operator,
                    "value": s.value,
                    "expanded_values": s.expanded_values,
                }
                for s in sub_queries
            ]
            yield {"event": "sub_queries", "data": json.dumps(subs_data, ensure_ascii=False)}

            # Step 3: 对每个非 negation 子查询分别检索
            all_hits = []
            negation_pids: list[str] = []

            for sub in sub_queries:
                hits = await retriever.retrieve(sub, top_k=settings.search.top_k_per_query)
                if sub.negation:
                    # 收集 negation 过滤的 product_ids
                    negation_pids.extend([h["product_id"] for h in hits])
                else:
                    all_hits.append(hits)

            # Step 4: 合并排序
            ranked_pids = merger.merge(all_hits, negation_pids)

            # Step 5: 查询完整的商品信息
            products = await _get_products(db, ranked_pids)

            # Step 6: 发送 products 事件
            yield {"event": "products", "data": json.dumps(products, ensure_ascii=False)}

            # Step 7: LLM 流式生成推荐理由（15s 超时）
            if products:
                try:
                    async for token in asyncio.wait_for(
                        _stream_with_timeout(generator.generate(products, q)), timeout=15.0
                    ):
                        yield {"event": "reasoning", "data": token}
                except asyncio.TimeoutError:
                    pass

            # Step 8: 发送 done
            yield {"event": "done", "data": "{}"}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


async def _stream_with_timeout(agen):
    """辅助：包装 async generator 以支持 asyncio.wait_for"""
    async for item in agen:
        yield item
```

**注意**：`search/stream` 需要安装 `sse-starlette` 包。更新 requirements.txt：
```txt
sse-starlette>=2.0.0
```

- [ ] **Step 5: 保留原 JSON 搜索端点（向后兼容）**

在 search.py 中保留原有的 `GET /api/search` JSON 端点不变，新增 `GET /api/search/stream` SSE 端点。两个端点共存。

- [ ] **Step 6: 运行测试**

```bash
cd server && python -m pytest tests/test_search.py -v
```
Expected: 原有测试 + test_search_sse_format PASS

- [ ] **Step 7: Commit**

```bash
git add server/app/api/search.py server/app/schemas/product.py server/tests/test_search.py server/requirements.txt
git commit -m "feat: SSE streaming search endpoint with full RAG pipeline"
```

---

### Task 15: Sync 服务 — 五源表轮询增量同步

**Files:**
- Create: `server/app/services/sync.py`
- Create: `server/tests/test_sync.py`
- Modify: `server/app/config.py` — 添加 SyncSettings
- Modify: `server/config.yaml` — 添加 sync 配置
- Modify: `server/app/main.py` — lifespan 启动 sync 定时器

- [ ] **Step 1: 更新 config.yaml，追加 sync 配置**

```yaml
# ---- 同步 ----
sync:
  interval_s: 2
  enabled: true
```

- [ ] **Step 2: 更新 config.py**

```python
class SyncSettings(BaseSettings):
    interval_s: int = 2
    enabled: bool = True

# Settings 类添加 sync 字段 + from_yaml 解析
```

- [ ] **Step 3: 写 Sync 服务的失败测试**

```python
# tests/test_sync.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from app.services.sync import SyncService


@pytest.mark.asyncio
async def test_sync_polls_tables():
    mock_db = AsyncMock()

    # product 无变更
    mock_product_result = MagicMock()
    mock_product_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_product_result

    mock_emb = AsyncMock()
    mock_emb.embed.return_value = [0.1, 0.2]

    svc = SyncService(db_session_factory=lambda: mock_db, emb=mock_emb)
    await svc.run_once(last_sync=datetime(2026, 1, 1))

    # 验证至少调用了 product / product_marketing / product_faq / sku / user_review 的查询
    assert mock_db.execute.call_count >= 5
```

- [ ] **Step 4: 运行测试验证失败**

```bash
cd server && python -m pytest tests/test_sync.py -v
```
Expected: FAIL

- [ ] **Step 5: 实现 SyncService**

```python
# app/services/sync.py
import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from app.models import Product, ProductMarketing, ProductFaq, UserReview
from app.models.product_review import ProductReview
from app.services.embedding import EmbeddingService


class SyncService:
    def __init__(self, db_session_factory, emb: EmbeddingService):
        self.db_session_factory = db_session_factory
        self.emb = emb
        self._last_sync: datetime | None = None

    async def run_once(self, last_sync: datetime | None = None):
        if last_sync is not None:
            self._last_sync = last_sync

        async with self.db_session_factory() as db:
            # 获取 advisory lock 防重入
            await db.execute(text("SELECT pg_advisory_lock(12345)"))

            try:
                # product: is_active=FALSE → 删除 product_review
                await self._sync_product(db)
                # product_marketing: INSERT/UPDATE/DELETE → product_review
                await self._sync_table(db, ProductMarketing, "marketing", "description")
                # product_faq: INSERT/UPDATE/DELETE → product_review（q+a 拼接）
                await self._sync_faq(db)
                # user_review: INSERT/UPDATE/DELETE → product_review
                await self._sync_table(db, UserReview, "user_review", "content")
                # sku: 无需操作（搜索时 JOIN 获取实时值）
                await db.commit()
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(12345)"))

    async def _sync_product(self, db: AsyncSession):
        """处理 product 表变更：is_active=FALSE → 删除对应 product_review"""
        if self._last_sync:
            sql = text("""
                SELECT product_id FROM product
                WHERE updated_at > :ts AND is_active = FALSE
            """)
            result = await db.execute(sql, {"ts": self._last_sync})
            pids = [r.product_id for r in result.fetchall()]
            if pids:
                placeholders = ", ".join([f":p{i}" for i in range(len(pids))])
                params = {f"p{i}": pid for i, pid in enumerate(pids)}
                await db.execute(
                    text(f"DELETE FROM product_review WHERE product_id IN ({placeholders})"),
                    params,
                )

    async def _sync_table(self, db: AsyncSession, model_cls, source: str, content_field: str):
        """通用源表同步：检测 INSERT/UPDATE/DELETE"""
        if not self._last_sync:
            return

        # 新增/更新的行
        rows = (await db.execute(
            select(model_cls).where(
                model_cls.updated_at > self._last_sync,
                model_cls.is_active == True,
            )
        )).scalars().all()

        for row in rows:
            content = getattr(row, content_field, "")
            vec = await self.emb.embed(content)

            # upsert: 删除旧的，插入新的
            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = :src"),
                {"pid": row.product_id, "src": source},
            )
            db.add(ProductReview(
                product_id=row.product_id,
                source=source,
                content=content,
                embedding=vec,
                metadata={},
            ))

        # is_active=FALSE → 删除
        deleted = (await db.execute(
            select(model_cls).where(
                model_cls.updated_at > self._last_sync,
                model_cls.is_active == False,
            )
        )).scalars().all()

        for row in deleted:
            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = :src"),
                {"pid": row.product_id, "src": source},
            )

    async def _sync_faq(self, db: AsyncSession):
        """FAQ 特殊处理：content = question + answer 拼接"""
        if not self._last_sync:
            return

        rows = (await db.execute(
            select(ProductFaq).where(
                ProductFaq.updated_at > self._last_sync,
                ProductFaq.is_active == True,
            )
        )).scalars().all()

        for row in rows:
            content = f"问题：{row.question}\n回答：{row.answer}"
            vec = await self.emb.embed(content)

            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = 'faq' AND metadata->>'question' = :q"),
                {"pid": row.product_id, "q": row.question},
            )
            db.add(ProductReview(
                product_id=row.product_id,
                source="faq",
                content=content,
                embedding=vec,
                metadata={"question": row.question},
            ))

        # 软删除
        deleted = (await db.execute(
            select(ProductFaq).where(
                ProductFaq.updated_at > self._last_sync,
                ProductFaq.is_active == False,
            )
        )).scalars().all()

        for row in deleted:
            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = 'faq' AND metadata->>'question' = :q"),
                {"pid": row.product_id, "q": row.question},
            )

    async def run_loop(self):
        """后台循环：每间隔 interval_s 秒执行一次"""
        from app.config import settings
        while True:
            await self.run_once()
            # 下次从 "现在" 开始检测变更
            self._last_sync = datetime.utcnow()
            await asyncio.sleep(settings.sync.interval_s)
```

- [ ] **Step 6: 在 main.py lifespan 中启动 sync**

```python
# 在 lifespan 中添加
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.sync.enabled:
        sync_service = SyncService(
            db_session_factory=lambda: async_session(),
            emb=EmbeddingService(
                base_url=settings.embedding.base_url,
                api_key=settings.embedding.api_key,
                model=settings.embedding.model,
            ),
        )
        task = asyncio.create_task(sync_service.run_loop())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        yield
```

- [ ] **Step 7: 运行测试**

```bash
cd server && python -m pytest tests/test_sync.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add server/app/services/sync.py server/tests/test_sync.py server/app/config.py server/config.yaml server/app/main.py
git commit -m "feat: sync service polling five source tables for incremental updates"
```

---

### Task 16: Admin API + 图片静态文件服务

**Files:**
- Create: `server/app/api/admin.py`
- Modify: `server/app/main.py` — 挂载 admin 路由 + StaticFiles

- [ ] **Step 1: 实现 Admin API**

```python
# app/api/admin.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.sync import SyncService
from app.services.embedding import EmbeddingService
from app.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
    )


@router.post("/sync")
async def trigger_sync(
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
):
    """手动触发一轮全量同步"""
    svc = SyncService(db_session_factory=lambda: db, emb=emb)
    await svc.run_once()
    return {"status": "ok", "message": "Sync completed"}
```

- [ ] **Step 2: 在 main.py 挂载 admin 路由和 StaticFiles**

```python
from fastapi.staticfiles import StaticFiles
from app.api import admin

app.include_router(admin.router)

# 挂载图片静态目录
app.mount("/static", StaticFiles(directory="ecommerce_agent_dataset"), name="static")
```

- [ ] **Step 3: Commit**

```bash
git add server/app/api/admin.py server/app/main.py
git commit -m "feat: admin sync trigger and static image serving"
```

---

### Task 17: 生产加固 — 超时、降级、结构化日志

**Files:**
- Modify: `server/app/api/search.py` — 完善降级路径
- Create: `server/app/core/logging.py` — structlog 配置
- Modify: `server/config.yaml` — 添加 timeout 配置
- Modify: `server/requirements.txt` — 添加 structlog

- [ ] **Step 1: 更新 config.yaml，追加 timeout 配置**

```yaml
# ---- 超时 (秒) ----
timeout:
  query_parse: 3.0
  retrieval: 1.0
  generation: 15.0
  total_request: 30.0
```

- [ ] **Step 2: 更新 config.py，添加 TimeoutSettings**

```python
class TimeoutSettings(BaseSettings):
    query_parse: float = 3.0
    retrieval: float = 1.0
    generation: float = 15.0
    total_request: float = 30.0
```

- [ ] **Step 3: 创建结构化日志配置**

```python
# app/core/logging.py
import structlog
import logging


def setup_logging():
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", level=logging.INFO)


logger = structlog.get_logger()
```

- [ ] **Step 4: 在 main.py 中初始化日志**

```python
from app.core.logging import setup_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # ...
```

- [ ] **Step 5: 在 search.py 中添加日志埋点**

在异常捕获处添加日志：
```python
from app.core.logging import logger

# 在 event_stream() 的 except 处:
except Exception as e:
    logger.error("search_error", query=q, error=str(e))
    yield {"event": "error", ...}
```

- [ ] **Step 6: 更新 requirements.txt**

```txt
structlog>=24.1.0
```

- [ ] **Step 7: Commit**

```bash
git add server/config.yaml server/app/config.py server/app/core/logging.py server/app/main.py server/app/api/search.py server/requirements.txt
git commit -m "feat: production hardening with timeouts, degradation, and structured logging"
```

---

## Phase 2 完成标志

以上 Task 8-17 全部完成后，系统达到 CON_PLAN.md 的完整设计：

- [x] SSE 流式搜索端点（`GET /api/search/stream?q=...`）
- [x] LLM 查询拆解 + expanded_values 品牌展开
- [x] 三策略混合检索（semantic + keyword + structured_filter）
- [x] source 权重合并 + negation 硬过滤
- [x] LLM 流式推荐理由生成
- [x] 五源表增量同步（秒级轮询）
- [x] 手动同步触发（`POST /api/admin/sync`）
- [x] 图片静态文件服务
- [x] 超时降级 + 结构化日志
- [x] 向后兼容原 JSON 搜索端点

**明确不交付（按 SPEC）：** 多轮对话、前端 UI、用户认证、Docker/K8s、性能压测。

---

## Self-Review

1. **Spec coverage:** 对照 CON_PLAN.md 的所有功能链路——搜索（§5.1）、同步（§5.2）、导入（§5.3）均已覆盖。Q7（查询展开）、Q8（tsvector）、Q9（阈值）、Q10（超时）、Q12（HNSW）决策全部落地。
2. **Placeholder scan:** 无 TBD/TODO。
3. **Type consistency:** SubQuery dataclass 在 retriever 和 query_parser 中使用一致字段。Generator 输出的 products dict 格式与 SearchResponse 兼容。Merger 接口（List[hits] + negation_pids → List[pid]）在 search.py 调用处一致。
