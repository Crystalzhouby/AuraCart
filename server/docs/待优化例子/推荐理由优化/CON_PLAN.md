# 推荐理由优化 — 编码骨架

> 来源：[PLAN.md](PLAN.md) + [DEFINE.md](DEFINE.md) | 日期：2026-05-30

---

## 1. 模块拆分

```
generator.py  _format_sub_queries()   ← [新增] 私有方法，sub_queries → 自然语言
              generate()              ← [扩展] 签名加 sub_queries 参数
              _build_context()        ← 不改（已有逻辑+matched_texts，复用）

prompt.py     GENERATOR_SYSTEM        ← [扩展] 追加规则 8（覆盖全部商品）、规则 9（回应全部意图）、规则 7 字数配置化

search.py     _run_pipeline()         ← [扩展] 两处 generate() 调用传入 sub_queries

config.yaml / config.py               ← [扩展] SearchSettings 加 reasoning_max_chars 字段（可选）
```

**不改的文件：** `retriever.py` / `merger.py` / `schemas/product.py` / `models/*` / `generator._build_context`

---

## 2. 目录结构（仅列出涉及的文件）

```
server/
├── app/
│   ├── api/
│   │   └── search.py              ← _run_pipeline 两处 generate() 调用适配
│   ├── rag/
│   │   ├── generator.py           ← generate() 签名扩展 + _format_sub_queries()
│   │   └── prompt.py              ← GENERATOR_SYSTEM 追加规则
│   └── config.py                  ← SearchSettings 加 reasoning_max_chars（可选）
├── config.yaml                    ← search 节加 reasoning_max_chars（可选）
└── tests/
    ├── test_generator.py           ← _format_sub_queries 测试 + generate() 新签名测试
    └── test_search.py              ← sub_queries 透传测试（如有必要）
```

---

## 3. 核心接口与实现思路

### 3.1 `Generator._format_sub_queries(sub_queries) -> str`

**所在文件：** `app/rag/generator.py`（新增私有方法）

```python
@staticmethod
def _format_sub_queries(sub_queries: list[dict] | None) -> str:
    """将 sub_queries 列表格式化为自然语言文本。

    只提取 text 非空的子查询（structured_filter 的 text 通常为空，
    已经在 DB 层过滤，不需要 LLM 再关注）。

    参数:
        sub_queries: 查询解析阶段产出的子查询列表，或 None。

    返回:
        格式化后的自然语言字符串；sub_queries 为空/None 时返回 ""。
    """
```

**实现思路：**
1. 若 `sub_queries` 为 None 或空列表 → 返回 `""`
2. 遍历，过滤出 `text` 非空且非空白字符的项
3. 编号后格式化为 `"用户关心以下方面：\n1. {text}\n2. {text}\n..."`
4. 若过滤后为空 → 返回 `""`
5. 纯函数，无副作用，无外部依赖

### 3.2 `Generator.generate()` 签名扩展

**所在文件：** `app/rag/generator.py`

```python
# 改前
async def generate(self, products: list[dict], user_query: str):

# 改后
async def generate(
    self,
    products: list[dict],
    user_query: str,
    sub_queries: list[dict] | None = None,
):
```

**用户消息模板变更：**

```
改前:
  "请根据以上商品信息，为用户推荐：{user_query}"

改后:
  "请根据以上商品信息，为用户推荐：{user_query}"
  + ("\n\n{formatted_subs}" if formatted_subs else "")
```

**实现思路：**
1. `system_prompt` 构建逻辑不变
2. `user_msg` 追加 `_format_sub_queries(sub_queries)` 的内容（非空时）
3. `sub_queries=None` 时退化到原有行为，100% 向后兼容

### 3.3 `GENERATOR_SYSTEM` prompt 扩展

**所在文件：** `app/rag/prompt.py`

**实现思路：**

1. **规则 7 更新**（字数限制配置化）：将硬编码 `200` 替换为占位符 `{reasoning_max_chars}`
2. **规则 8 追加**（覆盖全部商品）：`"必须为结果列表中的每一个商品都说明推荐理由，不能只推荐其中一个"`
3. **规则 9 追加**（回应全部意图）：`"如果用户消息中列出了用户关心的方面，请逐条回应每个方面是否满足"`

### 3.4 `search.py` `_run_pipeline()` 适配

**所在文件：** `app/api/search.py`

**实现思路：** 两处 `generator.generate(products, q)` 改为 `generator.generate(products, q, sub_queries=subs_detail)`：
- 非流式模式（约第 185 行）
- 流式模式 SSE（约第 232 行）

### 3.5 `SearchSettings` 配置扩展（可选，Step 4）

```python
# config.py
reasoning_max_chars: int = 200
"""推荐理由生成的字数软约束。"""
```

---

## 4. 关键数据结构

### 4.1 sub_queries 传递链

```
QUERY_PARSE_SYSTEM (LLM)
    │
    ▼
QueryParser.parse(q) → list[SubQuery]
    │  SubQuery.text / .strategy / .field / .operator / .value
    ▼
search.py _run_pipeline:
    subs_detail = [{"text": s.text, "strategy": s.strategy, ...}, ...]
    │
    ▼
generator.generate(products, q, sub_queries=subs_detail)
    │
    ▼
_format_sub_queries(subs_detail) → "用户关心以下方面：\n1. ...\n2. ..."
    │
    ▼
user_msg = "请根据以上商品信息，为用户推荐：防晒霜\n\n用户关心以下方面：\n1. 产品评价中是否提及酒精成分\n2. 产品防晒效果是否出色"
    │
    ▼
LLM 看到完整的用户意图上下文
```

### 4.2 格式化规则

```python
# 输入
sub_queries = [
    {"text": "防晒霜", "strategy": "keyword", ...},           # ✅ text 非空 → 纳入
    {"text": "产品评价中是否提及酒精成分", "strategy": "semantic", ...},  # ✅
    {"text": "", "strategy": "structured_filter", ...},        # ❌ text 为空 → 跳过
    {"text": "产品防晒效果是否出色", "strategy": "semantic", ...},      # ✅
]

# 输出
"""
用户关心以下方面：
1. 防晒霜
2. 产品评价中是否提及酒精成分
3. 产品防晒效果是否出色
"""
```

---

## 5. 主功能链路时序

```
search.py                              generator.py                    prompt.py
  │                                        │                               │
  │── _run_pipeline(q)                     │                               │
  │   │                                    │                               │
  │   │── QueryParser.parse(q)             │                               │
  │   │   → subs_detail                    │                               │
  │   │                                    │                               │
  │   │── Retriever.retrieve(subs)         │                               │
  │   │── Merger.merge(kw, sem)            │                               │
  │   │── _get_skus(db, skuhits)           │                               │
  │   │   → products                       │                               │
  │   │                                    │                               │
  │   │── generator.generate(              │                               │
  │   │       products, q,                 │                               │
  │   │       sub_queries=subs_detail) ────▶                               │
  │   │   │                                │                               │
  │   │   │── _build_context(products)     │                               │
  │   │   │   → context_str                │                               │
  │   │   │                                │                               │
  │   │   │── _format_sub_queries(         │                               │
  │   │   │       sub_queries)             │  ← ★ 新逻辑                   │
  │   │   │   → formatted_subs             │                               │
  │   │   │                                │                               │
  │   │   │── GENERATOR_SYSTEM.format(     │                               │
  │   │   │     product_context=context,   │                               │
  │   │   │     user_query=q)              │                               │
  │   │   │   → system_prompt              │                               │
  │   │   │                                │                               │
  │   │   │── user_msg = f"请根据以上...   │                               │
  │   │   │     + formatted_subs            │  ← ★ 新逻辑                   │
  │   │   │                                │                               │
  │   │   │── chat_stream(messages)        │                               │
  │   │   │   ← token stream               │                               │
  │   │   │                                │                               │
  │   │── SSE: products → reasoning → done                               │
```

---

## 6. 边界、隔离与降级

### 6.1 模块边界

| 模块 | 职责 | 不关心 |
|------|------|--------|
| `search.py` | 将 subs_detail 传给 generator | generator 如何使用 sub_queries |
| `generate()` | 组装 messages，调用 LLM | sub_queries 如何产生 |
| `_format_sub_queries()` | list[dict] → 自然语言字符串 | LLM 如何理解字符串 |
| `_build_context()` | SKU 列表 → 商品上下文文本 | sub_queries 内容 |
| `GENERATOR_SYSTEM` | 约束 LLM 生成行为 | 运行时数据 |

### 6.2 降级路径

```
sub_queries 为 None?
  → _format_sub_queries 返回 ""
  → user_msg 与改前完全一致
  → 行为 100% 退化

sub_queries 全部 text 为空?
  → _format_sub_queries 返回 ""
  → 同上退化

sub_queries 键缺失?
  → .get("text", "") 兜底
  → 不抛异常
```

### 6.3 不发生的事

- `_build_context(products)` 不改 —— LLM 看到的商品数据格式不变
- `products` 列表不改 —— 排序、截断逻辑不变
- API 响应 schema 不变 —— `SearchResponse` 字段不变
- `QueryParser.parse()` 不改 —— 查询解析逻辑不变
- LLM 调用次数不增加 —— 仍是 2 次（parse + generate）

### 6.4 已确认的设计决策

| # | 决策点 | 结论 |
|---|--------|------|
| D-1 | sub_queries 注入位置 | **用户消息**（非 system prompt），职责分离 |
| D-2 | _format_sub_queries 过滤规则 | 只提取 `text` 非空的项，跳过 structured_filter |
| D-3 | 向后兼容 | `sub_queries=None` 默认值，行为完全不变 |
| D-4 | 字数限制 | 软约束（prompt 中建议），不做代码截断 |
| D-5 | reasoning_max_chars | 放在 `SearchSettings`，可配置 |
