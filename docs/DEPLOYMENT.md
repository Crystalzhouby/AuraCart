# AuraCart — 部署与快速体验指南

> 更新日期：2026-06-10 | 版本：v2.5

本文档指导你完成 AuraCart 智能导购系统的完整部署，并通过命令行和 Android 客户端两种方式快速体验产品功能。

---

## 1. 前置条件

### 1.1 硬件/系统要求

| 项目 | 最低要求 |
|------|----------|
| 操作系统 | Windows 10+ / macOS 12+ / Linux |
| 内存 | 8 GB (Docker 部署) / 4 GB (手动部署) |
| 磁盘 | 5 GB 可用空间 |
| 网络 | 可访问 LLM/Embedding API 端点 |

### 1.2 软件依赖

| 软件 | 版本 | 用途 | 必需 |
|------|------|------|------|
| Python | 3.12+ | 后端运行环境 | 是 |
| PostgreSQL | 14+ | 数据库 + pgvector + zhparser | 是 |
| Docker | 24+ | 数据库容器化部署 | 推荐 |
| Git | 2.0+ | 克隆仓库 | 是 |
| Android Studio | Hedgehog 2023.1.1+ | 客户端构建 | 仅客户端 |

### 1.3 外部 API Key

你需要准备以下 API 密钥（OpenAI 兼容接口）：

| 密钥 | 用途 | 获取方式 |
|------|------|----------|
| Embedding API Key | 商品文本向量化 | 豆包/阿里云/OpenAI 等 |
| LLM API Key | 意图分类、回复生成、推荐理由 | 同上 |

---

## 2. 部署步骤

### 2.1 克隆仓库

```bash
git clone https://github.com/Crystalzhouby/AI-Agent-Ecom-Guide.git
cd AI-Agent-Ecom-Guide
```

### 2.2 Python 环境

```bash
# 创建 conda 环境
conda create -n AuraCart python=3.12
conda activate AuraCart

# 安装依赖
cd server
pip install -r requirements.txt
```

### 2.3 配置 API 密钥

在 `server/` 目录下创建 `.secrets.yaml`：

```yaml
# server/.secrets.yaml
embedding:
  api_key: "your-embedding-api-key"

llm:
  api_key: "your-llm-api-key"
```

编辑 `server/config.yaml` 中的模型端点配置（如使用非默认端点）：

```yaml
# server/config.yaml (需要修改的部分)
embedding:
  base_url: "https://your-embedding-api.com/v1"
  model: "your-embedding-model"

llm:
  base_url: "https://your-llm-api.com/v1"
  model: "your-llm-model"

database:
  host: "localhost"
  port: 5432
  user: "postgres"
  password: "123456"
  dbname: "ecommerce"
```

### 2.4 启动数据库

**方式一：Docker Compose（推荐）**

```bash
cd server/scripts
docker compose up -d --build
```

**方式二：手动 PostgreSQL**

确保已安装 pgvector 和 zhparser 扩展，然后创建数据库：

```sql
CREATE DATABASE ecommerce;
CREATE EXTENSION pgvector;
CREATE EXTENSION zhparser;
CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l,j WITH simple;
```

### 2.5 初始化中文分词（Docker 方式）

```bash
docker exec -it pg17-vector-zhparser psql -U postgres -d ecommerce
```

在 psql 中执行：

```sql
CREATE EXTENSION zhparser;
CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l,j WITH simple;
\q
```

### 2.6 初始化表结构与数据

```bash
cd server

# 数据库迁移
alembic upgrade head

# 导入商品数据 (100 条商品)
python scripts/import_data.py

# 初始化品类查找表
python scripts/setup_category_lookup.py
```

### 2.7 启动后端服务

```bash
cd server

# 默认启动 (端口 8000, INFO 日志)
python run.py

# 开发模式 (hot reload + DEBUG 日志)
python run.py --reload --log DEBUG

# 指定端口
python run.py --port 8080
```

验证服务存活：

```bash
curl http://localhost:8000/health
# 返回: {"status": "ok"}
```

### 2.8 （可选）构建 Android 客户端

1. 用 Android Studio 打开 `client/` 目录
2. 等待 Gradle 同步完成
3. 在 `RetrofitClient.kt` 中确认 `BASE_URL`：
   - 模拟器：`http://10.0.2.2:8000`（默认，映射宿主机 localhost）
   - 真机：改为电脑局域网 IP（如 `http://192.168.1.100:8000`）
4. 点击 **Run ▶** 构建并安装到设备/模拟器

---

## 3. 快速体验

### 3.1 通过命令行体验

**Step 1：创建会话**

```bash
curl http://localhost:8000/api/conversation
```

记录返回的 `conversation_id`，例如 `550e8400-e29b-41d4-a716-446655440000`。

**Step 2：发起商品搜索（单品类）**

```bash
curl -N "http://localhost:8000/api/search/<conversation_id>?q=推荐一款200元以下的防晒霜"
```

你将看到 SSE 事件流实时推送：

```
event: welcome_chat_stream
data: {"type": "start"}

event: welcome_chat_stream
data: {"type": "delta", "text": "帮你找几款清爽不粘腻的防晒霜～"}

event: welcome_chat_stream
data: {"type": "end"}

event: products
data: {"product_id":"p_beauty_001","category":"美妆护肤","sub_category":"防晒霜"}

event: product_reason
data: "安热沙小金瓶——SPF50+，¥198，水感轻薄质地..."

event: ending_stream
data: {"type": "start"}

event: ending_stream
data: {"type": "end"}

event: next_options
data: ["有没有更平价的？","比较一下这几款的防晒指数"]

event: done
data: {"conversation_id":"550e8400-..."}
```

**Step 3：多轮对话（同一 conversation_id）**

```bash
curl -N "http://localhost:8000/api/search/<conversation_id>?q=要轻量不粘腻的"
```

系统自动加载历史记忆，上下文感知继续推荐。

**Step 4：场景化搜索**

```bash
# 需要先创建新会话获取新的 conversation_id
curl http://localhost:8000/api/conversation

curl -N "http://localhost:8000/api/search/<new_conversation_id>?q=下周去三亚度假，帮我搭配一套装备"
```

系统自动拆分为多品类（防晒霜、墨镜、沙滩裤、遮阳帽、凉鞋等）并行检索，逐品类推送。

**Step 5：查询商品详情**

```bash
# 商品基本信息
curl http://localhost:8000/api/products/p_beauty_001

# 商品图片
curl -o product.jpg http://localhost:8000/api/products/image/p_beauty_001

# 商品所有 SKU 变体
curl http://localhost:8000/api/all_skus/p_beauty_001

# 商品评价与 FAQ
curl http://localhost:8000/api/review/p_beauty_001

# 对话历史
curl http://localhost:8000/api/history/<conversation_id>
```

### 3.2 通过 Android App 体验

1. 启动后端服务（确保服务在 `http://localhost:8000` 运行）
2. 打开 Android 模拟器或连接真机
3. 启动 AuraCart App
4. 在聊天输入框输入查询，例如：
   - "推荐一款抗初老的精华液"
   - "200 元以内的蓝牙耳机"
   - "去海边旅游需要准备什么"
5. 观察流式欢迎语 → 品类介绍 → 商品卡片 → 推荐理由 → 结束语 → 追问标签的完整交互
6. 点击商品卡片查看详情（半屏/全屏），点击追问标签继续对话
7. 点击侧边栏查看历史对话、购物车等

### 3.3 体验场景速查

| 场景 | 查询示例 | 预期行为 |
|------|---------|----------|
| 单品类明确查询 | "推荐一款200元以下的防晒霜" | 单品类商品卡片横向排列 |
| 多轮对话 | 接上轮"要轻量的" | 自动融合历史偏好 |
| 场景化推荐 | "下周去三亚度假帮我搭配装备" | 多品类场景入口卡片 |
| 闲聊 | "今天天气怎么样" | 助手引导回购物话题 |
| 品牌约束 | "安热沙的防晒霜" | SQL 条件过滤 + 语义匹配 |

---

## 4. 常见问题

### 4.1 数据库连接失败

```text
sqlalchemy.exc.OperationalError: could not connect to server
```

**解决**：
- 确认 PostgreSQL 已启动：`docker ps | grep pg17`
- 检查 `config.yaml` 中 `database.host` / `port` 是否正确
- Docker 方式检查容器：`docker logs pg17-vector-zhparser`

### 4.2 中文分词不生效

**现象**：关键词检索返回空结果。

**解决**：
```bash
docker exec -it pg17-vector-zhparser psql -U postgres -d ecommerce -c "\dF+ chinese"
```

确认 `chinese` 配置存在且 PARSER 为 `zhparser`。如不存在，重新执行初始化 SQL。

### 4.3 LLM/Embedding API 调用失败

**现象**：`error` 事件或服务返回空结果。

**解决**：
- 确认 `.secrets.yaml` 中的 `api_key` 有效
- 确认 `config.yaml` 中的 `base_url` 可访问
- 查看 `server/log/` 目录下的日志文件获取详细错误

### 4.4 conversation not found

**现象**：SSE 流返回 `{"detail": "conversation not found"}`。

**解决**：
- 前端自动重建会话并重试当前查询
- 手动操作：重新调用 `GET /api/conversation` 获取新 ID

### 4.5 pgvector 扩展未安装

```text
sqlalchemy.exc.ProgrammingError: extension "vector" is not available
```

**解决**：
```sql
CREATE EXTENSION vector;
```

若提示找不到扩展，需在 PostgreSQL 中安装 pgvector 包。

### 4.6 Android 模拟器无法连接后端

**现象**：App 提示网络错误。

**解决**：
- 模拟器使用 `10.0.2.2` 映射宿主机 localhost（默认已配置）
- 真机调试需连接同一 WiFi，将 `BASE_URL` 改为电脑局域网 IP
- 确认后端服务在 `0.0.0.0:8000` 监听（`python run.py` 默认绑定所有接口）

### 4.7 端口冲突

```text
ERROR: [Errno 10048] address already in use
```

**解决**：
```bash
# 指定其他端口
python run.py --port 8080
```

---

## 5. 测试验证

```bash
cd server

# 运行全部测试
python -m pytest tests/ -v

# 跳过需要网络的测试
python -m pytest tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_llm.py

# 运行特定测试文件
python -m pytest tests/test_chat_message_persistence.py -v
python -m pytest tests/test_data_awareness.py -v
```

---

## 6. 开发模式

```bash
cd server

# 热重载 + 调试日志
python run.py --reload --log DEBUG

# 日志文件位置
tail -f server/log/app_*.log
```

---

