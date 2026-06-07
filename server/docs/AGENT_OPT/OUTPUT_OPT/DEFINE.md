# DEFINE.md — 流式输出优化需求分析

> 输入：`server/docs/AGENT_OPT/OUTPUT_OPT/SPEC.md` + `server/docs/AGENT_OPT/MERGE_OPT/SPEC.md`
> 现状参考：`server/docs/AGENT_OPT/GENERAL/OUTPUT_DESIGN.md`

## 1. 功能需求

### F1: 流式/非流式输出开关
- `/api/search` 已有 `stream` 参数（默认 `true`），但目前未实际控制节点行为
- `stream=false`：保持当前行为，所有 SSE 事件以完整文本为单位推送
- `stream=true`：welcome / category_intro / ending / chat_reply 按 token 逐条推送

### F2: 文本类事件逐 token 流式
- welcome / category_intro / ending / chat_reply 使用 `chat_stream()` 生成
- 每个 token 作为独立 SSE 事件，事件名加 `_stream` 后缀
- 事件格式：`{"type":"start"}` → `{"type":"delta","text":"..."}`* → `{"type":"end"}`
- products / product_reason 保持业务事件级别推送不变

### F3: 合并结束语 + 选项生成（来自 MERGE_OPT）
- 一次 LLM 调用同时输出 ending 和 next_options
- 输出格式：`{"ending": "...", "next_options": ["...", "..."]}`
- ending 文本部分需逐 token 流式推送

### F4: 合并查询相关 LLM 调用（来自 MERGE_OPT）
- Router 不再做查询改写
- 欢迎语基于历史对话 + 原查询生成（不再基于重写后查询）
- Extraction / ScenarioGen 直接使用原查询

## 2. 性能需求

- 流式模式下，首个 welcome token 应尽快到达客户端（Router 完成后立即开始流式推送）
- category_intro 和 ending 的 token 延迟应与 LLM 生成同步
- 逐 token 推送不应对 LLM 生成吞吐造成显著影响
- 非流式模式性能应不低于当前实现

## 3. 最终交付物

1. 修改后的 AgentState 定义
2. 修改后的 Router 节点（流式 welcome + queue 传入）
3. 修改后的 ChitChat 节点（逐 token 推送）
4. 修改后的 Retriever 节点（流式 category_intro + 合并 ending/options 的流式生成）
5. 修改后的 OptionGen 节点（透传或兜底）
6. 新增流式 JSON 字段提取工具函数
7. 更新后的 `search.py`（stream 参数注入 state）
8. 更新后的 SSE 事件文档（OUTPUT_DESIGN.md）

## 4. 硬约束

- 不改变 products / product_reason 的事件格式和发送时机
- 不改变 `_agent_event_stream` 消费循环的核心逻辑
- 不改变单 `asyncio.Queue` 架构
- 向后兼容：客户端若只监听旧事件名（如 `welcome`），非流式模式下仍能正常工作
- 不与 MERGE_OPT 的变更冲突

## 5. 隐含要求

- 流式 JSON 提取器不依赖外部库（状态机即可满足需求）
- 异常情况下流式提取失败时，应有降级策略（退回到解析完整 JSON）
- stream 参数需在整个工作流中可访问，通过 AgentState 传递

## 6. 任务完成边界

**包含：**
- AgentState 新增 `stream` 字段，移除 `welcome_text` 和 `rewritten_query`
- Router / Retriever / ChitChat 的流式改造
- 合并 ending + option_gen 的 LLM 调用及流式提取
- Graph 构建层将 queue 传入 Router
- `search.py` 将 stream 参数注入 initial_state

**不包含：**
- 客户端 SSE 解析逻辑的更新
- 其他节点的功能变更（Extraction、ScenarioGen 保持非流式）
- MERGE_OPT 中除影响流式部分外的其他变更
- 非流式模式下的 LLM 调用合并（由 MERGE_OPT 复用的现有逻辑）

## 7. 风险点

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 流式 JSON 提取器在边界情况（ending 含特殊字符/嵌套引号）解析错误 | ending 文本截断或乱码 | 充分测试含转义字符、emoji 等场景；失败时回退到完整 JSON 解析 |
| LLM 输出格式不遵循 `{"ending":"...","next_options":[...]}` | 无法提取 ending 和 options | 兜底正则提取 + fallback 默认值 |
| Router 引入 queue 后职责增加 | 节点耦合度上升 | queue 通过 graph.py 构建层注入，Router 只知 `_sse_queue` 字段名 |
| stream 事件名变更导致旧客户端不兼容 | 旧客户端收不到 `_stream` 事件 | `_stream` 是新事件名，旧客户端监听的事件仍能正常接收（`stream=false` 默认） |
