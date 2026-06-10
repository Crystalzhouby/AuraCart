# DEFINE.md — 需求分析

> 输入：`SPEC.md` → 输出：本文件
> 日期：2026-06-09

## 1. 功能需求

**F1 — agent/nodes/ 下 5 个 Agent 文件重命名**

文件名规范化：用完整语义词替代缩写，统一 `_agent` 后缀。

| 当前 | 新名 |
|------|------|
| `extraction.py` | `intent_extract_agent.py` |
| `option_gen.py` | `option_generate_agent.py` |
| `retriever.py` | `product_retrieve_agent.py` |
| `router.py` | `intent_route_agent.py` |
| `scenario_gen.py` | `scene_generate_agent.py` |

**F2 — agent/prompts/ 下 6 个 Prompt 文件重命名**

文件名与对应 Agent 命名保持一致。

| 当前 | 新名 |
|------|------|
| `category_intro_prompt.py` | `category_introduct_prompt.py` |
| `extraction_prompt.py` | `intent_extract_prompt.py` |
| `option_gen_prompt.py` | `option_generate_prompt.py` |
| `product_reason_prompt.py` | `product_recommendation_prompt.py` |
| `scenario_gen_prompt.py` | `scene_generate_prompt.py` |
| `unified_router_prompt.py` | `intent_router_prompt.py` |

**F3 — api/ 下 2 个 API 文件重命名**

| 当前 | 新名 |
|------|------|
| `products.py` | `get_product_info.py` |
| `conversation.py` | `get_conversation.py` |

**F4 — 导出的函数/常量同步改名**

| 当前 | 新名 |
|------|------|
| `router_node` | `intent_route_node` |
| `extraction_node` | `intent_extract_node` |
| `option_gen_node` | `option_generate_node` |
| `retrieval_node` | `product_retrieve_node` |
| `scenario_gen_node` | `scene_generate_node` |
| `_parse_router_response` | `_parse_route_response` |
| `UNIFIED_ROUTER_SYSTEM` | `INTENT_ROUTER_SYSTEM` |
| `EXTRACTION_STEP1_SYSTEM` | `INTENT_EXTRACT_STEP1_SYSTEM` |
| `EXTRACTION_STEP3_SYSTEM` | `INTENT_EXTRACT_STEP3_SYSTEM` |
| `SCENARIO_GEN_SYSTEM` | `SCENE_GENERATE_SYSTEM` |
| `ENDING_OPTION_SYSTEM` | `OPTION_GENERATE_SYSTEM` |
| `CATEGORY_INTRO_SYSTEM` | `CATEGORY_INTRODUCT_SYSTEM` |
| `PRODUCT_REASON_SYSTEM` | `PRODUCT_RECOMMENDATION_SYSTEM` |

## 2. 性能需求

无。纯重命名，不改变运行时行为。

## 3. 最终交付物

1. 13 个源文件重命名（git mv）
2. 约 25 处 import 语句更新（跨 12 个文件）
3. 约 12 个导出函数/常量名更新（含调用方）
4. `main.py` `include_router` 更新
5. `.py` 文件内模块路径字符串更新（如 `graph.py`、测试文件）
6. `design docs/**/*.md` 中旧文件名的引用更新

## 4. 硬约束

- 不改变任何业务逻辑
- 内部辅助函数（仅文件内使用）不改名
- 所有测试通过后方可提交

## 5. 隐含要求

- `git mv` 保留文件历史
- 重命名后整个项目可正常运行（`python run.py` + `pytest`）

## 6. 任务完成边界

**完成标准：**
- 13 个文件完成重命名
- 所有 import 引用无遗漏更新
- 所有导出函数/常量名同步更新
- 120+ 测试全部通过
- 服务可正常启动

**不做的事：**
- 不修改内部辅助函数名
- 不改变测试逻辑
- 不调整文件目录结构

## 7. 风险点

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| import 遗漏导致运行时 ImportError | 中 | 高 | grep 全量扫描所有引用，按清单逐条更新 |
| 测试中断言使用旧常量名 | 中 | 中 | 测试文件同步 grep + 替换 |
| 设计文档引用旧文件名 | 低 | 低 | grep `server/docs/` 逐条更新 |

---

> 无 `[NEEDS CLARIFICATION]` 标记。命名映射已确认。
