# DEFINE.md — 需求分析

> 输入：`server/docs/AGENT_OPT/EXTRACT_OPT/SPEC.md`
> 输出：本文件
> 日期：2026-06-07

## 1. 功能需求

**F1 — Step 1 提示词注入对话历史**

Extraction 节点的 Step 1（`EXTRACTION_STEP1_SYSTEM`）目前只接收当前 `user_query` 和品类列表，当用户查询缺少主体时（如"要轻量的"、"预算500以内"），LLM 无法确定品类。

需要将最近 N 轮对话历史注入 Step 1 提示词，让 LLM 能根据上下文推断品类。

## 2. 性能需求

无新增性能要求。`get_recent_queries()` 是纯内存操作，不增加外部调用。

## 3. 最终交付物

1. 更新 `EXTRACTION_STEP1_SYSTEM` 提示词模板，新增 `{recent_queries}` 占位符
2. 更新 `_extract_categories_and_brands()` 函数，注入历史查询文本
3. 更新对应单元测试

## 4. 硬约束

- Step 1 仍然是单次 LLM 调用，不增加调用次数
- 历史查询使用 `get_recent_queries()`（跨品类最近 N 轮），与 Router 保持一致
- N 复用现有配置 `settings.search.memory_recent_rounds`（默认 10）
- 历史查询格式：纯文本拼接，简洁即可，不需要复杂结构

## 5. 隐含要求

- 多轮对话场景下，Step 1 品类识别准确率应提升（尤其是模糊查询）
- 首轮对话（无历史）行为不变
- 不影响 Scenario Gen 路径（它走独立的 Step 逻辑）
- 不影响 Step 2/Step 3（它们已有品类级历史检索）

## 6. 任务完成边界

**完成标准：**
- `EXTRACTION_STEP1_SYSTEM` 包含 `{recent_queries}` 占位符
- `_extract_categories_and_brands()` 从 `state` 获取 `session_memory`，调用 `get_recent_queries()` 格式化后注入 prompt
- 无历史时 `{recent_queries}` 显示"(无历史对话)"或等效提示
- 现有测试全部通过，新增测试覆盖"有历史 → 推断品类"场景

**不做的事：**
- 不改动 Step 2/Step 3 逻辑
- 不修改 `get_recent_queries()` 函数本身
- 不修改 Router 或 Scenario Gen
- 不改变 Extraction 节点的整体三步流程

## 7. 风险点

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 历史查询过长撑爆 prompt token 上限 | 低 | 中 | `memory_recent_rounds` 默认 10 轮，上限可控；首轮无历史 |
| 不相关历史误导 LLM 品类判断 | 低 | 中 | 历史查询按时间降序排列，LLM 能区分当前 vs 历史 |
| 测试需要模拟多轮对话场景 | — | — | 构造 mock state 含 `session_memory` 即可，无需网络 |

---

> 无 `[NEEDS CLARIFICATION]` 标记。需求边界清晰。
