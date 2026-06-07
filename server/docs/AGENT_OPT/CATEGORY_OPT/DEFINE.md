# CATEGORY_OPT — 需求分析

> 输入: `server/docs/AGENT_OPT/CATEGORY_OPT/SPEC.md`
> 输出: `server/docs/AGENT_OPT/CATEGORY_OPT/DEFINE.md`

## 1. 功能需求

### F1: SSE 事件标签重命名

涉及文件: `retriever.py`, `search.py`, `chitchat.py`

| 节点 | 当前 event | 新 event | 说明 |
|---|---|---|---|
| retrieval — 品类介绍 | `chat_reply` | `category_intro` | 品类过渡语 (retriever.py:454) |
| retrieval — 商品推荐理由 | `chat_reply` | `product_reason` | 单商品推荐语 (retriever.py:479) |
| retrieval — 结束语 | `ending` | `ending` | 已正确，无需改 |
| chitchat — 闲聊回复 | `chat_reply` | `chat_reply` | 闲聊路径，保持不改 |

关键约束: `_agent_event_stream` (search.py:252) 对 `done` 事件做了提前拦截 (`event["event"] == "done"`)。新事件名不会改变这个逻辑，无需修改 search.py。

### F2: 结束语上下文补充

涉及文件: `show_prompt.py`, `retriever.py`

- `ENDING_SYSTEM` 当前缺少 `{user_query}` 字段
- 需要在 prompt 中添加 `{rewritten_query}`，要求结束语生成主要回应当前用户查询
- 对话历史用于补充会话全局上下文
- `_generate_ending` (retriever.py:320-371) 调用 `.format()` 时需传入 `user_query`

### F3: scenario_gen_prompt 中 brand_map 补充

涉及文件: `scenario_gen.py`, `scenario_gen_prompt.py`, `graph.py`

**根因分析**: `graph.py:107-109` 调用 `scenario_gen_node` 时未传入 `category_list` 参数:

```python
# graph.py — 当前调用
result = await scenario_gen_node(
    state, llm=llm,
    db_session_factory=async_session_factory,
)
# ❌ 缺少 category_list=... → 默认为 ""
```

`category_list` 默认为 `""` → `_parse_category_list("")` 返回空集合 → `pairs` 为空列表 → `if pairs and db_session_factory` 条件不成立 → `brand_map_text` 保持初始值 `"(品牌数据暂不可用)"`。

**修复方案**: `scenario_gen_node` 内部自行加载 `category_list`（与 `extraction_node:121-126` 模式一致），调用 `fetch_category_context` 获取品类列表和品牌数据，不依赖调用者传入 `category_list`。

**需额外检查**: 修复后若品牌数据本身为空，`fallback` 文案需给 LLM 明确指引（如"当前暂无品牌数据，请基于品类信息生成推荐"）。

### F4: 品类交叉校验改为仅精确匹配

涉及文件: `scenario_gen.py`, `extraction.py`

用户决策: **完全移除模糊匹配**，仅保留精确匹配。配合数据修复 + 提示词强化。

需移除的位置:
- `scenario_gen.py:_cross_validate_categories` 中模糊匹配分支 (lines 61-71)
- `extraction.py:153-168` Step1 品类校验中同样逻辑
- 保留 strip 空白后的精确匹配（含对 lookup 的 strip 遍历匹配）

配合措施:
- 加强 `scenario_gen_prompt.py` 提示词：要求 LLM 输出的 category/sub_category 必须与可用品类列表逐字一致
- 提示词中明确列出可用品类的精确字符串

### F5: 修正测试/提示词中错误的 (category, sub_category) 对

涉及文件: `test_scenario_gen.py`, 其他可能存在的测试文件

已知错误:
- `test_scenario_gen.py:138`: `"美妆护肤|洗面奶"` — 该品类对不存在于 product/ category_lookup 表

排查范围: 所有 `.py` 文件中的 `category_list = "...|..."` 字符串，以及提示词中的示例 category/sub_category。

## 2. 性能需求

无新增性能需求。事件名重命名不影响延迟；精确匹配比模糊匹配更快。

## 3. 最终交付物

1. `retriever.py` — SSE event 标签修改 (F1)
2. `show_prompt.py` + `retriever.py` — 结束语 prompt 补充 user_query (F2)
3. `scenario_gen.py` + `graph.py` — brand_map 修复: scenario_gen_node 内部自行加载 category_list (F3)
4. `scenario_gen_prompt.py` — 提示词强化（精确匹配约束 + 品牌数据不足时的指引）(F3/F4)
5. `scenario_gen.py:_cross_validate_categories` — 移除模糊匹配，仅保留精确匹配 (F4)
6. `extraction.py` — 移除 Step1 模糊匹配 (F4)
7. `test_scenario_gen.py` — 修正错误品类对 (F5)
8. `server/docs/AGENT_OPT/GENERAL/SPEC.md` — 更新 SSE event 名引用（多处 `chat_reply` → `product_reason`/`category_intro`）
9. `delivery/API.md` — 更新 SSE event 表格

## 4. 硬约束

- 不能破坏现有 SSE 事件流: `welcome → category_intro → products → product_reason → ending → next_options → done`
- 不能改变 chitchat 路径的行为（保持 `chat_reply` event）
- 精确匹配仅限 `category_lookup` 表中真实存在的 (category, sub_category) 对
- 所有 71 个现有测试必须继续通过

## 5. 隐含要求

- 前端可能依赖 `chat_reply` event 名称 — 需要确认前端是否已适配新的 event 名
- 结束语生成质量应与欢迎语一致，需主动回应用户查询
- 移除模糊匹配后，LLM 输出的品类名若不在 lookup 中，该品类被丢弃（静默过滤）—— 比模糊匹配更严格，但也更可预测

## 6. 任务完成边界

- 完成 F1-F5 全部修改
- 修改后的测试全部通过（无回归）
- 手动 curl 验证 SSE 事件名正确、ending 内容回应用户查询
- 不涉及: 数据库 schema 变更、新增 API 接口、前端代码修改

## 7. 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| 移除模糊匹配后 LLM 输出不精确导致品类丢失 | 场景化推荐返回空品类 | 加强提示词，明确列出可用品类精确值；提示词中要求 LLM 从列表中选择而非自由生成 |
| 前端未适配新 event 名 | 前端无法渲染推荐理由 | 确认前端 event 消费代码 |
| 品牌数据本身为空 | brand_map 仍显示"暂无" | 非阻塞，品牌映射为辅助信息 |
| test_scenario_gen.py 修改后误删有效测试覆盖 | 测试覆盖降低 | 仅替换错误品类对，保留测试结构 |

## 8. 开放问题

无 `[NEEDS CLARIFICATION]` 项。所有设计决策已在 SPEC.md 和用户确认中明确。
