# /search/stream 检索结果优化 — 问题定义

## 1. 最终交付物

修复 `/api/search/stream` 阶段 3 的 SSE `products` 事件输出，使返回结果单位从 **product** 切换为 **SKU**。

当前阶段 3 虽然 RRF 融合产出的是 `list[SKUHit]`（含 `sku_id` + `product_id`），但后续处理丢弃了 `sku_id`，仅提取 `product_id` 去查询，返回的是 product 级别的数据（含该 product 下所有活跃 SKU）。

修复后每条结果应是一个匹配的 SKU + 其所属 product 的基本信息，合为一个扁平结构：

| 字段 | 来源 | 类型 |
|------|------|------|
| product_id | product | str |
| title | product | str |
| brand | product | str \| null |
| category | product | str \| null |
| sub_category | product | str \| null |
| sku_id | sku | str |
| properties | sku | dict \| null |
| price | sku | float |
| stock | sku | int |

涉及的变更文件：
- `api/search.py`：重写 `_get_products()` → 按 `sku_id` 查询、JOIN product 补全信息；调整阶段 3 调用方式
- `rag/generator.py`：`_build_context()` 适配新的扁平 SKU 级数据结构（当前按 product 分组 + 嵌套 skus 的格式将不可用）

---

## 2. 硬约束

1. SSE 事件名和顺序不变（`products` → `reasoning` → `done`）
2. 上游 Retriever/Merger 接口不变 — 它们已经正确输出 `list[SKUHit]`
3. 不影响 `/api/search`（非流式）接口
4. 不改变数据库 schema

---

## 3. 隐含要求

1. **同一 product 下多个 SKU 命中时去重策略**：若 RRF 返回的 Top-K 中包含同一 product 的多个 SKU，是全部保留（每个 SKU 各自一条结果）还是按 product 去重仅保留最高分的 SKU？**需确认**。当前 SPEC 倾向全部保留（每个命中 SKU 独立返回）。
全部保留

2. **generator 数据格式适配**：当前 `_build_context()` 按 product→嵌套 skus[] 分组格式化。若 SSE 输出改为扁平 SKU 级列表，generator 的 context 构建需同步改造，否则 LLM 推荐的上下文质量会受影响。改造方式有两种：
   - **选项 A**：在 generator 内部按 product_id 重新分组，恢复嵌套格式再构建 context。优点：最小化 generator 输出差异；缺点：多一次遍历。
   - **选项 B**：重写 `_build_context()` 直接处理 SKU 级列表。优点：更精确反映匹配结果；缺点：输出格式变化可能影响 LLM 推荐质量。**需确认**。
选项A吧

3. **结果顺序保持**：RRF 融合给出的 `list[SKUHit]` 顺序即为最终排序，数据补全后必须保持该顺序不变。

4. **_get_products 重命名**：函数职责从"按 product_id 查 product+skus"变为"按 sku_id 查 sku+product"，需重命名以避免误导（如 `_get_skus`）。

---

## 4. 任务完成边界

**在范围内：**
- `search.py` 中 `_get_products()` 重写为按 SKU 查询、JOIN product 返回扁平结果
- `search.py` 中阶段 3 调用改为传入 `ranked_skuhits`（而非仅 product_id）
- `generator.py` 中 `_build_context()` 适配新数据结构
- 相关测试适配

**不在范围内：**
- 前端/客户端 SSE 解析适配
- Retriever/Merger 逻辑变更
- `/api/search` 非流式接口
- DB schema 变更

---

## 5. 实现过程可能遇到的风险点

| 风险 | 影响 | 缓解 |
|------|------|------|
| generator context 格式变化导致 LLM 推荐质量下降 | 推荐文案不如之前自然/准确 | 保留 group-by-product 的结构化表达，仅把多 SKU 列表缩为匹配的单 SKU |
| 同一 product 多 SKU 命中时，generator context 中出现重复 product 描述 | LLM 产生困惑或冗余推荐 | 可在 context 中合并同 product 的 SKU 行 |
| 结果顺序在 DB 查询后被打乱 | RRF 排序失效 | 补全数据后按 `ranked_skuhits` 原始顺序重新排列 |
| `sku_id` 在 product_review 表中不存在（当前三表 JOIN 以 `s.sku_id` 为检索单元，但实际 product_review 不直接关联 sku） | **需核实**：当前 retriever 的 SQL 已经 JOIN sku 表并返回 s.sku_id，但 product_review 与 sku 通过 product_id 间接关联。语义检索中一个 product 的 review 可能对应多个 SKU，所有从该 review 命中的 SKU 会获得相同语义得分。这一点之前设计已确认（product 级得分继承给 SKU），不引入新问题。 | 无需额外处理 |
