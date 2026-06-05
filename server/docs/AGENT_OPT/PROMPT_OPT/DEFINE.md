# 问题定义 — 提示词品牌注入与格式对齐

> **输入**: `server/docs/AGENT_OPT/PROMPT_OPT/SPEC.md`

## 1. 功能需求

- **FR1 品牌工具函数**：在 `tools.py` 中新增 `get_brands_by_category(db, category, sub_category) → list[str]` 便捷函数，封装现有的 `query_field_values`。

- **FR2 extraction Step3 品牌注入**：在 Step3 LLM 调用前，按已识别的 (category, sub_category) 批量查询品牌列表，注入到 Step3 的 context 文本中。LLM 只能从注入的列表中选取品牌，不能编造。

- **FR3 scenario_gen 品牌注入**：在 scenario_gen LLM 调用前，根据可用品类列表预先查询所有品类的品牌，注入到 prompt 中。LLM 只能从注入的列表中选取品牌，不能编造。

- **FR4 提示词格式对齐**：
  - 移除 extraction Step3 中的 `### TODO 根据(category, sub_category)查询品牌名工具` 占位符，替换为品牌列表注入说明
  - 移除 scenario_gen 中的 `## TODO 根据(category, sub_category)查询品牌名工具` 占位符，替换为品牌列表注入说明
  - `brand` 字段默认值统一为 `[]`（空数组），不用 `null`
  - 提示词中明确：brand 值 MUST 从下方提供的品牌列表中选择

- **FR5 返回格式对齐**：extraction Step3 的 fallback 输出和 scenario_gen 的 normalized 输出中，`brand` 默认值从 `None` 对齐为 `[]`。

## 2. 性能需求

- **NFR1 Prompt token 增量**：品牌列表按品类注入，每个品类通常 5-20 个品牌名，总计增加 ~200-500 tokens。相比原 prompt（~2000 tokens），增幅控制在 25% 以内。
- **NFR2 DB 查询增量**：extraction Step3 前增加 1 次批量 DB 查询（按品类分组），scenario_gen 前增加 1 次批量查询（按全部可用品类），均在检索节点之前执行，不影响检索延迟。

## 3. 最终交付物

1. `server/app/agent/tools.py` — 新增 `get_brands_by_category` 便捷函数
2. `server/app/agent/prompts/extraction_prompt.py` — 移除 TODO 占位符，添加品牌列表注入占位符和选取规则
3. `server/app/agent/prompts/scenario_gen_prompt.py` — 同上
4. `server/app/agent/nodes/extraction.py` — Step3 前查询品牌并注入 context；brand 默认值对齐
5. `server/app/agent/nodes/scenario_gen.py` — 调用前查询品牌并注入 prompt；brand 默认值对齐

## 4. 硬约束

- **HC1** 不修改 `LLMService` 接口（不走 function calling 路线）
- **HC2** 不修改 `AgentState` 字段定义
- **HC3** 不修改 extraction Step1 的现有品牌校验逻辑（Step1 仍用 post-hoc 校验，独立不变）
- **HC4** category / sub_category 的交叉校验逻辑不变
- **HC5** 数据库 schema 不变（`query_field_values` 的 SQL 不变）

## 5. 隐含要求

1. `get_brands_by_category` 需处理 category 或 sub_category 为 None 的情况：当 category 为空时查询全部品牌，当仅 sub_category 已知时加 sub_category 过滤
2. 品牌列表为空时（数据库中该品类无商品），提示词中显示"(该品类下暂无品牌数据)"，LLM 应输出 `[]`
3. 国家/地区风格的品牌展开（如"日系"→["安热沙","资生堂"]）仍由 LLM 自行推理，但结果必须与注入的品牌列表取交集
4. extraction Step3 的 context 注入需保持现有格式不变，品牌信息作为附加段落追加到品类段末尾

## 6. 任务完成边界

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **工具函数** | `get_brands_by_category` 封装 | 新表/新字段 |
| **提示词** | 移除 TODO + 添加品牌注入占位符 + 选取规则 | 提示词其他内容修改 |
| **节点代码** | extraction Step3 品牌注入 + scenario_gen 品牌注入 + brand 默认值对齐 | Step1 逻辑修改 |
| **LLM 调用** | prompt 文本级品牌列表注入 | function calling 接口 |

## 7. 可能的风险点

| 风险 | 说明 |
|------|------|
| **R1 品牌列表过长** | 热门品类可能有 50+ 品牌，增加 prompt token。缓解：品牌列表截断（按商品数量排序取 top-20） |
| **R2 LLM 仍编造品牌** | Prompt 约束可能不够强。缓解：已有 Step1 post-hoc 校验作为安全网；Step3 和 scenario_gen 输出后，如果品牌非空，可在代码中做软校验（warning 日志） |
| **R3 DB 查询失败** | 品牌查询失败时不应阻断流程。缓解：catch exception → 注入"(品牌数据暂不可用)"→ LLM 输出 `[]` |

## 8. 待明确问题

无 `[NEEDS CLARIFICATION]` 项。策略已在 brainstorming 阶段确认（策略 B — Prompt 嵌入式）。
