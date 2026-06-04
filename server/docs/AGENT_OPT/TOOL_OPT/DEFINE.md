# DEFINE.md — Agent Tool 优化需求分析

> 输入：[SPEC.md](SPEC.md) | 日期：2026-06-04

## 1. 功能需求

### FR1: 数据库查询 Tool（3 个）

| ID | 功能 | 说明 |
|----|------|------|
| FR1.1 | `list_tables` | 查询 ecommerce 数据库下所有表，返回表名及每张表存储内容的描述 |
| FR1.2 | `list_fields` | 查询指定表的所有字段，返回字段名、类型、含义描述 |
| FR1.3 | `query_field_values` | 查询指定表的某个字段有哪些取值，支持多字段联合过滤（如 `category='面部护肤' AND sub_category='防晒霜'` 条件下查 `brand` 取值） |

**调用方式：** Agent 节点内部 Python 函数直接调用，不走 LLM function calling。Tool 输出格式已确认（见 SPEC.md 核对记录）。

### FR2: 目录结构调整

| ID | 功能 | 说明 |
|----|------|------|
| FR2.1 | 移动 `rag/prompt.py` | 将 `server/app/rag/prompt.py` 移至 `server/app/agent/prompts/` 下，统一提示词管理 |

### FR3: Router 节点重构

| ID | 功能 | 说明 |
|----|------|------|
| FR3.1 | 保留现有两级分类 | 闲聊 vs 商品查询 → 明确商品查询 vs 场景化查询 |
| FR3.2 | 新增查询改写 | 识别为"商品查询"后，利用历史对话记录通过 LLM 改写当前查询（补充查询主体） |
| FR3.3 | 完整查询透传 | 若当前查询已完整（不缺少主体），LLM 不做改写，直接透传 |
| FR3.4 | 输出改写结果 | 改写后的查询传递给 extraction 和 scenario_gen 节点 |

**改写示例：**
```
历史: "帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"
当前: "要轻量的"
改写: "要轻量的跑鞋"（补充主体"跑鞋"）

历史: "帮我推荐跑鞋" → "要轻量的"
当前: "预算 500 以内"
改写: "预算 500 以内的跑鞋"（补充主体"跑鞋"）
```

### FR4: Extraction 节点重构

| ID | 功能 | 说明 |
|----|------|------|
| FR4.1 | Step 1: 提取品类/品牌意图 | 从改写后的查询中提取 brand/category/sub_category，借助 Tool 函数查询合法取值 |
| FR4.2 | Step 2: 检索历史并拼接 | 从 memory 按 (category,sub_category) 检索历史原始查询，与当前改写查询按时间顺序平铺拼接 |
| FR4.3 | Step 3: 分组提取意图 | 按 (category,sub_category) 分组，提取 structured_filter（price/stock）和 semantic（主观感受+客观属性）条件 |
| FR4.4 | 冲突处理 | 历史与当前查询意图冲突时，以时间靠后的为准（如先说不超 200 后说不超 300 → 不超 300） |
| FR4.5 | 移除 keyword 分支 | 不再生成 strategy="keyword" 的子查询 |
| FR4.6 | 新输出格式 | 按品类分组的意图列表（见下方） |

**输出格式（已确认）：**
```json
[
  {
    "category": "面部护肤",
    "sub_category": "防晒霜",
    "text": "不含酒精、不粘腻、适合敏感肌",
    "min_price": 0,
    "max_price": 200,
    "order_num": 1,
    "brand": ["安热沙", "资生堂"]
  }
]
```

### FR5: Retrieval 节点重构

| ID | 功能 | 说明 |
|----|------|------|
| FR5.1 | 按品类分组检索 | 每个 (category,sub_category) 意图独立检索 |
| FR5.2 | SQL 条件转换 | category/sub_category/min_price/max_price/brand → SQL WHERE；order_num → stock ≥ order_num |
| FR5.3 | 语义检索 | SQL 条件 + text embedding 余弦相似度，返回 top-25 |
| FR5.4 | 关键词检索 | SQL 条件 + `plainto_tsquery('chinese', ...)` + tsvector，返回 top-25 |
| FR5.5 | RRF 融合 | 语义权重 0.7 + 关键词权重 0.3，取 top-25 |
| FR5.6 | 精排重排序 | bge-reranker-v2-m3（SiliconFlow API）精排，取 top-5 |
| FR5.7 | SKU 去重 | 同 product_id 多个 SKU 满足时，取 sku_id 字典序最小的 |
| FR5.8 | Review 截断 | 单 product_id 最多保留 5 条 product_review |
| FR5.9 | 参数可配置 | 以上阈值均可在 config.yaml 中配置，替换现有重叠参数（如 `top_k_per_query`、`final_sku_limit`） |

### FR6: 会话记忆系统重构

| ID | 功能 | 说明 |
|----|------|------|
| FR6.1 | 存储原始查询 | 存储用户发送的原始查询（非改写后、非提取意图），按 (category,sub_category) 分组 |
| FR6.2 | Router 检索 | 检索该会话最近 N 轮历史原始查询（N 可配置），用于改写当前查询 |
| FR6.3 | Extraction 检索 | 按 (category,sub_category) 检索历史原始查询，与当前查询拼接后提取意图 |
| FR6.4 | Scenario_gen 检索 | 先从改写后查询确定相关品类列表，再按各 (category,sub_category) 检索历史原始查询，拼接后生成 sub_queries |
| FR6.5 | Retrieval 更新 | 检索完成后，将原始查询按 (category,sub_category) 累加到 memory |
| FR6.6 | 记忆数据结构 | 数组形式，每个元素包含 category、sub_category、queries 列表（见下方） |

**记忆数据结构（已确认）：**
```json
[
  {
    "category": "服饰运动",
    "sub_category": "跑步鞋",
    "queries": [
      {"query": "帮我推荐跑鞋", "timestamp": "2026-06-04T10:00:00"},
      {"query": "要轻量的", "timestamp": "2026-06-04T10:01:00"}
    ]
  }
]
```

## 2. 性能需求

| ID | 需求 | 说明 |
|----|------|------|
| PR1 | Reranker API 超时 | bge-reranker 调用需设置超时，失败时有降级策略 |
| PR2 | 并行检索 | 多品类并行检索，复用现有 `asyncio.Semaphore` 模式 |
| PR3 | Tool 响应时间 | 3 个 Tool 为纯数据库查询，响应应在 100ms 内 |

## 3. 最终交付物

1. 新增 `server/app/agent/tools.py` — 3 个数据库查询 Tool 函数
2. 移动后的 `server/app/agent/prompts/` — 包含原 `rag/prompt.py` 的内容
3. 重构后的节点文件：`router.py`、`extraction.py`、`retrieval.py`
4. 重构后的 `memory.py` — 新的记忆存取接口
5. 更新后的 `state.py` — 新增字段（如 `rewritten_query`）
6. 更新后的 `graph.py` — 适配新的数据流
7. 更新后的 `config.yaml` — 新增检索参数
8. 更新/新增的测试文件

## 4. 硬约束

| ID | 约束 |
|----|------|
| HC1 | 数据库 schema 不变（8 张表结构不修改） |
| HC2 | bge-reranker-v2-m3 走 SiliconFlow API（`https://api.siliconflow.cn/v1`），不本地部署 |
| HC3 | 不引入 hanlp，关键词检索继续使用 PostgreSQL 内置 `plainto_tsquery('chinese', ...)` |
| HC4 | Tool 为内部 Python 函数调用，不走 LLM function calling |
| HC5 | Python 3.12+ / LangGraph StateGraph / SQLAlchemy 2.0 async |
| HC6 | 现有 chitchat 节点、option_gen 节点逻辑不变（仅可能调整输入来源） |

## 5. 隐含要求

| ID | 要求 |
|----|------|
| IR1 | 现有 113+ 离线测试尽量保持通过，最小化破坏性变更 |
| IR2 | Config 新参数不与已有参数重复，复用现有的 `rrf_k`、`final_sku_limit`、`max_match_texts_per_sku` 等 |
| IR3 | Extraction 输出格式变更需协调下游所有消费方（retrieval、option_gen、memory） |
| IR4 | 已有 Conversation 会话的旧格式 memory 需兼容或迁移 |

## 6. 任务完成边界

**包含：**
- 3 个 Tool 函数的实现
- 目录结构调整（prompt.py 移动）
- Router / Extraction / Retrieval 节点重构
- 会话记忆系统重构（存储、检索、更新）
- AgentState 适配
- config.yaml 新增参数
- 相关测试更新

**不包含：**
- hanlp 分词器部署
- bge-reranker 本地部署（已确认走云端 API）
- chitchat / option_gen 节点逻辑变更
- 数据库 schema 变更
- 新增 API 端点

## 7. 风险点

| ID | 风险 | 影响 | 缓解措施 |
|----|------|------|----------|
| RK1 | bge-reranker API 不可用 | 检索结果质量下降 | API 失败时跳过精排，直接用 RRF top-5 作为 fallback |
| RK2 | 记忆结构变更 | 已有会话数据不兼容 | 读取时做格式兼容判断，旧格式空数组视为无历史 |
| RK3 | 多节点协同变更 | 集成联调复杂，易出 bug | 按节点顺序开发，每步跑测试；router → extraction → retrieval → memory |
| RK4 | Extraction 输出格式变更 | 下游 retrieval / option_gen 消费旧字段 | 统一修改所有消费方，去除对 `strategy`/`field`/`operator`/`value` 的依赖 |
| RK5 | Router 改写质量 | 改写不准确导致后续提取偏差 | LLM 改写 + 完整查询透传策略降低风险 |

## 8. 澄清确认记录

以下为设计过程中与用户确认的关键决策（已同步到 SPEC.md 和 DEFINE.md）：

| # | 事项 | 确认结果 |
|----|------|----------|
| 1 | SPEC 残留描述 | SPEC.md 已更新，记忆不再存储意图信息，仅存储原始查询数据 |
| 2 | Scenario_gen 检索 memory | 先从改写后查询确定相关品类列表 → 再按品类检索 memory → 拼接后生成 sub_queries |
| 3 | Router 检索历史范围 | 检索该会话最近 N 轮查询（N 可配置，建议默认 10） |
| 4 | SKU 去重排序 | 按 sku_id 字典序取最小 |
| 5 | Config 参数处理 | 替换现有重叠参数（`top_k_per_query`、`final_sku_limit`），不叠加 |
| 6 | Tool 输出格式 | 3 个 Tool 的输出格式已确认（见 SPEC.md 核对记录） |
| 7 | 记忆数据结构 | 数组形式，每元素含 category、sub_category、queries 列表 |
| 8 | 查询改写范围 | 全部商品查询都做 LLM 改写，完整查询提示词中注明不做改写（透传） |
| 9 | 历史拼接方式 | 按时间顺序编号的平铺文本，冲突以后续意图为准 |
| 10 | 新品类无历史 | 仅基于当前改写查询提取意图 |
