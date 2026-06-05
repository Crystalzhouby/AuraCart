# 问题定义 — SSE 展示流重构

> **输入**: `server/docs/AGENT_OPT/SHOW_OPT/SPEC.md`

## 1. 功能需求

- **FR1 欢迎语（welcome 事件）**：retrieval 节点入口处，基于 requirements 生成一段欢迎语，通过 SSE `welcome` 事件发送。单品类如"不含酒精的防晒霜对敏感肌超友好！帮你挑了几款口碑好、温和不刺激的。"，多品类如"海边度假装备得备齐！结合你的出游场景，帮你整理了几个超实用的品类～"

- **FR2 品类介绍语（chat_reply 事件，仅多品类）**：retrieval 节点内，每个品类处理前生成品类介绍语，通过 `chat_reply` 发送。如"🧴 首先是美妆护肤（防晒必备）。海边紫外线强，高倍数且防水的防晒必不可少："

- **FR3 products 事件改为单商品**：从发送该品类下所有商品的数组 `[{...},{...}]` 改为逐商品发送单对象 `{product_id, sku_id, category, sub_category}`。每发一个 product 紧跟一个 chat_reply 推荐该商品理由。

- **FR4 chat_reply 逐商品推荐理由**：从按品类聚合生成推荐理由（1 品类 1 次 LLM 调用）改为按商品独立生成（1 商品 1 次 LLM 调用）。检索与推荐理由生成解耦——`_category_task` 只做检索，推荐理由在 retrieval 主节点逐商品生成。

- **FR5 done 事件新增结束语**：在 retrieval 节点末尾，基于全部推荐结果调用 LLM 生成结束语，写入 done 事件的 `text` 字段。如"以上就是为你搭配的海边出游三件套，有看中的款式吗？或者告诉我你的预算，帮你再进一步筛选～"。

- **FR6 done 事件发送权变更**：done 事件从 option_gen 节点移至 retrieval 节点末尾发送（因为结束语需要 retrieval 上下文）。option_gen 只输出 next_options。

- **FR7 修复重复传参**：`scenario_gen.py` 中 `rewritten_query` 在 system prompt（`{user_query}` 占位符）和 user message 中重复传入，移除 user message 中的重复。

## 2. 性能需求

- **NFR1 LLM 调用增量**：推荐理由从 per-category 变为 per-product，LLM 调用次数增加。设 3 品类 × 2 商品 = 6 次（原来 3 次）+ 欢迎语 1 次 + 品类介绍 ~3 次 + 结束语 1 次 = 总计最大 ~11 次（原来 ~4 次）。需通过并发控制避免延迟爆炸——欢迎语/品类介绍/结束语可串行（轻量 prompt），商品推荐理由可并发（prompt 较重）。
- **NFR2 首字延迟**：逐商品发送有利于前端渐进式渲染，首个商品结果出现时间不变（检索延迟占主导）。

## 3. 最终交付物

1. `server/app/agent/nodes/retriever.py` — 重构 SSE 发送逻辑：欢迎语生成 + 品类介绍生成 + 逐商品推荐理由生成 + 结束语生成 + done 发送
2. `server/app/agent/nodes/option_gen.py` — 移除 done 事件发送，仅输出 next_options
3. `server/app/agent/nodes/scenario_gen.py` — 修复重复 rewritten_query
4. `server/app/agent/prompts/` — 新增 4 个提示词模板：欢迎语、品类介绍、单商品推荐理由、结束语
5. `delivery/API.md` — 同步更新 SSE 事件规格和示例
6. `server/app/agent/state.py` — 无变更（welcome_text/ending_text 不写入 state，直接通过 SSE 发送）

## 4. 硬约束

- **HC1** 不修改 AgentState 字段定义
- **HC2** 不修改 extraction_node / scenario_gen_node 的输出契约
- **HC3** 检索管线（SQL 条件→双路检索→RRF→reranker）不变
- **HC4** 前端 SSE 消费逻辑需同步更新（products 从数组变为单对象，welcome 为新事件类型）
- **HC5** 现有 fallback 策略不变（单品类失败隔离、reranker 降级等）

## 5. 隐含要求

1. welcome 事件为必需事件，所有路径（explicit/scenario）均需发送
2. 品类介绍语仅在 requirements 数量 > 1 时生成（单品类跳过）
3. 推荐理由 prompt 需比当前 GENERATOR_SYSTEM 更轻量（单商品上下文，非聚合）
4. 结束语需提及推荐的商品数量和各品类名称
5. 逐商品发送时保持品类内顺序（reranker 排序结果）
6. `retriever.py` 当前 ~435 行，重构后预计 ~550 行——需考虑拆分为子模块
7. 并行检索结果（`asyncio.gather`）完成后，SSE 发送为串行（逐个品类、逐个商品），保证前端展示顺序

## 6. 任务完成边界

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **SSE 事件流** | welcome / products(单) / chat_reply(单) / 品类介绍 / done(text) / next_options | 前端 SSE 消费代码 |
| **LLM 调用** | 欢迎语/品类介绍/逐商品推荐/结束语 prompt | 推荐理由质量调优 |
| **retrieval 重构** | SSE 发送逻辑从 _category_task 移至主节点 | 检索管线逻辑 |
| **代码清理** | 移除 option_gen 的 done 发送、修复 scenario_gen 重复 | option_gen 其他逻辑 |
| **文档** | API.md SSE 事件规格更新 | 新独立文档 |

## 7. 可能的风险点

| 风险 | 说明 |
|------|------|
| **R1 LLM 调用量膨胀** | 从 ~4 次/请求增至 ~11 次/请求，token 消耗和延迟增加。缓解：轻量 prompt + 欢迎语/介绍语复用轻量模型温度 |
| **R2 推荐理由质量下降** | 单商品推荐缺少品类内横向比较上下文。缓解：prompt 中注入用户原始需求 + 该品类下的全部商品概览 |
| **R3 done 事件语义变化** | done 原由 option_gen 发送（含 next_options_count），现改 retrieval 发送（含 next_options_count + text）。前端需要处理 text 字段 |
| **R4 retriever.py 膨胀** | 新增 ~4 个 LLM 调用 + SSE 编排逻辑，文件可能过大。缓解：将 LLM 生成逻辑抽到独立辅助函数或 retriever_llm.py |

## 8. 待明确问题

无 `[NEEDS CLARIFICATION]` 项。以下决策已在 brainstorming 阶段确认：

- 欢迎语生成位置：retrieval 入口（方案 B）
- 商品推荐理由策略：逐商品独立 LLM 调用（方案 A）
- 结束语生成位置：retrieval 末尾（方案 B）
