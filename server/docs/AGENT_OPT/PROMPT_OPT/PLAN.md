# 架构方案 — 提示词品牌注入与格式对齐

> **输入**: `server/docs/AGENT_OPT/PROMPT_OPT/DEFINE.md`

## 1. 整体实现架构

```mermaid
flowchart TD
    subgraph "extraction.py 变更"
        A[Step1: LLM 提取品类] --> B[Step2: 拼接历史 context]
        B --> C[新增: 按品类批量查询品牌]
        C --> D[品牌列表追加到 context 末尾]
        D --> E[Step3: LLM 提取意图]
        E --> F[brand 默认值 None→[]]
    end

    subgraph "scenario_gen.py 变更"
        G[解析 category_list] --> H[新增: 批量查询全部品类品牌]
        H --> I[品牌映射表注入 prompt]
        I --> J[LLM 生成 requirements]
        J --> K[brand 默认值 None→[]]
    end

    subgraph "tools.py 新增"
        L[get_brands_by_category<br/>按单品类查询]
        M[get_brands_by_categories<br/>批量查询]
    end

    C --> L
    H --> M
```

**关键设计**：
- extraction Step3：已知品类（Step1 输出），精确查询对应品牌，追加到 context
- scenario_gen：品类未定，预先查询 category_list 中全部品类的品牌，格式化为映射表注入 prompt
- 两个新工具函数：单品类查询 + 批量查询

## 2. 核心功能接口 vs 需求映射

| FR | 功能 | 实现位置 | 说明 |
|----|------|---------|------|
| FR1 | 品牌工具函数 | `tools.py` → `get_brands_by_category`, `get_brands_by_categories` | 封装 `query_field_values` |
| FR2 | Step3 品牌注入 | `extraction.py:_extract_intents_per_category` 调用前 | 按 Step1 品类查询品牌 → 追加到 context |
| FR3 | scenario_gen 品牌注入 | `scenario_gen.py:scenario_gen_node` | 查询 category_list 全部品牌 → 注入 prompt `{brand_map}` |
| FR4 | 提示词格式对齐 | `extraction_prompt.py`, `scenario_gen_prompt.py` | 移除 TODO + 品牌注入说明 + 选取规则 |
| FR5 | 返回格式对齐 | `extraction.py:223`, `scenario_gen.py:193` | `brand` 默认 `None` → `[]` |

## 3. 模块设计

### 3.1 `tools.py` — 新增 2 个函数

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `get_brands_by_category` | db, category, sub_category | `list[str]` | 单品类品牌列表，截断 top-20 |
| `get_brands_by_categories` | db, pairs: `list[tuple[str,str]]` | `dict[(cat,sub), list[str]]` | 批量查询，1 次 SQL，返回映射表 |

**`get_brands_by_categories` 实现思路**：
```sql
SELECT category, sub_category, brand, COUNT(*) AS cnt
FROM product
WHERE (category, sub_category) IN ((...), (...), ...)
  AND brand IS NOT NULL
GROUP BY category, sub_category, brand
ORDER BY category, sub_category, cnt DESC
```
按商品数量排序后每个品类取 top-20 品牌。

### 3.2 `extraction_prompt.py` — 移除 TODO，新增品牌选取规则

**Step3 prompt 变更**：
- 移除 `### TODO 根据(category, sub_category)查询品牌名工具`
- 新增规则：品牌从下方列表选取，不能编造；列表为空时填 `[]`
- 新增占位符 `{brand_reference}` 用于注入品牌列表

### 3.3 `scenario_gen_prompt.py` — 同上

- 移除 `## TODO 根据(category, sub_category)查询品牌名工具`
- 新增占位符 `{brand_map}` 用于注入品类→品牌映射表
- brand 示例值 `null` → `[]`

### 3.4 `extraction.py` — Step3 品牌注入 + 格式对齐

**变更点**：

1. `extraction_node()` 第 259 行：Step2 和 Step3 之间插入品牌查询
2. `_extract_intents_per_category()` 接受新增的 `brand_map` 参数，注入到 prompt
3. 第 220 行：brand 默认值 `None` → `[]`

### 3.5 `scenario_gen.py` — 品牌注入 + 格式对齐

**变更点**：

1. `scenario_gen_node()` 第 146 行之前：解析 category_list → 批量查询品牌
2. prompt 增加 `{brand_map}` 占位符替换
3. 第 193 行：brand 默认值 `None` → `[]`

## 4. 数据流

```
extraction 路径:
Step1 品类列表 → get_brands_by_categories(pairs) → {(cat,sub): [brands]}
→ 追加到 Step3 context → LLM 从列表中选取 brand

scenario_gen 路径:
category_list 全部品类 → get_brands_by_categories(pairs) → {(cat,sub): [brands]}
→ 注入 prompt {brand_map} → LLM 从列表中选取 brand
```

## 5. 方案优点

1. **零 LLMService 改动**：纯 prompt 文本注入，不碰 API 接口
2. **复用现有工具**：`get_brands_by_categories` 基于 `query_field_values`，共享白名单和参数化 SQL
3. **批量查询高效**：scenario_gen 全部品类 1 次 SQL，extraction Step3 也是 1 次批量 SQL
4. **Step1 不变**：现有 post-hoc 校验逻辑完全保留
5. **品牌截断控制**：每品类 top-20 品牌（按商品数），token 增量可控

## 6. 主要风险

| 风险 | 缓解 |
|------|------|
| R1: 品牌列表过长 | 每品类截断 top-20（按商品数量）；scenario_gen 仅注入 category_list 中品类 |
| R2: LLM 仍编造 | 提示词强化约束 + Step1 post-hoc 校验作为安全网 |
| R3: DB 查询失败 | catch exception → 品牌列表为空 → LLM 输出 `[]`，不阻断流程 |

## 7. 实现复杂度评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 代码量 | 低 | 新增 ~60 行（2 个函数）、修改 ~20 行（提示词 + 节点） |
| 逻辑复杂度 | 低 | 查询→注入→LLM 调用的直线流程 |
| 测试复杂度 | 低 | 工具函数纯 DB 查询，可 mock；LLM 调用可验证 prompt 包含品牌列表 |
| 风险等级 | 低 | 增量式修改，不影响现有检索/推荐管线 |

## 8. 可测试性评估

- `get_brands_by_category` / `get_brands_by_categories` 可独立 mock DB 测试
- extraction Step3 context 可通过单元测试验证品牌列表注入
- scenario_gen prompt 可测试 `{brand_map}` 占位符替换正确性
- brand 默认值 `None` → `[]` 的变更可被现有测试覆盖

## 9. 可交付性评估

- 全部改动在 5 个已有文件，无新文件
- 无外部依赖
- 可独立于其他优化分支开发
- prompt 注入失败有优雅降级（brand=[]），不影响核心功能

---

> 下一阶段: `CON_PLAN.md` — 编码级详细设计
