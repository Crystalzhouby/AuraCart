# 优化推荐理由生成 — 问题定义

> 来源：[SPEC.md](SPEC.md) | 日期：2026-05-30

---

## 1. 最终交付物

1. **检索阶段返回匹配文本**：语义检索和关键词检索阶段，除 `sku_id` / `product_id` / `score` 外，同步返回命中的 `product_review` 行的 `content`、`source`、`metadata` 字段（即匹配到的评论/营销描述/FAQ原文）。
2. **LLM 生成上下文增强**：将 top-k 商品关联的匹配文本注入 `Generator` 的上下文，使 LLM 推荐理由生成时能引用真实的用户评价、营销卖点、FAQ 内容。
3. **索引检查与按需补充**：确认 `product_review` 表上是否存在 HNSW 向量索引（语义检索加速）和 GIN 全文索引（关键词检索加速）；若缺失，输出建议 DDL（是否实际创建由用户决定）。

---

## 2. 硬约束

1. **不改变 RAG 管线外部接口**：`GET /api/search?q=...&stream=true|false` 的请求/响应 schema 保持兼容，SSE 事件类型（`sub_queries` / `products` / `reasoning` / `done`）不增不减。
2. **不改变检索排序逻辑**：RRF 融合算法、`SKUHit` 得分计算、`final_sku_limit` 截断逻辑保持原样。
3. **不改变数据库 schema**：不在 `product_review` 或其他表上新增列；索引创建为可选项（输出建议 DDL，不在代码中自动执行）。
4. **LLM 上下文长度限制**：`config.yaml` 中 LLM 的 max_tokens 和上下文窗口约束必须遵守。新增的评论文本可能导致 token 超限，需有截断策略。
5. **不引入额外的 LLM 调用**：匹配文本直接从数据库已有字段读取，不额外调用 LLM 做摘要/重写。

---

## 3. 隐含要求

1. **匹配文本需标注来源**：注入 LLM 的评论文本需标明 `source`（marketing / faq / user），便于 LLM 区分"官方营销描述"vs"用户评价"并调整推荐语气。
2. **文本去重**：同一 `product_id` 下多条 `product_review` 行可能内容高度相似，需做基础去重或截断，避免 LLM 上下文被重复信息占满。
3. **按匹配得分截断**：当匹配文本总量超出上下文预算时，优先保留高得分（语义相似度 / ts_rank）的文本行，而非随机截断。
4. **向后兼容**：若检索结果中无匹配文本（如仅通过 structured_filter 命中），LLM 生成退化到当前行为（仅用商品基本信息），不报错。
5. **日志可观测**：在 structlog 中记录每条 SKU 携带的匹配文本行数和总字符数，便于调试生成质量。

---

## 4. 任务完成边界

### 范围内

| 项 | 说明 |
|---|------|
| 修改 `Retriever._semantic_search` | 返回结果增加 `content` / `source` / `metadata` 字段 |
| 修改 `Retriever._keyword_search` | 返回结果增加 `content` / `source` / `metadata` 字段 |
| 修改 `SKUHit` 或新建数据结构 | 【不确定】是否扩展 `SKUHit` dataclass，还是用并行 dict 传递匹配文本 |
| 修改 `Merger.merge`（如需要） | 在 RRF 融合时保留匹配文本不丢失 |
| 修改 `_get_skus` 或新增查询 | 按 top-k sku_id 回查 `product_review` 表获取匹配文本 |
| 修改 `Generator._build_context` | 将匹配文本格式化注入上下文模板 |
| 修改 `GENERATOR_SYSTEM` prompt | 增加匹配文本的使用指引 |
| 添加文本截断逻辑 | 基于 token 预算的截断策略 |
| 索引检查 | 查询现有索引，输出 HNSW/GIN 建议 DDL |
| 更新测试 | 补充/修改 `test_search.py` 和 `test_demo.py` |

### 范围外

- 不新增 LLM 调用做文本摘要/重写
- 不新增 API 端点
- 不修改前端/客户端
- 不改变 `product_review` 表结构
- 不自动执行索引创建 DDL
- 不修改 RRF 融合算法本身

---

## 5. 潜在风险点

| 风险 | 影响 | 缓解方向 |
|------|------|----------|
| **LLM 上下文超限**：匹配文本（尤其是长营销描述+多条评价）总量可能远超 LLM context window | 生成失败或截断丢失关键信息 | 设计 token 预算分配策略（如产品信息占 40%，匹配文本占 60%），超出部分按 score 截断 |
| **响应延迟增加**：`_get_skus` 需额外查询 `product_review` 表，或 retriever SQL 返回更多列 | 端到端延迟增加 | 【不确定】是否可合并到现有 JOIN 查询中一次完成，还是需要额外 DB round-trip |
| **现有 `SKUHit` 数据类扩散**：`SKUHit` 目前是轻量 dataclass，加入 text 字段后会在 merger → _get_skus → generator 全链路传递，可能影响所有引用方 | 改动面大 | 权衡是否新建 `MatchContext` 结构做并行传递 |
| **全文索引缺失导致 keyword 检索慢**：确认 migration 中无 GIN 索引，ILIKE 降级时对 `product_review.content` 的扫描是全表 | 关键词检索延迟高 | 输出建索引 DDL 作为可选建议 |
| **HNSW 索引缺失导致语义检索慢**：migration 中无 HNSW 索引，pgvector 顺序扫描 | 语义检索延迟随数据量线性增长 | 输出建 HNSW 索引的 DDL；100 商品规模下暂不紧急，但扩量后成为瓶颈 |
| **prompt 注入风险**：用户评价内容可能包含对抗性文本，注入 LLM 上下文后可能影响生成行为 | 生成质量下降或输出不当内容 | 【不确定】是否需要做文本过滤/清洗，还是信任 LLM 的 system prompt 约束 |

# 针对不确定点的回答

1.匹配文本用扩展 SKUHit 还是新建并行结构传递
用并行 dict 传递匹配文本

2._get_skus 的额外查询能否合并到现有 JOIN 一次完成
合并到现有的SQL语句一次完成。

3.用户评价内容是否需要做文本过滤/清洗
暂不需要


# 针对不同来源的商品评论信息做信息优化 — 问题定义

> 来源：[SPEC.md](SPEC.md) 第二节 | 日期：2026-05-30

---

## 1. 最终交付物

1. **来源权重配置**：`config.yaml` 中新增各 source 的检索权重配置项（如 `marketing`、`user_review`、`faq` 各自独立权重），支持运行时调整。
2. **检索得分加权改造**：语义检索（`_semantic_search`）和关键词检索（`_keyword_search`）的得分计算从"各 product_review 行等权累加"改为"按 source 加权后累加"：`final_score = Σ(source_weight_i × match_score_i)`。
3. **Config 模型扩展**：`SearchSettings` 新增 source_weights 字段，从 `config.yaml` 读取。

---

## 2. 硬约束

1. **不改变 RRF 融合逻辑**：加权发生在 Retriever 内部（RRF 之前），RRF 公式和参数（k=60）保持不变。
2. **不改变 API 接口**：`GET /api/search` 请求/响应 schema 不变，SSE 事件类型不变。
3. **不改变 DB schema**：不在 `product_review` 表新增列，source 字段值不变。
4. **权重要可配置**：不在代码中硬编码具体权重值，从 `config.yaml` 读取。
5. **DB source 实际值为准**：SPEC 中提到的 `marketing_description`/`official_faq`/`user_reviews` 为概念名称，**实现时以 DB 中实际存储的 `marketing`/`faq`/`user_review` 为准**。

---

## 3. 隐含要求

1. **权重缺省安全值**：未在配置中指定权重的 source，默认权重为 1.0（等权，与当前行为兼容）。
2. **零权重的语义**：权重设为 0 表示该 source 的匹配文本不参与检索得分计算（但不影响该 source 的文本仍可被检索到并返回给 LLM 使用）。
3. **与上下文截断的解耦**：检索阶段的 source 权重（影响排序）与 LLM 上下文阶段的 `_SOURCE_PRIORITY`（影响哪些文本优先注入 prompt）是两个独立维度，互不干扰。
4. **SQL 层面加权**：加权计算应在 SQL 中完成（CASE WHEN source = 'xxx' THEN weight ELSE ...），避免在 Python 中二次遍历。
5. **日志可观测**：structlog 中记录加权后的各 source 贡献分布，便于权重调优。

---

## 4. 任务完成边界

### 范围内

| 项 | 说明 |
|---|------|
| `config.yaml` 新增 source_weights | 如 `search.source_weights.marketing: 1.0` 等 |
| `SearchSettings` 新增字段 | `source_weights: dict[str, float]`，默认 `{}`（即全部 1.0） |
| 修改 `Retriever._semantic_search` | SQL 得分表达式加入 source 权重因子 |
| 修改 `Retriever._keyword_search` | SQL 得分表达式加入 source 权重因子 |
| **修复已发现的 source 值 bug** | `_SOURCE_PRIORITY` 中 `"user"` → `"user_review"`，与 DB 实际值对齐 |
| 更新测试 | 补充加权得分计算、零权重、缺省权重的测试用例 |

### 范围外

- 不修改 RRF 融合算法
- 不修改 `_truncate_texts` 优先级（那是上下文阶段的独立逻辑）
- 不修改 `SOURCE_LABEL` 映射
- 不修改 Merger / Generator / _get_skus
- 不新增 API 端点
- 不修改前端

---

## 5. 潜在风险点

| 风险 | 影响 | 缓解方向 |
|------|------|----------|
| **权重调优无基准**：SPEC 提议 user_review=0.7 但无数据支撑 | 推荐排序可能劣化（好的用户评价被降权） | 先以当前等权行为为基线，权重值作为可配置项，通过 A/B 对比验证 |
| **source 值不一致 bug**：现有代码 `_SOURCE_PRIORITY` 使用 `"user"` 但 DB 存储 `"user_review"`，导致用户评价被当作未知来源（优先级 99）排到末尾 | LLM 上下文中用户评价被错误降权，推荐理由缺少用户真实反馈 | **本次一并修复**，改 `"user"` → `"user_review"`；同时 `SOURCE_LABEL` 也需确认是否受影响 |
| **SPEC 与 DB 命名不一致**：SPEC 中 `marketing_description`/`official_faq`/`user_reviews` vs DB 中 `marketing`/`faq`/`user_review` | 如果按 SPEC 字面值配置权重，会匹配不到任何行 | **标注为待确认**：建议以 DB 实际值为准，SPEC 中的名称为概念性描述 |
| **SQL CASE WHEN 复杂度**：多个 source + 多个 subquery 的加权组合可能使 SQL 冗长 | SQL 可读性下降，调试困难 | 将权重参数化绑定（`:weight_marketing` 等），不在 SQL 中硬编码 |
| **零权重行为边界**：权重为 0 时，SQL 中 `score * 0 = 0`，该行对 SUM 无贡献但仍被 GROUP BY 包含 | 零权重 source 的匹配行白白占用 DB 扫描 | 【不确定】是否需要在 WHERE 中排除 weight=0 的 source 以减少扫描行数，还是保持简单先不过滤 |
