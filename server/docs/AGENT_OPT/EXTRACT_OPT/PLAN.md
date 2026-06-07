# PLAN.md — 实现方案

> 输入：`DEFINE.md` → 输出：本文件
> 日期：2026-06-07

## 1. 整体架构

本次改动仅触及 Extraction 节点 Step 1 的内部逻辑，不改变 Extraction 三步流程的对外接口和下游行为。

```mermaid
graph LR
    A[extraction_node] --> B["Step 1: _extract_categories_and_brands()"]
    B --> C[LLM: EXTRACTION_STEP1_SYSTEM]
    B --> D[memory.get_recent_queries()]
    A --> E[Step 2: _build_context_with_memory]
    A --> F[Step 3: _extract_intents_per_category]
    
    D -->|"最近 N 轮查询文本"| B
    B -->|"{recent_queries} 占位符"| C
```

## 2. 核心变更点

### 2.1 提示词模板 — `extraction_prompt.py`

**变更：** `EXTRACTION_STEP1_SYSTEM` 新增 `{recent_queries}` 占位符和上下文说明段。

```
## 对话历史（最近 N 轮，用于推断模糊查询的品类）
{recent_queries}
```

### 2.2 函数签名 — `_extract_categories_and_brands()`

**变更：** 新增 `session_memory` 参数。

```
async def _extract_categories_and_brands(
    user_query: str,
    llm: LLMService,
    db_session_factory,
    session_memory: list[dict] | None = None,   # 新增
) -> list[dict]:
```

内部逻辑：
- 调用 `get_recent_queries(session_memory, settings.search.memory_recent_rounds)` 获取历史
- 格式化为纯文本：`#1 帮我推荐跑鞋\n#2 要轻量的`
- `.replace("{recent_queries}", history_text)` 注入 prompt

### 2.3 调用方 — `extraction_node()`

**变更：** 调用 `_extract_categories_and_brands()` 时传入 `session_memory`。

## 3. 模块影响范围

| 模块 | 变更类型 | 说明 |
|------|---------|------|
| `agent/prompts/extraction_prompt.py` | 修改 | 新增 `{recent_queries}` 占位符 |
| `agent/nodes/extraction.py` | 修改 | `_extract_categories_and_brands()` 新增参数 + 注入逻辑 |
| `tests/test_extraction.py` | 新增测试 | 验证有历史时品类推断 |

## 4. 主要优点

- **改动极小**：只改 1 个 prompt 模板 + 1 个函数签名 + 1 个调用点
- **复用现有能力**：`get_recent_queries()` 和 `memory_recent_rounds` 已被 Router 使用，成熟可靠
- **零回归风险**：首轮无历史时行为完全不变
- **不增加 LLM 调用**：仅 enrich 已有调用的 prompt

## 5. 风险

| 风险 | 缓解 |
|------|------|
| 长历史撑爆 token | `memory_recent_rounds=10` 可控；每轮查询中文约 20 字，总计 ~200 字 |
| 历史误导 | LLM 本身具备区分当前 vs 历史的能力；Step 1 只提取品类不拆意图 |

## 6. 复杂度评估

| 维度 | 评级 |
|------|------|
| 实现复杂度 | **低** — 3 个文件，~20 行新增代码 |
| 测试复杂度 | **低** — mock session_memory 即可 |
| 回归风险 | **极低** — 首轮无历史行为不变 |
| 可交付性 | **高** — 单次 commit 即可完成 |

## 7. 可测试性

- 新增测试：构造 `session_memory` 含历史查询，验证 Step 1 能从"要轻量的"推断出"跑鞋"品类
- 回归测试：无历史时行为不变（现有测试覆盖）
- 所有测试 mock LLM，无需网络

---

> 无 `[NEEDS CLARIFICATION]`。方案明确，可直接进入 CON_PLAN.md。
