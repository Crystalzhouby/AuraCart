# /search/stream 查询优化 — 实现方案

## 1. 当前实现链路（分阶段描述）

### 阶段 1：查询分解 (Query Parse)

```
用户输入: "推荐一款200元以下的不含酒精的非日系防晒霜"
                │
                ▼
   query_parser.py: QueryParser.parse(user_query)
                │
                ├─ 构建 messages = [QUERY_PARSE_SYSTEM, user_query]
                ├─ llm.chat_stream(messages, temperature=0.1) → 流式收集完整响应
                ├─ _parse_response() 清洗 Markdown 围栏 → JSON → SubQuery[]
                │
                ▼
   输出: list[SubQuery]
   [
     SubQuery(text="防晒霜",       strategy="keyword",           negation=false),
     SubQuery(text="防晒效果",      strategy="semantic",          negation=false),
     SubQuery(text="不含酒精",      strategy="keyword",           negation=true),
     SubQuery(text="不要日系品牌",   strategy="structured_filter", negation=true, operator="not_in", expanded_values=[...])
   ]
```

当前 prompt（[prompt.py:23-57](server/app/rag/prompt.py#L23-L57)）将查询拆为 semantic/keyword/structured_filter 三类，每类可带 `negation` 标记。semantic 查询文本为名词短语（如"防晒效果"），非评价短句。

### 阶段 2：多策略检索 (Multi-Strategy Retrieval)

```
search.py 对每条 SubQuery 调用 retriever.retrieve(sub, top_k=20)
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
 semantic   keyword    structured_filter
    │           │           │
    │           │           └─► SQL WHERE 字段过滤 (in/lt/gt/contains/not_contains)
    │           │               → 返回 product_id + source + 固定 score=1.0
    │           │
    │           └─► tsvector @@ plainto_tsquery → ts_rank
    │               回退: ILIKE brand/category/title
    │               → 返回 product_id + source + rank
    │
    └─► pgvector cosine <=> 排序
        → 返回 product_id + source + similarity
```

三条路径各自独立执行，互不知晓对方的存在。结果按 `negation` 标记分流：`negation=false` 的结果进入 `all_hits[]`，`negation=true` 的结果收集 `negation_pids[]`。

### 阶段 3：合并排序 (Merge)

```
merger.merge(all_hits, negation_pids)
    │
    ├─ 1. 每条命中 × source_weight (faq:1.0, marketing:0.9, user_review:0.6, basic_info:0.4)
    ├─ 2. 按 product_id 分组，计算加权得分算术均值（"共识加成"）
    ├─ 3. 剔除 negation_pids 中的 product_id
    ├─ 4. 按最终得分降序 → 截取 top final_product_limit (默认 10)
    │
    ▼
   ranked_pids: ["p001", "p003", ...]
                │
                ▼
   _get_products(db, ranked_pids) → 逐 product 补全 Product + Sku 数据
                │
                ▼
   SSE event: "products" → JSON
```

### 阶段 4-5：LLM 生成 + 结束

- 阶段 4：`generator.generate(products, q)` 流式输出推荐理由 token，超时静默截断
- 阶段 5：`done` 或 `error` + `done`

---

## 2. 优化后实现链路

### 整体架构变更

```
用户查询: "推荐一款200元以下、防晒效果好、质地清爽的防晒霜"
                │
                ▼
   ┌─ 阶段1: Query Parse (prompt 重写，输出无 negation 的 SubQuery[]) ─┐
   │                                                                  │
   │  structured_filter: 品类=防晒霜, 价格≤200                         │
   │  keyword:           ["防晒霜"]                                    │
   │  semantic:          ["产品防晒效果是否出色", "产品质地是否清爽"]      │
   │                                                                  │
   └──────────────────────┬───────────────────────────────────────────┘
                          │
                          ▼
   ┌─ 阶段2: 双路并行检索 ────────────────────────────────────────────┐
   │                                                                  │
   │  提取 hard_filters: category="美妆护肤" AND price≤200              │
   │                                                                  │
   │  ┌─ keyword 路 ─────────────────┐  ┌─ semantic 路 ──────────────┐│
   │  │ ts_rank 检索                  │  │ 对每条 semantic 子查询独立  ││
   │  │ FROM product_review           │  │ 计算余弦相似度:             ││
   │  │ JOIN product ON ...           │  │ score_i = 1-(emb<=>:vec_i) ││
   │  │ JOIN sku ON ...               │  │ 综合得分 = sum(score_i)    ││
   │  │ WHERE hard_filters            │  │ FROM 同上三表 JOIN         ││
   │  │ ORDER BY ts_rank DESC         │  │ WHERE hard_filters         ││
   │  │ LIMIT top_k                   │  │ ORDER BY sum_score DESC    ││
   │  └───────────┬───────────────────┘  │ LIMIT top_k                ││
   │              │                      └───────────┬───────────────┘│
   │              ▼                                  ▼                │
   │   ranked_skus_kw[:K]              ranked_skus_sem[:K]            │
   │                                                                  │
   └──────────────────────┬───────────────────────────────────────────┘
                          │
                          ▼
   ┌─ 阶段3: RRF 融合 ────────────────────────────────────────────────┐
   │                                                                  │
   │  RRF(sku) = Σ 1/(k + rank_i)    (k=60, i ∈ {keyword, semantic}) │
   │                                                                  │
   │  按 RRF 得分降序 → 截取 Top K SKU                                 │
   │                                                                  │
   │  补全 Product + Sku 实时数据 → SSE event: "products"              │
   │                                                                  │
   └──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
              阶段4-5: LLM 生成 + done (不变)
```

### 关键变化对比

| 维度 | 当前 | 优化后 |
|------|------|--------|
| 检索结果单位 | product_id | sku_id |
| structured_filter 定位 | 独立检索路径，产出结果 | SQL WHERE 硬约束，不单独产出结果 |
| semantic 子查询关系 | 各查各的，加权平均合并 | 独立打分后加和为综合得分 |
| keyword + semantic 关系 | 独立查，加权平均合并 | 双路并行，RRF 排名融合 |
| negation 处理 | 独立检索 → 事后排除 | 不存在此字段。结构化否定=SQL NOT 条件；内容否定=语义相似度自然降权 |
| SQL JOIN 范围 | keyword: product_review+product; semantic: product_review+product | 统一三表 JOIN: product_review + product + sku |
| merger 逻辑 | source 加权 → 算术均值 → 排除 negation | RRF 融合，无 negation_pids 参数 |
| prompt 输出 | semantic 为名词短语，含 negation 标记 | semantic 为评价短句，无 negation 标记 |

---

## 3. 主要优点

1. **检索精度提升**：structured_filter 作为硬约束确保不满足用户明确要求的商品不会出现（如价格>200 的商品绝不返回），比"事后排除"更可靠
2. **多意图融合**：多 semantic 独立打分加和能捕捉用户的多维偏好（"防晒效果好"+"质地清爽"），单一向量查询无法同时表达多个独立维度
3. **RRF 免校准**：keyword 的 ts_rank 和 semantic 的 cosine similarity 尺度完全不同，RRF 只关心排名不关心原始分数，天然适合异构检索源融合
4. **SKU 粒度**：用户购买的是 SKU 而非产品，SKU 级结果可展示具体变体的价格/库存，用户体验更好
5. **管线简化**：移除 negation 标记消除了独立的否定检索路径和事后排除逻辑，检索结果集就是最终结果集
6. **零外部依赖**：ts_rank 替代 BM25，RRF 纯 Python 计算，不引入新扩展或服务

---

## 4. 主要风险

| 风险 | 概率 | 缓解策略 |
|------|------|----------|
| prompt 重写后 LLM 输出质量下降 | 中 | 保留旧 prompt 作为回退模板；用 5-10 条典型查询做回归对比 |
| 三表 JOIN + 多向量 `<=>` 计算延迟超预期 | 低 | N 通常 ≤3，向量计算在 PG 内完成无数据传输开销；可加 EXPLAIN ANALYZE 验证 |
| 语义否定覆盖不全 | 中 | 已在 DEFINE 中标记为可接受精度损失，不阻塞交付 |
| RRF k=60 不适合本数据集 | 低 | k 值对最终排序不敏感（影响的是极端排名差异的权重），k=60 是业界通用值 |
| 测试适配工作量大 | 中 | 优先适配核心路径测试，非核心用例可暂时 skip 并标记 TODO |

---

## 5. 实现复杂度

### 按模块拆分

| 模块 | 变更量 | 复杂度 | 说明 |
|------|--------|--------|------|
| `prompt.py` | 重写 `QUERY_PARSE_SYSTEM` | 中 | 纯文本变更，但需多轮调试验证输出质量 |
| `retriever.py` | 重构检索策略 | **高** | 最复杂模块：hard_filters 提取、三表 JOIN、多 semantic sum 单 SQL、keyword 路 SQL 构建 |
| `merger.py` | 重写为 RRF | 低 | RRF 公式 ~10 行，纯函数，无外部依赖 |
| `search.py` | 适配新编排 | 中 | 移除 negation_pids、适配新 retriever/merger 接口、调整 SSE 输出为 SKU |
| `query_parser.py` | 移除 negation | 低 | 删除 `_parse_response` 中的 `negation` 字段映射 |
| `config.yaml` | search 组调整 | 低 | 移除 source_weights、新增 rrf_k、调整 top_k 语义 |
| 测试文件 | 适配接口变更 | 中 | 接口签名变更导致多数测试需微调 |

### 总复杂度：中高

核心难点在 `retriever.py` 的动态 SQL 构建——需要根据 structured_filter 子查询的字段分布（product 表 vs sku 表）决定 JOIN 结构和 WHERE 子句。建议先在 retriever 内部写一个独立的 `_build_filtered_query()` 方法，封装这一复杂性。

---

## 6. 可测试性

### 各模块测试策略

| 模块 | 测试类型 | 说明 |
|------|----------|------|
| `prompt.py` | 单元（mock LLM） | 给定 mock 响应，验证 `_parse_response` 正确解析无 negation 字段的 SubQuery |
| `retriever.py` | 集成（真实 PG） | 用 fixture 数据验证三表 JOIN SQL 正确性、hard_filters 过滤效果、多 semantic sum 得分计算 |
| `merger.py` | **纯单元** | RRF 是纯数学函数，给定两组排名输入验证融合输出，无需 DB/网络。测试最简单 |
| `search.py` | 集成（SSE 流） | 端到端验证 SSE 事件序列、SKU 级输出结构、超时降级 |
| `query_parser.py` | 单元（mock LLM） | 验证新 prompt 模板渲染、SubQuery 字段正确映射 |

### 测试友好度评估

- **merger**: 最佳 — 纯函数，输入输出确定，可 100% 覆盖
- **retriever**: 需 PG fixture，但 SQL 结果是确定的
- **prompt**: 依赖 LLM 输出（不确定），建议 mock + 少量真实调用回归
- **search.py**: 端到端 SSE 测试，需启动完整服务

---

## 7. 可交付性

### 推荐交付顺序（四步，每步独立可验证）

```
Step A: 数据结构 + prompt 变更（不改变检索行为）
  ├─ query_parser.py: SubQuery 移除 negation
  ├─ prompt.py: 重写 QUERY_PARSE_SYSTEM
  └─ 验证: 运行 query_parser 单元测试，手工检查 prompt 输出质量
        └─ 交付物: 无行为变更，可安全合入

Step B: merger 重写（独立模块，无外部依赖）
  ├─ merger.py: RRF 融合替代加权均值
  └─ 验证: 纯单元测试，给定输入验证输出
        └─ 交付物: 可独立合入，不影响现有管线

Step C: retriever 重构（核心变更）
  ├─ retriever.py: hard_filters 提取 + 三表 JOIN + 多 semantic sum + keyword 路
  └─ 验证: 集成测试，EXPLAIN ANALYZE 性能检查
        └─ 交付物: 本步最重，建议单独 PR

Step D: search.py 编排 + config + 端到端验证
  ├─ search.py: 适配新 retriever/merger 接口，SSE 输出调整为 SKU
  ├─ config.yaml: search 组更新
  └─ 验证: 全链路 curl 测试，日志检查
        └─ 交付物: 功能完整
```

### 每步之间无强依赖

- Step A 和 Step B 可并行开发
- Step C 依赖 A（SubQuery 结构），不依赖 B（merger 接口独立）
- Step D 依赖 A+B+C

### 回滚策略

- `config.yaml` 中新增 `search.rrf_k` 和 `search.use_optimized_pipeline` 开关（默认 false）
- Step A-C 合入后不影响线上，Step D 合入后通过开关激活
- 旧 merger 和旧 retriever 逻辑在 Step C/D 中标记 deprecated，保留一个版本后删除
