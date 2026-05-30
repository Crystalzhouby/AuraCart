# 优化推荐理由生成 — 编码骨架

> 来源：[PLAN.md](PLAN.md) | 日期：2026-05-30

---

## 1. 模块拆分

```
search.py  _get_skus()          ← SQL 扩展 + 聚合 + 截断（★ 核心改动）
           _run_pipeline()       ← 阶段3 后加 structlog 日志
           _truncate_texts()     ← [新增] 截断纯函数，从 _get_skus 中抽出

generator.py  _build_context()  ← 末尾追加 matched_texts 段落
              SOURCE_LABEL       ← [新增] 模块常量，source→中文标签映射

prompt.py  GENERATOR_SYSTEM     ← 追加规则 6、7

config.yaml / config.py         ← SearchSettings 加 2 个 int 字段

tests/test_search.py            ← 新增 5 个单元测试
```

**不改的文件：** `retriever.py` / `merger.py` / `schemas/product.py` / `models/*` / `alembic/*`

---

## 2. 目录结构（仅列出涉及的文件）

```
server/
├── app/
│   ├── api/
│   │   └── search.py              ← _get_skus 改造、_truncate_texts 新增
│   ├── rag/
│   │   ├── generator.py           ← _build_context 扩展 + SOURCE_LABEL
│   │   └── prompt.py              ← GENERATOR_SYSTEM 追加
│   └── config.py                  ← SearchSettings 加字段
├── config.yaml                    ← search 节加 2 项
└── tests/
    └── test_search.py             ← 新增匹配文本相关用例
```

---

## 3. 核心接口与实现思路

### 3.1 `_get_skus(db, skuhits) -> list[dict]`

**所在文件：** `app/api/search.py`

**签名不变，行为扩展：**

```
输入: AsyncSession, list[SKUHit]     ← 不变
输出: list[dict]                      ← 每个 dict 新增 "matched_texts" 键
```

**dict 结构：**
```python
{
    # ---- 原有字段（不变） ----
    "product_id": str,
    "title": str,
    "brand": str | None,
    "category": str | None,
    "sub_category": str | None,
    "base_price": float | None,
    "sku_id": str,
    "properties": dict | None,
    "price": float,
    "stock": int,

    # ---- 新增字段 ----
    "matched_texts": [
        {"content": str, "source": str, "metadata": dict | None},
        ...
    ]
}
```

**实现思路：**
1. 原 SQL（`product JOIN sku`）扩展为 `product JOIN sku LEFT JOIN product_review`，SELECT 增加 `pr.content, pr.source, pr.metadata`
2. Python 侧遍历 rows，首次遇到 sku_id 时写入产品+SKU 基础字段；每行若 `content` 非空则追加到 `matched_texts` 列表
3. 聚合完成后调用 `_truncate_texts()` 做截断
4. `matched_texts` 为空列表时行为完全等价于原代码

### 3.2 `_truncate_texts(matched_texts, max_count, max_chars) -> list[dict]`

**所在文件：** `app/api/search.py`（新增内部函数）

```python
def _truncate_texts(
    matched_texts: list[dict],
    max_count: int,
    max_chars: int,
) -> list[dict]:
    """按 source 优先级排序后截断。"""
```

**实现思路：**
1. 按 `SOURCE_PRIORITY[text["source"]]` 升序排列（user=0, faq=1, marketing=2）
2. 遍历排序后列表，累计字符数，超过 `max_chars` 时停止
3. 截取前 `max_count` 条
4. 纯函数，无副作用，无 DB/IO 依赖

### 3.3 `Generator._build_context(skus: list[dict]) -> str`

**所在文件：** `app/rag/generator.py`

**签名不变，输出扩展：**

现有输出末尾追加段落（仅当 SKU 有 `matched_texts` 时）：

```
【用户评价与描述】
[用户评价] <content>
[官方描述] <content>
[FAQ] <content>
```

**新增模块常量：**
```python
SOURCE_LABEL = {"user": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}
```

**实现思路：**
1. 现有 `_build_context` 逻辑完全不改
2. 循环 `skus`，对每个 SKU 的 `matched_texts` 做：
   - 若列表为空 → 跳过该 SKU
   - 若列表非空 → 先输出 `【用户评价与描述】` 标题（仅一次），再逐条输出 `{SOURCE_LABEL[source]} {content}`
3. 全空 → 不输出标题，输出与改造前完全一致

### 3.4 `GENERATOR_SYSTEM` prompt

**所在文件：** `app/rag/prompt.py`

**实现思路：** 在现有 `## 规则` 块末尾追加两条规则（见 PLAN.md 功能点 4），不改变已有 5 条规则。

### 3.5 `SearchSettings` 配置扩展

**所在文件：** `app/config.py` + `config.yaml`

```python
# config.py
class SearchSettings(BaseSettings):
    # ... 现有 3 个字段不变 ...
    max_match_texts_per_sku: int = 3
    max_match_chars_per_sku: int = 500
```

```yaml
# config.yaml
search:
  # ... 现有项不变 ...
  max_match_texts_per_sku: 3
  max_match_chars_per_sku: 500
```

---

## 4. 关键数据结构

### 贯穿管线的核心 dict（从 _get_skus 产出 → Generator 消费）

```python
# 单个 SKU 的完整表示
SkuDict = {
    # product 字段
    "product_id":   str,
    "title":        str,
    "brand":        str | None,
    "category":     str | None,
    "sub_category": str | None,
    "base_price":   float | None,
    # sku 字段
    "sku_id":       str,
    "properties":   dict[str, str] | None,  # JSONB
    "price":        float,
    "stock":        int,
    # ★ 新增：匹配文本
    "matched_texts": list[MatchText],
}

MatchText = {
    "content":  str,
    "source":   str,       # "user" | "marketing" | "faq"
    "metadata": dict | None,
}
```

### 管线中的传递链

```
SKUHit (retriever/merger)           → 仅有 sku_id/product_id/score
        │
        ▼
_get_skus 查询 DB 后产出 SkuDict   → 加入 product/sku 字段 + matched_texts
        │
        ▼
_build_context 消费 SkuDict        → 序列化为 LLM 上下文字符串
```

**关键边界：** `matched_texts` 是 `_get_skus` 阶段新产生的，上游（Retriever/Merger）不感知；下游（Generator）通过 dict key 读取，不存在时退化。

---

## 5. 主功能链路时序

```
search.py                        generator.py              PostgreSQL
  │                                   │                        │
  │── _run_pipeline(q)                │                        │
  │   │                               │                        │
  │   │── Retriever.retrieve()        │                        │
  │   │   → {keyword:[], semantic:[]} │                        │
  │   │                               │                        │
  │   │── Merger.merge(kw, sem)       │                        │
  │   │   → list[SKUHit] (top-10)     │                        │
  │   │                               │                        │
  │   │── _get_skus(db, skuhits) ─────────────────────────────▶│
  │   │   SQL: product ⋈ sku ⟕ product_review                  │
  │   │   ← list[SkuDict] (含 matched_texts)                   │
  │   │                               │                        │
  │   │── structlog: match_stats      │                        │
  │   │                               │                        │
  │   │── Generator.generate(skus, q) │                        │
  │   │   │                           │                        │
  │   │   │── _build_context(skus)    │                        │
  │   │   │   格式化产品信息           │                        │
  │   │   │   追加 matched_texts 段落  │  ← ★ 新逻辑            │
  │   │   │   ← context_str           │                        │
  │   │   │                           │                        │
  │   │   │── chat_stream(messages)   │                        │
  │   │   │   ← token stream          │                        │
  │   │                               │                        │
  │   │── SSE: products → reasoning → done                     │
```

---

## 6. 边界、隔离与降级

### 6.1 模块边界

| 模块 | 职责 | 不关心 |
|------|------|--------|
| `_get_skus` | 查询产品+SKU+评论文本，聚合截断 | LLM 如何使用文本 |
| `_truncate_texts` | 按优先级 + 数量 + 字符数截断 | 文本来源、DB schema |
| `_build_context` | 将 SkuDict 序列化为 LLM 可读字符串 | 文本如何获取、如何截断 |
| `GENERATOR_SYSTEM` | 约束 LLM 如何使用评论文本 | 运行时数据 |

### 6.2 降级路径

```
matched_texts 为空列表?
  → _build_context 不输出【用户评价与描述】段落
  → LLM 上下文与改造前完全一致
  → 推荐理由生成退化为原行为

product_review 表无数据?
  → LEFT JOIN 返回 NULL
  → Python 侧 content 为空不追加
  → 降级同上

配置缺失?
  → Pydantic default 生效 (3 条 / 500 字符)
  → 不影响启动
```

### 6.3 不发生的事（防御性约束）

- `_get_skus` 不改动 `SKUHit` —— 它只读取 `sku_id`，不写回
- `_build_context` 不改动传入的 `skus` 列表 —— 只读遍历
- prompt 模板不引用任何未注入的变量 —— `{product_context}` 中已有或没有 `【用户评价与描述】` 均可

### 6.4 【不确定】待确认的边界

1. **`_get_skus` 的 `LEFT JOIN product_review` 是否过滤 `is_active`？** — `product_review` 表没有 `is_active` 列（对照 migration），无需过滤。但若后续 migration 加了该列，需要同步更新。
不需要过滤`is_active` 列，`product_review`也不需要添加`is_active` 列，当user_review等评论表的`is_active`属性发生变化时，会自动更新`product_review`表中的数据。

2. **同一 SKU 的 `matched_texts` 中 source 优先级是否合理？** — 当前 user > faq > marketing。若实际效果不佳，调整 `_truncate_texts` 中的优先级常量即可。
按照可信度和真实度，排名应该是faq > marketing > user，用户评论可能包含虚假信息。


# 针对不同来源的商品评论信息做信息优化 — 编码骨架

> 来源：[PLAN.md](PLAN.md) 第二节 | 日期：2026-05-30

---

## 1. 模块拆分

```
retriever.py  _semantic_search()       ← SQL 得分表达式加入 source 权重因子
              _keyword_search()         ← ts_rank / ILIKE 得分加入 source 权重因子
              _build_weight_expr()      ← [新增] 私有方法，根据 weights dict 生成 CASE WHEN 片段

config.yaml / config.py                 ← SearchSettings 加 source_weights: dict 字段

search.py     _SOURCE_PRIORITY          ← [修复] 改名 + 重排优先级
              _truncate_texts()         ← 行为跟随 _SOURCE_PRIORITY 更新

generator.py  SOURCE_LABEL              ← [修复] "user" → "user_review"

tests/test_retriever.py                 ← [新增] 加权得分相关用例
tests/test_search.py                    ← 更新现有用例的 source 值
```

**改动量：5 个已有文件（其中 retriever.py 为本次新增改动），不改 merger.py / prompt.py / models。**

---

## 2. 目录结构（仅列出涉及的文件）

```
server/
├── app/
│   ├── api/
│   │   └── search.py              ← _SOURCE_PRIORITY 修复（值改名 + 优先级重排）
│   ├── rag/
│   │   └── generator.py           ← SOURCE_LABEL 修复（"user" → "user_review"）
│   ├── services/
│   │   └── retriever.py           ← ★ _semantic_search / _keyword_search SQL 加权
│   └── config.py                  ← SearchSettings 加 source_weights 字段
├── config.yaml                    ← search 节加 source_weights 映射
└── tests/
    ├── test_search.py             ← 更新现有 source 值
    └── test_retriever.py          ← [新增] 加权得分测试
```

---

## 3. 核心接口与实现思路

### 3.1 `Retriever._build_weight_expr(weights: dict[str, float]) -> tuple[str, dict]`

**所在文件：** `app/services/retriever.py`（新增私有方法）

```python
def _build_weight_expr(self, weights: dict[str, float]) -> tuple[str, dict]:
    """根据权重配置生成 CASE WHEN 片段和参数绑定。

    返回:
        (sql_fragment, params)
        sql_fragment:  "CASE pr.source WHEN :w_mkt THEN :wv_mkt WHEN ... ELSE 1.0 END"
        params:        {":wv_mkt": 1.0, ":wv_faq": 1.0, ":wv_usr": 0.7}
    """
```

**实现思路：**
1. 遍历已知 source 列表 `["marketing", "faq", "user_review"]`，对每个 source 生成 `WHEN :w_src THEN :wv_src`
2. 权重值从 `weights.get(source, 1.0)` 获取（缺省 1.0）
3. 参数名的 `:w_src` 部分用于去重（两次引用同一个 bind param 在 PostgreSQL 中不允许），所以 WHEN 条件用字符串常量，THEN 值用参数绑定
4. 纯字符串拼接，无 DB 访问

> **【不确定】** 是否改用动态遍历 weights dict 的 keys 生成 CASE WHEN，而非硬编码已知 source 列表？PLAN.md 建议首次交付硬编码 3 个 source，更安全。此处以硬编码为准。

### 3.2 `_semantic_search()` — 得分加权

**所在文件：** `app/services/retriever.py`

**签名不变。内部 SQL 得分表达式改造：**

```
改前:
  score_parts = ["(1 - (pr.embedding <=> :vec_0))", "(1 - (pr.embedding <=> :vec_1))", ...]
  score_expr_full = "SUM(score_part_0 + score_part_1 + ...) AS score"

改后:
  weight_expr, w_params = self._build_weight_expr(weights)
  score_parts = ["(1 - (pr.embedding <=> :vec_0))", ...]
  score_expr = " + ".join(score_parts)
  score_expr_full = f"SUM({weight_expr} * ({score_expr})) AS score"
  params.update(w_params)  # 绑定 :wv_xxx 参数
```

**实现思路：**
1. 在 `_semantic_search` 方法开头从 `settings.search.source_weights` 获取权重
2. 调用 `_build_weight_expr()` 生成 CASE WHEN 片段和参数
3. 原 `score_expr` 加括号后乘以 `weight_expr`，嵌套在 `SUM()` 内
4. 参数绑定追加到现有 `params` dict（注意参数名不能与 `:vec_N`、`:limit` 冲突）
5. `SKUHit.score` 含义不变（仍是 float），但值域从 `[0, N]` 变为 `[0, N * max_weight]`

### 3.3 `_keyword_search()` — 得分加权

**所在文件：** `app/services/retriever.py`

**签名不变。两处得分表达式改造：**

```
改前 (ts_rank):
  "ts_rank(pr.content_tsv, plainto_tsquery(:tsv_config, :kw)) AS score"

改后:
  f"{weight_expr} * ts_rank(pr.content_tsv, plainto_tsquery(:tsv_config, :kw)) AS score"

改前 (ILIKE 降级):
  "0.3 AS score"

改后:
  f"{weight_expr} * 0.3 AS score"
```

**实现思路：**
1. 与 `_semantic_search` 共用同一套权重配置和 `_build_weight_expr()`
2. `weight_expr` 在构建 SQL 字符串时拼接，`w_params` 合并到查询参数
3. ts_rank 和 ILIKE 降级两处都要加权，保持一致性

### 3.4 `_SOURCE_PRIORITY` 修复

**所在文件：** `app/api/search.py`

```
修复前:
  _SOURCE_PRIORITY = {"user": 0, "faq": 1, "marketing": 2}

修复后:
  _SOURCE_PRIORITY = {"faq": 0, "marketing": 1, "user_review": 2}
```

**变更点：**
1. `"user"` → `"user_review"`（与 DB 实际值对齐）
2. 优先级顺序反转：faq(0) > marketing(1) > user_review(2)（依据可信度：官方FAQ最高，用户评论最低）
3. `_truncate_texts()` 函数本身不改，自动跟随新常量排序

### 3.5 `SOURCE_LABEL` 修复

**所在文件：** `app/rag/generator.py`

```
修复前:
  SOURCE_LABEL = {"user": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}

修复后:
  SOURCE_LABEL = {"user_review": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}
```

### 3.6 `SearchSettings` 配置扩展

**所在文件：** `app/config.py` + `config.yaml`

```python
# config.py
class SearchSettings(BaseSettings):
    # ... 现有 5 个字段不变 ...
    source_weights: dict[str, float] = Field(default_factory=dict)
    # 默认 {} → 全部 source 等权 1.0，完全向后兼容
```

```yaml
# config.yaml
search:
  # ... 现有项不变 ...
  source_weights:
    marketing: 1.0
    faq: 1.0
    user_review: 0.7
```

**实现思路：**
1. `dict` 类型的 Field 默认 `{}`，Pydantic 从 YAML 加载时自动填充
2. `_build_weight_expr` 通过 `weights.get(source, 1.0)` 兜底，未配置的 source 默认等权
3. 启动时 structlog 打印实际加载的权重，便于排查拼写错误

---

## 4. 关键数据结构

### 权重配置

```python
# config.yaml → SearchSettings.source_weights
# key: product_review.source 的值
# value: 权重系数（0.0 ~ N），默认 1.0 表示等权
source_weights: dict[str, float]
# 示例: {"marketing": 1.0, "faq": 1.0, "user_review": 0.7}
```

### SQL 权重片段（由 `_build_weight_expr` 产出）

```sql
CASE pr.source
  WHEN 'marketing' THEN :wv_mkt
  WHEN 'faq' THEN :wv_faq
  WHEN 'user_review' THEN :wv_usr
  ELSE 1.0
END
```

### 加权前后的 SKUHit.score 变化

```
改前（等权）:
  SKU_A 有 3 条 user_review 匹配（sim=0.9, 0.8, 0.7）
  score = 0.9 + 0.8 + 0.7 = 2.4

改后（user_review=0.7）:
  score = 0.7*(0.9 + 0.8 + 0.7) = 0.7 * 2.4 = 1.68

→ SKU_A 在 RRF 中的排名可能下降（相比拥有更多 marketing/faq 匹配的 SKU）
```

### 管线中的传递链（不改）

```
SKUHit (加权后的 score)               → Merger.merge() 无感知
        │
        ▼
_get_skus 产出 SkuDict                → matched_texts 截断优先级跟随 _SOURCE_PRIORITY
        │                              （faq > marketing > user_review）
        ▼
_build_context 消费 SkuDict           → SOURCE_LABEL 映射 source → 中文标签
```

**关键边界：** 检索阶段的 source 权重（影响 SKU 排名）与上下文阶段的 source 优先级（影响哪些文本先注入 prompt）是**两个独立维度**，分别由 `source_weights` 和 `_SOURCE_PRIORITY` 控制。

---

## 5. 主功能链路时序

```
config.yaml                    retriever.py                     merger.py
    │                              │                                │
    │  加载 source_weights          │                                │
    │──────────────────────────────│                                │
    │                              │                                │
    │  _semantic_search(subs)      │                                │
    │  │                           │                                │
    │  │── _build_weight_expr()    │                                │
    │  │   → (case_when_sql,       │                                │
    │  │      w_params)            │                                │
    │  │                           │                                │
    │  │── 构建加权 SQL:           │                                │
    │  │   SUM(CASE source...      │                                │
    │  │    * (sim_0 + sim_1...))  │                                │
    │  │─────────────────────▶ DB  │                                │
    │  │   ← [SKUHit(score=加权)]  │                                │
    │  │                           │                                │
    │  _keyword_search(subs)       │                                │
    │  │── 同 weight_expr *        │                                │
    │  │   ts_rank(...)            │                                │
    │  │─────────────────────▶ DB  │                                │
    │  │   ← [SKUHit(score=加权)]  │                                │
    │  │                           │                                │
    │                              │── Merger.merge(kw, sem)        │
    │                              │   RRF 输入分数已含权重          │
    │                              │──────────────────────────────▶│
    │                              │   ← [SKUHit] (RRF 排序)        │
    │                              │                                │
    │                              │── _get_skus()                  │
    │                              │   _SOURCE_PRIORITY 决定        │
    │                              │   matched_texts 截断顺序       │
    │                              │   (faq > marketing >           │
    │                              │    user_review)                │
    │                              │                                │
    │                              │── Generator.generate()         │
    │                              │   SOURCE_LABEL 决定            │
    │                              │   source → 中文标签映射        │
```

---

## 6. 边界、隔离与降级

### 6.1 模块边界

| 模块 | 职责 | 不关心 |
|------|------|--------|
| `config.yaml` / `SearchSettings` | 提供 source → weight 映射 | SQL 如何拼接权重 |
| `_build_weight_expr` | 将 dict 转为 CASE WHEN 片段 + 参数 | 上游调用者如何聚合得分 |
| `_semantic_search` | 构建加权 SQL，返回加权后 SKUHit | RRF 如何融合 |
| `_keyword_search` | 构建加权 SQL，返回加权后 SKUHit | RRF 如何融合 |
| `_SOURCE_PRIORITY` | 定义 source → 截断优先级排序 | 检索阶段的权重值 |
| `SOURCE_LABEL` | 定义 source → 中文标签映射 | 检索和截断逻辑 |

### 6.2 降级路径

```
source_weights 配置为空 {} ?
  → _build_weight_expr 中所有 source 走 ELSE 1.0
  → 得分计算完全等价于改前（等权累加）
  → 行为 100% 向后兼容

某 source 在 weights 中未配置?
  → weights.get(source, 1.0) 返回 1.0（等权）
  → 不报错，静默退化

权重为 0?
  → CASE WHEN 返回 0.0，该 source 行对 SUM 无贡献
  → 等价于该 source 的匹配文本不影响排名
  → 【不确定】是否需要同时在 WHERE 中排除 weight=0 的 source 以减少扫描行？
    当前数据规模（100 商品）无影响，暂不过滤。

product_review 表新增 source 类型?
  → ELSE 1.0 兜底，新 source 等权参与
  → 但 _build_weight_expr 的 CASE WHEN 不包含新 source（需手动追加）
  → 【不确定】交付后是否需要主动监控 source 值分布并在日志告警?
```

### 6.3 不发生的事（防御性约束）

- `SKUHit` dataclass 不改 —— `score` 字段含义不变
- `Merger.merge()` 不改 —— RRF 只读 `SKUHit.score`，不关心分数来源
- `_get_skus()` 不改 —— 检索 → 排序的权重逻辑与查询补全解耦
- `prompt.py` 不改 —— GENERATOR_SYSTEM 不受影响

### 6.4 【不确定】待确认的边界

1. **SPEC 建议的权重值 (1.0/1.0/0.7) 是否直接采用？** — 当前无数据支撑，建议首次交付直接采用，作为可配置值后续 A/B 调整。

2. **`_build_weight_expr` 硬编码 source 列表 vs 动态遍历 weights.keys()？** — PLAN.md 选择硬编码（更安全），此处保持与 PLAN.md 一致。若后续频繁新增 source 类型，可重构为动态生成。

3. **权重变更是否需要重启服务？** — 当前 `settings` 是模块级单例，启动时加载。若要热更新权重，需要额外机制（如文件监听或 API），首次交付不做。