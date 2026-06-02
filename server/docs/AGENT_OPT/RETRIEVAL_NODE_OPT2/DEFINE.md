# DEFINE.md — Retrieval + Option Gen 节点设计完善需求分析

> 基于 [SPEC.md](SPEC.md)，分析功能需求、约束和边界。

---

## 1. 功能需求

### F1: Retrieval 节点日志增强
- 每个品类的检索语句（sub_queries text）需打印到日志
- 每个品类的检索结果数量（RRF 排名后的 SKU 数）需打印
- 每个品类的推荐理由（Generator 输出）需打印

### F2: Retrieval 节点输出变更
- **移除** `products_summary` 输出（当前为轻量摘要：`product_id/sku_id/title/price/category/sub_category`）
- **新增** `retrieval_results` 输出：完整 SKU 数据（`_get_skus()` 返回的全部字段），**包含 `matched_texts`（即 product_review）**
- `retrieval_results` 通过 AgentState 传递给 option_gen 节点
- SSE 事件（products/reasoning）不变

### F3: Option Gen 节点输入变更
- **不再接收** `products_summary`
- **改为接收** `retrieval_results`：包含商品基础信息 + product_review（matched_texts）
- 复用 retrieval 已查询的数据，**不重复查 DB**（方案A）
- Prompt 模板更新：同时利用商品基础信息和 product_review 生成下一步选项

### F4: AgentState 字段调整
- `products_summary: list[dict]` → `retrieval_results: list[dict]`

---

## 2. 性能需求

- 无新增 DB 查询（方案A 复用已有数据）
- 日志输出为同步 `logger.info`，不影响检索并行度
- `retrieval_results` 包含 matched_texts，数据量大于原 `products_summary`，但仍在内存可接受范围内（每个品类 ≤10 SKU，每 SKU ≤3 条 FAQ 文本）

---

## 3. 最终交付物

1. 代码变更：`retrieval.py`、`option_gen.py`、`option_gen_prompt.py`、`state.py`、`graph.py`
2. 测试适配：`test_retrieval_node.py`、`test_option_gen.py`（如有）
3. 文档：`DEFINE.md`、`PLAN.md`、`CON_PLAN.md`（本目录）

---

## 4. 硬约束

| ID | 约束 |
|---|---|
| C1 | 不改变 Generator、Retriever、Merger、SKU utils 的接口 |
| C2 | SSE 事件结构不变（products/reasoning/done 的 event 和数据格式保持兼容） |
| C3 | option_gen 不新增 DB 依赖（方案A） |
| C4 | 不改变 LangGraph 图结构（节点顺序、边不变） |
| C5 | 不改变 `_get_skus()` 函数签名和实现 |

---

## 5. 隐含要求

- `matched_texts` 即 SPEC 所指的"检索到的 product_review"——在语义/关键词检索步骤中命中、经 `_get_skus()` SQL JOIN 聚合后挂载到每个 SKU 上的 ProductReview 记录
- option_gen 接收到 product_review 后能生成更精准的选项（如基于 FAQ 中提到的搭配产品、使用场景等）
- 日志输出需使用 structlog（与项目一致的日志框架）

---

## 6. 任务完成边界

### 范围内
- retrieval 节点日志打印
- `products_summary` → `retrieval_results` 字段重命名和数据充实
- option_gen 适配新输入格式和 prompt
- 测试适配

### 范围外
- Generator 流式输出的 token 级 SSE 改造
- Router / Extraction / Scenario Gen / ChitChat 节点变更
- `search.py` API 层变更（SSE consumer 逻辑不变）
- product_review 数据结构的变更
- 新增任何配置项

---

## 7. 风险点

| ID | 风险 | 缓解 |
|---|---|---|
| R1 | `retrieval_results` 数据量增大导致 state 序列化开销 | 仅内存传递，不涉及序列化；品类数 ≤ max_category_concurrency |
| R2 | option_gen prompt 中注入 matched_texts 后 token 超限 | prompt 模板需控制 matched_texts 长度，复用 `_truncate_texts` 截断 |
| R3 | 改名遗漏导致下游读取 KeyError | `products_summary` 全量搜索替换为 `retrieval_results` |

---

> **状态**: 已确认，无 `[NEEDS CLARIFICATION]` 项。可进入 PLAN.md 阶段。
