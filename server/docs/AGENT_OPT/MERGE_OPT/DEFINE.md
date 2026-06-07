# MERGE_OPT — 需求分析

> 输入: `server/docs/AGENT_OPT/MERGE_OPT/SPEC.md`
> 输出: `server/docs/AGENT_OPT/MERGE_OPT/DEFINE.md`

## 1. 功能需求

### F1: 去除查询改写 LLM 调用，全链路使用原始查询

涉及文件: `router.py`, `state.py`, `search.py`, `extraction.py`, `scenario_gen.py`, `retriever.py`, `show_prompt.py`

**目标:** 删除 Router 中的 `_rewrite_query()` LLM 调用（减少 1 次 LLM 调用），下游节点直接使用 `user_query` + 历史记录推断所需品类。

**具体改动:**

| 文件 | 改动 |
|---|---|
| `router.py` | 删除 `_rewrite_query()` 函数（lines 120-161）；`router_node()` 不再调用改写，`rewritten_query` 字段设为 `user_query` 并在后续 clean-up 中移除；`_generate_welcome()` 移除 `rewritten_query` 参数，欢迎语基于 `user_query` + history 生成 |
| `state.py` | 删除 `rewritten_query` 字段（AgentState 定义 + TypedDict 注释） |
| `search.py` | 初始 state 中删除 `"rewritten_query": ""` |
| `extraction.py` | `rewritten_query` 变量改为 `user_query = state.get("user_query", "")`（原为 `state.get("rewritten_query", state.get("user_query"))`） |
| `scenario_gen.py` | 同上；模块 docstring 更新 |
| `retriever.py` | `_generate_ending` 调用处改为 `user_query=state.get("user_query", "")`；若 F3 合并后此函数被移除则无需改 |
| `show_prompt.py` | `WELCOME_SYSTEM`: 移除 `{rewritten_query}` 占位及对应规则；`ENDING_SYSTEM`: 若合并到 option_gen 则移除 |
| `rewrite_prompt.py` | **删除文件** |
| `tests/` | 更新所有 mock state 中对 `rewritten_query` 的引用 |

**设计意图:** 查询改写本身是一次 LLM 调用，但其效果（补全商品主体）已可通过在 extraction/scenario_gen 的上下文中注入最近几轮历史查询来实现——让 LLM 直接从历史+当前查询推断 category/sub_category，而非先改写再提取。

### F2: 合并结束语生成与选项生成

涉及文件: `option_gen.py`, `option_gen_prompt.py`, `retriever.py`, `show_prompt.py`, `state.py`

**目标:** 将 `ENDING_SYSTEM` 和 `OPTION_GEN_SYSTEM` 合并为一次 LLM 调用，输出 `{"ending": "...", "next_options": [...]}`（减少 1 次 LLM 调用）。

**合并位置:** `option_gen_node` — 此节点已在 graph 末尾，拥有完整 state 访问权。

**具体改动:**

| 文件 | 改动 |
|---|---|
| `option_gen_prompt.py` | 新增合并后的 prompt `ENDING_OPTION_SYSTEM`，整合结束语 + 选项生成的规则和输出格式 |
| `option_gen.py` | `option_gen_node` 扩展：注入 session_memory/retrieval 品类汇总等结束语所需的上下文；解析 LLM 返回的 `ending` + `next_options`；将 `ending` 通过 `_sse_queue` 发送；返回 `{"next_options": [...], "ending": "..."}` |
| `retriever.py` | 删除 `_generate_ending()` 函数（lines 320-371）；删除 `retrieval_node` 中结束语生成调用（line 482-484 附近）；结束语 SSE 事件或由 `option_gen_node` 通过 queue 发送 |
| `show_prompt.py` | 删除 `ENDING_SYSTEM`（lines 69-91，已迁移到 `option_gen_prompt.py`） |
| `state.py` | 可选：新增 `ending: str` 字段（若需要在 state 中持久化结束语） |

**SSE 事件流（变更后）:**

```
welcome → category_intro → products → product_reason → ... → ending → next_options → done
                                                              ↑                ↑
                                              option_gen_node 发送     finally 块发送
```

**数据流对比:**

```
Before:
  retrieval_node → _generate_ending() → queue.put("ending", ...)
  option_gen_node → state.next_options → finally block → yield "next_options"

After:
  option_gen_node → LLM(merged_prompt) → {ending, next_options}
                 → queue.put("ending", ending_text)
                 → state.next_options = [...]
  finally block → yield "next_options" → yield "done"
```

## 2. LLM 调用节省

以典型多品类推荐路径为例（Router → ScenarioGen → Retrieval → OptionGen）：

| 阶段 | 优化前 | 优化后 | 节省 |
|---|---|---|---|
| Router | 3 次（分类 + 改写 + 欢迎语） | 2 次（分类 + 欢迎语） | -1 |
| Extraction/ScenarioGen | 1 次 | 1 次 | 0 |
| Retrieval（品类介绍） | N 次（仅多品类） | N 次 | 0 |
| Retrieval（商品推荐理由） | M 次（每商品） | M 次 | 0 |
| Retrieval（结束语） | 1 次 | — | -1 |
| OptionGen | 1 次 | 1 次（合并） | 0 |
| **总计** | **6 + N + M** | **4 + N + M** | **-2** |

## 3. 性能需求

无新增。减少 2 次 LLM 调用可降低首字延迟约 1-2 秒（取决于 LLM 响应速度）。

## 4. 最终交付物

1. `router.py` — 删除 `_rewrite_query()`，`_generate_welcome()` 去除 `rewritten_query`
2. `state.py` — 删除 `rewritten_query` 字段
3. `search.py` — 初始 state 删除 `rewritten_query`
4. `extraction.py` — `rewritten_query` → `user_query`
5. `scenario_gen.py` — `rewritten_query` → `user_query`
6. `retriever.py` — 删除 `_generate_ending()`，删除结束语 queue.put 调用
7. `option_gen.py` — 扩展：合并结束语 + 选项生成为一次 LLM 调用，通过 queue 发送 `ending`
8. `option_gen_prompt.py` — 新增合并 prompt `ENDING_OPTION_SYSTEM`
9. `show_prompt.py` — 移除 `ENDING_SYSTEM`，`WELCOME_SYSTEM` 移除 `{rewritten_query}`
10. `rewrite_prompt.py` — **删除**
11. `tests/` — 更新 `rewritten_query` 相关引用
12. `GENERAL SPEC.md` + `API.md` — 文档同步

## 5. 硬约束

- 不能破坏现有 SSE 事件流顺序: `welcome → category_intro → products → product_reason → ending → next_options → done`
- ChitChat 路径不受影响（闲聊不走 extraction/retrieval）
- `done` 事件仍然由消费循环 finally 块发送
- 结束语 SSE event 从 `option_gen_node` 通过 queue 发送（而非 retrieval_node）
- 所有离线测试（148 个）必须继续通过

## 6. 隐含要求

- `ending` 事件的发送时机必须在所有 `product_reason` 之后、`next_options` 之前
- `option_gen_node` 默认在 `retrieval_node` 之后执行（graph 边: retrieval → option_gen），queue 中的 ending 事件自然在所有 retrieval 事件之后
- 合并后的 prompt 不能丢失去任一功能的质量

## 7. 任务完成边界

- 完成 F1 + F2 全部修改
- 删除 `rewrite_prompt.py`
- 修改后的测试全部通过（无回归）
- 手动 curl 验证: `ending` + `next_options` 正确发送、欢迎语基于原查询
- 不涉及: 数据库 schema 变更、新增 API 接口

## 8. 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| 去除查询改写后，省略主语的查询（如"要轻量的"）无法正确提取品类 | extraction/scenario_gen 收到不完整查询 | extraction/scenario_gen prompt 已注入历史上下文，可从此推断；测试验证多轮对话场景 |
| 合并 prompt 导致 ending 质量下降或 next_options 偏离 | 结束语空洞或选项不相关 | prompt 中明确分隔两个任务，保留各自的核心规则 |
| `option_gen_node` 通过 queue 发送 ending 但 queue 可能已被 graph 结束影响 | ending 丢失 | graph 边确保 retrieval → option_gen 顺序执行，queue 在 graph 完成前仍活跃 |
| 删除 `rewritten_query` 后 WELCOME_SYSTEM 的 `{rewritten_query}` 引用忘记移除 | `.format()` 报错 | grep 全量排查 |

## 9. 开放问题

无 `[NEEDS CLARIFICATION]` 项。用户已确认: 删除 `rewritten_query` 字段（方案 B），全链路使用 `user_query`。
