# 优化推荐理由生成 — 实现方案

> 来源：[DEFINE.md](DEFINE.md) | 日期：2026-05-30

---

## 总体策略

**原则：稳定交付优先，最小化改动面，性能优化按需追加。**

核心思路 —— 不在检索阶段（Retriever）改动 SQL 或 SKUHit，而是在数据补全阶段（`_get_skus`）通过一条扩展 SQL 将 `product_review` 的评论文本一并查出，聚合后以 `matched_texts` 字段挂到每个 SKU dict 上，最后在 Generator 中格式化注入 LLM 上下文。

```
                        ┌── 不改 ──┐                ┌── 不改 ──┐
Retriever.retrieve()  →  Merger.merge()  →  _get_skus()  →  Generator.generate()
                                                  │                  │
                                             ★ 扩展 SQL      ★ 注入 matched_texts
                                             ★ 聚合文本       ★ prompt 更新
                                             ★ 截断控制       ★ 截断兜底
```

改动涉及 5 个文件：

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `app/api/search.py` | 修改 | `_get_skus` SQL 扩展 + Python 聚合 |
| `app/rag/generator.py` | 修改 | `_build_context` 追加 matched_texts 段落 |
| `app/rag/prompt.py` | 修改 | `GENERATOR_SYSTEM` 增加评论文本使用指引 |
| `config.yaml` | 新增项 | `search.max_match_texts_per_sku` / `search.max_match_chars_per_sku` |
| `app/config.py` | 新增项 | `SearchSettings` 增加对应字段 |

不改动的文件：`retriever.py`、`merger.py`、`schemas/product.py`、所有 ORM 模型、数据库 migration。

---

## 功能点 1：_get_skus SQL 扩展 + matched_texts 聚合

### 概要链路

```
当前 SQL（2 表 JOIN）:
  SELECT p.*, s.*
  FROM product p JOIN sku s ...
  WHERE s.sku_id IN (:ids)

改造后 SQL（3 表 LEFT JOIN）:
  SELECT p.*, s.*, pr.content, pr.source, pr.metadata
  FROM product p
  JOIN sku s ON s.product_id = p.product_id
  LEFT JOIN product_review pr ON pr.product_id = p.product_id
  WHERE s.sku_id IN (:ids)
    AND s.is_active = TRUE
    AND p.is_active = TRUE

Python 聚合:
  for row in rows:
      if row.sku_id not in seen:
          创建基础 dict（product + SKU 字段）
      if row.content:
          追加 {"content": ..., "source": ..., "metadata": ...} 到 matched_texts

截断:
  每个 SKU 的 matched_texts:
    1. 按 source 优先级排序: user > faq > marketing
    2. 截取前 max_match_texts_per_sku 条（默认 3）
    3. 截取总字符数不超过 max_match_chars_per_sku（默认 500）
```

### 主要优点
- 1 次 DB 往返完成，不引入额外查询
- `SKUHit`、`Merger`、`Retriever` 零改动
- LEFT JOIN 保证无评论文本时不会丢 SKU（退化到原行为）

### 主要风险
- `product_review` 表行数膨胀后（10 万商品 × 10 条评论 = 100 万行），LEFT JOIN 返回的行数增加。当前 100 商品规模完全无影响；**缓解**：Python 侧截断保证内存占用可控
- 返回的评论文本未按检索得分排序（因为 _get_skus 阶段已丢失匹配得分信息）→ 用 source 优先级代替

### 实现复杂度：**低**
- SQL 加一个 LEFT JOIN，Python 加 15 行聚合逻辑
- 改动完全局限在 `_get_skus` 一个函数内

### 可测试性：**高**
- 输入：`list[SKUHit]` + mock DB rows（含 product_review 列）
- 输出：`list[dict]`，每个 dict 的 `matched_texts` 字段可精确断言
- 边界 case 明确：空 SKUHit、无 product_review 行、超长文本、超多行

### 可交付性：**高**
- 独立函数，可单独提交和验证
- 不依赖后续步骤即可验证 SQL 正确性和聚合逻辑

---

## 功能点 2：Generator._build_context 扩展

### 概要链路

```
当前 _build_context 输出:
  1. 安耐晒小金瓶防晒霜
     品牌: 安耐晒
     品类: 美妆护肤
     基础价格: ¥198.00
     - SKU SKU001_60ml: ¥198.00 (容量: 60ml)

改造后追加 matched_texts 段落:
  1. 安耐晒小金瓶防晒霜
     品牌: 安耐晒
     ...
     - SKU SKU001_60ml: ¥198.00 (容量: 60ml)

     【用户评价与描述】
     [用户评价] 这个防晒霜保湿效果真的好，冬天用也不干
     [官方描述] 添加玻尿酸保湿成分，防晒同时滋养肌肤
     [FAQ] Q:干皮能用吗 A:适合所有肤质，含保湿精华
```

source 映射：
- `user` → `[用户评价]`
- `marketing` → `[官方描述]`
- `faq` → `[FAQ]`

无 matched_texts 或为空列表时，不输出 `【用户评价与描述】` 段落，行为完全退化。

### 主要优点
- `_build_context` 是纯文本拼接函数，改动为追加式，不影响现有输出
- source 标签让 LLM 能区分信息权威性（官方 vs 用户）

### 主要风险
- 评论文本中可能含特殊字符（如 markdown 语法）干扰 LLM 解析 → **缓解**：不做清洗（DEFINE.md 已确定），依赖 LLM system prompt 约束
- 商品基本信息 + matched_texts 总 token 超限 → **缓解**：功能点 1 的截断已在源头控制；功能点 4 的 prompt 更新增加长度警示

### 实现复杂度：**低**
- `_build_context` 末尾追加 8 行文本拼接逻辑
- source → label 映射用 dict 常量

### 可测试性：**高**
- 纯函数：`list[dict]` → `str`
- 可精确断言输出字符串包含 expected 子串
- 空 matched_texts、单条、多条、超长内容均可覆盖

### 可交付性：**高**
- 不依赖其他功能点即可单独验证

---

## 功能点 3：配置项新增

### 概要链路

```
config.yaml 新增:
  search:
    max_match_texts_per_sku: 3    # 每个 SKU 最多附带几条评论文本
    max_match_chars_per_sku: 500  # 每个 SKU matched_texts 总字符数上限

config.py SearchSettings 新增:
  max_match_texts_per_sku: int = 3
  max_match_chars_per_sku: int = 500

search.py _get_skus 引用:
  limit = settings.search.max_match_texts_per_sku
  char_limit = settings.search.max_match_chars_per_sku
```

### 主要优点
- 截断参数可调，无需改代码
- 默认值保守（3 条/500 字符），适合首次交付

### 主要风险
- 默认值过于保守时推荐理由提升不明显 → 交付后根据实际效果调参

### 实现复杂度：**低**
- 2 个 int 字段，YAML + Pydantic 各加一行

### 可测试性：**高**
- 配置加载测试已有框架，加断言即可

### 可交付性：**高**

---

## 功能点 4：GENERATOR_SYSTEM prompt 更新

### 概要链路

在现有 prompt 规则块中追加两条指引：

```
当前:
  ## 规则
  1. 只能使用以下提供的商品信息...
  2. 如果商品信息不足以满足...
  3. 推荐时说明推荐理由，引用商品的真实属性
  4. 以自然、友好的语气回复
  5. 不要提及"根据检索结果"等元表述

追加:
  6. 商品信息中附带【用户评价与描述】段落时：
     a. 优先引用用户评价中的真实体验作为推荐依据
     b. 区分"官方描述"（品牌声称）和"用户评价"（真实反馈），
        用户评价的权重高于官方描述
     c. 如果用户评价与官方描述矛盾，以用户评价为准
  7. 推荐理由控制在 200 字以内，简洁有据
```

### 主要优点
- 约束 LLM 正确使用新增的评论文本
- 规则 7（长度控制）间接缓解 token 超限风险
- prompt 改动独立，可单独 A/B 测试

### 主要风险
- LLM 对 prompt 指令的遵循度不稳定，可能仍然忽略 matched_texts → **缓解**：这是 prompt engineering 的固有不确定性，通过实际查询效果观察迭代
- 规则 7 "200 字"是硬编码 → **缓解**：中文推荐 200 字足够，后续可参数化

### 实现复杂度：**低**
- 纯文本修改

### 可测试性：**低**
- LLM 输出非确定性，需要人工评估推荐理由是否引用了用户评价
- 可做 smoke test：检查 reasoning 事件中是否出现商品/评价关键词

### 可交付性：**高**
- 独立修改，不影响其他功能

---

## 功能点 5：structlog 可观测性

### 概要链路

在 `search.py` 的 `_run_pipeline` 中，`_get_skus` 返回后添加日志：

```python
# 阶段 3 完成后，_get_skus 返回的 skus 已含 matched_texts
match_stats = [
    {"sku_id": s["sku_id"], "texts": len(s.get("matched_texts", [])),
     "chars": sum(len(t["content"]) for t in s.get("matched_texts", []))}
    for s in skus
]
pipeline_log.info("阶段3: 匹配文本统计", match_stats=match_stats)
```

### 主要优点
- 不影响主流程
- 便于观察实际数据分布，为后续调参提供依据
- structlog 已有基础设施，一行 `pipeline_log.info` 即可

### 主要风险
- 无

### 实现复杂度：**低**
- 3 行统计代码 + 1 行日志

### 可测试性：**中**
- 日志输出可在集成测试中捕获验证

### 可交付性：**高**

---

---

## 功能点 7：测试更新

### 概要链路

**单元测试（`tests/test_search.py`）：**

| 测试用例 | 说明 |
|----------|------|
| `test_get_skus_with_matched_texts` | mock DB 返回含 product_review 列的行，断言 matched_texts 聚合正确 |
| `test_get_skus_without_reviews` | mock DB 返回无 product_review 的行，断言 matched_texts 为空列表 |
| `test_get_skus_truncation` | 超过 max_match_texts_per_sku 条，断言截断到配置值 |
| `test_build_context_with_matched_texts` | 输入含 matched_texts 的 dict，断言输出含 `【用户评价与描述】` |
| `test_build_context_without_matched_texts` | 输入不含 matched_texts，断言输出不含 `【用户评价与描述】` |

**集成测试（`test_demo.py`）：**
- 现有 SSE 测试用例保持（验证 `sub_queries`/`products`/`reasoning`/`done` 事件）
- 人工观察 reasoning 内容是否引用了评价信息（不做自动化断言）

### 主要优点
- _get_skus 和 _build_context 都是纯函数，mock 成本极低
- 不需要真实 DB 或 LLM 即可覆盖核心逻辑

### 主要风险
- 集成测试依赖真实 LLM，输出不定 → 不做自动化断言，仅做 smoke

### 实现复杂度：**低-中**
- 单元测试参考现有 `test_search.py` 的 mock 模式

### 可测试性：**高**（单元）/ **中**（集成）

### 可交付性：**高**

---

## 汇总

| 功能点 | 复杂度 | 风险 | 可测试性 | 改动文件数 |
|--------|--------|------|----------|------------|
| 1. _get_skus SQL 扩展 | 低 | 低 | 高 | 1 |
| 2. _build_context 扩展 | 低 | 低 | 高 | 1 |
| 3. 配置项新增 | 低 | 低 | 高 | 2 |
| 4. prompt 更新 | 低 | 低 | 低 | 1 |
| 5. 可观测性日志 | 低 | 低 | 中 | 1 |
| 6. 索引检查脚本 | 低 | 低 | 高 | 1（新增） |
| 7. 测试更新 | 低-中 | 低 | 高 | 2 |

**改动总量：6 个已有文件 + 1 个新增脚本，均属低复杂度改动。**

### 核心数据流（改造后）

```
Retriever.retrieve()
  │  返回: {"keyword": [SKUHit], "semantic": [SKUHit]}  ← 不改
  ▼
Merger.merge(kw, sem)
  │  返回: [SKUHit] (RRF 排序, top-10)  ← 不改
  ▼
_get_skus(ranked_skuhits)
  │  SQL: product JOIN sku LEFT JOIN product_review  ← ★ 改动点
  │  返回: [{"product_id":..., "sku_id":..., "matched_texts": [...]}]
  ▼
Generator.generate(skus, q)
  │  _build_context(skus)  ← ★ 改动点（追加 matched_texts 段落）
  │  chat_stream(messages)  ← 不改
  ▼
SSE: products → reasoning → done   ← 不改
```

### 不做的事（明确排除）
- 不修改 Retriever SQL（保持 GROUP BY 语义不变）
- 不扩展 SKUHit dataclass
- 不修改 Merger
- 不新增 API 端点或 SSE 事件类型
- 不在 migration 中自动建索引
- 不做评论文本过滤/清洗
- 不做 LLM 摘要/重写


# 针对不同来源的商品评论信息做信息优化 — 实现方案

> 来源：[DEFINE.md](DEFINE.md) 第二节 | 日期：2026-05-30

---

## 总体策略

**原则：最小改动面，权重计算下沉到 SQL，不改检索结果数据结构。**

核心思路 —— 在 Retriever 的 `_semantic_search` 和 `_keyword_search` 的 SQL 得分表达式中，对每条 `product_review` 行按其 `source` 字段乘以对应权重，使得不同来源的匹配文本对最终 SKU 得分的贡献度不同。权重从 `config.yaml` 注入，支持运行时调整。

```
                        ┌── ★ 加权 ──┐                ┌── 不改 ──┐
Retriever._semantic_search()  →  Merger.merge()  →  _get_skus()  →  Generator.generate()
Retriever._keyword_search()          │
     │                           RRF 输入分数已含权重差异
     │
  SQL: SUM(source_weight * sim_score) GROUP BY sku_id
```

改动涉及 5 个文件：

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `config.yaml` | 新增节 | `search.source_weights` — 各 source 的权重映射 |
| `app/config.py` | 修改 | `SearchSettings` 增加 `source_weights: dict[str, float]` |
| `app/services/retriever.py` | 修改 | `_semantic_search` 和 `_keyword_search` SQL 得分表达式加入权重 |
| `app/api/search.py` | 修改 | **Bug 修复**：`_SOURCE_PRIORITY` 中 `"user"` → `"user_reward"` |
| `app/rag/generator.py` | 修改 | **Bug 修复**：`SOURCE_LABEL` 中 `"user"` → `"user_review"` |

不改动的文件：`merger.py`、`schemas/product.py`、所有 ORM 模型、`prompt.py`。

---

## 功能点 S1：配置项新增（source_weights）

### 概要链路

```
config.yaml 新增:
  search:
    source_weights:
      marketing: 1.0
      faq: 1.0
      user_review: 0.7

config.py SearchSettings 新增:
  source_weights: dict[str, float] = Field(default_factory=dict)
  # 默认 {} 表示全部 source 等权（1.0），向后兼容

retriever.py 使用:
  weights = settings.search.source_weights
  w = weights.get(source, 1.0)   # 未配置的 source 默认 1.0
```

### 主要优点
- 权重可热调整，无需改代码重新部署
- 默认 `{}` 完全向后兼容（等权行为不变）
- 支持未来新增 source 类型而不需改 config model

### 主要风险
- `dict` 类型配置的 key 拼写错误（如 `user_review` 写成 `user_reviews`）静默失效（get 返回默认 1.0）→ **缓解**：启动时 structlog 打印实际加载的权重，便于排查

### 实现复杂度：**低**
- YAML 3 行 + Pydantic 1 个字段

### 可测试性：**高**
- 配置加载已有框架，断言 `settings.search.source_weights` 值与预期一致

### 可交付性：**高**

---

## 功能点 S2：`_semantic_search` 得分加权

### 概要链路

```
当前得分表达式（等权累加）:
  score_parts = [
    "(1 - (pr.embedding <=> :vec_0))",
    "(1 - (pr.embedding <=> :vec_1))",
    ...
  ]
  score_expr_full = "SUM(score_part_0 + score_part_1 + ...) AS score"

改造后（source 加权）:
  weight_expr = """
    CASE pr.source
      WHEN 'marketing' THEN :w_mkt
      WHEN 'faq' THEN :w_faq
      WHEN 'user_review' THEN :w_usr
      ELSE 1.0
    END
  """
  score_expr_full = f"SUM({weight_expr} * ({score_expr})) AS score"

SQL 参数绑定:
  params["w_mkt"] = weights.get("marketing", 1.0)
  params["w_faq"] = weights.get("faq", 1.0)
  params["w_usr"] = weights.get("user_review", 1.0)
```

### 主要优点
- 权重乘法在 SQL 聚合前完成，不增加 Python 侧计算开销
- 只改得分表达式构建逻辑（`_semantic_search` 内部约 5 行），不改 SQL 骨架（`_build_base_query`）
- `SKUHit.score` 字段含义不变（仍是 float），下游 RRF 无感知

### 主要风险
- `CASE WHEN` 分支硬编码了已知的 3 个 source → 新增 source 类型时需要同步更新 SQL → **缓解**：可以改用动态生成 CASE WHEN（从 weights dict 遍历拼接），但首次交付固定 3 个已知 source 更安全
- 权重 0 时该 source 行得分为 0，但仍参与 DB 扫描和 GROUP BY → 当前数据规模（100 商品）无性能影响，扩量后可按需在 WHERE 中过滤 weight=0 的 source

### 实现复杂度：**低-中**
- SQL 字符串拼接逻辑修改，需仔细处理括号嵌套
- 参数绑定需确保参数名不冲突（`:w_xxx` 与现有的 `:vec_N`、`:limit`）

### 可测试性：**中**
- Mock DB execute 返回的 rows，验证传入 SQL 文本包含 CASE WHEN + 权重参数
- 完整的端到端验证需要真实 pgvector（但权重逻辑是纯算术，mock 可覆盖）

### 可交付性：**高**
- 独立修改，不影响其他检索路径

---

## 功能点 S3：`_keyword_search` 得分加权

### 概要链路

```
当前 ts_rank 得分:
  "ts_rank(pr.content_tsv, plainto_tsquery(:tsv_config, :kw)) AS score"

改造后（source 加权）:
  weight_expr = "CASE pr.source WHEN 'marketing' THEN :w_mkt WHEN 'faq' THEN :w_faq WHEN 'user_review' THEN :w_usr ELSE 1.0 END"
  f"{weight_expr} * ts_rank(pr.content_tsv, plainto_tsquery(:tsv_config, :kw)) AS score"

当前 ILIKE 降级:
  "0.3 AS score"

改造后（source 加权）:
  f"{weight_expr} * 0.3 AS score"
```

### 主要优点
- 与 semantic 路径使用相同的权重参数，保证两路一致性
- ts_rank 和 ILIKE 降级都加权，覆盖完整

### 主要风险
- 同 S2：CASE WHEN 硬编码 source 值 → 同上缓解
- ts_rank 本身分数范围非标化（依赖分词匹配度），乘以权重后分数更不可比 → RRF 不依赖绝对分数，只依赖排名，因此不影响融合质量

### 实现复杂度：**低**
- 在现有 SQL 字符串拼接处加 `weight_expr * (...)`

### 可测试性：**中**
- 同 S2

### 可交付性：**高**

---

## 功能点 S4：Bug 修复 — source 值对齐

### 概要链路

DB 中 `product_review.source` 实际值为 `"user_review"`（见 `sync.py:78`），但上一轮实现中两处使用了错误的值 `"user"`：

```
修复点 1: app/api/search.py _SOURCE_PRIORITY
  当前: {"user": 0, "faq": 1, "marketing": 2}
  修复: {"user_review": 0, "faq": 1, "marketing": 2}

修复点 2: app/rag/generator.py SOURCE_LABEL
  当前: {"user": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}
  修复: {"user_review": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}
```

### 主要优点
- 两处改动均为常量 dict 的 1 个 key 替换，零风险
- 修复后 `_truncate_texts` 中用户评价不再被当作"未知来源"排到末尾
- 修复后 `_build_context` 中用户评价显示为 `[用户评价]` 而非 `[其他]`

### 主要风险
- 无。现有单元测试中 mock 数据也使用了 `"user"` → 需要同步更新测试中的 source 值

### 实现复杂度：**极低**
- 2 个文件各改 1 行

### 可测试性：**高**
- 现有 `TestTruncateTexts` 和 `TestBuildContext` 的测试用例需将 `"user"` → `"user_review"`，断言不变

### 可交付性：**高**
- 可与 S1-S3 同批次交付

---

## 功能点 S5：测试更新

### 概要链路

**配置测试：**
- `test_search.py` 新增 `test_source_weights_default`：验证 `source_weights` 默认值
- `test_search.py` 新增 `test_source_weights_from_yaml`：验证从 YAML 加载的值

**加权得分测试：**
- `test_retriever.py` 新增 `TestWeightedSemanticSearch`：
  - `test_weight_applied_to_semantic_score`：mock DB，验证 SQL 文本含 `CASE pr.source` 和 `:w_xxx` 参数
  - `test_default_weight_for_unknown_source`：未知 source 权重默认 1.0
- `test_retriever.py` 新增 `TestWeightedKeywordSearch`：
  - `test_weight_applied_to_ts_rank`：ts_rank 路径含权重表达式
  - `test_weight_applied_to_ilike_fallback`：ILIKE 降级路径含权重表达式

**Bug 修复回归测试：**
- `TestTruncateTexts.test_sort_by_source_priority`：`"user"` → `"user_review"`，断言 `user_review` 排最前
- `TestBuildContext.test_source_labels`：`"user"` → `"user_review"`，断言 `[用户评价]` 标签正确

### 主要优点
- Retriever 测试通过 mock DB execute 验证 SQL 文本，不依赖真实 pgvector
- 配置测试复用现有 settings 加载机制

### 主要风险
- Retriever 测试需要 mock `EmbeddingService.embed` 和 `db.execute`，mock 链稍长 → **缓解**：参考现有 `TestGetSkus` 的 `_make_mock_db` 模式

### 实现复杂度：**中**
- 配置测试简单（2 个用例）
- Retriever 加权测试需要构造 mock（约 4 个用例）
- Bug 修复回归：修改现有测试的 source 值（约 4 个用例受影响）

### 可测试性：**高**

### 可交付性：**高**

---

## 汇总（第二节）

| 功能点 | 复杂度 | 风险 | 可测试性 | 改动文件数 |
|--------|--------|------|----------|------------|
| S1. 配置项新增 | 低 | 低 | 高 | 2 |
| S2. _semantic_search 加权 | 低-中 | 低 | 中 | 1 |
| S3. _keyword_search 加权 | 低 | 低 | 中 | 1 |
| S4. Bug 修复 source 对齐 | 极低 | 低 | 高 | 2 |
| S5. 测试更新 | 中 | 低 | 高 | 2 |

**改动总量：5 个已有文件（第一节已涉及的文件中 4 个有增量改动），0 个新增文件。**

### 核心数据流（加权后）

```
Retriever._semantic_search()
  │  SQL: SUM(CASE source WHEN... THEN weight END * (sim_0 + sim_1 + ...))
  │  返回: [SKUHit(score=加权后的综合得分)]  ← ★ score 已含 source 权重
  │
Retriever._keyword_search()
  │  SQL: weight * ts_rank(...) AS score
  │  返回: [SKUHit(score=加权后的综合得分)]  ← ★ score 已含 source 权重
  ▼
Merger.merge(kw, sem)
  │  RRF 融合，输入分数已含权重差异  ← 不改
  ▼
_get_skus() → Generator.generate()  ← 不改
```

### 不做的事（第二节明确排除）
- 不修改 RRF 融合算法
- 不修改 `_truncate_texts` 的 source 优先级逻辑（仅修 bug）
- 不修改 Merger / Generator / _get_skus 的核心逻辑
- 不新增 ORM 模型或 migration
- 不在 SQL 中动态遍历 weights dict 生成 CASE WHEN（首次交付硬编码已知 source，后续可重构）
