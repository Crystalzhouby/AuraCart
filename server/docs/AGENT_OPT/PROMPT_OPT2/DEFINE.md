# PROMPT_OPT2 — DEFINE.md

## 1. 功能需求

1. **欢迎词生成移至 Router**：将 `_generate_welcome()` 从 `retrieval_node` 移至 `router_node`。生成时额外传入跨品类最近 N 轮对话历史，使欢迎词语境更连贯。欢迎词写入 `state["welcome_text"]`，由 retrieval_node 入口发送 SSE。
2. **推荐理由融入对话历史**：`_generate_product_reason()` 新增按品类匹配的历史查询，注入提示词，增强推荐语的上下文感。
3. **结束语融入对话历史**：`_generate_ending()` 新增跨品类最近 N 轮对话历史，注入提示词。
4. **检索日志增加 score**：`semantic_search 结果` 和 `keyword_search 结果` 两处 debug 日志的 top_rows 增加 `score` 字段。

## 2. 性能需求

- 欢迎词生成在 router 节点多一次 LLM 调用（~1-2s），需与现有意图分类+改写串行，整体 router 耗时增加有限
- 推荐理由/结束语的 LLM 调用已存在，仅增加 prompt token 量（历史文本 ~500 chars），影响可忽略

## 3. 最终交付物

- 修改 4 个源文件（router.py, retriever.py, show_prompt.py, retriever_service.py）
- 3 个提示词模板各新增历史对话占位符

## 4. 硬约束

- 不改变 SSE 事件顺序和格式
- 不改变 AgentState 的 top-level 字段结构（welcome_text 为仅展示用的临时字段）
- 不新增 config 参数
- 不新增 Python 依赖

## 5. 隐含要求

- 欢迎词生成失败不阻塞主流程（返回空字符串，retrieval 跳过发送）
- 对话历史为空时各提示词正常降级（显示"(无历史记录)"）

## 6. 完成边界

- 不涉及前端改动
- 不涉及 API 接口变更
- 不涉及数据库 schema 变更
- 不涉及单元测试（现有测试无需修改，若涉及则更新 mock）

## 7. 风险点

- 欢迎词引用历史查询可能导致 LLM"泄露"之前的推荐内容（已在 prompt 中约束"不要编造商品名或具体品牌"）
- router 节点 LLM 调用从 2 次增至 3 次（分类+改写+欢迎语），router 整体耗时增加 ~1-2s
