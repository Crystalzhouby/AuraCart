# DEFINE.md — Retrieval Node SSE 重构需求分析

> 基于 SPEC.md，经需求澄清后的需求定义文档。

## 1. 功能需求

### F1: _category_task 职责精简

当前 `_category_task` 承担检索 + SSE 发送 + 推荐理由生成。改造后：

- **保留**：SubQuery 构建 → Retriever 检索 → RRF 融合 → SKU 详情获取 → Generator 流式生成推荐理由 → token 缓冲拼接
- **移除**：`queue.put({"event": "products", ...})` — 不再发送任何 SSE 事件
- **移除**：`queue` 参数
- **返回**：结构化结果 `{category, sub_category, products_summary, reasoning_text, error}`
  - `reasoning_text` 为 `"".join(tokens)` 的完整字符串（替代原来的 `reasoning_tokens: list[str]`）

### F2: retrieval_node 统一 SSE 发送

`retrieval_node` 接管全部 SSE 发送职责，按品类顺序单线程迭代：

```
for each category in group order:
    1. 发送 products SSE 事件（product_id, sku_id, category, sub_category）
    2. 发送 reasoning SSE 事件（reasoning_text, category, sub_category）
    3. 若有下一品类 → 继续
```

- `products` 事件结构不变：`{"event": "products", "data": [{product_id, sku_id, category, sub_category}, ...]}`
- `reasoning` 事件结构不变：`{"event": "reasoning", "data": {token, category, sub_category}}`（`token` 字段名保持不变以兼容前端）

### F3: 删除 _send_reasoning_sequential

`_send_reasoning_sequential` 的逻辑合并到 `retrieval_node` 主流程，该函数直接删除。

### F4: products_summary 聚合保持不变

`_aggregate_results` 的聚合逻辑不变，`products_summary` 仍写回 AgentState 供 `option_gen` 使用。

## 2. 性能需求

- 并行检索不受影响：各品类的 `_category_task` 仍通过 `asyncio.gather` + `Semaphore` 并行执行
- SSE 发送从并行变串行，但发送的是已缓存好的完整数据，无额外 I/O 开销
- 前端首字节延迟：第一个品类的 products 事件到达时间不变（并行 task 中最快完成的那个）

## 3. 最终交付物

1. 修改后的 `server/app/agent/nodes/retrieval.py`
2. 相关测试用例更新（`tests/test_retrieval_node.py`）
3. 确认 112 个离线测试通过，0 回归

## 4. 硬约束

- **不修改** Generator 的接口和流式生成逻辑
- **不修改** SSE 事件的数据结构（`products` / `reasoning` 的 JSON schema 不变）
- **不修改** `option_gen_node` 和 `search.py` 中的 SSE 消费逻辑
- **不修改** `_category_task` 的检索和生成时序（仍是检索→生成→返回）

## 5. 隐含要求

- `_category_task` 失败时仍需返回 `error` 字段，`reasoning_text` 为空字符串
- `retrieval_node` 需要处理 `_sse_queue` 为 None 的情况（非 SSE 调用路径）
- `products_summary` 字段的 `price` 和 `title` 仍需保留，供 `option_gen` 使用

## 6. 任务完成边界

| 范围 | 包含 | 不包含 |
|---|---|---|
| retrieval.py | `_category_task`、`retrieval_node`、删除 `_send_reasoning_sequential` | 其他节点 |
| tests | 更新 `test_retrieval_node.py` 中相关 mock 和断言 | 新功能的新增测试 |
| Generator | 无变更 | — |
| search.py / API 层 | 无变更 | — |
| option_gen | 无变更 | — |

## 7. 风险点

- **R1**: `_category_task` 移除 `queue` 参数后，所有调用方（`_bounded_task`、测试）需要同步修改
- **R2**: 并行 task 完成后 `reasoning_text` 可能是空字符串（LLM 生成失败），需要跳过对应品类的 SSE 发送
- **R3**: 原 `reasoning_tokens: list[str]` 改为 `reasoning_text: str`，`_aggregate_results` 不需要修改（它只读 `products_summary`），但 `retrieval_node` 内部的数据解构需适配

---

> **状态**: 已确认，无 `[NEEDS CLARIFICATION]` 项。可进入 PLAN.md 阶段。
