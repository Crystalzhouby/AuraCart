# 推荐理由优化 — 实现方案

> 来源：[SPEC.md](SPEC.md) + [DEFINE.md](DEFINE.md) | 日期：2026-05-30

---

## 总体策略

**核心原则**：只改 prompt 内容和 `generate()` 签名，不改管线结构、不改 LLM 调用次数、不改检索/排序逻辑。所有功能点在一次 LLM 调用内完成。

**改动模块**（共 3 个文件）：

| 文件 | 改动类型 | 影响 |
|------|----------|------|
| [prompt.py](../../app/rag/prompt.py) | `GENERATOR_SYSTEM` 追加新规则，新增 `{sub_queries}` 占位符 | LLM 行为约束 |
| [generator.py](../../app/rag/generator.py) | `generate()` 签名新增 `sub_queries` 参数，用户消息格式化 | 调用方传参 |
| [search.py](../../app/api/search.py) | 两处 `generate()` 调用都传入 `sub_queries` | 数据透传 |

---

## F1：推荐理由覆盖全部商品

### 概要实现链路

```
search.py: _run_pipeline() → products (RRF 排序，含多 SKU)
    ↓
generator.generate(products, q, sub_queries=...)
    ↓
_build_context(products) → 按 product_id 分组后的文本（现有逻辑，不改）
    ↓
GENERATOR_SYSTEM.format(product_context=..., user_query=..., sub_queries=...)
    ↓
新规则约束 LLM: "为每个 product 说明推荐理由"
    ↓
LLM chat_stream → 逐 token 输出
```

**改动点**：仅在 `GENERATOR_SYSTEM` 中追加 1 条规则（约 3 行），不修改 `_build_context`、管线流程、API 接口。

### 主要优点

1. **最小改动**：只需在 prompt 中加 1 条约束规则，不改变任何代码逻辑
2. **向后兼容**：旧 prompt 中规则 7 本就允许推荐多商品，新规则 8 只是明确化"必须为每个商品都写理由"
3. **无性能影响**：不改 LLM 调用次数、不改 token 消耗量级（输出变长是需求本身要求的，不是架构开销）
4. **LLM 天然理解**：`_build_context` 已将 product 编号为 "1./2./3."，LLM 可直接引用

### 主要风险

| 风险 | 缓解 |
|------|------|
| LLM 可能忽略"逐个推荐"约束，仍然只推荐 1 个 | 规则用强约束词（"必须为列表中的每个商品都说明推荐理由"），放在规则列表末尾（近因效应）；**测试时用 count 校验** |
| 商品数多（5+ product）时输出冗长 | 约束每个商品 1-3 句话，参见 DEFINE.md 不确定项 1（推理总长度限制） |

### 实现复杂度

**低**。1 条 prompt 规则，不涉及代码逻辑修改。

### 可测试性

**高**。测试方式：
1. **单元测试**（`test_generator.py`）：验证 `generate()` 传入多 product 时，用户消息/系统 prompt 中包含新规则
2. **集成测试**（`test_search.py`）：验证 sub_queries 正确传入 generator
3. **效果验证**（manual）：用 example.txt 中的 query 1 重新执行，检查 reasoning 是否提及 ≥2 个 product

### 可交付性

**高**。改动 1 个文件的 1 个 prompt 变量，风险极低，可独立交付。

---

## F2：推荐理由回应全部用户意图

### 概要实现链路

```
sub_queries = [
  {"text": "产品评价中是否提及酒精成分", "strategy": "semantic", ...},
  {"text": "产品防晒效果是否出色", "strategy": "semantic", ...},
  {"text": "", "strategy": "structured_filter", "field": "brand", ...},
]
    ↓
_format_sub_queries(sub_queries) → 自然语言列表:
  "用户关心以下方面：
   1. 产品评价中是否提及酒精成分
   2. 产品防晒效果是否出色"
    ↓
注入用户消息: "请根据以上商品信息，为用户推荐：{user_query}\n\n{formatted_subs}"
    ↓
GENERATOR_SYSTEM 规则 9: "逐条回应用户关心的每个方面"
    ↓
LLM 生成的 reasoning 中必须包含对每个意图的回应
```

**改动点**：
1. `GENERATOR_SYSTEM` 追加规则 9（约 2 行）
2. `generator.py` 新增 `_format_sub_queries()` 私有方法（约 10 行）
3. `generate()` 用户消息模板追加 formatted sub_queries

### 主要优点

1. **信息已在管线中**：`subs_detail` 在 `_run_pipeline` 中已产出，只需透传，不需要额外计算
2. **自然语言格式化**：非 JSON 格式，避免 LLM 角色混淆（LLM 不会因此开始输出 JSON）
3. **结构化过滤项自动跳过**：`text` 为空的 `structured_filter` 不需要 LLM 关注（已经在 DB 查询层面过滤），`_format_sub_queries` 只提取 `text` 非空的项
4. **降级安全**：`sub_queries=[], None` 时格式化为空字符串，prompt 退化为当前行为

### 主要风险

| 风险 | 缓解 |
|------|------|
| `sub_queries` 中的 text 可能重复或语义相近，导致 LLM 冗余回应 | **不需要在代码层去重**（增加复杂度），LLM 自身会合并相近意图 |
| 如果数据中确实没有某个意图的对应信息（如"不含酒精"但所有商品 FAQ 都没提酒精），LLM 仍被要求回应 | 规则中用"根据已有信息"限定，允许 LLM 诚实说明"目前商品信息中未提及酒精成分" |

### 实现复杂度

**低**。新增一个 10 行的字符串格式化方法 + 1 条 prompt 规则。

### 可测试性

**高**。测试方式：
1. **`_format_sub_queries` 单元测试**（`test_generator.py`）：验证
   - 混合 sub_queries（有 text / 无 text）→ 只输出 text 非空的
   - 空列表 → 空字符串
   - None → 空字符串
   - 输出格式为自然语言而非 JSON
2. **集成测试**：验证 prompt 中包含格式化后的 sub_queries 文本

### 可交付性

**高**。改动仅 generator.py + prompt.py，无外部依赖。

---

## F3：子查询信息注入 LLM 上下文

### 概要实现链路

```
┌─ search.py _run_pipeline() ─────────────────────────────┐
│                                                          │
│  subs_detail = [                                         │
│    {"text": "...", "strategy": "semantic",                │
│     "field": null, "operator": null, "value": null},     │
│    ...                                                    │
│  ]                                                        │
│                                                          │
│  # 传入 generator.generate()                              │
│  generator.generate(products, q, sub_queries=subs_detail) │
│                                                          │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│ generator.py generate()                                   │
│                                                          │
│  def generate(self, products, user_query,                 │
│               sub_queries: list[dict] | None = None):     │
│                                                          │
│    formatted = self._format_sub_queries(sub_queries)      │
│                                                          │
│    user_msg = "请根据以上商品信息，为用户推荐："          │
│             + user_query                                  │
│             + ("\n\n" + formatted if formatted else "")   │
│                                                          │
│    system_prompt = GENERATOR_SYSTEM.format(               │
│      product_context=context,                             │
│      user_query=user_query,                               │
│    )                                                      │
│                                                          │
│    messages = [                                           │
│      {"role": "system", "content": system_prompt},        │
│      {"role": "user", "content": user_msg},               │
│    ]                                                      │
└──────────────────────────────────────────────────────────┘
```

### 主要优点

1. **签名扩展向后兼容**：`sub_queries=None` 默认值，调用方不传参时行为完全不变
2. **sub_queries 注入用户消息而非 system prompt**：理由——sub_queries 是"用户想要什么"的信息，属于用户侧上下文；system prompt 是"助手应该怎么回答"的约束。职责分离清晰
3. **不引入新的 LLM 调用**：不增加网络 IO
4. **token 开销可控**：sub_queries text 通常在 50-200 字符（2-4 个子查询），格式化后约增加 100-300 字符

### 主要风险

| 风险 | 缓解 |
|------|------|
| sub_queries 与 user_query 信息重复（如 user_query 本身已包含"不含酒精"）→ LLM 可能啰嗦 | 这是可接受的冗余，重复强调反而帮助 LLM 记住约束 |
| sub_queries 中可能包含用户未直接表达但 parser 推断的意图（如 parser 展开"日系品牌"→ expanded_values）| 这些推断意图注入后可能限制 LLM 的推荐范围（如用户没说不要日系，但 parser 推断要排除）→ 只传 `text` 非空的子查询，不传 expanded_values 细节到 LLM |

### 实现复杂度

**低**。改动 3 个文件，核心是参数透传 + 字符串拼接。

### 可测试性

**高**。测试方式：
1. **`generate()` 签名测试**：不传 `sub_queries` 时行为与原来一致（向后兼容）
2. **`generate()` 传入 sub_queries**：验证用户消息中包含格式化后的 sub_queries 文本
3. **search.py 集成测试**：mock entire pipeline，验证 `generate()` 被调用时 `sub_queries` 参数正确

### 可交付性

**高**。改动范围明确，不涉及数据库、API schema 变更。

---

## 补充功能点：推理长度限制（DEFINE.md 不确定项 1）

DEFINE.md 中标记的不确定项：**"是否需要配置项控制推荐理由总长度上限？"** 已确认需要。

### 概要实现链路

```
config.yaml → search.reasoning_max_chars: 500  (新增)
    ↓
config.py → SearchSettings.reasoning_max_chars: int = 500  (新增)
    ↓
prompt.py → GENERATOR_SYSTEM 规则 7 更新:
  旧: "推荐理由控制在200字以内，简洁有据"
  新: "推荐理由控制在{reasoning_max_chars}字以内，简洁有据"
    ↓
generator.py → GENERATOR_SYSTEM.format(..., reasoning_max_chars=...)
    ↓
search.py → generator.generate() 读取 settings.search.reasoning_max_chars 并传入（或 generator 内部直接引用 settings）
```

**设计选择**：`reasoning_max_chars` 放在 `SearchSettings` 中（与 `max_match_chars_per_sku` 同类），而非 prompt 中硬编码。

**注意**：LLM 对字数限制的遵循程度有限（通常在 ±30% 范围内），因此这是"软约束"而非精确截断。生成后不做代码级截断（避免截断不完整句子）。

### 主要优点

1. **可配置**：不同场景可调整（如移动端 300 字、详情页 800 字）
2. **与现有配置模式一致**：参考 `max_match_chars_per_sku` 的设计

### 主要风险

| 风险 | 缓解 |
|------|------|
| 字数限制可能导致 LLM 为了凑字数而省略重要信息（如某个 product 被完全跳过） | 规则 8（覆盖全部商品）优先级高于规则 7（字数限制），在 prompt 中规则 8 排在规则 7 之后 |
| LLM 对中文字数估算不准 | 设置为"软约束"，不用代码截断；中文字数 ≈ token 数，LLM 的 token 限制机制可辅助控制 |

### 实现复杂度

**低**。3 个文件各加 1 行。

### 可测试性

**中**。可验证配置值是否正确注入 prompt，但 LLM 输出字数是否确实 ≤ 限制需要人工评估。

### 可交付性

**高**。与其他功能点一起交付。

---

## 实现顺序建议

```
Step 1: prompt.py — 更新 GENERATOR_SYSTEM
        ├─ 追加规则 8（覆盖全部商品）
        ├─ 追加规则 9（回应全部意图）
        └─ 更新规则 7（reasoning_max_chars 可配置）【可选，取决于是否要一起做】

Step 2: generator.py — 扩展 generate() 签名 + 辅助方法
        ├─ 新增 sub_queries: list[dict] | None = None 参数
        ├─ 新增 _format_sub_queries() 私有方法
        ├─ 修改用户消息模板
        └─ 更新 GENERATOR_SYSTEM.format() 传参

Step 3: search.py — 透传 sub_queries
        ├─ 流式模式: generator.generate(products, q, sub_queries=subs_detail)
        └─ 非流式模式: 同上

Step 4: config.yaml + config.py — 新增 reasoning_max_chars【可选】

Step 5: 更新测试
        ├─ test_generator.py: 测试 _format_sub_queries + generate() 新签名
        └─ test_search.py: 适配如有需要
```

每个 Step 完成后运行 `pytest server/tests/ -v` 验证不退化。

---

## 总结

| 维度 | 评价 |
|------|------|
| **改动文件数** | 3-4 个（prompt.py, generator.py, search.py, 可选 config.yaml/config.py） |
| **新增代码行数** | 约 30-40 行（含注释和 prompt 文本） |
| **LLM 调用次数变化** | 无变化（仍为 2 次：query_parse + generate） |
| **API schema 变化** | 无变化 |
| **数据库变化** | 无变化 |
| **向后兼容** | 完全兼容（sub_queries 默认 None） |
| **合并风险** | 低。改动集中在 RAG 管线末端，与检索/排序改动无冲突 |
