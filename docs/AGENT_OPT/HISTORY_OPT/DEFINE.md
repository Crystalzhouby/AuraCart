# DEFINE.md — 需求分析

> 输入：`SPEC.md` → 输出：本文件
> 日期：2026-06-09

## 1. 功能需求

**F1 — chitchat 也记录对话历史**

当前只有 retriever 节点调用 `append_query` 将查询写入 `session_memory`，chitchat 路径不记录。需要在 Router 的 chitchat 分支（`intent == "chat"` → END）中追加历史记录，使 chitchat 对话可见于后续多轮。

**F2 — 历史查询时间关注度提示**

所有使用对话历史的节点，在 prompt 中对历史查询文本增加"越近越重要"的引导，让 LLM 优先关注最近的对话。

## 2. 性能需求

无新增性能要求。`append_query` 是纯内存操作，不增加外部调用。

## 3. 最终交付物

1. `router.py` chitchat 分支新增 `append_query` 调用
2. 相关 prompt 模板增加时间关注度提示

## 4. 硬约束

- chitchat 无品类信息，`append_query` 的 `categories=[]` → 自动落入 `unknown` 组
- 不新增 LLM 调用
- 不改动 `session_memory` 数据结构
- 不改动 `append_query` 函数本身

## 5. 隐含要求

- 多轮切换场景（chitchat → 导购 → chitchat → 导购）下，历史完整性提升
- chitchat 对话不影响品类检索（存入 `unknown` 组，品类级检索不会命中）
- Router 的 `get_recent_queries` 跨品类检索能包含 chitchat 记录

## 6. 任务完成边界

**完成标准：**
- chitchat 路径结束后，`session_memory` 包含该轮查询记录
- 各节点 prompt 中历史段包含"最近对话优先"或等效提示
- 现有测试全部通过

**不做的事：**
- 不新增 `chat_history` 字段
- 不实现滑动窗口或对话摘要
- 不改动 `get_recent_queries()` / `get_queries_by_category()` / `append_query()` 函数本身
- 不改动 retriever 已有的 `append_query` 逻辑

## 7. 风险点

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| chitchat 频繁刷入 useless 历史，影响 Router 后续判断 | 低 | 低 | Router 只取 `memory_recent_rounds=10` 轮，自然淘汰旧记录 |
| chitchat 存入 `unknown` 组后，品类检索不受影响 | — | 无 | 设计保证 |

---

> 无 `[NEEDS CLARIFICATION]` 标记。需求边界清晰。
